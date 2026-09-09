"""Smoke: ccxt symbol -> Bitget id / display helpers (no network).

Exit 0 on success.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.symbols import enrich_symbol_fields, to_bitget_id, to_display  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    cases = [
        ("CRCL/USDT:USDT", "CRCLUSDT", "CRCL-USDT Perp"),
        ("BTC/USDT:USDT", "BTCUSDT", "BTC-USDT Perp"),
        ("SOPH/USDT:USDT", "SOPHUSDT", "SOPH-USDT Perp"),
        ("XAG/USDT:USDT", "XAGUSDT", "XAG-USDT Perp"),
        ("AAPL/USDT:USDT", "AAPLUSDT", "AAPL-USDT Perp"),
        ("ETHUSDT", "ETHUSDT", "ETH-USDT Perp"),
        ("", "", ""),
    ]
    for src, expect_id, expect_disp in cases:
        got_id = to_bitget_id(src)
        got_disp = to_display(src)
        _assert(got_id == expect_id, f"to_bitget_id({src!r})={got_id!r} want {expect_id!r}")
        _assert(got_disp == expect_disp, f"to_display({src!r})={got_disp!r} want {expect_disp!r}")

    row = enrich_symbol_fields({"symbol": "CRCL/USDT:USDT", "side": "long"})
    _assert(row["symbol"] == "CRCL/USDT:USDT", "keep ccxt symbol")
    _assert(row["symbol_id"] == "CRCLUSDT", "symbol_id")
    _assert(row["symbol_display"] == "CRCL-USDT Perp", "symbol_display")
    _assert(row["side"] == "long", "passthrough")

    empty = enrich_symbol_fields({"side": "long"})
    _assert("symbol_id" not in empty and "symbol_display" not in empty, "no fake fields")

    print("smoke_symbols: ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"smoke_symbols FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
