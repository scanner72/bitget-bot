"""Smoke: fake candidates prove risk allow then deny (dup symbol, daily loss).

Exit 0 on success. Paper-only; no exchange.
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

from risk.gate import RiskGate, RiskLimits, RiskState  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    os.environ["PAIR_BLOCKER_ENABLED"] = "0"
    os.environ["TF_BLOCKER_ENABLED"] = "0"
    os.environ.pop("PAIR_BLOCKS_PATH", None)

    with tempfile.TemporaryDirectory(prefix="bitget_risk_smoke_") as tmp:
        tmp_path = Path(tmp)
        state_path = tmp_path / "risk_state.json"
        limits = RiskLimits(
            max_notional_usd=100.0,
            max_daily_loss_usd=50.0,
            max_positions=3,
            one_position_per_symbol=True,
            cooldown_sec=900.0,
            allowed_types=None,
        )
        gate = RiskGate(limits=limits, state=RiskState(), state_path=state_path, persist=True)

        cand_a = {"symbol": "BTC/USDT:USDT", "type": "BULLISH_DIV"}
        cand_b = {"symbol": "ETH/USDT:USDT", "type": "BEARISH_DIV"}

        # 1) Allow first entry
        r1 = gate.check(cand_a, 50.0)
        print(f"check1 allow={r1['allowed']} reason={r1['reason']}")
        _assert(r1["allowed"] is True and r1["reason"] == "ok", f"expected allow: {r1}")
        gate.record_open(cand_a["symbol"], 50.0, meta={"type": cand_a["type"]})

        # 2) Deny duplicate symbol (one pos / symbol)
        r2 = gate.check(cand_a, 50.0)
        print(f"check2 allow={r2['allowed']} reason={r2['reason']}")
        _assert(
            r2["allowed"] is False and r2["reason"] == "one_pos_per_symbol",
            f"expected one_pos_per_symbol deny: {r2}",
        )

        # 3) Allow different symbol
        r3 = gate.check(cand_b, 40.0)
        print(f"check3 allow={r3['allowed']} reason={r3['reason']}")
        _assert(r3["allowed"] is True, f"expected allow other symbol: {r3}")
        gate.record_open(cand_b["symbol"], 40.0)

        # 4) Deny oversize notional
        cand_c = {"symbol": "SOL/USDT:USDT", "type": "BULLISH_DIV"}
        r4 = gate.check(cand_c, 250.0)
        print(f"check4 allow={r4['allowed']} reason={r4['reason']}")
        _assert(
            r4["allowed"] is False and r4["reason"] == "max_notional",
            f"expected max_notional: {r4}",
        )

        # 5) Daily loss kill switch
        gate.record_close(cand_b["symbol"], realized_pnl=-60.0)
        r5 = gate.check(cand_c, 50.0)
        print(f"check5 allow={r5['allowed']} reason={r5['reason']}")
        _assert(
            r5["allowed"] is False and r5["reason"] == "daily_loss_kill",
            f"expected daily_loss_kill: {r5}",
        )

        # Persist round-trip
        _assert(state_path.exists(), "risk_state.json missing")
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        print(f"persisted daily_pnl={raw.get('daily_pnl')} opens={len(raw.get('open_positions') or [])}")
        _assert(float(raw["daily_pnl"]) <= -50.0, "daily pnl not persisted")

        # Reload gate and confirm kill still active
        gate2 = RiskGate(limits=limits, state_path=state_path, persist=True)
        r6 = gate2.check(cand_c, 50.0)
        print(f"check6(reload) allow={r6['allowed']} reason={r6['reason']}")
        _assert(r6["allowed"] is False and r6["reason"] == "daily_loss_kill", f"reload kill: {r6}")

        # 7) Hard ban: USDCUSDT never opens
        gate_ok = RiskGate(
            limits=RiskLimits(
                max_notional_usd=100.0,
                max_daily_loss_usd=150.0,
                max_positions=15,
                cooldown_sec=0.0,
                allowed_types=None,
            ),
            state=RiskState(),
            persist=False,
        )
        r7 = gate_ok.check({"symbol": "USDC/USDT:USDT", "type": "BULLISH_DIV"}, 50.0)
        print(f"check7 USDC deny allow={r7['allowed']} reason={r7['reason']}")
        _assert(
            r7["allowed"] is False and str(r7["reason"]).startswith("symbol_denied:USDCUSDT"),
            f"expected symbol_denied USDCUSDT: {r7}",
        )
        r8 = gate_ok.check({"symbol": "BTC/USDT:USDT", "type": "BULLISH_DIV"}, 50.0)
        _assert(r8["allowed"] is True, f"BTC must still allow: {r8}")
        os.environ["MEME_DENY_ENABLED"] = "1"
        os.environ.pop("MEME_DENY_ALLOW", None)
        r9 = gate_ok.check({"symbol": "1000PEPE/USDT:USDT", "type": "BULLISH_DIV"}, 50.0)
        print(f"check9 meme deny allow={r9['allowed']} reason={r9['reason']}")
        _assert(
            r9["allowed"] is False and str(r9["reason"]).startswith("symbol_denied:1000PEPEUSDT"),
            f"expected symbol_denied 1000PEPE: {r9}",
        )

    print("smoke_risk OK: allow + deny (dup symbol, max_notional, daily_loss_kill, USDCUSDT, meme)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
