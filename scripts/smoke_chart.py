"""Smoke: chart payload + history pairing + dashboard href helper."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _ohlcv(n: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC")
    close = pd.Series(range(n), dtype=float) + 100.0
    df = pd.DataFrame(
        {
            "open": close - 0.4,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def test_chart_payload() -> None:
    from api.chart_data import build_chart_payload, normalize_chart_symbol

    _assert(normalize_chart_symbol("BTCUSDT") == "BTC/USDT:USDT", "ccxt map")
    with patch("api.chart_data.get_ohlcv", return_value=_ohlcv(90)):
        out = build_chart_payload("BTCUSDT", timeframe="15m", limit=90)
    _assert(out["status"] == "ok", out)
    _assert(len(out["candles"]) == 90, len(out["candles"]))
    _assert(out["candles"][0]["time"] > 0, out["candles"][0])
    _assert(out["source"] == "bitget_live", out)
    _assert("rsi" in out, out.keys())


def test_closed_trades() -> None:
    from exec import hub_view as hv

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "paper_fills.jsonl"
        rows = [
            {
                "ts": "2026-09-11T10:00:00+00:00",
                "position_id": "pos_a",
                "event": "open",
                "symbol": "ETH/USDT:USDT",
                "side": "short",
                "price": 4000.0,
                "meta": {"sl": 4100.0, "tp1": 3900.0, "tp2": 3800.0, "timeframe": "15m", "exec_venue": "hub"},
            },
            {
                "ts": "2026-09-11T11:00:00+00:00",
                "position_id": "pos_a",
                "event": "close",
                "symbol": "ETH/USDT:USDT",
                "side": "short",
                "price": 3950.0,
                "entry_price": 4000.0,
                "realized_pnl": 12.5,
                "meta": {"exit_status": "trailing_hit", "sl": 4100.0, "tp1": 3900.0, "tp2": 3800.0, "exec_venue": "hub"},
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        with patch.object(hv, "_paper_fill_rows", return_value=rows):
            out = hv.list_closed_trades_for_ui(limit=10)
    _assert(out["count"] == 1, out)
    t = out["trades"][0]
    _assert(t["entry_price"] == 4000.0, t)
    _assert(t["exit_price"] == 3950.0, t)
    _assert(t["source"] == "hub", t)
    _assert(t["sl"] == 4100.0, t)


def test_chart_href() -> None:
    from api.app import _chart_href

    href = _chart_href(
        "ETH/USDT:USDT",
        timeframe="15m",
        entry=4000,
        sl=4100,
        tp2=3800,
        direction="short",
        opened="2026-09-11T10:00:00+00:00",
        exit_px=3950,
        closed="2026-09-11T11:00:00+00:00",
        pnl=-1.2,
        reason="sl_hit",
    )
    _assert(href.startswith("/chart?"), href)
    _assert("symbol=ETH" in href, href)
    _assert("dir=short" in href, href)
    _assert("exit=3950" in href, href)


def main() -> int:
    test_chart_payload()
    test_closed_trades()
    test_chart_href()
    print("smoke_chart: ok")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
