"""Smoke: paper account cash wallet + equity.

fresh 10000 -> open 50 -> cash 9950 equity 10000 -> close +pnl -> equity updates;
insufficient cash deny.

Exit 0 on success. Paper-only; no exchange / network / API keys.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exec.account import PaperAccount  # noqa: E402
from exec.paper import PaperBook, close_paper, open_paper  # noqa: E402
from risk.gate import RiskGate, RiskLimits, RiskState  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bitget_account_smoke_") as tmp:
        tmp_path = Path(tmp)
        acct_path = tmp_path / "paper_account.json"
        fills = tmp_path / "paper_fills.jsonl"
        positions = tmp_path / "paper_positions.json"
        state_path = tmp_path / "risk_state.json"

        acct = PaperAccount.load(acct_path, start_balance=10000.0, persist=True)
        print(f"fresh snapshot: {acct.snapshot()}")
        _assert(acct.start_balance == 10000.0, acct.start_balance)
        _assert(acct.cash == 10000.0, acct.cash)
        _assert(acct.realized_pnl == 0.0, acct.realized_pnl)
        _assert(acct.open_notional == 0.0, acct.open_notional)
        _assert(abs(acct.equity() - 10000.0) < 1e-9, acct.equity())

        gate = RiskGate(
            limits=RiskLimits(
                max_notional_usd=100000.0,
                max_daily_loss_usd=5000.0,
                max_positions=10,
                one_position_per_symbol=True,
                cooldown_sec=0.0,
                allowed_types=None,
            ),
            state=RiskState(),
            state_path=state_path,
            persist=True,
            account=acct,
        )
        book = PaperBook(
            gate=gate,
            fills_file=fills,
            positions_file=positions,
            account=acct,
        )

        # open 50
        pid = open_paper(
            "BTC/USDT:USDT",
            "long",
            50.0,
            65000.0,
            meta={"smoke": "account"},
            gate=gate,
            book=book,
        )
        print(f"after open 50: {acct.snapshot()} pos={pid}")
        _assert(abs(acct.cash - 9950.0) < 1e-9, acct.cash)
        _assert(abs(acct.open_notional - 50.0) < 1e-9, acct.open_notional)
        _assert(abs(acct.equity() - 10000.0) < 1e-9, acct.equity())
        _assert(abs(acct.realized_pnl - 0.0) < 1e-9, acct.realized_pnl)

        # risk.check also denies insufficient cash
        deny = gate.check(
            {"symbol": "ETH/USDT:USDT", "type": "BULLISH_DIV"},
            20000.0,
            account=acct,
        )
        print(f"insufficient check: {deny}")
        _assert(deny["allowed"] is False, deny)
        _assert(deny["reason"] == "insufficient_cash", deny)

        # direct can_open
        ok, reason = acct.can_open(20000.0)
        _assert(ok is False and reason == "insufficient_cash", (ok, reason))

        # open_paper raises on insufficient cash
        raised = False
        try:
            open_paper(
                "SOL/USDT:USDT",
                "long",
                20000.0,
                100.0,
                gate=gate,
                book=book,
            )
        except ValueError as exc:
            raised = True
            _assert("insufficient_cash" in str(exc), str(exc))
        _assert(raised, "expected ValueError insufficient_cash")

        # close with +pnl
        exit_price = 66000.0
        closed = close_paper(pid, exit_price, gate=gate, book=book)
        expected_pnl = 50.0 * ((exit_price / 65000.0) - 1.0)
        print(f"CLOSE: {closed}")
        print(f"after close: {acct.snapshot()}")
        _assert(abs(closed["realized_pnl"] - expected_pnl) < 1e-6, closed)
        _assert(abs(acct.open_notional - 0.0) < 1e-9, acct.open_notional)
        _assert(abs(acct.realized_pnl - expected_pnl) < 1e-6, acct.realized_pnl)
        # cash = start - 50 + 50 + pnl = start + pnl
        _assert(abs(acct.cash - (10000.0 + expected_pnl)) < 1e-6, acct.cash)
        _assert(abs(acct.equity() - (10000.0 + expected_pnl)) < 1e-6, acct.equity())

        # reload from disk
        reloaded = PaperAccount.load(acct_path, persist=True)
        _assert(abs(reloaded.cash - acct.cash) < 1e-9, reloaded.cash)
        _assert(abs(reloaded.realized_pnl - expected_pnl) < 1e-6, reloaded.realized_pnl)
        snap = reloaded.snapshot()
        _assert(snap["currency"] == "USDT", snap)
        _assert("equity" in snap and "start_balance" in snap, snap)
        print(f"reloaded snapshot (sample /equity shape): {snap}")

    print("smoke_account OK: cash wallet + equity + insufficient deny")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
