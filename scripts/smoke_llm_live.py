"""Live LLM smoke: one decide() call via .env (Groq / OpenAI-compatible).

Does not print API keys. Exit 0 if rules_fired contains llm (not only llm_fallback).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)

from agent.decide import decide  # noqa: E402


def main() -> int:
    mode = (os.getenv("AGENT_MODE") or "").strip()
    model = (os.getenv("OPENAI_MODEL") or "").strip()
    base = (os.getenv("OPENAI_BASE_URL") or "").strip()
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    print(f"mode={mode} model={model} base={base} key={'set' if key else 'MISSING'}")
    if mode != "llm" or not key:
        print("FAIL: AGENT_MODE=llm and OPENAI_API_KEY required")
        return 1
    cand = {
        "symbol": "BTC/USDT:USDT",
        "type": "BEARISH_DIV",
        "price": 65000.0,
        "rsi": 62.0,
        "timeframe": "15m",
    }
    out = decide(cand, {"open_count": 0})
    rules = out.get("rules_fired") or []
    rationale = str(out.get("rationale") or "")
    # Never print Authorization / gsk_ blobs if a fallback message includes them.
    if "gsk_" in rationale.lower() or "bearer " in rationale.lower():
        rationale = rationale.split("(llm_fallback:")[0] + "(llm_fallback: [redacted])"
    print(
        "decision",
        {
            "action": out.get("action"),
            "side": out.get("side"),
            "size_usd": out.get("size_usd"),
            "rules_fired": rules,
            "rationale": rationale[:400],
        },
    )
    if "llm" in rules and "llm_fallback" not in rules:
        print("smoke_llm_live OK")
        return 0
    print("FAIL: expected live llm, got fallback or rules")
    try:
        import json
        import urllib.request

        req = urllib.request.Request(
            f"{base.rstrip('/')}/models",
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
                "User-Agent": "bitget-desk/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        ids = [x.get("id") for x in (data.get("data") or []) if isinstance(x, dict)]
        print("groq_models", ids[:20], "n=", len(ids))
    except Exception as exc:  # noqa: BLE001
        print("groq_models_error", type(exc).__name__, str(exc)[:200])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
