"""Agent decide: rules-first, optional LLM veto.

Paper-only policy. AGENT_MODE=rules|llm (default rules).
When llm: rules run first. LLM may only SKIP a rules ENTER. It cannot
ENTER a rules SKIP. LLM errors keep the rules ENTER (`llm_fallback`).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Literal

DecisionAction = Literal["ENTER", "SKIP", "REDUCE"]

# Bias maps (signal type -> side)
LONG_TYPES = {"BULLISH_DIV", "LEVEL_CROSS_DOWN"}
SHORT_TYPES = {"BEARISH_DIV", "LEVEL_CROSS_UP"}

_VALID_ACTIONS = {"ENTER", "SKIP", "REDUCE"}


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip()


def _agent_mode() -> str:
    mode = _env_str("AGENT_MODE", "rules").lower()
    if mode in {"llm", "rules"}:
        return mode
    # Back-compat: AGENT_LLM=1 -> llm
    if _env_str("AGENT_LLM", "0") in {"1", "true", "yes", "on"}:
        return "llm"
    return "rules"


def _allow_long() -> bool:
    """Long ENTER allowed when ALLOW_LONG=1 (v1 default: both sides)."""
    return _env_str("ALLOW_LONG", "1").lower() in {"1", "true", "yes", "on"}


def _allow_short() -> bool:
    return _env_str("ALLOW_SHORT", "1").lower() in {"1", "true", "yes", "on"}


def _rsi_thresholds() -> tuple[float, float]:
    """Overbought / oversold for extreme-RSI SKIP. Prefer signals.config."""
    ob, os_ = 70.0, 30.0
    try:
        from signals import config as sigcfg  # noqa: WPS433

        ob = float(getattr(sigcfg, "RSI_OVERBOUGHT", ob))
        os_ = float(getattr(sigcfg, "RSI_OVERSOLD", os_))
    except Exception:  # noqa: BLE001
        pass
    # Env overrides (optional)
    ob = _env_float("RSI_OVERBOUGHT", ob)
    os_ = _env_float("RSI_OVERSOLD", os_)
    return ob, os_


def _proposed_size_usd(context: dict[str, Any] | None = None) -> float:
    if context and context.get("proposed_size_usd") is not None:
        try:
            s = float(context["proposed_size_usd"])
            if s > 0:
                return s
        except (TypeError, ValueError):
            pass
    size = _env_float("PROPOSED_SIZE_USD", 0.0)
    if size > 0:
        return size
    return _env_float("MAX_NOTIONAL_USD", 100.0)


def _missing_fields(candidate: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if candidate.get("price") is None:
        missing.append("price")
    if candidate.get("rsi") is None:
        missing.append("rsi")
    return missing


def _risk_context_summary(context: dict[str, Any] | None) -> dict[str, Any]:
    """Compact risk/context summary for the LLM prompt (no secrets)."""
    ctx = context or {}
    keys = (
        "proposed_size_usd",
        "max_notional_usd",
        "max_daily_loss_usd",
        "max_positions",
        "open_positions",
        "daily_pnl_usd",
        "symbol_open",
        "cooldown_sec",
        "allowed_types",
    )
    out: dict[str, Any] = {}
    for k in keys:
        if k in ctx and ctx[k] is not None:
            out[k] = ctx[k]
    # Always include size hint
    out.setdefault("proposed_size_usd", _proposed_size_usd(ctx))
    return out


def decide_rules(
    candidate: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rules-first decision (unchanged when AGENT_MODE=rules)."""
    context = context or {}
    size = _proposed_size_usd(context)
    rules: list[str] = []

    if not candidate:
        rules.append("empty_candidate")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": None,
            "rationale": "no candidate",
            "rules_fired": rules,
        }

    missing = _missing_fields(candidate)
    if missing:
        rules.append("missing_fields")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": None,
            "rationale": "missing " + ",".join(missing),
            "rules_fired": rules,
        }

    t = str(candidate.get("type", "")).upper().strip()
    rsi = float(candidate["rsi"])
    overbought, oversold = _rsi_thresholds()
    rules.append(f"type:{t}")

    side: str | None = None
    if t in LONG_TYPES:
        side = "long"
        rules.append("bias_long")
    elif t in SHORT_TYPES:
        side = "short"
        rules.append("bias_short")
    else:
        rules.append("unknown_type")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": None,
            "rationale": f"unknown type {t or '?'}",
            "rules_fired": rules,
        }

    # Extreme RSI filters
    if side == "long" and rsi >= overbought:
        rules.append("rsi_extreme_long")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": side,
            "rationale": f"long bias but rsi={rsi:.1f}>={overbought} overbought",
            "rules_fired": rules,
        }
    if side == "short" and rsi <= oversold:
        rules.append("rsi_extreme_short")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": side,
            "rationale": f"short bias but rsi={rsi:.1f}<={oversold} oversold",
            "rules_fired": rules,
        }

    # v1: longs only in RSI zone (pairs.rsi_long_max default 30)
    rsi_long_max = _env_float("RSI_LONG_MAX", 30.0)
    if side == "long" and rsi_long_max > 0 and rsi > rsi_long_max:
        rules.append("rsi_long_zone")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": side,
            "rationale": f"long RSI zone rsi={rsi:.1f}> {rsi_long_max:.0f}",
            "rules_fired": rules,
        }

    # Side gate (v1 trades both; ALLOW_LONG=0 is opt-out)
    if side == "long" and not _allow_long():
        rules.append("long_veto")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": side,
            "rationale": "long veto (ALLOW_LONG=0)",
            "rules_fired": rules,
        }
    if side == "short" and not _allow_short():
        rules.append("short_veto")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": side,
            "rationale": "short veto (ALLOW_SHORT=0)",
            "rules_fired": rules,
        }

    # MVP: fixed size (confidence scaling hook later)
    rules.append("size_fixed")
    # REDUCE reserved for later position-management rules / LLM
    action: DecisionAction = "ENTER"
    rules.append("enter")
    return {
        "action": action,
        "size_usd": float(size),
        "side": side,
        "rationale": f"{side} ENTER on {t} rsi={rsi:.1f} size={size:.2f}",
        "rules_fired": rules,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse strict JSON object; tolerate fences and Qwen <think> traces."""
    s = (text or "").strip()
    if not s:
        raise ValueError("empty LLM content")
    lower = s.lower()
    if "<think>" in lower:
        end = lower.find("</think>")
        if end >= 0:
            s = s[end + len("</think>") :].strip()
        else:
            raise ValueError("LLM content is unfinished <think> (raise max_tokens)")
    if s.startswith("```"):
        lines = s.splitlines()
        # drop first fence line and optional trailing fence
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("no JSON object in LLM content")
    obj, _end = json.JSONDecoder().raw_decode(s[start:])
    if not isinstance(obj, dict):
        raise ValueError("LLM JSON root must be object")
    return obj


def _validate_llm_decision(obj: dict[str, Any]) -> dict[str, Any]:
    action = str(obj.get("action", "")).upper().strip()
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid action: {action!r}")

    try:
        size = float(obj.get("size_usd"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid size_usd: {obj.get('size_usd')!r}") from exc
    if size < 0 or size != size:  # NaN check
        raise ValueError(f"invalid size_usd: {size}")

    side_raw = obj.get("side", None)
    if side_raw is None or (isinstance(side_raw, str) and side_raw.strip() == ""):
        side: str | None = None
    else:
        side = str(side_raw).strip().lower()
        if side not in {"long", "short"}:
            raise ValueError(f"invalid side: {side_raw!r}")

    rationale = obj.get("rationale", "")
    if rationale is None:
        rationale = ""
    rationale = str(rationale)

    if action == "SKIP":
        size = 0.0
    elif size <= 0:
        raise ValueError("size_usd must be > 0 for ENTER/REDUCE")

    if action == "ENTER" and side is None:
        raise ValueError("ENTER requires side long|short")

    return {
        "action": action,
        "size_usd": float(size),
        "side": side,
        "rationale": rationale or f"llm {action}",
        "rules_fired": ["llm"],
    }


def _llm_chat_completions(
    candidate: dict[str, Any] | None,
    context: dict[str, Any] | None,
    rules_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call OpenAI-compatible Chat Completions; return validated decision."""
    base = _env_str("OPENAI_BASE_URL", "http://127.0.0.1:8787/v1").rstrip("/")
    api_key = _env_str("OPENAI_API_KEY", "")
    model = _env_str("OPENAI_MODEL", "gpt-4o-mini")
    timeout = _env_float("OPENAI_TIMEOUT_SEC", 20.0)
    if timeout <= 0:
        timeout = 20.0

    risk_summary = _risk_context_summary(context)
    user_payload = {
        "candidate": candidate,
        "risk_context": risk_summary,
        "rules_decision": rules_decision or {},
        "instructions": (
            "Return ONLY a JSON object with keys: "
            "action (ENTER|SKIP|REDUCE), size_usd (number), "
            "side (long|short|null), rationale (string). "
            "Rules already said ENTER. SKIP or REDUCE = veto (do not trade). "
            "ENTER = confirm. Do not change side. size_usd is ignored. "
            "Paper trading only; be conservative."
        ),
    }
    system = (
        "You are a paper-trading veto agent. "
        "Deterministic rules already approved this candidate. "
        "You may SKIP (veto) or ENTER (confirm). You cannot originate a trade. "
        "Respond with a single JSON object only. No markdown, no thinking, no extra text. "
        "The first character of the reply must be '{'."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]
    url = f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "bitget-desk/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _post(
        with_json_object: bool, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "messages": messages,
            "max_tokens": 800,
        }
        if with_json_object:
            payload["response_format"] = {"type": "json_object"}
        if extra:
            payload.update(extra)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM envelope is not an object")
        return parsed

    use_json_object = "groq.com" not in base.lower()
    extras: list[dict[str, Any] | None] = [None]
    if "groq.com" in base.lower() and "qwen" in model.lower():
        extras = [
            {"chat_template_kwargs": {"enable_thinking": False}},
            {"reasoning_effort": "none"},
            None,
        ]
    envelope: dict[str, Any] | None = None
    last_err: Exception | None = None
    for extra in extras:
        try:
            envelope = _post(use_json_object, extra)
            break
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                detail = str(exc.reason or "")
            last_err = RuntimeError(f"LLM HTTP {exc.code}: {detail}")
            if exc.code not in {400, 404, 422}:
                raise last_err from exc
            continue
    if envelope is None:
        raise last_err or RuntimeError("LLM request failed")
    choices = envelope.get("choices") or []
    if not choices:
        raise ValueError("LLM response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        # Some providers return content parts
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        content = "".join(parts)
    if not isinstance(content, str):
        raise ValueError("LLM message content not a string")
    try:
        parsed = _extract_json_object(content)
    except Exception:
        try:
            dump = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "data", "_llm_last.txt"
            )
            with open(dump, "w", encoding="utf-8") as fh:
                fh.write(content[:4000])
        except Exception:
            pass
        raise
    return _validate_llm_decision(parsed)


def _attach_llm_fallback(rules_out: dict[str, Any], err: str) -> dict[str, Any]:
    rules = list(rules_out.get("rules_fired") or [])
    if "llm_fallback" not in rules:
        rules.insert(0, "llm_fallback")
    return {
        **rules_out,
        "rules_fired": rules,
        "rationale": f"{rules_out.get('rationale')} (llm_fallback: {err})",
    }


def decide(
    candidate: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide ENTER | SKIP | REDUCE.

    AGENT_MODE=rules (default): pure rules path.
    AGENT_MODE=llm: rules first. LLM is called only on rules ENTER and may
    SKIP (veto). It cannot ENTER a rules SKIP. On LLM failure/timeout keep
    the rules ENTER and set rules_fired including llm_fallback.

    Returns:
        {
          "action": "ENTER" | "SKIP" | "REDUCE",
          "size_usd": float,
          "side": "long" | "short" | None,
          "rationale": str,
          "rules_fired": list[str],
        }
    """
    rules_out = decide_rules(candidate, context)
    if _agent_mode() != "llm":
        return rules_out

    if str(rules_out.get("action", "SKIP")).upper() != "ENTER":
        return rules_out

    try:
        llm_out = _llm_chat_completions(candidate, context, rules_out)
    except Exception as exc:  # noqa: BLE001 - any failure -> keep rules ENTER
        err = f"{type(exc).__name__}: {exc}"
        return _attach_llm_fallback(rules_out, err)

    llm_action = str(llm_out.get("action", "")).upper()
    rules = list(rules_out.get("rules_fired") or [])
    if llm_action in {"SKIP", "REDUCE"}:
        if "llm_veto" not in rules:
            rules.insert(0, "llm_veto")
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": rules_out.get("side"),
            "rationale": f"{llm_out.get('rationale') or 'llm veto'} (llm_veto)",
            "rules_fired": rules,
        }

    if "llm" not in rules:
        rules.insert(0, "llm")
    rationale = str(rules_out.get("rationale") or "")
    extra = str(llm_out.get("rationale") or "").strip()
    if extra:
        rationale = f"{rationale} | llm: {extra}"
    return {**rules_out, "rules_fired": rules, "rationale": rationale}

