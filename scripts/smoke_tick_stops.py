"""Smoke: tick QuoteBus + full evaluate_exit (TP1 partial, BE remainder)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def _close_fills(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") == "close":
            rows.append(row)
    return rows


def _tick_env(**extra: str) -> dict[str, str]:
    env = {
        "EXEC_MODE": "paper",
        "TICK_STOPS": "1",
        # Intentional TP1 wick (~8.5% from entry); mark-sanity is for Demo/public
        # scale drift, not strategy exit distance on paper.
        "MARK_SANITY_MAX_DEV_PCT": "25",
        "RTOKEN_MARK_SANITY_MAX_DEV_PCT": "25",
    }
    env.update(extra)
    return env


def _open_short(book) -> str:
    return book.open_paper(
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


def main() -> int:
    from exec.account import PaperAccount
    from exec.paper import PaperBook
    from risk.tick_stops import QuoteBus, apply_tick_quotes

    with tempfile.TemporaryDirectory(prefix="tick_stops_") as td:
        tdir = Path(td)
        acct = PaperAccount.load(tdir / "acct.json", start_balance=10000.0, persist=True)
        fills = tdir / "fills.jsonl"
        book = PaperBook(
            fills_file=fills,
            positions_file=tdir / "pos.json",
            account=acct,
        )
        pid = _open_short(book)

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

        # TP1 (short: low <= 9.2) closes half, parks remainder SL at entry.
        bus.set_open_symbols(["ONDO/USDT:USDT"])
        bus.on_quote("ONDO/USDT:USDT", 9.15, 9.4, 9.1)
        with patch.dict(os.environ, _tick_env(TP1_CLOSE_FRACTION="0.5"), clear=False):
            ev = apply_tick_quotes(bus, book=book, timeframe="15m")
        _assert(any(e.get("action") == "reduce" for e in ev), ev)
        _assert(not any(e.get("action") == "close" for e in ev), ev)
        reduced = next(e for e in ev if e.get("action") == "reduce")
        _assert(abs(float(reduced["size_usd_left"]) - 50.0) < 1e-6, reduced)
        _assert(abs(float(reduced["realized_pnl"]) - 4.25) < 1e-6, reduced)
        _assert(abs(float(reduced["close_price"]) - 9.15) < 1e-9, reduced)
        pos = book.list_open()[0]
        _assert(pos.get("position_id") == pid, pos)
        _assert(abs(float(pos.get("size_usd") or 0) - 50.0) < 1e-6, pos)
        _assert(abs(float(pos.get("qty") or 0) - 5.0) < 1e-6, pos)
        _assert(bool(pos.get("tp1_hit") or (pos.get("meta") or {}).get("tp1_hit")), pos)
        _assert(abs(float(pos.get("sl") or 0) - 10.0) < 1e-9, pos)
        partials = _close_fills(fills)
        _assert(len(partials) == 1, partials)
        _assert(abs(float(partials[0]["size_usd"]) - 50.0) < 1e-6, partials[0])
        _assert(partials[0].get("meta", {}).get("tp1_partial") is True, partials[0])
        _assert(partials[0].get("meta", {}).get("exit_status") == "tp1_hit", partials[0])

        # Follow-up BE stop must close the remainder (50), not the original 100.
        sl_after = float(pos.get("sl") or 0)
        bus.set_open_symbols(["ONDO/USDT:USDT"])
        bus.on_quote("ONDO/USDT:USDT", sl_after + 0.05, sl_after + 0.1, sl_after - 0.2)
        with patch.dict(os.environ, _tick_env(TP1_CLOSE_FRACTION="0.5"), clear=False):
            ev2 = apply_tick_quotes(bus, book=book, timeframe="15m")
        _assert(any(e.get("action") == "close" for e in ev2), ev2)
        closed = next(e for e in ev2 if e.get("action") == "close")
        _assert(abs(float(closed["close_price"]) - 10.0) < 1e-9, closed)
        _assert(abs(float(closed["realized_pnl"])) < 1e-9, closed)
        _assert(book.list_open() == [], book.list_open())
        closes = _close_fills(fills)
        _assert(len(closes) == 2, closes)
        remainder = closes[-1]
        _assert(abs(float(remainder["size_usd"]) - 50.0) < 1e-6, remainder)
        _assert(abs(float(remainder["qty"]) - 5.0) < 1e-6, remainder)
        _assert(remainder.get("meta", {}).get("exit_status") == "trailing_hit", remainder)
        _assert(abs(float(acct.realized_pnl) - 4.25) < 1e-6, acct.realized_pnl)
        _assert(abs(float(acct.open_notional)) < 1e-9, acct.open_notional)
        _assert(abs(float(acct.cash) - 10004.25) < 1e-6, acct.cash)

        # TP1_CLOSE_FRACTION=0: breakeven update only, full size stays open.
        acct0 = PaperAccount.load(tdir / "acct0.json", start_balance=10000.0, persist=True)
        fills0 = tdir / "fills0.jsonl"
        book0 = PaperBook(
            fills_file=fills0,
            positions_file=tdir / "pos0.json",
            account=acct0,
        )
        pid0 = _open_short(book0)
        bus0 = QuoteBus()
        bus0.set_open_symbols(["ONDO/USDT:USDT"])
        bus0.on_quote("ONDO/USDT:USDT", 9.15, 9.4, 9.1)
        with patch.dict(os.environ, _tick_env(TP1_CLOSE_FRACTION="0"), clear=False):
            ev0 = apply_tick_quotes(bus0, book=book0, timeframe="15m")
        _assert(any(e.get("action") == "update" for e in ev0), ev0)
        _assert(not any(e.get("action") == "reduce" for e in ev0), ev0)
        _assert(not any(e.get("action") == "close" for e in ev0), ev0)
        _assert(_close_fills(fills0) == [], _close_fills(fills0))
        pos0 = book0.list_open()[0]
        _assert(pos0.get("position_id") == pid0, pos0)
        _assert(abs(float(pos0.get("size_usd") or 0) - 100.0) < 1e-6, pos0)
        _assert(abs(float(pos0.get("qty") or 0) - 10.0) < 1e-6, pos0)
        _assert(bool(pos0.get("tp1_hit") or (pos0.get("meta") or {}).get("tp1_hit")), pos0)
        sl0 = float(pos0.get("sl") or 0)
        _assert(sl0 <= 10.0 + 1e-9, sl0)

        bus0.set_open_symbols(["ONDO/USDT:USDT"])
        bus0.on_quote("ONDO/USDT:USDT", sl0 + 0.05, sl0 + 0.1, sl0 - 0.2)
        with patch.dict(os.environ, _tick_env(TP1_CLOSE_FRACTION="0"), clear=False):
            ev0b = apply_tick_quotes(bus0, book=book0, timeframe="15m")
        _assert(any(e.get("action") == "close" for e in ev0b), ev0b)
        _assert(book0.list_open() == [], book0.list_open())
        full = _close_fills(fills0)
        _assert(len(full) == 1, full)
        _assert(abs(float(full[0]["size_usd"]) - 100.0) < 1e-6, full[0])
        _assert(abs(float(full[0]["qty"]) - 10.0) < 1e-6, full[0])
        _assert(full[0].get("meta", {}).get("tp1_partial") is not True, full[0])

    print("smoke_tick_stops OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
