"""Smoke: skip hub open when Demo mark/fill is on a different scale than public."""
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


def _book(tdir: Path, name: str):
    from exec.account import PaperAccount
    from exec.paper import PaperBook

    acct = PaperAccount.load(
        tdir / f"{name}_account.json",
        start_balance=10000.0,
        persist=True,
    )
    return PaperBook(
        fills_file=tdir / f"{name}_fills.jsonl",
        positions_file=tdir / f"{name}_positions.json",
        account=acct,
    )


class _HubClient:
    demo = True

    def __init__(self, pos: dict | None = None) -> None:
        self.placed = 0
        self.closed = 0
        self.pos = pos

    def place_perp_market(self, *args, **kwargs):
        self.placed += 1
        return {"orderId": "o1", "clientOid": "c1"}

    def close_perp_market(self, *args, **kwargs):
        self.closed += 1
        return {"orderId": "x1"}

    def current_positions(self):
        return {"list": [self.pos] if self.pos else []}

    def place_position_tpsl(self, *args, **kwargs):
        raise RuntimeError("tpsl should not run on mismatch")


def main() -> int:
    from exec.router import DemoPriceMismatchError
    from exec import router as router_mod

    env = {
        "EXEC_MODE": "hub_demo",
        "BITGET_DEMO": "1",
        "PAPER_FALLBACK": "0",
        "SIGNAL_PRICE_MAX_DEV_PCT": "5",
    }

    with tempfile.TemporaryDirectory(prefix="bitget_hub_scale_") as td:
        tdir = Path(td)

        # 1) Pre-open: Demo SAMSUNG ~1.86 vs public ~182 — do not place.
        pre_client = _HubClient()
        book1 = _book(tdir, "pre")
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=pre_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=182.63), patch.object(
            router_mod, "_fetch_hub_mark", return_value=1.86
        ):
            raised = False
            try:
                router_mod.open_position(
                    symbol="SAMSUNG/USDT:USDT",
                    side="short",
                    size_usd=500.0,
                    price=182.63,
                    meta={"atr": 3.65, "type": "BEARISH_DIV"},
                    book=book1,
                )
            except DemoPriceMismatchError as exc:
                raised = True
                _assert("demo_mark" in str(exc), str(exc))
        _assert(raised, "pre-open scale mismatch must skip")
        _assert(pre_client.placed == 0, f"placed={pre_client.placed}")
        _assert(book1.list_open() == [], book1.list_open())

        # 2) Post-fill backup: ticker looked fine, fill came back at 1.85 — flatten, no paper.
        pos = {
            "symbol": "SAMSUNGUSDT",
            "posSide": "short",
            "total": "2.73",
            "available": "2.73",
            "avgPrice": "1.85",
            "markPrice": "1.88",
        }
        fill_client = _HubClient(pos)
        book2 = _book(tdir, "fill")
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=fill_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=182.63), patch.object(
            router_mod, "_fetch_hub_mark", return_value=182.50
        ), patch.object(router_mod, "_find_hub_position", return_value=pos):
            raised = False
            try:
                router_mod.open_position(
                    symbol="SAMSUNG/USDT:USDT",
                    side="short",
                    size_usd=500.0,
                    price=182.63,
                    meta={"atr": 3.65},
                    book=book2,
                )
            except DemoPriceMismatchError as exc:
                raised = True
                _assert("hub_entry" in str(exc), str(exc))
        _assert(raised, "fill scale mismatch must flatten")
        _assert(fill_client.placed == 1, f"placed={fill_client.placed}")
        _assert(fill_client.closed == 1, f"closed={fill_client.closed}")
        _assert(book2.list_open() == [], book2.list_open())

        # 3) Matching scale (AAPL): keep hub fill as paper entry.
        aapl_pos = {
            "symbol": "AAPLUSDT",
            "posSide": "long",
            "total": "1.5",
            "available": "1.5",
            "avgPrice": "332.10",
            "markPrice": "332.20",
        }
        ok_client = _HubClient(aapl_pos)
        book3 = _book(tdir, "ok")
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=ok_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=331.57), patch.object(
            router_mod, "_fetch_hub_mark", return_value=332.19
        ), patch.object(router_mod, "_find_hub_position", return_value=aapl_pos), patch.object(
            router_mod, "_place_hub_tpsl"
        ):
            pid = router_mod.open_position(
                symbol="AAPL/USDT:USDT",
                side="long",
                size_usd=500.0,
                price=331.57,
                meta={"atr": 2.0},
                book=book3,
            )
        opens = book3.list_open()
        _assert(len(opens) == 1, opens)
        _assert(opens[0]["position_id"] == pid, opens[0])
        _assert(abs(float(opens[0]["entry_price"]) - 332.10) < 1e-9, opens[0])
        _assert(ok_client.placed == 1, ok_client.placed)
        _assert(ok_client.closed == 0, ok_client.closed)

        # 4) Pipeline records the skip, no fill.
        os.environ["EXEC_MODE"] = "paper"
        os.environ["AGENT_MODE"] = "rules"
        os.environ.pop("AGENT_LLM", None)
        os.environ["ALLOW_LONG"] = "1"
        os.environ["ALLOW_SHORT"] = "1"
        os.environ["RSI_LONG_MAX"] = "30"
        os.environ["BTC_FILTERS_ENABLED"] = "0"
        os.environ["PROPOSED_SIZE_USD"] = "50"
        os.environ["RISK_USD_PER_TRADE"] = "2"
        os.environ["MAX_NOTIONAL_USD"] = "100"

        import pandas as pd

        from desk.pipeline import evaluate_candidate
        from exec.account import PaperAccount
        from exec.paper import PaperBook
        from risk.gate import RiskGate, RiskLimits, RiskState

        idx = pd.date_range("2024-01-01", periods=40, freq="15min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": 65000.0,
                "high": 65050.0,
                "low": 64950.0,
                "close": 65000.0,
                "volume": 1.0,
            },
            index=idx,
        )
        gate = RiskGate(
            limits=RiskLimits(
                max_notional_usd=100.0,
                max_daily_loss_usd=50.0,
                max_positions=3,
                one_position_per_symbol=True,
                cooldown_sec=0.0,
                allowed_types=None,
            ),
            state=RiskState(),
            persist=False,
        )
        book4 = PaperBook(
            gate=gate,
            fills_file=tdir / "pipe_fills.jsonl",
            positions_file=tdir / "pipe_positions.json",
            account=PaperAccount.load(
                tdir / "pipe_account.json",
                start_balance=10000.0,
                persist=True,
            ),
        )
        with patch(
            "desk.pipeline.open_position",
            side_effect=DemoPriceMismatchError(
                "SAMSUNG/USDT:USDT: demo_mark:1.86 vs ref=182.63 dev=98.98%>5.0"
            ),
        ):
            out = evaluate_candidate(
                {
                    "symbol": "BTC/USDT:USDT",
                    "type": "BULLISH_DIV",
                    "price": 65000.0,
                    "rsi": 28.0,
                },
                gate,
                decisions_path=tdir / "decisions.jsonl",
                paper_book=book4,
                context={"ohlcv_df": df},
            )
        _assert(out.get("fill_id") is None, out)
        _assert(out.get("position_id") is None, out)
        _assert(
            "demo_price_mismatch" in str(out.get("paper_error") or ""),
            out,
        )
        _assert(book4.list_open() == [], book4.list_open())

    print("smoke_hub_price_scale OK: pre-open skip + flatten fill + keep matched + pipeline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
