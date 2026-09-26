"""Smoke: tick QuoteBus + full evaluate_exit (SL close, TP1 update)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    from exec.account import PaperAccount
    from exec.paper import PaperBook
    from risk.tick_stops import QuoteBus, apply_tick_quotes

    with tempfile.TemporaryDirectory(prefix="tick_stops_") as td:
        tdir = Path(td)
        acct = PaperAccount.load(tdir / "acct.json", start_balance=10000.0, persist=True)
        book = PaperBook(
            fills_file=tdir / "fills.jsonl",
            positions_file=tdir / "pos.json",
            account=acct,
        )
        # Short: SL 10.5, TP1 9.2, TP2 8.5, entry 10
        pid = book.open_paper(
            "ONDO/USDT:USDT",
            "short",
            100.0,
            10.0,
            meta={
                "exec_venue": "paper",
                "atr": 0.5,
                "sl": 10.5,
                "tp1": 9.2,
                "tp2": 8.5,
                "original_sl": 10.5,
            },
        )

        bus = QuoteBus()
        bus.set_open_symbols(["ONDO/USDT:USDT"])
        # Unknown symbol ignored
        bus.on_quote("BTC/USDT:USDT", 100.0)
        _assert(bus.drain() == [], "closed universe must drop quotes")

        # Coalesce: keep wick high/low, latest last
        bus.on_quote("ONDO/USDT:USDT", 10.1, 10.2, 10.0)
        bus.on_quote("ONDO/USDT:USDT", 10.3, 10.4, 10.05)
        drained = bus.drain()
        _assert(len(drained) == 1, drained)
        last, high, low = drained[0][1], drained[0][2], drained[0][3]
        _assert(last == 10.3, last)
        _assert(high == 10.4, high)
        _assert(low == 10.0, low)

        env = {
            "EXEC_MODE": "paper",
            "TICK_STOPS": "1",
            # Intentional TP1 wick (~8.5% from entry); mark-sanity is for Demo/public
            # scale drift, not strategy exit distance on paper.
            "MARK_SANITY_MAX_DEV_PCT": "25",
            "RTOKEN_MARK_SANITY_MAX_DEV_PCT": "25",
        }
        # TP1 tag (short: low <= 9.2) → BE update, still open
        bus.on_quote("ONDO/USDT:USDT", 9.15, 9.4, 9.1)
        with patch.dict(os.environ, env, clear=False):
            ev = apply_tick_quotes(bus, book=book, timeframe="15m")
        _assert(any(e.get("action") == "update" for e in ev), ev)
        pos = book.list_open()[0]
        _assert(bool(pos.get("tp1_hit") or (pos.get("meta") or {}).get("tp1_hit")), pos)
        sl_after = float(pos.get("sl") or 0)
        _assert(sl_after <= 10.0 + 1e-9, sl_after)

        # Trailing/BE SL tagged (short: high >= sl)
        bus.set_open_symbols(["ONDO/USDT:USDT"])
        bus.on_quote("ONDO/USDT:USDT", sl_after + 0.05, sl_after + 0.1, sl_after - 0.2)
        with patch.dict(os.environ, env, clear=False):
            ev2 = apply_tick_quotes(bus, book=book, timeframe="15m")
        _assert(any(e.get("action") == "close" for e in ev2), ev2)
        _assert(book.list_open() == [], book.list_open())
        _assert(pid, "opened")

    print("smoke_tick_stops OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
