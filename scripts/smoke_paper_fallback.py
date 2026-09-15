"""Smoke: hub_demo paper-live fallback when pair is missing on Demo."""
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
    from exec import router as router_mod

    with tempfile.TemporaryDirectory(prefix="bitget_paper_fallback_") as td:
        tdir = Path(td)
        acct = PaperAccount.load(
            tdir / "paper_account.json",
            start_balance=10000.0,
            persist=True,
        )
        book = PaperBook(
            fills_file=tdir / "fills.jsonl",
            positions_file=tdir / "positions.json",
            account=acct,
        )

        class BoomClient:
            demo = True

            def place_perp_market(self, *args, **kwargs):
                raise RuntimeError("should not place on demo")

            def close_perp_market(self, *args, **kwargs):
                raise RuntimeError("should not close on demo")

            @classmethod
            def from_env(cls):
                return cls()

        env = {
            "EXEC_MODE": "hub_demo",
            "BITGET_DEMO": "1",
            "PAPER_FALLBACK": "1",
            "PAPER_FALLBACK_SLIPPAGE_BPS": "0",
        }
        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=False
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", BoomClient.from_env
        ), patch.object(router_mod, "_live_fill_price", return_value=(0.81, "live_mark")):
            pid = router_mod.open_position(
                symbol="ONDO/USDT:USDT",
                side="short",
                size_usd=100.0,
                price=0.80,
                meta={"atr": 0.01, "type": "BEARISH_DIV"},
                book=book,
            )
        opens = book.list_open()
        _assert(len(opens) == 1, opens)
        pos = opens[0]
        _assert(pos["position_id"] == pid, pos)
        meta = pos.get("meta") or {}
        _assert(meta.get("exec_venue") == "paper", meta)
        _assert(meta.get("exec_reason") == "not_on_demo", meta)
        _assert(abs(float(pos["entry_price"]) - 0.81) < 1e-9, pos)

        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "exec_mode", return_value="hub_demo"
        ), patch("exec.bitget_hub.BitgetUtaClient.from_env", BoomClient.from_env):
            closed = router_mod.close_position(pid, 0.79, book=book)
        _assert(closed.get("position_id") == pid, closed)
        _assert(len(book.list_open()) == 0, book.list_open())

        # 25100 after catalog said tradable
        book2 = PaperBook(
            fills_file=tdir / "fills2.jsonl",
            positions_file=tdir / "positions2.json",
            account=PaperAccount.load(
                tdir / "paper_account2.json",
                start_balance=10000.0,
                persist=True,
            ),
        )

        class MissingClient:
            demo = True

            def place_perp_market(self, *args, **kwargs):
                raise RuntimeError(
                    "Bitget HTTP 400 code=25100 msg=Trading pair XPLUSDT does not exist"
                )

            @classmethod
            def from_env(cls):
                return cls()

        with patch.dict(os.environ, env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", MissingClient.from_env
        ), patch.object(
            router_mod, "drop_demo_symbol"
        ) as drop, patch.object(
            router_mod, "_live_fill_price", return_value=(1.11, "live_mark")
        ):
            pid2 = router_mod.open_position(
                symbol="XPL/USDT:USDT",
                side="short",
                size_usd=100.0,
                price=1.10,
                meta={"atr": 0.02},
                book=book2,
            )
        drop.assert_called()
        pos2 = book2.list_open()[0]
        _assert(pid2 == pos2["position_id"], pos2)
        _assert((pos2.get("meta") or {}).get("exec_reason") == "hub_25100", pos2)

        from exec.demo_universe import NotOnDemoError, filter_to_demo_symbols

        book3 = PaperBook(
            fills_file=tdir / "fills3.jsonl",
            positions_file=tdir / "positions3.json",
            account=PaperAccount.load(
                tdir / "paper_account3.json",
                start_balance=10000.0,
                persist=True,
            ),
        )
        off_env = {
            "EXEC_MODE": "hub_demo",
            "BITGET_DEMO": "1",
            "PAPER_FALLBACK": "0",
        }
        with patch.dict(os.environ, off_env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=False
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", BoomClient.from_env
        ):
            raised = False
            try:
                router_mod.open_position(
                    symbol="ONDO/USDT:USDT",
                    side="short",
                    size_usd=100.0,
                    price=0.80,
                    meta={"atr": 0.01},
                    book=book3,
                )
            except NotOnDemoError:
                raised = True
        _assert(raised, "demo-only must skip missing pairs")
        _assert(book3.list_open() == [], book3.list_open())

        book4 = PaperBook(
            fills_file=tdir / "fills4.jsonl",
            positions_file=tdir / "positions4.json",
            account=PaperAccount.load(
                tdir / "paper_account4.json",
                start_balance=10000.0,
                persist=True,
            ),
        )
        with patch.dict(os.environ, off_env, clear=False), patch.object(
            router_mod, "symbol_tradable_on_demo", return_value=True
        ), patch.object(router_mod, "exec_mode", return_value="hub_demo"), patch(
            "exec.bitget_hub.BitgetUtaClient.from_env", MissingClient.from_env
        ), patch.object(router_mod, "drop_demo_symbol") as drop_off:
            raised = False
            try:
                router_mod.open_position(
                    symbol="XPL/USDT:USDT",
                    side="short",
                    size_usd=100.0,
                    price=1.10,
                    meta={"atr": 0.02},
                    book=book4,
                )
            except NotOnDemoError:
                raised = True
        _assert(raised, "25100 without fallback must skip")
        drop_off.assert_called()
        _assert(book4.list_open() == [], book4.list_open())

        with patch(
            "exec.demo_universe.demo_tradable_symbols",
            return_value={"BTCUSDT", "ETHUSDT"},
        ):
            kept = filter_to_demo_symbols(
                ["BTC/USDT:USDT", "ONDO/USDT:USDT", "ETH/USDT:USDT"]
            )
        _assert(kept == ["BTC/USDT:USDT", "ETH/USDT:USDT"], kept)

    print("smoke_paper_fallback OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
