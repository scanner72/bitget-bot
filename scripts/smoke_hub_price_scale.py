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

    def __init__(self, pos: dict | None = None, *, tpsl_exc: Exception | None = None) -> None:
        self.placed = 0
        self.closed = 0
        self.tpsl_calls = 0
        self.pos = pos
        self.tpsl_exc = tpsl_exc

    def place_perp_market(self, *args, **kwargs):
        self.placed += 1
        return {"orderId": "o1", "clientOid": "c1"}

    def close_perp_market(self, *args, **kwargs):
        self.closed += 1
        return {"orderId": "x1"}

    def current_positions(self):
        return {"list": [self.pos] if self.pos else []}

    def place_position_tpsl(self, *args, **kwargs):
        self.tpsl_calls += 1
        if self.tpsl_exc is not None:
            raise self.tpsl_exc
        raise RuntimeError("tpsl should not run on mismatch")

    def _round_px(self, price, symbol=None):
        return f"{float(price):.2f}"


def main() -> int:
    from exec.router import DemoPriceMismatchError, HubTpslError
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
        ), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
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
        ), patch.object(router_mod, "_find_hub_position", return_value=pos), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
        ):
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
        ), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
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

        # 3b) TPSL API failure (25592-style) → flatten, no paper shadow.
        ltc_pos = {
            "symbol": "LTCUSDT",
            "posSide": "short",
            "total": "8.5",
            "available": "8.5",
            "avgPrice": "59.78",
            "markPrice": "59.80",
        }
        tpsl_client = _HubClient(
            ltc_pos,
            tpsl_exc=RuntimeError(
                "HTTP 400 code=25592: stop-loss trigger must be greater than mark"
            ),
        )
        book3b = _book(tdir, "tpsl")
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=tpsl_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=58.02), patch.object(
            router_mod, "_fetch_hub_mark", return_value=59.80
        ), patch.object(router_mod, "_find_hub_position", return_value=ltc_pos), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
        ):
            raised = False
            try:
                router_mod.open_position(
                    symbol="LTC/USDT:USDT",
                    side="short",
                    size_usd=500.0,
                    price=58.02,
                    meta={"atr": 1.2},
                    book=book3b,
                )
            except HubTpslError as exc:
                raised = True
                _assert("25592" in str(exc) or "tpsl" in str(exc).lower(), str(exc))
        _assert(raised, "tpsl failure must fail-closed")
        _assert(tpsl_client.placed == 1, f"placed={tpsl_client.placed}")
        _assert(tpsl_client.tpsl_calls == 1, f"tpsl_calls={tpsl_client.tpsl_calls}")
        _assert(tpsl_client.closed == 1, f"closed={tpsl_client.closed}")
        _assert(book3b.list_open() == [], book3b.list_open())

        # 3c) 31008 (position book lag): retry with backoff, then succeed.
        class _SeqTpslClient(_HubClient):
            def __init__(self, pos: dict, errors: list[Exception | None]) -> None:
                super().__init__(pos)
                self._errors = list(errors)

            def place_position_tpsl(self, *args, **kwargs):
                self.tpsl_calls += 1
                if self._errors:
                    err = self._errors.pop(0)
                    if err is not None:
                        raise err
                return {"orderId": f"tpsl-{self.tpsl_calls}", "clientOid": "c-tpsl"}

        retry_pos = {
            "symbol": "AAPLUSDT",
            "posSide": "long",
            "total": "1.5",
            "available": "1.5",
            "avgPrice": "332.10",
            "markPrice": "332.20",
        }
        retry_client = _SeqTpslClient(
            retry_pos,
            [RuntimeError("HTTP 400 code=31008: No position in this position")],
        )
        book3c = _book(tdir, "tpsl31008ok")
        slept: list[float] = []
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=retry_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=331.57), patch.object(
            router_mod, "_fetch_hub_mark", return_value=332.19
        ), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
        ), patch.object(router_mod.time, "sleep", side_effect=lambda s: slept.append(float(s))):
            pid = router_mod.open_position(
                symbol="AAPL/USDT:USDT",
                side="long",
                size_usd=500.0,
                price=331.57,
                meta={"atr": 2.0},
                book=book3c,
            )
        opens = book3c.list_open()
        _assert(len(opens) == 1, opens)
        _assert(opens[0]["position_id"] == pid, opens[0])
        _assert(retry_client.tpsl_calls == 2, retry_client.tpsl_calls)
        _assert(retry_client.closed == 0, retry_client.closed)
        _assert(slept == [0.6], slept)
        _assert((opens[0].get("meta") or {}).get("hub_tpsl_order_id") == "tpsl-2", opens[0])
        _assert((opens[0].get("meta") or {}).get("hub_qty") == "1.5", opens[0])

        # 3d) 31008 exhausted: same backoff, then main's fail-closed flatten.
        class _Always31008(_HubClient):
            def place_position_tpsl(self, *args, **kwargs):
                self.tpsl_calls += 1
                raise RuntimeError("HTTP 400 code=31008: No position in this position")

        exhaust_client = _Always31008(ltc_pos)
        book3d = _book(tdir, "tpsl31008fail")
        slept_ex: list[float] = []
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", return_value=exhaust_client
        ), patch.object(router_mod, "_qty_ref_price", return_value=58.02), patch.object(
            router_mod, "_fetch_hub_mark", return_value=59.80
        ), patch.object(router_mod, "_find_hub_position", return_value=ltc_pos), patch(
            "exec.bitget_hub.price_decimals_for_symbol", return_value=2
        ), patch.object(
            router_mod.time, "sleep", side_effect=lambda s: slept_ex.append(float(s))
        ):
            raised = False
            try:
                router_mod.open_position(
                    symbol="LTC/USDT:USDT",
                    side="short",
                    size_usd=500.0,
                    price=58.02,
                    meta={"atr": 1.2},
                    book=book3d,
                )
            except HubTpslError as exc:
                raised = True
                _assert("31008" in str(exc), str(exc))
        _assert(raised, "exhausted 31008 must fail-closed")
        _assert(exhaust_client.tpsl_calls == 4, exhaust_client.tpsl_calls)
        _assert(exhaust_client.placed == 1, exhaust_client.placed)
        _assert(exhaust_client.closed == 1, exhaust_client.closed)
        _assert(slept_ex == [0.6, 1.2, 2.0], slept_ex)
        _assert(book3d.list_open() == [], book3d.list_open())

        # 4) Pipeline records the skip, no fill.
        os.environ["EXEC_MODE"] = "paper"
        os.environ["AGENT_MODE"] = "rules"
        os.environ.pop("AGENT_LLM", None)
        os.environ["ALLOW_LONG"] = "1"
        os.environ["ALLOW_SHORT"] = "1"
        os.environ["RSI_LONG_MAX"] = "30"
        os.environ["BTC_FILTERS_ENABLED"] = "0"
        # Isolate from ambient data/pair_blocks.json so a live pair block on BTC
        # does not pre-empt the price-mismatch path under test.
        os.environ["PAIR_BLOCKER_ENABLED"] = "0"
        os.environ["PAIR_BLOCKS_PATH"] = str(tdir / "pair_blocks.json")
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

    print(
        "smoke_hub_price_scale OK: pre-open skip + flatten fill + keep matched "
        "+ tpsl fail-closed + pipeline"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
