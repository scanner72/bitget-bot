"""Tamper-evident decision JSONL: canonical SHA-256, session, context, manifest.

Not a signature scheme and not on-chain. Judges recompute hashes with
``python scripts/verify_decision_log.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

HASH_SKIP_KEYS = frozenset({"hash"})
NON_JSON_CONTEXT_KEYS = frozenset({"ohlcv_df", "ohlcv_atr_df"})
CONTEXT_KEEP_KEYS = (
    "symbol",
    "timeframe",
    "ohlcv_limit",
    "proposed_size_usd",
    "session_id",
    "agent_mode",
    "exec_mode",
)

_SESSION_ID: str | None = None


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(float(v))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not json serializable: {type(obj).__name__}")


def canonical_dumps(obj: Any) -> str:
    """Stable JSON for hashing: sorted keys, no extra spaces."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_session_id() -> str:
    """Process-wide desk session id (override with DESK_SESSION_ID)."""
    global _SESSION_ID
    if _SESSION_ID:
        return _SESSION_ID
    env = (os.getenv("DESK_SESSION_ID") or "").strip()
    _SESSION_ID = env or uuid.uuid4().hex
    return _SESSION_ID


def reset_session_id(session_id: str | None = None) -> str:
    """Tests / explicit desk start."""
    global _SESSION_ID
    _SESSION_ID = (session_id or "").strip() or uuid.uuid4().hex
    os.environ["DESK_SESSION_ID"] = _SESSION_ID
    return _SESSION_ID


def public_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """JSON-safe slice of decide context — never candles or DataFrames."""
    ctx = dict(context or {})
    out: dict[str, Any] = {}
    for key in CONTEXT_KEEP_KEYS:
        if key not in ctx or key in NON_JSON_CONTEXT_KEYS:
            continue
        val = ctx[key]
        if val is None:
            continue
        try:
            json.dumps(val, default=_json_default)
        except TypeError:
            continue
        out[key] = val
    out.setdefault("session_id", ensure_session_id())
    try:
        from agent.decide import _agent_mode
        from exec.router import exec_mode

        out.setdefault("agent_mode", _agent_mode())
        out.setdefault("exec_mode", exec_mode())
    except Exception:  # noqa: BLE001
        pass
    tf = (os.getenv("TIMEFRAME") or "15m").strip() or "15m"
    out.setdefault("timeframe", tf)
    return out


def desk_manifest() -> dict[str, Any]:
    """Policy snapshot hashed onto every decision (no secrets)."""
    from agent.decide import _agent_mode
    from exec.router import exec_mode

    allowed = (
        os.getenv("ALLOWED_TYPES")
        or "BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_UP,LEVEL_CROSS_DOWN"
    ).strip()
    return {
        "schema": "bitget-desk-manifest-v1",
        "exec_mode": exec_mode(),
        "agent_mode": _agent_mode(),
        "timeframe": (os.getenv("TIMEFRAME") or "15m").strip() or "15m",
        "risk_usd_per_trade": _env_float("RISK_USD_PER_TRADE", 2.0),
        "max_notional_usd": _env_float("MAX_NOTIONAL_USD", 100.0),
        "min_notional_usd": _env_float("MIN_NOTIONAL_USD", 10.0),
        "max_positions": _env_int("MAX_POSITIONS", 15),
        "hub_leverage": _env_int("HUB_LEVERAGE", 20),
        "btc_regime_tf": (os.getenv("BTC_REGIME_TF") or "1h").strip() or "1h",
        "btc_regime_enabled": _env_bool("BTC_REGIME_ENABLED", True),
        "btc_ema50_filter_enabled": _env_bool("BTC_EMA50_FILTER_ENABLED", False),
        "tf_blocker_enabled": _env_bool("TF_BLOCKER_ENABLED", False),
        "pair_blocker_enabled": _env_bool("PAIR_BLOCKER_ENABLED", True),
        "paper_fallback": _env_bool("PAPER_FALLBACK", False),
        "bitget_allow_live": _env_bool("BITGET_ALLOW_LIVE", False),
        "bitget_demo": _env_bool("BITGET_DEMO", True),
        "allowed_types": allowed,
        "rsi_long_max": _env_float("RSI_LONG_MAX", 30.0),
        "allow_long": _env_bool("ALLOW_LONG", True),
        "allow_short": _env_bool("ALLOW_SHORT", True),
    }


def manifest_hash(manifest: dict[str, Any] | None = None) -> str:
    return sha256_hex(canonical_dumps(manifest if manifest is not None else desk_manifest()))


def decision_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in HASH_SKIP_KEYS}


def decision_hash(record: dict[str, Any]) -> str:
    return sha256_hex(canonical_dumps(decision_payload(record)))


def seal_decision(
    record: dict[str, Any],
    *,
    prev_hash: str | None = None,
    context: dict[str, Any] | None = None,
    session_id: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach session/context/manifest + SHA-256. Does not write."""
    rec = dict(record)
    rec.pop("hash", None)
    sid = (session_id or rec.get("session_id") or ensure_session_id())
    rec["session_id"] = str(sid)
    merged_ctx = dict(context or rec.get("context") or {})
    if "session_id" not in merged_ctx:
        merged_ctx["session_id"] = rec["session_id"]
    rec["context"] = public_context(merged_ctx)
    snap = dict(manifest if manifest is not None else rec.get("manifest") or desk_manifest())
    rec["manifest"] = snap
    rec["manifest_hash"] = manifest_hash(snap)
    rec["prev_hash"] = (
        prev_hash if prev_hash is not None else str(rec.get("prev_hash") or "")
    )
    rec["hash"] = decision_hash(rec)
    return rec


def append_sealed_decision(
    record: dict[str, Any],
    path: Path | str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal + append one JSONL line. Returns the sealed record."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sealed = seal_decision(record, prev_hash=tail_hash(out), context=context)
    line = json.dumps(sealed, ensure_ascii=False, separators=(",", ":"))
    with out.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return sealed


def tail_hash(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    last = ""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                last = line
    if not last:
        return ""
    try:
        row = json.loads(last)
    except json.JSONDecodeError:
        return ""
    return str(row.get("hash") or "") if isinstance(row, dict) else ""


def verify_record(
    record: dict[str, Any],
    *,
    prev_hash: str = "",
    require_session: bool = True,
) -> list[str]:
    """Return a list of problems (empty = ok)."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["not an object"]
    got = str(record.get("hash") or "")
    if not got:
        errors.append("missing hash")
        return errors
    expected = decision_hash(record)
    if got != expected:
        errors.append(f"hash mismatch expected={expected} got={got}")
    stored_prev = str(record.get("prev_hash") or "")
    if stored_prev != str(prev_hash or ""):
        errors.append(
            f"prev_hash mismatch expected={prev_hash or ''} got={stored_prev}"
        )
    man = record.get("manifest")
    mh = str(record.get("manifest_hash") or "")
    if not mh:
        errors.append("missing manifest_hash")
    elif isinstance(man, dict):
        expect_mh = manifest_hash(man)
        if mh != expect_mh:
            errors.append(
                f"manifest_hash mismatch expected={expect_mh} got={mh}"
            )
    if require_session and not str(record.get("session_id") or "").strip():
        errors.append("missing session_id")
    ctx = record.get("context")
    if require_session and not isinstance(ctx, dict):
        errors.append("missing context object")
    return errors


def verify_jsonl(
    path: Path,
    *,
    allow_legacy: bool = False,
    require_session: bool = True,
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    errors: list[str] = []
    prev = ""
    n = 0
    legacy = 0
    for i, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {i}: invalid json ({exc})")
            continue
        n += 1
        if allow_legacy and isinstance(row, dict) and not row.get("hash"):
            legacy += 1
            prev = ""
            continue
        problems = verify_record(
            row, prev_hash=prev, require_session=require_session
        )
        for p in problems:
            errors.append(f"line {i}: {p}")
        if isinstance(row, dict) and row.get("hash"):
            prev = str(row.get("hash") or "")
        else:
            prev = ""
    return {
        "ok": not errors,
        "path": str(path),
        "rows": n,
        "legacy": legacy,
        "errors": errors,
    }
