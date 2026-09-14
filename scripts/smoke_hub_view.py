"""Smoke: hub UI helpers + equity overlay (no live orders)."""
from __future__ import annotations

import json
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


def test_overlay_anchor() -> None:
    from exec import hub_balance as hb

    paper = {
        "start_balance": 10000.0,
        "cash": 8000.0,
        "realized_pnl": 9.9,
        "equity": 10447.0,
        "currency": "USDT",
        "total_unrealized_pnl": 0.0,
    }
    hub = {
        "account_equity": 9884.16,
        "usdt_equity": 9888.71,
        "available": 9888.71,
        "unrealised_pnl": 0.0,
    }
    with tempfile.TemporaryDirectory() as td:
        anchor = Path(td) / "demo_start_equity.json"
        with patch.object(hb, "ANCHOR_PATH", anchor), patch.object(
            hb, "fetch_hub_usdt", return_value=hub
        ), patch.dict(os.environ, {"EXEC_MODE": "hub_demo", "DEMO_START_EQUITY": "10000"}):
            out = hb.overlay_equity_snapshot(paper)
        _assert(out["equity"] == 9884.16, out["equity"])
        _assert(out["start_balance"] == 10000.0, out["start_balance"])
        _assert(abs(out["pnl_vs_start"] - (9884.16 - 10000)) < 1e-6, out["pnl_vs_start"])
        _assert(out["realized_pnl"] == out["pnl_vs_start"] - out["total_unrealized_pnl"], out)
        _assert(out["paper"]["realized_pnl"] == 9.9, out["paper"])
        _assert(out["source"] == "hub_demo", out["source"])


def test_positions_hub_first() -> None:
    from exec import hub_view as hv

    class FakeClient:
        def current_positions(self, category: str = "USDT-FUTURES"):
            return {
                "list": [
                    {
                        "symbol": "LTCUSDT",
                        "posSide": "short",
                        "total": "9.3",
                        "available": "9.3",
                        "avgPrice": "54.65",
                        "markPrice": "54.12",
                        "unrealisedPnl": "4.9",
                        "positionBalance": "25.8",
                        "leverage": "20",
                    }
                ]
            }

        def unfilled_strategy_orders(self, type: str = "tpsl"):
            return [
                {
                    "symbol": "LTCUSDT",
                    "posSide": "short",
                    "stopLoss": "55.71",
                    "takeProfit": "51.99",
                    "status": "pending",
                }
            ]

        @classmethod
        def from_env(cls):
            return cls()

    paper = [
        {
            "symbol": "AVAX/USDT:USDT",
            "side": "short",
            "size_usd": 500,
            "position_id": "pos_ghost",
            "sl": 7.61,
        },
        {
            "symbol": "ONDO/USDT:USDT",
            "side": "short",
            "size_usd": 500,
            "qty": 625.0,
            "entry_price": 0.80,
            "position_id": "pos_ondo",
            "sl": 0.82,
            "tp1": 0.78,
            "tp2": 0.76,
            "meta": {"exec_venue": "paper", "exec_reason": "not_on_demo"},
        },
        {
            "symbol": "LTC/USDT:USDT",
            "side": "short",
            "size_usd": 500,
            "position_id": "pos_ltc",
            "tp1": 53.05,
            "meta": {"type": "BEARISH_DIV"},
        },
    ]
    with patch("exec.router.exec_mode", return_value="hub_demo"), patch(
        "exec.hub_view.list_open", return_value=paper
    ), patch("exec.bitget_hub.BitgetUtaClient.from_env", FakeClient.from_env), patch(
        "ingest.bitget_ohlcv.fetch_mark_price", return_value=0.79
    ):
        out = hv.list_positions_for_ui()
    _assert(out["count"] == 2, out)
    by_id = {r.get("position_id"): r for r in out["positions"]}
    row = by_id.get("pos_ltc") or out["positions"][0]
    _assert(row["symbol_id"] == "LTCUSDT" or "LTC" in row["symbol"], row)
    _assert(row["entry_price"] == 54.65, row)
    _assert(row["hub_sl_price"] == "55.71", row)
    _assert(row["tpsl_on_exchange"] is True, row)
    _assert(out["stale_count"] == 1, out)  # AVAX ghost not listed
    _assert(row["tracked"] is True, row)
    ondo = by_id.get("pos_ondo")
    _assert(ondo is not None, out)
    _assert(ondo["venue"] == "paper", ondo)
    _assert(ondo["pnl_source"] == "paper_live", ondo)
    _assert(out["paper_live_count"] == 1, out)


def test_fills_join() -> None:
    from exec import hub_view as hv

    class FakeClient:
        def fills(self, **kwargs):
            return {
                "list": [
                    {
                        "symbol": "LTCUSDT",
                        "side": "buy",
                        "tradeSide": "close",
                        "execPrice": "52.99",
                        "execQty": "9.3",
                        "execPnl": "15.1",
                        "orderId": "close1",
                        "clientOid": "bgclose",
                        "createdTime": "1757570000000",
                    }
                ]
            }

        @classmethod
        def from_env(cls):
            return cls()

    with patch("exec.router.exec_mode", return_value="hub_demo"), patch(
        "exec.bitget_hub.BitgetUtaClient.from_env", FakeClient.from_env
    ), patch.object(hv, "_paper_fill_rows", return_value=[]):
        out = hv.list_fills_for_ui(limit=10)
    _assert(out["source"] == "hub_demo", out)
    _assert(out["count"] == 1, out)
    _assert(out["fills"][0]["exec_pnl"] == 15.1, out["fills"][0])


def main() -> int:
    test_overlay_anchor()
    test_positions_hub_first()
    test_fills_join()
    print("smoke_hub_view OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
