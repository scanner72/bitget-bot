"""Smoke: unrealized PnL enrichment with mocked mark prices (no network).

long/short formulas, ticker-failure nulls, equity_mtm = cash + notional + upnl.

Exit 0 on success. Paper-only.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exec.account import PaperAccount  # noqa: E402
from exec.paper import (  # noqa: E402
    PaperBook,
    enrich_position_mtm,
    list_open_with_pnl,
    open_paper,
    unrealized_pnl_usd,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    # unit formulas
    long_upnl = unrealized_pnl_usd("long", 100.0, 110.0, 200.0)
    _assert(abs(long_upnl - 20.0) < 1e-9, long_upnl)  # (110-100)/100 * 200
    short_upnl = unrealized_pnl_usd("short", 100.0, 90.0, 200.0)
    _assert(abs(short_upnl - 20.0) < 1e-9, short_upnl)  # (100-90)/100 * 200

    row = enrich_position_mtm(
        {"symbol": "CRCL/USDT:USDT", "side": "long", "size_usd": 100.0, "entry_price": 97.36},
        mark_price=100.0,
    )
    _assert(row["mark_price"] == 100.0, row)
    _assert(row["unrealized_pnl_usd"] is not None, row)
    _assert(row["unrealized_pnl_pct"] is not None, row)
    expected = 100.0 * ((100.0 / 97.36) - 1.0)
    _assert(abs(row["unrealized_pnl_usd"] - expected) < 1e-6, row)

    fail = enrich_position_mtm(
        {"symbol": "X", "side": "long", "size_usd": 10.0, "entry_price": 1.0},
        mark_price=None,
        error="ticker boom",
    )
    _assert(fail["unrealized_pnl_usd"] is None, fail)
    _assert("ticker boom" in str(fail.get("mtm_error")), fail)

    with tempfile.TemporaryDirectory(prefix="bitget_upnl_smoke_") as tmp:
        tmp_path = Path(tmp)
        acct = PaperAccount.load(tmp_path / "acct.json", start_balance=10000.0)
        book = PaperBook(
            fills_file=tmp_path / "fills.jsonl",
            positions_file=tmp_path / "positions.json",
            account=acct,
        )
        open_paper("CRCL/USDT:USDT", "long", 100.0, 97.36, book=book)
        open_paper("SOPH/USDT:USDT", "short", 50.0, 0.006, book=book)

        prices = {"CRCL/USDT:USDT": 100.0, "SOPH/USDT:USDT": 0.005}
        enriched, total, errors = list_open_with_pnl(
            book=book,
            price_fn=lambda s: prices[s],
        )
        _assert(len(enriched) == 2, enriched)
        _assert(not errors, errors)
        _assert(total is not None, total)
        long_u = enriched[0]["unrealized_pnl_usd"]
        short_u = enriched[1]["unrealized_pnl_usd"]
        _assert(abs(total - (long_u + short_u)) < 1e-9, (total, long_u, short_u))

        # equity_mtm alignment: cash + open_notional + upnl
        snap = acct.snapshot(unrealized=float(total))
        equity_mtm = snap["equity"]
        expected_eq = acct.cash + acct.open_notional + float(total)
        _assert(abs(equity_mtm - expected_eq) < 1e-9, (equity_mtm, expected_eq))
        print(f"sample enriched CRCL: {enriched[0]}")
        print(f"total_unrealized_pnl={total} equity_mtm={equity_mtm}")

        # failure path: price_fn raises
        def boom(sym: str) -> float:
            raise RuntimeError(f"no ticker for {sym}")

        bad, total_bad, err_notes = list_open_with_pnl(book=book, price_fn=boom)
        _assert(all(r["unrealized_pnl_usd"] is None for r in bad), bad)
        _assert(total_bad is None, total_bad)
        _assert(len(err_notes) == 2, err_notes)
        print(f"failure notes OK: {err_notes[0][:60]}...")

    print("smoke_upnl OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
