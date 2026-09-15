"""Smoke: AGENT_MODE rules ENTER/SKIP + llm veto + unreachable fallback.

Exit 0 on success. Paper-only; does not require a live LLM.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.decide import decide  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _bull() -> dict:
    return {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 42.0,
    }


def _overbought() -> dict:
    return {
        "symbol": "BTC/USDT:USDT",
        "type": "BULLISH_DIV",
        "price": 65000.0,
        "rsi": 82.0,
    }


def _rules_mode() -> None:
    os.environ["AGENT_MODE"] = "rules"
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["RSI_LONG_MAX"] = "0"
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["OPENAI_TIMEOUT_SEC"] = "1"

    d1 = decide(_bull())
    print(f"rules ENTER: {d1}")
    _assert(d1["action"] == "ENTER", d1)
    _assert(d1["side"] == "long", d1)
    _assert(d1["size_usd"] == 50.0, d1)
    _assert("bias_long" in d1["rules_fired"], d1)
    _assert("llm_fallback" not in d1["rules_fired"], d1)
    _assert("llm" not in d1["rules_fired"], d1)

    d2 = decide(_overbought())
    print(f"rules SKIP: {d2}")
    _assert(d2["action"] == "SKIP", d2)
    _assert("rsi_extreme_long" in d2["rules_fired"], d2)
    _assert("llm_fallback" not in d2["rules_fired"], d2)


def _llm_fallback_mode() -> None:
    os.environ["AGENT_MODE"] = "llm"
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["RSI_LONG_MAX"] = "0"
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["OPENAI_API_KEY"] = "test-key"
    os.environ["OPENAI_MODEL"] = "test-model"
    os.environ["OPENAI_TIMEOUT_SEC"] = "2"

    d1 = decide(_bull())
    print(f"llm fallback ENTER: {d1}")
    _assert(d1["action"] == "ENTER", d1)
    _assert(d1["side"] == "long", d1)
    _assert(d1["size_usd"] == 50.0, d1)
    _assert("llm_fallback" in d1["rules_fired"], d1)
    _assert("bias_long" in d1["rules_fired"], d1)
    _assert("llm_fallback" in str(d1.get("rationale", "")), d1)

    d2 = decide(_overbought())
    print(f"llm skip no-call: {d2}")
    _assert(d2["action"] == "SKIP", d2)
    _assert("rsi_extreme_long" in d2["rules_fired"], d2)
    _assert("llm_fallback" not in d2["rules_fired"], d2)
    _assert("llm_veto" not in d2["rules_fired"], d2)


def _llm_veto_mode() -> None:
    os.environ["AGENT_MODE"] = "llm"
    os.environ["PROPOSED_SIZE_USD"] = "50"
    os.environ["RSI_LONG_MAX"] = "0"

    skip_llm = {
        "action": "SKIP",
        "size_usd": 0.0,
        "side": None,
        "rationale": "crowded book",
        "rules_fired": ["llm"],
    }
    with patch("agent.decide._llm_chat_completions", return_value=skip_llm) as mocked:
        d = decide(_bull())
        print(f"llm veto SKIP: {d}")
        _assert(d["action"] == "SKIP", d)
        _assert(d["size_usd"] == 0.0, d)
        _assert(d["side"] == "long", d)
        _assert("llm_veto" in d["rules_fired"], d)
        _assert("bias_long" in d["rules_fired"], d)
        mocked.assert_called_once()

    force_enter = {
        "action": "ENTER",
        "size_usd": 999.0,
        "side": "short",
        "rationale": "override",
        "rules_fired": ["llm"],
    }
    with patch("agent.decide._llm_chat_completions", return_value=force_enter) as mocked:
        d = decide(_overbought())
        print(f"llm cannot originate: {d}")
        _assert(d["action"] == "SKIP", d)
        _assert("rsi_extreme_long" in d["rules_fired"], d)
        _assert("llm_veto" not in d["rules_fired"], d)
        mocked.assert_not_called()

    confirm = {
        "action": "ENTER",
        "size_usd": 999.0,
        "side": "short",
        "rationale": "ok",
        "rules_fired": ["llm"],
    }
    with patch("agent.decide._llm_chat_completions", return_value=confirm) as mocked:
        d = decide(_bull())
        print(f"llm confirm ENTER: {d}")
        _assert(d["action"] == "ENTER", d)
        _assert(d["side"] == "long", d)
        _assert(d["size_usd"] == 50.0, d)
        _assert("llm" in d["rules_fired"], d)
        _assert("bias_long" in d["rules_fired"], d)
        mocked.assert_called_once()


def main() -> int:
    _rules_mode()
    _llm_fallback_mode()
    _llm_veto_mode()
    print("smoke_llm_decide OK: rules + llm veto + unreachable fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
