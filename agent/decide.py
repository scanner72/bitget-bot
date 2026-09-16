"""Agent decide: rules-first, optional OpenAI-compatible LLM with the same algorithm.

Paper-only policy. AGENT_MODE=rules|llm (default rules).
LLM prompt is a copy of decide_rules — not a conservative overlay.
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


def _allowed_types() -> list[str] | None:
    """Same parse as risk/gate.py ALLOWED_TYPES. None = all types allowed."""
    v = _env_str("ALLOWED_TYPES", "")
    if not v:
        return None
    parts = [p.strip().upper() for p in v.split(",") if p.strip()]
    return parts or None


def _rsi_long_max() -> float:
    return _env_float("RSI_LONG_MAX", 30.0)


def _algorithm_spec(context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live decide_rules + type filter numbers for the LLM (no secrets)."""
    overbought, oversold = _rsi_thresholds()
    return {
        "timeframe": "15m",
        "rsi_length": 14,
        "pivot_lookback_left": 5,
        "pivot_lookback_right": 5,
        "type_to_side": {
            "BULLISH_DIV": "long",
            "LEVEL_CROSS_DOWN": "long",
            "BEARISH_DIV": "short",
            "LEVEL_CROSS_UP": "short",
        },
        "allowed_types": _allowed_types(),
        "allow_long": _allow_long(),
        "allow_short": _allow_short(),
        "rsi_overbought": overbought,
        "rsi_oversold": oversold,
        "rsi_long_max": _rsi_long_max(),
        "proposed_size_usd": _proposed_size_usd(context),
    }


def _slim_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not candidate:
        return None
    keys = (
        "symbol",
        "type",
        "price",
        "level_price",
        "rsi",
        "timeframe",
        "bar_ts",
        "bar_index",
    )
    out = {k: candidate[k] for k in keys if k in candidate}
    t = out.get("type")
    if t is not None:
        out["type"] = str(t).upper().strip()
    return out


def build_llm_messages(
    candidate: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """System+user messages: copy of decide_rules, not a discretionary overlay."""
    spec = _algorithm_spec(context)
    allowed = spec["allowed_types"]
    allowed_txt = (
        "any of BULLISH_DIV, BEARISH_DIV, LEVEL_CROSS_UP, LEVEL_CROSS_DOWN"
        if not allowed
        else ", ".join(allowed)
    )
    rsi_long = float(spec["rsi_long_max"])
    long_zone = (
        f"7. long AND rsi_long_max ({rsi_long:.0f}) > 0 AND rsi > {rsi_long:.0f} "
        f"→ SKIP (rsi_long_zone). This is the only 'RSI not low enough' rule. "
        f"It applies to longs only. Shorts have no RSI_LONG_MAX."
        if rsi_long > 0
        else "7. rsi_long_max is 0/off — do not skip longs for a mid RSI."
    )
    size = float(spec["proposed_size_usd"])
    system = f"""You are decide() for the Bitget S2 Divergent desk (UTA Demo execution + local paper shadow). You do not search for signals. The candidate is already a confirmed 15m detector event (RSI 14, pivot lookback 5 left / 5 right). Confirmation, structure, and "is this a real divergence" are done. Your job is the same as decide_rules() in agent/decide.py.

Apply ONLY this algorithm. Do not add filters. Forbidden extra reasons (never SKIP for these): weak/low-conviction, unconfirmed, late entry, price already through/below/above level, poor risk/reward, 15m noise, wait for HTF, RSI not oversold/overbought enough (except the numbered RSI rules below), "be conservative", "paper trading favors waiting". Demo/paper is the venue, not a SKIP reason.

Actions: ENTER or SKIP only. Never REDUCE on a new candidate (exits are ATR TP1 → BE/trail, TP2, SL, dollar-stop, stale_no_tp1 — not you).

Type → side (fixed, do not invert):
- BULLISH_DIV → long
- LEVEL_CROSS_DOWN → long (fade: cross down through bullish-div support)
- BEARISH_DIV → short
- LEVEL_CROSS_UP → short (cross up through bearish-div resistance)
- unknown type → SKIP

Allowed types this desk: {allowed_txt}.
If allowed_types is a non-empty list and type is not in it → SKIP (type_not_allowed).

Hard SKIP, in order:
1. missing candidate, or missing price, or missing rsi
2. unknown type
3. type not in allowed_types (when that list is set)
4. long while allow_long is false
5. short while allow_short is false
6. long AND rsi >= rsi_overbought ({float(spec['rsi_overbought']):.0f}) → SKIP (rsi_extreme_long)
   short AND rsi <= rsi_oversold ({float(spec['rsi_oversold']):.0f}) → SKIP (rsi_extreme_short)
   A short with rsi 40–69 is valid. A long with rsi 31–69 is NOT, if rsi_long_max is on.
{long_zone}

If none of the SKIP rules fired → ENTER.
side must match the type map. size_usd = {size:.2f} on ENTER, 0 on SKIP. Do not resize; ATR notional clamp is later.

Do not apply: BTC 1h regime/momentum/EMA50, pair blocker, max positions, cooldown, daily loss, Demo catalog. Later stages do that. risk_context is informational only.

Reply with one JSON object, first character '{{':
{{"action":"ENTER"|"SKIP","size_usd":number,"side":"long"|"short"|null,"rationale":string}}
rationale must name the fired rule, same style as decide_rules, e.g. "long ENTER on BULLISH_DIV rsi=28.1 size={size:.2f}" or "long RSI zone rsi=42.0> {rsi_long:.0f}". No markdown, no thinking, no extra text."""

    user_payload = {
        "algorithm": spec,
        "candidate": _slim_candidate(candidate),
        "risk_context": {
            **_risk_context_summary(context),
            "note": "Informational. Do not SKIP because of these fields.",
        },
        "task": "Run the algorithm on this candidate. ENTER or SKIP only.",
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


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
) -> dict[str, Any]:
    """Call OpenAI-compatible Chat Completions; return validated decision."""
    base = _env_str("OPENAI_BASE_URL", "http://127.0.0.1:8787/v1").rstrip("/")
    api_key = _env_str("OPENAI_API_KEY", "")
    model = _env_str("OPENAI_MODEL", "gpt-4o-mini")
    timeout = _env_float("OPENAI_TIMEOUT_SEC", 20.0)
    if timeout <= 0:
        timeout = 20.0

    messages = build_llm_messages(candidate, context)
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


def decide(
    candidate: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide ENTER | SKIP | REDUCE.

    AGENT_MODE=rules (default): pure rules path.
    AGENT_MODE=llm: same algorithm as decide_rules, via Chat Completions;
    on any failure/timeout fall back to rules and set llm_fallback.

    Returns:
        {
          "action": "ENTER" | "SKIP" | "REDUCE",
          "size_usd": float,
          "side": "long" | "short" | None,
          "rationale": str,
          "rules_fired": list[str],
        }
    """
    mode = _agent_mode()
    if mode != "llm":
        return decide_rules(candidate, context)

    try:
        return _llm_chat_completions(candidate, context)
    except Exception as exc:  # noqa: BLE001 - any failure -> rules
        err = f"{type(exc).__name__}: {exc}"
        out = decide_rules(candidate, context)
        rules = list(out.get("rules_fired") or [])
        if "llm_fallback" not in rules:
            rules.insert(0, "llm_fallback")
        out = {
            **out,
            "rules_fired": rules,
            "rationale": f"{out.get('rationale')} (llm_fallback: {err})",
        }
        return out

