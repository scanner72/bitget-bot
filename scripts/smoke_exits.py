"""Smoke: synthetic candle path proves SL and TP2 closes via risk.exits.

No network. Exit 0 on success. Paper-only tempfile book.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exec.account import PaperAccount
from exec.paper import PaperBook, open_paper
from risk.atr import levels_from_atr
from risk.exits import ExitConfig, apply_position_updates, evaluate_exit


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows: open,high,low,close"""
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="15min", tz="UTC")
    data = {
        "open": [r[0] for r in rows],
        "high": [r[1] for r in rows],
        "low": [r[2] for r in rows],
        "close": [r[3] for r in rows],
        "volume": [1.0] * len(rows),
    }
    return pd.DataFrame(data, index=idx)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bitget_exits_smoke_") as tmp:
        tmp_path = Path(tmp)
        fills = tmp_path / "fills.jsonl"
        positions = tmp_path / "positions.json"
        acct_path = tmp_path / "account.json"
        acct = PaperAccount.load(acct_path, start_balance=10_000.0, persist=True)
        book = PaperBook(
            fills_file=fills,
            positions_file=positions,
            account=acct,
            gate=None,
        )

        entry = 100.0
        atr = 2.0  # explicit; levels: SL=98, TP1=103, TP2=105 long
        levels = levels_from_atr(entry, "long", atr)
        _assert(abs(levels["sl"] - 98.0) < 1e-9, levels)
        _assert(abs(levels["tp1"] - 103.0) < 1e-9, levels)
        _assert(abs(levels["tp2"] - 105.0) < 1e-9, levels)

        # --- Case A: SL hit ---
        meta_a = dict(levels)
        meta_a["original_sl"] = levels["sl"]
        pid_a = open_paper(
            "TEST/USDT:USDT",
            "long",
            100.0,
            entry,
            meta=meta_a,
            book=book,
        )
        pos_a = next(p for p in book.list_open() if p["position_id"] == pid_a)
        # candle low pierces SL
        df_sl = _df([(100, 100.5, 97.5, 98.0)] * 20)
        ev_sl = evaluate_exit(
            pos_a,
            candle_high=100.5,
            candle_low=97.5,
            mark_price=98.0,
            df=df_sl,
            cfg=ExitConfig(
                be_hours=999,
                max_hold_hours=999,
                max_loss_pct_of_margin=0,
                early_close_hours=0,
                enable_trailing=True,
            ),
        )
        print(f"SL event: action={ev_sl.action} status={ev_sl.status} px={ev_sl.close_price}")
        _assert(ev_sl.action == "close" and ev_sl.status == "sl_hit", ev_sl)
        closed_a = book.close_paper(pid_a, float(ev_sl.close_price), meta={"exit_status": ev_sl.status})
        _assert(closed_a.get("exit_status") == "sl_hit", closed_a)
        _assert(closed_a["realized_pnl"] < 0, closed_a)

        # --- Case B: TP2 hit ---
        meta_b = dict(levels)
        meta_b["original_sl"] = levels["sl"]
        pid_b = open_paper(
            "TEST2/USDT:USDT",
            "long",
            100.0,
            entry,
            meta=meta_b,
            book=book,
        )
        pos_b = next(p for p in book.list_open() if p["position_id"] == pid_b)
        ev_tp2 = evaluate_exit(
            pos_b,
            candle_high=105.5,
            candle_low=104.0,
            mark_price=105.2,
            df=_df([(104, 105.5, 104.0, 105.2)] * 20),
            cfg=ExitConfig(
                be_hours=999,
                max_hold_hours=999,
                max_loss_pct_of_margin=0,
                early_close_hours=0,
                enable_trailing=True,
            ),
        )
        print(f"TP2 event: action={ev_tp2.action} status={ev_tp2.status} px={ev_tp2.close_price}")
        _assert(ev_tp2.action == "close" and ev_tp2.status == "tp2_hit", ev_tp2)
        closed_b = book.close_paper(pid_b, float(ev_tp2.close_price), meta={"exit_status": ev_tp2.status})
        _assert(closed_b.get("exit_status") == "tp2_hit", closed_b)
        _assert(closed_b["realized_pnl"] > 0, closed_b)

        # --- Case C: TP1 -> BE update (no close) ---
        meta_c = dict(levels)
        meta_c["original_sl"] = levels["sl"]
        pid_c = open_paper(
            "TEST3/USDT:USDT",
            "long",
            100.0,
            entry,
            meta=meta_c,
            book=book,
        )
        pos_c = next(p for p in book.list_open() if p["position_id"] == pid_c)
        ev_tp1 = evaluate_exit(
            pos_c,
            candle_high=103.2,
            candle_low=101.0,
            mark_price=103.0,
            df=_df([(101, 103.2, 101.0, 103.0)] * 20),
            cfg=ExitConfig(
                be_hours=999,
                max_hold_hours=999,
                max_loss_pct_of_margin=0,
                early_close_hours=0,
                enable_trailing=False,  # isolate TP1 BE
            ),
        )
        print(f"TP1 event: action={ev_tp1.action} status={ev_tp1.status} updates={ev_tp1.updates}")
        _assert(ev_tp1.action == "update", ev_tp1)
        _assert(ev_tp1.updates.get("tp1_hit") is True, ev_tp1.updates)
        _assert(abs(float(ev_tp1.updates["sl"]) - entry) < 1e-9, ev_tp1.updates)
        updated = apply_position_updates(pos_c, ev_tp1.updates)
        book.update_position(pid_c, updated)
        pos_c2 = next(p for p in book.list_open() if p["position_id"] == pid_c)
        _assert(abs(float(pos_c2["sl"]) - entry) < 1e-9, pos_c2)
        _assert(pos_c2.get("tp1_hit") is True or pos_c2["meta"].get("tp1_hit") is True, pos_c2)

        # cleanup remaining
        book.close_paper(pid_c, entry, meta={"exit_status": "smoke_cleanup"})

        print("smoke_exits OK: sl_hit + tp2_hit + tp1_be")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
