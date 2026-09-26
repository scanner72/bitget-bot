"""Smoke: reconcile closes ghosts, respects grace, keeps live hub positions.

Uses a temp paper book + mocked hub keys (no live orders).
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
    from exec import reconcile as rec_mod

    now = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc)
    old_ts = (now - timedelta(hours=2)).isoformat()
    fresh_ts = (now - timedelta(seconds=10)).isoformat()

    with tempfile.TemporaryDirectory(prefix="bitget_reconcile_smoke_") as td:
        tdir = Path(td)
        fills = tdir / "fills.jsonl"
        positions = tdir / "positions.json"
        acct = PaperAccount.load(
            tdir / "paper_account.json",
            start_balance=10000.0,
            persist=True,
        )
        book = PaperBook(
            fills_file=fills,
            positions_file=positions,
            account=acct,
        )

        book.open_paper("AVAX/USDT:USDT", "short", 100.0, 7.5, meta={"test": True})
        book.open_paper("SHIB/USDT:USDT", "short", 100.0, 5e-6, meta={"test": True})
        book.open_paper("SAMSUNG/USDT:USDT", "short", 100.0, 1.88, meta={"test": True})
        book.open_paper("DOGE/USDT:USDT", "long", 100.0, 0.1, meta={"test": True})
        book.open_paper(
            "ONDO/USDT:USDT",
            "short",
            100.0,
            0.8,
            meta={"exec_venue": "paper", "exec_reason": "not_on_demo"},
        )

        for p in book.list_open():
            sym = str(p.get("symbol") or "")
            if (
                sym.startswith("AVAX")
                or sym.startswith("SAMSUNG")
                or sym.startswith("ONDO")
                or sym.startswith("DOGE")
            ):
                p["opened_ts"] = old_ts
            elif sym.startswith("SHIB"):
                p["opened_ts"] = fresh_ts
            book.update_position(str(p["position_id"]), p)

        hub_keys = {("SAMSUNGUSDT", "short")}

        with patch.object(rec_mod, "exec_mode", return_value="hub_demo"), patch.object(
            rec_mod, "reconcile_enabled", return_value=True
        ), patch.object(rec_mod, "reconcile_grace_sec", return_value=60.0), patch.object(
            rec_mod, "_hub_open_keys", return_value=(hub_keys, None)
        ), patch.object(
            rec_mod,
            "_close_from_exchange",
            side_effect=lambda pos, **_k: (
                (float(pos["entry_price"]), {"hub_exec_pnl": 0.0, "close_price_source": "hub_fill"})
                if str(pos.get("symbol") or "").startswith("AVAX")
                else (None, {})
            ),
        ):
            events = rec_mod.reconcile_paper_with_exchange(
                book=book, force=True, now=now
            )

        actions = [e.get("action") for e in events]
        print("events", json.dumps(events, ensure_ascii=False, default=str))
        _assert("close" in actions, "expected ghost close")
        _assert("skip_grace" in actions, "expected grace skip")
        left = {p["symbol"].split("/")[0] for p in book.list_open()}
        print("left", left)
        _assert("AVAX" not in left, "AVAX ghost should be closed")
        _assert("SHIB" in left, "fresh SHIB should remain (grace)")
        _assert("SAMSUNG" in left, "SAMSUNG on hub must remain")
        _assert("DOGE" in left, "DOGE with no close fill must remain")
        _assert("ONDO" in left, "paper-live ONDO must not be reconciled")
        _assert("skip_paper_live" in actions, "expected paper-live skip")
        _assert("skip_no_close_fill" in actions, "expected skip when no close fill")
        _assert(
            all(e.get("error") != "no_close_price" for e in events),
            events,
        )

        closes = []
        for line in fills.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "close":
                closes.append(row)
        _assert(len(closes) == 1, f"expected 1 close fill, got {len(closes)}")
        _assert(
            (closes[0].get("meta") or {}).get("exit_status") == "exchange_closed",
            "exit_status",
        )

    # Bitget /trade/fills ignores ?symbol= — client must drop other pairs.
    from exec.bitget_hub import filter_fill_rows

    mixed = [
        {
            "symbol": "TRXUSDT",
            "tradeSide": "close_short",
            "posSide": "short",
            "execPrice": "0.33581",
            "execQty": "1499",
            "execPnl": "-3.56762",
            "orderId": "trx-oid",
            "execId": "trx-fill",
            "createdTime": 1789550208077,
        },
        {
            "symbol": "NEARUSDT",
            "tradeSide": "close_short",
            "posSide": "short",
            "execPrice": "0.33581",
            "execQty": "1499",
            "execPnl": "-3.56762",
            "orderId": "near-wrong-oid",
            "execId": "near-wrong-fill",
            "createdTime": 1789550208077,
        },
        {
            "symbol": "NEARUSDT",
            "tradeSide": "close_short",
            "posSide": "short",
            "execPrice": "2.407",
            "execQty": "212",
            "execPnl": "-13.568",
            "orderId": "near-oid",
            "execId": "near-fill",
            "createdTime": 1789550208077,
        },
    ]
    kept = filter_fill_rows(mixed, "NEAR/USDT:USDT")
    _assert(len(kept) == 2, kept)
    _assert(all(r["symbol"] == "NEARUSDT" for r in kept), kept)

    class _FillClient:
        def fills(self, **kwargs):  # noqa: ARG002
            return {"list": mixed}

    near_pos = {
        "symbol": "NEAR/USDT:USDT",
        "side": "short",
        "entry_price": 2.343,
        "qty": 213.4,
        "opened_ts": "2026-09-16T08:15:38+00:00",
        "meta": {"hub_qty": "212"},
    }
    with patch("exec.bitget_hub.BitgetUtaClient.from_env", return_value=_FillClient()):
        px, extras = rec_mod._close_from_exchange(near_pos)
    print("near close from mixed fills", px, extras)
    _assert(px is not None and abs(float(px) - 2.407) < 1e-9, px)
    _assert(abs(float(extras.get("hub_exec_pnl") or 0) - (-13.568)) < 1e-6, extras)
    _assert(abs(float(extras.get("hub_close_qty") or 0) - 212) < 1e-6, extras)
    _assert(int(extras.get("hub_fills_skipped_other_symbol") or 0) >= 1, extras)
    _assert(extras.get("hub_close_qty_match") == "hub_qty", extras)

    wrong_only = {
        "symbol": "NEAR/USDT:USDT",
        "side": "short",
        "entry_price": 2.343,
        "opened_ts": "2026-09-16T08:15:38+00:00",
        "meta": {"hub_qty": "212"},
    }

    class _WrongQtyClient:
        def fills(self, **kwargs):  # noqa: ARG002
            return {"list": [mixed[1]]}

    with patch("exec.bitget_hub.BitgetUtaClient.from_env", return_value=_WrongQtyClient()):
        px_bad, extras_bad = rec_mod._close_from_exchange(wrong_only)
    print("near qty mismatch", px_bad, extras_bad)
    _assert(px_bad is None, px_bad)
    _assert(extras_bad.get("close_price_source") == "rejected_qty_mismatch", extras_bad)

    print("smoke_reconcile OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
