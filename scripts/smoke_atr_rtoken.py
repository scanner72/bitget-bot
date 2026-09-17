"""Smoke: rToken ATR spec (1h, no 2% floor, min 0.5%) vs crypto."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from risk.atr import atr_filter_ok, atr_spec_for_symbol, compute_levels_from_df  # noqa: E402


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def _range_df(entry: float, range_pct: float, n: int = 20) -> pd.DataFrame:
    half = entry * range_pct / 200.0
    rows = {
        "open": [entry] * n,
        "high": [entry + half] * n,
        "low": [entry - half] * n,
        "close": [entry] * n,
        "volume": [1.0] * n,
    }
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def main() -> int:
    os.environ.pop("RTOKEN_ATR_TF", None)
    os.environ.pop("RTOKEN_ATR_FLOOR_PCT", None)
    os.environ.pop("RTOKEN_ATR_PCT_MIN", None)

    crypto = atr_spec_for_symbol("BTC/USDT:USDT")
    stock = atr_spec_for_symbol("AAPL/USDT:USDT")
    sndk = atr_spec_for_symbol("SNDK/USDT:USDT")
    print("crypto", crypto)
    print("aapl", stock)
    _assert(crypto["kind"] == "crypto" and crypto["floor_pct"] == 0.02, crypto)
    _assert(crypto["timeframe"] is None, crypto)
    _assert(stock["kind"] == "rtoken" and stock["floor_pct"] == 0.0, stock)
    _assert(stock["timeframe"] == "1h" and stock["min_pct"] == 0.5, stock)
    _assert(sndk["kind"] == "rtoken" and sndk["timeframe"] == "1h", sndk)

    entry = 100.0
    quiet = _range_df(entry, 0.4)  # 0.4% range — below rToken min, above nothing
    lv_c = compute_levels_from_df(entry, "long", quiet, floor_pct=crypto["floor_pct"])
    lv_s = compute_levels_from_df(entry, "long", quiet, floor_pct=stock["floor_pct"])
    _assert(lv_c is not None and abs(lv_c["atr_pct"] - 2.0) < 0.05, lv_c)
    _assert(lv_s is not None and lv_s["atr_pct"] < 0.5, lv_s)
    ok_s, reason_s = atr_filter_ok(lv_s["atr"], entry, min_pct=stock["min_pct"], max_pct=6.0)
    _assert(not ok_s and "atr_pct_low" in reason_s, reason_s)

    wide = _range_df(entry, 1.2)
    lv_s2 = compute_levels_from_df(entry, "long", wide, floor_pct=0.0)
    ok_s2, reason_s2 = atr_filter_ok(lv_s2["atr"], entry, min_pct=0.5, max_pct=6.0)
    _assert(ok_s2, reason_s2)

    print("smoke_atr_rtoken OK: stock 1h/no-floor/min0.5 vs crypto 2% floor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
