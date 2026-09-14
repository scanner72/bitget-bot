"""Multi-symbol candle -> signal -> candidate -> agent decide -> risk log.

Config from env / .env:
  SYMBOLS            comma-separated (BTCUSDT or BTC/USDT:USDT); used when SCAN_MODE=fixed
  SCAN_MODE          fixed|auto (default auto) — auto = top crypto + rToken USDT-M perps
  SCAN_CRYPTO_TOP    default 70 (with WS)
  SCAN_RTOKEN_TOP    default 30
  MARKET_DATA_MODE   ws|rest (default ws) — public candles via WebSocket
  POLL_SEC           rest poll interval / exit cadence hint
  TIMEFRAME          default 15m
  ONCE=1             single REST pass then exit
  OHLCV_LIMIT        default 200

NO SPOT — Bitget USDT-M swap + rToken/RWA stock perps only.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from desk.candidate_log import CandidateLog, candidate_from_signal
from desk.pipeline import evaluate_candidate
from risk.gate import RiskGate
from risk.exits import ExitConfig, check_open_exits
from ingest.symbols import to_display
from ingest.bitget_ohlcv import get_ohlcv, set_shared_exchange
from ingest.bitget_ws import BitgetPublicWs, market_data_mode
from ingest.universe import UniverseCache, load_scan_env, resolve_scan_symbols
from signals.engine import run_full_detection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAIR_CONFIG = {
    "rsi_length": 14,
    "mom_period": 10,
    "lookback_left": 5,
    "lookback_right": 5,
    "min_bars": 5,
    "max_bars": 50,
}


@dataclass
class LoopConfig:
    symbols: list[str]
    timeframe: str = "15m"
    poll_sec: float = 60.0
    once: bool = False
    ohlcv_limit: int = 200
    candidates_path: Path = ROOT / "data" / "candidates.jsonl"
    decisions_path: Path = ROOT / "data" / "decisions.jsonl"
    pair_config: dict[str, Any] | None = None
    scan_mode: str = "auto"
    scan_crypto_top: int = 20
    scan_rtoken_top: int = 20
    scan_refresh_sec: float = 300.0
    fixed_symbols: list[str] = field(default_factory=list)

    @property
    def risk_decisions_path(self) -> Path:
        """Alias: decisions JSONL (agent + risk chain)."""
        return self.decisions_path


def normalize_symbol(raw: str) -> str:
    """Map BTCUSDT / BTC/USDT -> Bitget ccxt swap BTC/USDT:USDT."""
    s = raw.strip().upper().replace("-", "/")
    if not s:
        return s
    if ":" in s:
        return s
    if "/" in s:
        return f"{s}:USDT"
    for quote in ("USDT", "USDC"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}:USDT"
    return s


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def load_config(env_path: Path | None = None) -> LoopConfig:
    load_dotenv(env_path or (ROOT / ".env"), override=False)
    raw_symbols = os.getenv("SYMBOLS", "BTC/USDT:USDT")
    symbols = [normalize_symbol(p) for p in raw_symbols.split(",") if p.strip()]
    if not symbols:
        symbols = ["BTC/USDT:USDT"]
    timeframe = os.getenv("TIMEFRAME", "15m").strip() or "15m"
    try:
        poll_sec = float(os.getenv("POLL_SEC", "60") or "60")
    except ValueError:
        poll_sec = 60.0
    # Default 200 for scan speed; override via OHLCV_LIMIT
    try:
        ohlcv_limit = int(os.getenv("OHLCV_LIMIT", "200") or "200")
    except ValueError:
        ohlcv_limit = 200
    cand = os.getenv("CANDIDATES_PATH", "").strip()
    candidates_path = Path(cand) if cand else (ROOT / "data" / "candidates.jsonl")
    dec_raw = (
        os.getenv("DECISIONS_PATH", "").strip()
        or os.getenv("RISK_DECISIONS_PATH", "").strip()
    )
    decisions_path = Path(dec_raw) if dec_raw else (ROOT / "data" / "decisions.jsonl")
    scan = load_scan_env()
    return LoopConfig(
        symbols=list(symbols),
        timeframe=timeframe,
        poll_sec=max(1.0, poll_sec),
        once=_env_bool("ONCE", True),
        ohlcv_limit=max(50, ohlcv_limit),
        candidates_path=candidates_path,
        decisions_path=decisions_path,
        pair_config=dict(DEFAULT_PAIR_CONFIG),
        scan_mode=scan["mode"],
        scan_crypto_top=scan["crypto_top"],
        scan_rtoken_top=scan["rtoken_top"],
        scan_refresh_sec=scan["refresh_sec"],
        fixed_symbols=list(symbols),
    )


def process_symbol(
    symbol: str,
    cfg: LoopConfig,
    clog: CandidateLog,
    gate: RiskGate | None = None,
) -> dict[str, Any]:
    """Fetch -> detect -> log candidate -> agent.decide -> risk. Returns summary."""
    summary: dict[str, Any] = {
        "symbol": symbol,
        "ok": False,
        "bars": 0,
        "has_zones": False,
        "candidate": None,
        "logged": False,
        "deduped": False,
        "action": None,
        "risk_allowed": None,
        "risk_reason": None,
        "error": None,
    }
    try:
        df = get_ohlcv(symbol=symbol, timeframe=cfg.timeframe, limit=cfg.ohlcv_limit)
        summary["bars"] = len(df)
        signal, has_zones = run_full_detection(df, cfg.pair_config or DEFAULT_PAIR_CONFIG)
        summary["has_zones"] = bool(has_zones)
        summary["ok"] = True
        if signal is None:
            return summary
        rec = candidate_from_signal(
            signal,
            symbol=symbol,
            timeframe=cfg.timeframe,
            ts=datetime.now(timezone.utc),
        )
        summary["candidate"] = rec["type"]
        if clog.is_duplicate(rec):
            summary["deduped"] = True
            return summary
        written = clog.append(rec)
        summary["logged"] = bool(written)
        summary["deduped"] = not written
        if written and gate is not None:
            out = evaluate_candidate(
                rec,
                gate,
                decisions_path=cfg.decisions_path,
                context={
                    "symbol": symbol,
                    "timeframe": cfg.timeframe,
                    "ohlcv_df": df,
                    "ohlcv_limit": cfg.ohlcv_limit,
                },
            )
            summary["action"] = out.get("action")
            summary["risk_allowed"] = out.get("allowed")
            summary["risk_reason"] = out.get("reason")
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary


def _active_symbols(
    cfg: LoopConfig,
    cache: UniverseCache | None,
) -> tuple[list[str], UniverseCache | None]:
    """Resolve symbols for this pass (auto refresh or fixed SYMBOLS)."""
    if cfg.scan_mode != "auto":
        return list(cfg.fixed_symbols or cfg.symbols), cache
    if cache is None:
        cache = UniverseCache()
        set_shared_exchange(cache.exchange)
    symbols, _mode, snap = resolve_scan_symbols(
        cfg.fixed_symbols or cfg.symbols,
        cache=cache,
    )
    cfg.symbols = list(symbols)
    if snap is not None:
        print(
            f"[universe] crypto_top={len(snap.crypto)}/{snap.crypto_total} "
            f"rtoken_top={len(snap.rtoken)}/{snap.rtoken_total} "
            f"union={len(symbols)}"
        )
    return symbols, cache


def run_pass(
    cfg: LoopConfig,
    clog: CandidateLog,
    gate: RiskGate | None = None,
    *,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    use = symbols if symbols is not None else cfg.symbols
    results = [process_symbol(sym, cfg, clog, gate) for sym in use]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = []
    for r in results:
        if r["error"]:
            parts.append(f"{to_display(r['symbol']) or r['symbol']}:ERR({r['error']})")
        elif r["candidate"]:
            flag = "LOG" if r["logged"] else ("DEDUP" if r["deduped"] else "CAND")
            agent_bit = ""
            if r.get("action"):
                agent_bit = f" action={r['action']}"
            risk_bit = ""
            if r.get("risk_allowed") is not None:
                risk_bit = (
                    f" risk={'ALLOW' if r['risk_allowed'] else 'DENY'}"
                    f":{r.get('risk_reason')}"
                )
            elif r.get("action") == "SKIP":
                risk_bit = f" skip_reason={r.get('risk_reason')}"
            parts.append(
                f"{to_display(r['symbol']) or r['symbol']}:{r['candidate']}[{flag}] zones={r['has_zones']} "
                f"bars={r['bars']}{agent_bit}{risk_bit}"
            )
        else:
            parts.append(f"{to_display(r['symbol']) or r['symbol']}:EMPTY zones={r['has_zones']} bars={r['bars']}")
    logged_n = sum(1 for r in results if r.get("logged"))
    print(f"[{ts}] pass symbols={len(results)} logged={logged_n} | " + " | ".join(parts))
    return results


def run_loop(cfg: LoopConfig | None = None) -> int:
    cfg = cfg or load_config()
    clog = CandidateLog(cfg.candidates_path)
    gate = RiskGate()
    try:
        from exec.paper import list_open

        n = gate.sync_opens_from_paper(list_open())
        print(f"[RISK] synced opens from paper: {n}")
    except Exception as _sync_exc:  # noqa: BLE001
        print(f"[RISK] sync opens skipped: {_sync_exc}")
    try:
        from exec.hub_balance import sync_paper_account_from_hub

        sync_paper_account_from_hub()
    except Exception as _hub_sync_exc:  # noqa: BLE001
        print(f"[HUB] sync paper from hub skipped: {_hub_sync_exc}")
    try:
        from exec.reconcile import reconcile_paper_with_exchange

        _rec = reconcile_paper_with_exchange(gate=gate)
        _n_close = sum(1 for e in _rec if e.get("action") == "close")
        if _rec:
            print(f"[RECONCILE] startup events={len(_rec)} closed={_n_close}")
    except Exception as _rec_exc:  # noqa: BLE001
        print(f"[RECONCILE] startup skipped: {_rec_exc}")

    md_mode = market_data_mode()
    # ONCE always uses one REST pass (deterministic smoke / demo)
    if cfg.once:
        md_mode = "rest"

    mode = "ONCE" if cfg.once else f"{md_mode.upper()}/poll={cfg.poll_sec}s"
    cache: UniverseCache | None = None
    if cfg.scan_mode == "auto":
        cache = UniverseCache()
        set_shared_exchange(cache.exchange)
    print(
        f"desk.loop start mode={mode} market_data={md_mode} scan={cfg.scan_mode} "
        f"tf={cfg.timeframe} "
        f"ohlcv_limit={cfg.ohlcv_limit} "
        f"crypto_top={cfg.scan_crypto_top} rtoken_top={cfg.scan_rtoken_top} "
        f"refresh={cfg.scan_refresh_sec}s "
        f"fixed_symbols={cfg.fixed_symbols} out={cfg.candidates_path} "
        f"decisions={cfg.decisions_path}"
    )
    exit_cfg = ExitConfig.from_env()
    last_blocker_ts = 0.0
    try:
        from risk.pair_blocker import BlockerConfig, run_blocker

        _bcfg = BlockerConfig.from_env()
        _sum = run_blocker(_bcfg)
        print(
            f"[BLOCKER] startup pairs={_sum.get('blocked_pairs')} "
            f"tfs={_sum.get('blocked_tfs')} new={_sum.get('new_pair_blocks')}/"
            f"{_sum.get('new_tf_blocks')} trades={_sum.get('closed_trades')}"
        )
        last_blocker_ts = time.time()
    except Exception as _blk_exc:  # noqa: BLE001
        print(f"[BLOCKER] startup skipped: {_blk_exc}")
        _bcfg = None

    if md_mode == "ws":
        return _run_loop_ws(
            cfg,
            clog,
            gate,
            cache,
            exit_cfg,
            _bcfg,
            last_blocker_ts,
        )

    while True:
        symbols, cache = _active_symbols(cfg, cache)
        run_pass(cfg, clog, gate, symbols=symbols)
        _run_exits(gate, exit_cfg, cfg)
        last_blocker_ts = _run_blocker(_bcfg, last_blocker_ts)
        if cfg.once:
            print("desk.loop done (ONCE)")
            return 0
        time.sleep(cfg.poll_sec)


def _run_exits(gate: RiskGate, exit_cfg: ExitConfig, cfg: LoopConfig) -> None:
    # Exchange SoT first: drop paper ghosts before soft SL/TP evaluation.
    try:
        from exec.reconcile import reconcile_paper_with_exchange

        reconcile_paper_with_exchange(gate=gate)
    except Exception as _rec_exc:  # noqa: BLE001
        print(f"[RECONCILE] error: {_rec_exc}")
    try:
        from ingest.bitget_ohlcv import get_mark_price, get_ohlcv

        check_open_exits(
            gate=gate,
            cfg=exit_cfg,
            timeframe=cfg.timeframe,
            ohlcv_limit=min(80, max(50, cfg.ohlcv_limit)),
            fetch_ohlcv_fn=get_ohlcv,
            fetch_mark_fn=get_mark_price,
        )
    except Exception as _exit_exc:  # noqa: BLE001
        print(f"[EXIT] check error: {_exit_exc}")


def _run_blocker(bcfg: Any, last_blocker_ts: float) -> float:
    try:
        from risk.pair_blocker import BlockerConfig, run_blocker

        cfg_b = bcfg
        if cfg_b is None:
            cfg_b = BlockerConfig.from_env()
        if time.time() - last_blocker_ts >= float(cfg_b.interval_sec):
            _sum = run_blocker(cfg_b)
            print(
                f"[BLOCKER] pairs={_sum.get('blocked_pairs')} "
                f"new_pair={_sum.get('new_pair_blocks')} "
                f"new_tf={_sum.get('new_tf_blocks')}"
            )
            return time.time()
    except Exception as _blk_exc:  # noqa: BLE001
        print(f"[BLOCKER] error: {_blk_exc}")
    return last_blocker_ts


def _run_loop_ws(
    cfg: LoopConfig,
    clog: CandidateLog,
    gate: RiskGate,
    cache: UniverseCache | None,
    exit_cfg: ExitConfig,
    bcfg: Any,
    last_blocker_ts: float,
) -> int:
    """Event-driven desk: process on candle bar_close; REST fallback if WS unhealthy."""
    bar_q: queue.Queue[str] = queue.Queue()
    pending: set[str] = set()
    pending_lock = threading.Lock()

    def _on_bar_close(symbol: str) -> None:
        with pending_lock:
            if symbol in pending:
                return
            pending.add(symbol)
        bar_q.put(symbol)

    from risk.tick_stops import QuoteBus, apply_tick_quotes, tick_stops_enabled

    quote_bus = QuoteBus()
    tick_on = tick_stops_enabled()

    def _on_quote(
        symbol: str,
        last: float,
        high: float | None = None,
        low: float | None = None,
    ) -> None:
        quote_bus.on_quote(symbol, last, high, low)

    ws = BitgetPublicWs(
        timeframe=cfg.timeframe,
        on_bar_close=_on_bar_close,
        on_quote=_on_quote if tick_on else None,
        subscribe_ticker=True,
        bootstrap_limit=cfg.ohlcv_limit,
        bootstrap_rate=float(os.getenv("WS_BOOTSTRAP_RATE", "8") or "8"),
    )

    symbols, cache = _active_symbols(cfg, cache)
    print(f"[WS] starting n={len(symbols)} tick_stops={tick_on} (bootstrap in background)")
    ws.start(symbols)
    last_universe = time.time()
    last_exit = 0.0
    last_fallback = 0.0
    last_health_log = 0.0
    unhealthy_since: float | None = None

    try:
        while True:
            # Universe refresh → resubscribe diff
            if time.time() - last_universe >= max(30.0, float(cfg.scan_refresh_sec)):
                symbols, cache = _active_symbols(cfg, cache)
                ws.set_symbols(symbols, bootstrap=True)
                last_universe = time.time()
                print(f"[WS] universe refresh n={len(symbols)} healthy={ws.healthy}")

            if time.time() - last_health_log >= 30.0:
                print(
                    f"[WS] health={ws.healthy} shards={ws.connected_shards} "
                    f"q={bar_q.qsize()} tick={int(tick_on)}",
                    flush=True,
                )
                last_health_log = time.time()

            if tick_on:
                try:
                    from exec.paper import list_open as _list_open

                    quote_bus.set_open_symbols(
                        str(p.get("symbol") or "") for p in (_list_open() or [])
                    )
                    apply_tick_quotes(
                        quote_bus,
                        gate=gate,
                        cfg=exit_cfg,
                        timeframe=cfg.timeframe,
                    )
                except Exception as _tick_exc:  # noqa: BLE001
                    print(f"[TICK] error: {_tick_exc}")

            # Drain bar-close queue
            drained = 0
            while drained < 20:
                try:
                    sym = bar_q.get_nowait()
                except queue.Empty:
                    break
                drained += 1
                with pending_lock:
                    pending.discard(sym)
                try:
                    summary = process_symbol(sym, cfg, clog, gate)
                    flag = "ok"
                    if summary.get("error"):
                        flag = f"ERR:{summary['error']}"
                    elif summary.get("candidate"):
                        flag = (
                            f"{summary['candidate']}"
                            f"{'[DEDUP]' if summary.get('deduped') else ''}"
                            f" action={summary.get('action')}"
                        )
                    else:
                        flag = "EMPTY"
                    print(
                        f"[WS][bar_close] {to_display(sym) or sym}: {flag} "
                        f"bars={summary.get('bars')}"
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[WS][bar_close] {sym} error: {exc}")

            # Exits on a short cadence (marks from WS cache)
            if time.time() - last_exit >= max(5.0, min(30.0, float(cfg.poll_sec))):
                _run_exits(gate, exit_cfg, cfg)
                last_exit = time.time()

            last_blocker_ts = _run_blocker(bcfg, last_blocker_ts)

            # REST fallback if WS unhealthy for >60s (full pass, throttled)
            if ws.healthy:
                unhealthy_since = None
            else:
                if unhealthy_since is None:
                    unhealthy_since = time.time()
                    print("[WS] unhealthy — will REST-fallback if persists")
                elif time.time() - unhealthy_since >= 60.0:
                    if time.time() - last_fallback >= max(float(cfg.poll_sec), 60.0):
                        print("[WS] REST fallback pass")
                        symbols, cache = _active_symbols(cfg, cache)
                        run_pass(cfg, clog, gate, symbols=symbols)
                        last_fallback = time.time()

            time.sleep(0.5)
    finally:
        ws.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--once" in argv:
        os.environ["ONCE"] = "1"
    if "--poll" in argv:
        os.environ["ONCE"] = "0"
    return run_loop(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
