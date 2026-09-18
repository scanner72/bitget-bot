"""Bitget public WebSocket — candles + tickers for USDT-M swap universe.

Connects to wss://ws.bitget.com/v2/ws/public, shards subscriptions
(<= WS_MAX_CHANNELS_PER_CONN), ping every 30s, reconnect + resubscribe.
REST bootstrap warms CandleCache; bar_close callbacks drive the desk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

from ingest.symbols import to_bitget_id

logger = logging.getLogger(__name__)

ROOT = __file__
WS_URL = "wss://ws.bitget.com/v2/ws/public"
INST_TYPE = "USDT-FUTURES"

# Bitget candle channel names
_TF_CHANNEL = {
    "1m": "candle1m",
    "5m": "candle5m",
    "15m": "candle15m",
    "30m": "candle30m",
    "1h": "candle1H",
    "4h": "candle4H",
    "6h": "candle6H",
    "12h": "candle12H",
    "1d": "candle1D",
}
_CHANNEL_TO_TF = {v.lower(): k for k, v in _TF_CHANNEL.items()}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(float(v))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def candle_channel(timeframe: str) -> str:
    tf = (timeframe or "15m").strip().lower()
    if tf not in _TF_CHANNEL:
        raise ValueError(f"Unsupported WS timeframe: {timeframe!r}")
    return _TF_CHANNEL[tf]


def _chunk(items: list[str], size: int) -> list[list[str]]:
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]


class BitgetPublicWs:
    """Background public WS hub (thread + asyncio)."""

    def __init__(
        self,
        *,
        timeframe: str = "15m",
        timeframes: list[str] | None = None,
        on_bar_close: Callable[..., None] | None = None,
        on_quote: Callable[..., None] | None = None,
        subscribe_ticker: bool = True,
        max_channels_per_conn: int | None = None,
        bootstrap_limit: int = 200,
        bootstrap_rate: float = 8.0,
    ) -> None:
        load_dotenv(
            os.path.join(os.path.dirname(__file__), "..", ".env"), override=False
        )
        if timeframes:
            self.timeframes = [t.strip().lower() for t in timeframes if t.strip()]
        else:
            tf_env = (timeframe or os.getenv("TIMEFRAMES", "") or os.getenv("TIMEFRAME", "15m")).strip()
            self.timeframes = [t.strip().lower() for t in tf_env.split(",") if t.strip()]
        if not self.timeframes:
            self.timeframes = ["15m"]
        self.timeframe = self.timeframes[0]
        self.channel = candle_channel(self.timeframe)
        self.on_bar_close = on_bar_close
        self.on_quote = on_quote
        self.subscribe_ticker = bool(subscribe_ticker)
        # candle per timeframe (+ optional ticker) per symbol
        ch_per_sym = len(self.timeframes) + (1 if self.subscribe_ticker else 0)
        max_ch = max_channels_per_conn or _env_int("WS_MAX_CHANNELS_PER_CONN", 40)
        self._symbols_per_conn = max(1, int(max_ch) // max(1, ch_per_sym))
        self.bootstrap_limit = max(50, int(bootstrap_limit))
        self.bootstrap_rate = max(1.0, float(bootstrap_rate))
        self._url = os.getenv("BITGET_WS_PUBLIC_URL", WS_URL).strip() or WS_URL

        self._symbols: list[str] = []
        self._id_to_ccxt: dict[str, str] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wanted_gen = 0
        self._last_msg_ts = 0.0
        self._live_shards: set[int] = set()
        self._bootstrapped: set[str] = set()
        self._bootstrap_lock = threading.Lock()
        self._bootstrap_thread: threading.Thread | None = None

    @property
    def healthy(self) -> bool:
        """True if at least one shard connected and message within 90s."""
        if not self._live_shards:
            return False
        if self._last_msg_ts <= 0:
            return False
        return (time.time() - self._last_msg_ts) < 90.0

    @property
    def connected_shards(self) -> int:
        return len(self._live_shards)

    def start(self, symbols: list[str] | None = None) -> None:
        if symbols is not None:
            self.set_symbols(symbols, bootstrap=True)
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main, name="bitget-public-ws", daemon=True
        )
        self._thread.start()
        print(f"[WS] thread started watchlist={len(self._symbols)} shards~={max(1, (len(self._symbols) + self._symbols_per_conn - 1) // self._symbols_per_conn)}")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self._bootstrap_thread and self._bootstrap_thread.is_alive():
            self._bootstrap_thread.join(timeout=min(2.0, timeout))
        self._thread = None
        self._live_shards.clear()

    def set_symbols(self, symbols: list[str], *, bootstrap: bool = True) -> None:
        """Update watchlist; optionally bootstrap new symbols via REST in background."""
        cleaned: list[str] = []
        id_map: dict[str, str] = {}
        seen: set[str] = set()
        for raw in symbols or []:
            sym = str(raw).strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            cleaned.append(sym)
            id_map[to_bitget_id(sym)] = sym
        with self._lock:
            self._symbols = cleaned
            self._id_to_ccxt = id_map
            self._wanted_gen += 1
        if bootstrap:
            self._ensure_bootstrap_thread(cleaned)

    def _ensure_bootstrap_thread(self, symbols: list[str]) -> None:
        def _worker(batch: list[str]) -> None:
            self._bootstrap_missing(batch)

        with self._bootstrap_lock:
            # Always schedule; worker skips already-bootstrapped
            self._bootstrap_thread = threading.Thread(
                target=_worker,
                args=(list(symbols),),
                name="bitget-ws-bootstrap",
                daemon=True,
            )
            self._bootstrap_thread.start()

    def _bootstrap_missing(self, symbols: list[str]) -> None:
        from ingest.bitget_ohlcv import fetch_ohlcv
        from ingest import candle_cache

        delay = 1.0 / self.bootstrap_rate
        done = 0
        for sym in symbols:
            if self._stop.is_set():
                return
            for tf in self.timeframes:
                cache_key = f"{sym}:{tf}"
                if cache_key in self._bootstrapped:
                    continue
                if self._stop.is_set():
                    return
                try:
                    df = fetch_ohlcv(
                        symbol=sym, timeframe=tf, limit=self.bootstrap_limit
                    )
                    candle_cache.set_ohlcv(sym, tf, df)
                    self._bootstrapped.add(cache_key)
                    done += 1
                    if done == 1 or done % 20 == 0:
                        print(f"[WS] bootstrap progress {done} (+{sym} [{tf}] bars={len(df)})")
                except Exception as exc:  # noqa: BLE001
                    print(f"[WS] bootstrap fail {sym} [{tf}]: {exc}")
                time.sleep(delay)
        print(f"[WS] bootstrap done new={done} total_cached={len(self._bootstrapped)}")

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_forever())
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                symbols = list(self._symbols)
                gen = self._wanted_gen
            if not symbols:
                await asyncio.sleep(1.0)
                continue
            shards = _chunk(symbols, self._symbols_per_conn)
            tasks = [
                asyncio.create_task(self._run_shard(i, chunk, gen))
                for i, chunk in enumerate(shards)
            ]
            # Restart all shards when symbol set changes or stop
            while not self._stop.is_set():
                with self._lock:
                    if self._wanted_gen != gen:
                        break
                await asyncio.sleep(0.5)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._live_shards.clear()

    async def _run_shard(self, shard_id: int, symbols: list[str], gen: int) -> None:
        try:
            import websockets
        except ImportError as exc:
            logger.error("websockets package missing: %s", exc)
            await asyncio.sleep(5)
            return

        backoff = 1.0
        while not self._stop.is_set():
            with self._lock:
                if self._wanted_gen != gen:
                    return
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=None,
                    max_size=8 * 1024 * 1024,
                ) as ws:
                    self._live_shards.add(shard_id)
                    backoff = 1.0
                    print(
                        f"[WS] shard={shard_id} connected symbols={len(symbols)}",
                        flush=True,
                    )
                    await self._subscribe(ws, symbols)
                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    try:
                        async for raw in ws:
                            if self._stop.is_set():
                                break
                            with self._lock:
                                if self._wanted_gen != gen:
                                    break
                            self._last_msg_ts = time.time()
                            if raw == "pong":
                                continue
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            self._handle_message(msg)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except Exception:
                            pass
                        self._live_shards.discard(shard_id)
            except asyncio.CancelledError:
                self._live_shards.discard(shard_id)
                return
            except Exception as exc:  # noqa: BLE001
                self._live_shards.discard(shard_id)
                print(
                    f"[WS] shard={shard_id} error: {exc} — reconnect in {backoff:.1f}s",
                    flush=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 1.8)

    async def _subscribe(self, ws: Any, symbols: list[str]) -> None:
        args: list[dict[str, str]] = []
        for sym in symbols:
            inst = to_bitget_id(sym)
            if not inst:
                continue
            for tf in self.timeframes:
                try:
                    ch = candle_channel(tf)
                    args.append(
                        {"instType": INST_TYPE, "channel": ch, "instId": inst}
                    )
                except ValueError:
                    continue
            if self.subscribe_ticker:
                args.append(
                    {"instType": INST_TYPE, "channel": "ticker", "instId": inst}
                )
        # Bitget: <=10 messages/sec — batch args but keep payloads modest
        batch = 20
        for i in range(0, len(args), batch):
            chunk = args[i : i + batch]
            await ws.send(json.dumps({"op": "subscribe", "args": chunk}))
            await asyncio.sleep(0.12)

    async def _ping_loop(self, ws: Any) -> None:
        while not self._stop.is_set():
            try:
                await ws.send("ping")
            except Exception:
                return
            await asyncio.sleep(20.0)

    def _handle_message(self, msg: dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        if msg.get("event") in {"subscribe", "unsubscribe", "error"}:
            if msg.get("event") == "error":
                logger.warning("WS error event: %s", msg)
            return
        action = msg.get("action")
        if action not in {"snapshot", "update"}:
            return
        arg = msg.get("arg") or {}
        channel = str(arg.get("channel") or "")
        inst = str(arg.get("instId") or "").upper()
        with self._lock:
            symbol = self._id_to_ccxt.get(inst)
        if not symbol:
            return
        data = msg.get("data")
        if not data:
            return

        if channel == "ticker":
            self._handle_ticker(symbol, data)
            return
        if channel.startswith("candle"):
            self._handle_candle(symbol, channel, data, action=str(action or ""))

    def _handle_ticker(self, symbol: str, data: Any) -> None:
        from ingest import candle_cache

        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            return
        for key in ("markPr", "markPrice", "lastPr", "last", "close"):
            raw = row.get(key)
            if raw is None or raw == "":
                continue
            try:
                px = float(raw)
            except (TypeError, ValueError):
                continue
            if px > 0:
                candle_cache.set_mark(symbol, px)
                self._emit_quote(symbol, px, px, px)
                return

    def _handle_candle(self, symbol: str, channel: str, data: Any, *, action: str = "") -> None:
        from ingest import candle_cache

        tf = _CHANNEL_TO_TF.get(channel.lower(), self.timeframe)
        rows = data if isinstance(data, list) else [data]
        # Snapshot can contain many bars — warm cache without firing bar_close spam.
        fire = action == "update"
        for item in rows:
            if not isinstance(item, (list, tuple)) or len(item) < 5:
                continue
            try:
                ts_ms = int(float(item[0]))
                o = float(item[1])
                h = float(item[2])
                low = float(item[3])
                c = float(item[4])
                vol = float(item[5]) if len(item) > 5 else 0.0
            except (TypeError, ValueError):
                continue
            closed = candle_cache.apply_candle_update(
                symbol,
                tf,
                ts_ms=ts_ms,
                open_=o,
                high=h,
                low=low,
                close=c,
                volume=vol,
            )
            if fire and closed and self.on_bar_close is not None:
                try:
                    self.on_bar_close(symbol, tf)
                except TypeError:
                    try:
                        self.on_bar_close(symbol)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("on_bar_close %s: %s", symbol, exc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("on_bar_close %s %s: %s", symbol, tf, exc)
            if fire:
                self._emit_quote(symbol, c, h, low)

    def _emit_quote(
        self,
        symbol: str,
        last: float,
        high: float | None = None,
        low: float | None = None,
    ) -> None:
        if self.on_quote is None:
            return
        try:
            self.on_quote(symbol, last, high, low)
        except Exception as exc:  # noqa: BLE001
            logger.warning("on_quote %s: %s", symbol, exc)


def market_data_mode() -> str:
    load_dotenv(
        os.path.join(os.path.dirname(__file__), "..", ".env"), override=False
    )
    mode = (os.getenv("MARKET_DATA_MODE", "ws") or "ws").strip().lower()
    if mode not in {"ws", "rest"}:
        return "ws"
    return mode
