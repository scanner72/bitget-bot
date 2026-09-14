"""Smoke: rules-first agent.decide ENTER + SKIP cases; pipeline chain.

Exit 0 on success. Paper-only; no exchange / network.
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

from agent.decide import decide  # noqa: E402
from desk.pipeline import evaluate_candidate  # noqa: E402
from risk.gate import RiskGate, RiskLimits, RiskState  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["ALLOW_LONG"] = "1"
    os.environ["ALLOW_SHORT"] = "1"
    os.environ["RSI_LONG_MAX"] = "30"
    os.environ["BTC_FILTERS_ENABLED"] = "0"
    os.environ["RISK_USD_PER_TRADE"] = "2"
    os.environ["MAX_NOTIONAL_USD"] = "100"
    os.environ["EXEC_MODE"] = "paper"
    os.environ.pop("AGENT_LLM", None)

    bull = {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 28.0,
    }
    d1 = decide(bull)
    print(f"ENTER bull: {d1}")
    _assert(d1["action"] == "ENTER", f"expected ENTER: {d1}")
    _assert(d1["side"] == "long", f"expected long: {d1}")
    _assert(d1["size_usd"] == 50.0, f"size: {d1}")
    _assert("bias_long" in d1["rules_fired"], d1)

    lcd = {
        "symbol": "ETH/USDT:USDT",
        "type": "LEVEL_CROSS_DOWN",
        "price": 3200.0,
        "rsi": 25.0,
    }
    d2 = decide(lcd)
    print(f"ENTER lcd: {d2}")
    _assert(d2["action"] == "ENTER" and d2["side"] == "long", d2)

    bear = {
        "symbol": "SOL/USDT:USDT",
        "type": "BEARISH_DIV",
        "price": 140.0,
        "rsi": 58.0,
    }
    d3 = decide(bear)
    print(f"ENTER bear: {d3}")
    _assert(d3["action"] == "ENTER" and d3["side"] == "short", d3)

    lcu = {
        "symbol": "BTC/USDT:USDT",
        "type": "LEVEL_CROSS_UP",
        "price": 66000.0,
        "rsi": 48.0,
    }
    d4 = decide(lcu)
    print(f"ENTER lcu: {d4}")
    _assert(d4["action"] == "ENTER" and d4["side"] == "short", d4)

    d5 = decide({"symbol": "BTC/USDT:USDT", "type": "BULLISH_DIV", "price": 1.0})
    print(f"SKIP missing rsi: {d5}")
    _assert(d5["action"] == "SKIP" and "missing_fields" in d5["rules_fired"], d5)

    d6 = decide(None)
    print(f"SKIP empty: {d6}")
    _assert(d6["action"] == "SKIP", d6)

    d7 = decide(
        {
            "symbol": "BTC/USDT:USDT",
            "type": "BULLISH_DIV",
            "price": 65000.0,
            "rsi": 82.0,
        }
    )
    print(f"SKIP rsi high long: {d7}")
    _assert(d7["action"] == "SKIP" and "rsi_extreme_long" in d7["rules_fired"], d7)

    d_zone = decide(
        {
            "symbol": "BTC/USDT:USDT",
            "type": "BULLISH_DIV",
            "price": 65000.0,
            "rsi": 42.0,
        }
    )
    print(f"SKIP rsi long zone: {d_zone}")
    _assert(d_zone["action"] == "SKIP" and "rsi_long_zone" in d_zone["rules_fired"], d_zone)

    d8 = decide(
        {
            "symbol": "ETH/USDT:USDT",
            "type": "BEARISH_DIV",
            "price": 3000.0,
            "rsi": 18.0,
        }
    )
    print(f"SKIP rsi low short: {d8}")
    _assert(d8["action"] == "SKIP" and "rsi_extreme_short" in d8["rules_fired"], d8)

    with tempfile.TemporaryDirectory(prefix="bitget_decide_smoke_") as tmp:
        tmp_path = Path(tmp)
        decisions = tmp_path / "decisions.jsonl"
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
            state_path=tmp_path / "risk_state.json",
            persist=False,
        )

        out_enter = evaluate_candidate(bull, gate, decisions_path=decisions)
        print(f"pipeline ENTER: action={out_enter['action']} allowed={out_enter['allowed']}")
        _assert(out_enter["action"] == "ENTER", out_enter)
        _assert(out_enter["allowed"] is True, out_enter)
        _assert(out_enter["risk"] is not None, out_enter)

        skip_cand = {
            "symbol": "XRP/USDT:USDT",
            "type": "BULLISH_DIV",
            "price": 0.5,
            "rsi": 90.0,
        }
        out_skip = evaluate_candidate(skip_cand, gate, decisions_path=decisions)
        print(f"pipeline SKIP: action={out_skip['action']} risk={out_skip['risk']}")
        _assert(out_skip["action"] == "SKIP", out_skip)
        _assert(out_skip["risk"] is None, out_skip)

        lines = decisions.read_text(encoding="utf-8").strip().splitlines()
        _assert(len(lines) == 2, f"expected 2 JSONL rows, got {len(lines)}")
        row0 = json.loads(lines[0])
        row1 = json.loads(lines[1])
        print(f"jsonl[0]={row0}")
        print(f"jsonl[1]={row1}")
        _assert(row0["agent"]["action"] == "ENTER" and row0["risk"]["allowed"] is True, row0)
        _assert(row1["agent"]["action"] == "SKIP" and row1["risk"] is None, row1)

    print("smoke_decide OK: ENTER + SKIP + pipeline JSONL chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
