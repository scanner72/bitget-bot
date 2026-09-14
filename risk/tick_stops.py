"""Tick-path exits: same evaluate_exit rules, driven by WS quotes.

Runs only for currently open positions (typically ≤ MAX_POSITIONS). Quotes for
the rest of the scan universe are ignored. ATR/trailing use the in-memory
candle cache — no REST on the hot path.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Iterable

from risk.exits import ExitConfig, apply_exit_event, evaluate_exit


def tick_stops_enabled() -> bool:
    raw = (os.getenv("TICK_STOPS") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


class QuoteBus:
    """Coalesce latest quote per open symbol (keep high/low extrema)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: set[str] = set()
        self._pending: dict[str, tuple[float, float, float]] = {}

    def set_open_symbols(self, symbols: Iterable[str]) -> None:
        cleaned = {str(s).strip() for s in symbols if str(s).strip()}
        with self._lock:
            self._open = cleaned
            for key in list(self._pending):
                if key not in cleaned:
                    self._pending.pop(key, None)

    def on_quote(
        self,
        symbol: str,
        last: float,
        high: float | None = None,
        low: float | None = None,
    ) -> None:
        try:
            last_f = float(last)
        except (TypeError, ValueError):
            return
        if last_f <= 0:
            return
        try:
            high_f = float(high) if high is not None else last_f
        except (TypeError, ValueError):
            high_f = last_f
        try:
            low_f = float(low) if low is not None else last_f
        except (TypeError, ValueError):
            low_f = last_f
        if high_f <= 0:
            high_f = last_f
        if low_f <= 0:
            low_f = last_f
        high_f = max(high_f, last_f)
        low_f = min(low_f, last_f)
        with self._lock:
            if symbol not in self._open:
                return
            prev = self._pending.get(symbol)
            if prev is not None:
                _, ph, pl = prev
                high_f = max(ph, high_f)
                low_f = min(pl, low_f)
            self._pending[symbol] = (last_f, high_f, low_f)

    def drain(self) -> list[tuple[str, float, float, float]]:
        with self._lock:
            items = [(s, t[0], t[1], t[2]) for s, t in self._pending.items()]
            self._pending.clear()
            return items


def apply_tick_quotes(
    bus: QuoteBus,
    *,
    gate: Any | None = None,
    book: Any | None = None,
    cfg: ExitConfig | None = None,
    timeframe: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate coalesced quotes against current opens. Main-thread only."""
    quotes = bus.drain()
    if not quotes:
        return []

    from exec.paper import PaperBook

    b = book or PaperBook(gate=gate)
    if gate is not None and getattr(b, "gate", None) is None:
        b.gate = gate
    opens = b.list_open()
    if not opens:
        return []

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for pos in opens:
        sym = str(pos.get("symbol") or "")
        if sym:
            by_sym.setdefault(sym, []).append(pos)

    cfg = cfg or ExitConfig.from_env()
    tf = (timeframe or os.getenv("TIMEFRAME", "15m") or "15m").strip()
    events: list[dict[str, Any]] = []

    try:
        from ingest import candle_cache
    except Exception:
        candle_cache = None  # type: ignore[assignment]

    for symbol, last, high, low in quotes:
        df = None
        if candle_cache is not None:
            try:
                df = candle_cache.get_cached_ohlcv(symbol, tf, min_bars=1)
            except Exception:
                df = None
        ch, cl = high, low
        if df is not None and len(df):
            try:
                ch = max(float(high), float(df["high"].iloc[-1]))
                cl = min(float(low), float(df["low"].iloc[-1]))
            except Exception:
                ch, cl = high, low
        for pos in by_sym.get(symbol) or []:
            ev = evaluate_exit(
                pos,
                candle_high=ch,
                candle_low=cl,
                mark_price=last,
                df=df,
                cfg=cfg,
            )
            if ev.action == "none":
                continue
            if ev.action == "close":
                extra = dict(ev.updates or {})
                extra["tick_stop"] = True
                ev.updates = extra
            applied = apply_exit_event(pos, ev, book=b, gate=gate)
            if applied:
                applied["tick"] = True
                events.append(applied)
    return events
