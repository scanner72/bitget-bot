"""Smoke: AGENT_MODE rules ENTER/SKIP + llm unreachable fallback.

Exit 0 on success. Paper-only; does not require a live LLM.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.decide import build_llm_messages, decide  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _rules_mode() -> None:
    os.environ["AGENT_MODE"] = "rules"
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["RSI_LONG_MAX"] = "0"
    # Point LLM at nowhere so accidental llm path would fail loudly if mis-routed
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["OPENAI_TIMEOUT_SEC"] = "1"

    bull = {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 42.0,
    }
    d1 = decide(bull)
    print(f"rules ENTER: {d1}")
    _assert(d1["action"] == "ENTER", d1)
    _assert(d1["side"] == "long", d1)
    _assert(d1["size_usd"] == 50.0, d1)
    _assert("bias_long" in d1["rules_fired"], d1)
    _assert("llm_fallback" not in d1["rules_fired"], d1)
    _assert("llm" not in d1["rules_fired"], d1)

    skip = {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 82.0,
    }
    d2 = decide(skip)
    print(f"rules SKIP: {d2}")
    _assert(d2["action"] == "SKIP", d2)
    _assert("rsi_extreme_long" in d2["rules_fired"], d2)
    _assert("llm_fallback" not in d2["rules_fired"], d2)


def _llm_fallback_mode() -> None:
    os.environ["AGENT_MODE"] = "llm"
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["RSI_LONG_MAX"] = "0"
    # Unreachable port - connection refused / timeout
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["OPENAI_API_KEY"] = "test-key"
    os.environ["OPENAI_MODEL"] = "test-model"
    os.environ["OPENAI_TIMEOUT_SEC"] = "2"

    bull = {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 42.0,
    }
    d1 = decide(bull)
    print(f"llm fallback ENTER: {d1}")
    _assert(d1["action"] == "ENTER", d1)
    _assert(d1["side"] == "long", d1)
    _assert(d1["size_usd"] == 50.0, d1)
    _assert("llm_fallback" in d1["rules_fired"], d1)
    _assert("bias_long" in d1["rules_fired"], d1)
    _assert("llm_fallback" in str(d1.get("rationale", "")), d1)

    skip = {
        "symbol": "ETH/USDT:USDT",
        "type": "BEARISH_DIV",
        "price": 3000.0,
        "rsi": 18.0,
    }
    d2 = decide(skip)
    print(f"llm fallback SKIP: {d2}")
    _assert(d2["action"] == "SKIP", d2)
    _assert("llm_fallback" in d2["rules_fired"], d2)
    _assert("rsi_extreme_short" in d2["rules_fired"], d2)


def _prompt_matches_rules() -> None:
    os.environ["PROPOSED_SIZE_USD"] = "100"
    os.environ["RSI_LONG_MAX"] = "30"
    os.environ["RSI_OVERBOUGHT"] = "70"
    os.environ["RSI_OVERSOLD"] = "30"
    os.environ["ALLOW_LONG"] = "1"
    os.environ["ALLOW_SHORT"] = "1"
    os.environ["ALLOWED_TYPES"] = "BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_DOWN"
    msgs = build_llm_messages(
        {
            "symbol": "ETH/USDT:USDT",
            "type": "BEARISH_DIV",
            "price": 2500.0,
            "rsi": 51.3,
        }
    )
    _assert(len(msgs) == 2, msgs)
    system = msgs[0]["content"]
    user = msgs[1]["content"]
    _assert("decide_rules" in system, "prompt must name decide_rules")
    _assert("Do not add filters" in system, system[:200])
    _assert("LEVEL_CROSS_DOWN → long" in system, system)
    _assert("Shorts have no RSI_LONG_MAX" in system, system)
    _assert("Paper trading only; be conservative." not in system, system[:200])
    _assert("Paper trading only; be conservative" not in user, user[:300])
    _assert("rsi_long_max" in user, user)
    _assert("BEARISH_DIV" in user, user)


def main() -> int:
    _prompt_matches_rules()
    _rules_mode()
    _llm_fallback_mode()
    print("smoke_llm_decide OK: desk prompt + rules ENTER/SKIP + llm unreachable fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
