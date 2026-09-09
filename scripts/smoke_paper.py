"""Smoke: paper ENTER fill + open position; second ENTER same symbol denied; close PnL.

Exit 0 on success. Paper-only; no exchange / network / API keys.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.pipeline import evaluate_candidate  # noqa: E402
from exec.account import PaperAccount  # noqa: E402
from exec.paper import PaperBook, close_paper, list_open, open_paper  # noqa: E402
from risk.gate import RiskGate, RiskLimits, RiskState  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ.pop("AGENT_LLM", None)

    with tempfile.TemporaryDirectory(prefix="bitget_paper_smoke_") as tmp:
        tmp_path = Path(tmp)
        fills = tmp_path / "paper_fills.jsonl"
        positions = tmp_path / "paper_positions.json"
        decisions = tmp_path / "decisions.jsonl"
        state_path = tmp_path / "risk_state.json"

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
            state_path=state_path,
            persist=True,
        )
        acct = PaperAccount.load(
            tmp_path / "paper_account.json",
            start_balance=10000.0,
            persist=True,
        )
        gate.account = acct
        book = PaperBook(
            gate=gate,
            fills_file=fills,
            positions_file=positions,
            account=acct,
        )

        bull = {
            "symbol": "BTC/USDT:USDT",
            "type": "BULLISH_DIV",
            "price": 65000.0,
            "rsi": 42.0,
        }

        # 1) Fake ENTER path via pipeline -> fill + open position
        out1 = evaluate_candidate(
            bull, gate, decisions_path=decisions, paper_book=book
        )
        print(
            f"ENTER1 action={out1['action']} allowed={out1['allowed']} "
            f"pos={out1.get('position_id')} fill={out1.get('fill_id')}"
        )
        _assert(out1["action"] == "ENTER", out1)
        _assert(out1["allowed"] is True, out1)
        _assert(out1.get("position_id"), "expected position_id")
        _assert(out1.get("fill_id"), "expected fill_id")
        _assert(out1.get("paper_error") is None, out1)

        opens = list_open(book=book)
        print(f"open positions after ENTER1: {opens}")
        _assert(len(opens) == 1, f"expected 1 open, got {len(opens)}")
        _assert(opens[0]["symbol"] == bull["symbol"], opens[0])
        _assert(positions.exists(), "paper_positions.json missing")
        _assert(fills.exists(), "paper_fills.jsonl missing")

        fill_lines = fills.read_text(encoding="utf-8").strip().splitlines()
        _assert(len(fill_lines) == 1, f"expected 1 fill, got {len(fill_lines)}")
        fill0 = json.loads(fill_lines[0])
        print(f"sample fill: {json.dumps(fill0, ensure_ascii=False)}")
        _assert(fill0["event"] == "open", fill0)
        _assert(fill0["symbol"] == bull["symbol"], fill0)
        _assert(fill0["side"] == "long", fill0)

        dec_lines = decisions.read_text(encoding="utf-8").strip().splitlines()
        row0 = json.loads(dec_lines[0])
        _assert(row0.get("fill_id") == out1["fill_id"], row0)
        _assert(row0.get("position_id") == out1["position_id"], row0)

        # Risk book should also show one open
        _assert(len(gate.state.open_positions) == 1, gate.state.open_positions)

        # 2) Second ENTER same symbol -> risk deny, no new fill
        out2 = evaluate_candidate(
            bull, gate, decisions_path=decisions, paper_book=book
        )
        print(
            f"ENTER2 action={out2['action']} allowed={out2['allowed']} "
            f"reason={out2.get('reason')} pos={out2.get('position_id')}"
        )
        _assert(out2["action"] == "ENTER", out2)
        _assert(out2["allowed"] is False, out2)
        _assert(out2["reason"] == "one_pos_per_symbol", out2)
        _assert(out2.get("position_id") is None, out2)
        _assert(out2.get("fill_id") is None, out2)

        fill_lines2 = fills.read_text(encoding="utf-8").strip().splitlines()
        _assert(len(fill_lines2) == 1, f"denied should not add fill: {fill_lines2}")
        opens2 = list_open(book=book)
        _assert(len(opens2) == 1, opens2)

        # 3) SKIP path -> no fill
        skip_cand = {
            "symbol": "ETH/USDT:USDT",
            "type": "BULLISH_DIV",
            "price": 3000.0,
            "rsi": 90.0,
        }
        out_skip = evaluate_candidate(
            skip_cand, gate, decisions_path=decisions, paper_book=book
        )
        print(f"SKIP action={out_skip['action']} fill={out_skip.get('fill_id')}")
        _assert(out_skip["action"] == "SKIP", out_skip)
        _assert(out_skip.get("fill_id") is None, out_skip)
        _assert(len(fills.read_text(encoding="utf-8").strip().splitlines()) == 1, "skip should not add fill")

        # 4) Optional close realizes PnL
        exit_price = 66000.0  # +~1.538% on long 50 => ~0.769 pnl
        closed = close_paper(out1["position_id"], exit_price, gate=gate, book=book)
        print(f"CLOSE: {closed}")
        _assert(closed["realized_pnl"] > 0, closed)
        expected = 50.0 * ((exit_price / 65000.0) - 1.0)
        _assert(abs(closed["realized_pnl"] - expected) < 1e-6, (closed, expected))
        _assert(len(list_open(book=book)) == 0, "expected flat book")
        _assert(len(gate.state.open_positions) == 0, gate.state.open_positions)
        _assert(abs(gate.state.daily_pnl - expected) < 1e-6, gate.state.daily_pnl)

        fill_lines3 = fills.read_text(encoding="utf-8").strip().splitlines()
        _assert(len(fill_lines3) == 2, fill_lines3)
        close_fill = json.loads(fill_lines3[1])
        print(f"close fill: {json.dumps(close_fill, ensure_ascii=False)}")
        _assert(close_fill["event"] == "close", close_fill)
        _assert(close_fill["realized_pnl"] > 0, close_fill)

        # Direct open_paper API sanity (different symbol)
        pid2 = open_paper(
            "ETH/USDT:USDT",
            "short",
            40.0,
            3200.0,
            meta={"smoke": True},
            gate=gate,
            book=book,
        )
        _assert(pid2, "direct open_paper")
        _assert(len(list_open(book=book)) == 1, "expected 1 after direct open")

    print("smoke_paper OK: ENTER fill + deny dup + SKIP no fill + close PnL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


