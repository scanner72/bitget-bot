"""Candidate -> agent.decide -> risk check -> paper fill -> decision JSONL."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.decide import decide
from desk.decision_log import append_sealed_decision, ensure_session_id
from exec.demo_universe import NotOnDemoError
from exec.paper import PaperBook
from exec.router import DemoPriceMismatchError, HubTpslError, open_position
from ingest.symbols import to_display
from risk.gate import RiskGate
from risk.sizing import notional_from_risk

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISIONS_PATH = ROOT / "data" / "decisions.jsonl"


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def default_proposed_size_usd() -> float:
    """Prefer PROPOSED_SIZE_USD, else clamp to MAX_NOTIONAL_USD default 100."""
    size = _env_float("PROPOSED_SIZE_USD", 0.0)
    if size > 0:
        return size
    return _env_float("MAX_NOTIONAL_USD", 100.0)


def append_decision(
    record: dict[str, Any],
    path: Path | str | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one sealed JSONL row (session/context/manifest_hash + SHA-256)."""
    out = Path(path) if path else DEFAULT_DECISIONS_PATH
    return append_sealed_decision(record, out, context=context)


append_risk_decision = append_decision


def evaluate_candidate(
    candidate: dict[str, Any],
    gate: RiskGate,
    *,
    proposed_size_usd: float | None = None,
    decisions_path: Path | str | None = None,
    context: dict[str, Any] | None = None,
    paper_book: PaperBook | None = None,
) -> dict[str, Any]:
    """decide -> risk.check -> (ENTER+allow) open_position -> print + JSONL.

    Paper-only: never places live Bitget orders.
    """
    ctx = dict(context or {})
    ctx.setdefault("session_id", ensure_session_id())
    if proposed_size_usd is not None:
        ctx["proposed_size_usd"] = float(proposed_size_usd)

    agent_out = decide(candidate, ctx)
    action = str(agent_out.get("action", "SKIP")).upper()
    _sym = str(candidate.get("symbol") or "")
    _sym_disp = to_display(_sym) if _sym else ""
    # Divergent BTC regime / momentum / EMA50 filters
    if action in {"ENTER", "REDUCE"}:
        try:
            from risk.btc_filters import check_btc_filters

            side = str(agent_out.get("side") or "")
            ok_btc, btc_reason = check_btc_filters(side, _sym)
            if not ok_btc:
                action = "SKIP"
                rules = list(agent_out.get("rules_fired") or [])
                rules.append("btc_filter")
                agent_out = {
                    **agent_out,
                    "action": "SKIP",
                    "rationale": f"btc_filter:{btc_reason}",
                    "rules_fired": rules,
                }
                print(
                    f"[BTC] SKIP {_sym_disp or _sym} side={side} reason={btc_reason}"
                )
        except Exception as _btc_exc:  # noqa: BLE001
            print(f"[BTC] filter error: {_btc_exc}")
    # Provisional size from agent (logging only); open uses risk notional after ATR.
    provisional_size = float(agent_out.get("size_usd") or 0.0)
    if provisional_size <= 0 and action in {"ENTER", "REDUCE"}:
        provisional_size = default_proposed_size_usd()
        agent_out = {**agent_out, "size_usd": provisional_size}
    size = provisional_size

    print(
        f"[AGENT] {action} {_sym_disp or _sym} ({_sym}) {candidate.get('type')} "
        f"side={agent_out.get('side')} size={provisional_size} "
        f"rationale={agent_out.get('rationale')} "
        f"rules={agent_out.get('rules_fired')}"
    )

    risk_result: dict[str, Any] | None = None
    if action in {"ENTER", "REDUCE"}:
        risk_result = gate.check(candidate, size)
        flag = "ALLOW" if risk_result.get("allowed") else "DENY"
        print(
            f"[RISK] {flag} {_sym_disp or _sym} ({_sym}) {candidate.get('type')} "
            f"size={size} reason={risk_result.get('reason')}"
        )

    fill_id: str | None = None
    position_id: str | None = None
    paper_error: str | None = None

    if (
        action == "ENTER"
        and risk_result is not None
        and bool(risk_result.get("allowed"))
    ):
        try:
            price = float(candidate.get("price") or 0)
            side = str(agent_out.get("side") or "long")
            if price <= 0:
                raise ValueError("candidate price missing/invalid for paper open")
            # ATR SL/TP sizing + volatility filter (divergent defaults)
            from risk.atr import atr_filter_ok, atr_spec_for_symbol, compute_levels_from_df

            levels = None
            ohlcv_df = ctx.get("ohlcv_df")
            atr_spec = atr_spec_for_symbol(str(candidate.get("symbol") or ""))
            sig_tf = str(ctx.get("timeframe") or candidate.get("timeframe") or "15m")
            atr_tf = str(atr_spec.get("timeframe") or sig_tf)
            atr_df = ohlcv_df
            if ohlcv_df is None or atr_tf != sig_tf:
                try:
                    from ingest.bitget_ohlcv import get_ohlcv

                    atr_df = get_ohlcv(
                        symbol=str(candidate.get("symbol")),
                        timeframe=atr_tf,
                        limit=int(ctx.get("ohlcv_limit") or 50),
                    )
                except Exception as _atr_exc:  # noqa: BLE001
                    print(f"[ATR] WARN fetch {atr_tf} failed: {_atr_exc}")
                    atr_df = ohlcv_df
                    if atr_df is None:
                        try:
                            from ingest.bitget_ohlcv import get_ohlcv

                            atr_df = get_ohlcv(
                                symbol=str(candidate.get("symbol")),
                                timeframe=sig_tf,
                                limit=int(ctx.get("ohlcv_limit") or 50),
                            )
                        except Exception as _atr_exc2:  # noqa: BLE001
                            print(f"[ATR] WARN fetch {sig_tf} failed: {_atr_exc2}")
                            atr_df = None
            if atr_df is not None:
                levels = compute_levels_from_df(
                    price,
                    side,
                    atr_df,
                    floor_pct=float(atr_spec["floor_pct"]),
                )
            if levels is not None:
                _amin = float(atr_spec["min_pct"])
                _amax = float(atr_spec["max_pct"])
                ok_atr, atr_reason = atr_filter_ok(
                    levels["atr"], price, min_pct=_amin, max_pct=_amax
                )
                if not ok_atr:
                    paper_error = atr_reason
                    print(f"[ATR] SKIP open {candidate.get('symbol')}: {atr_reason}")
                    levels = None
                    # Treat as paper skip (no open)
                    raise ValueError(f"atr_filter:{atr_reason}")

            # Risk-based notional from distance to SL (fallback: MAX_NOTIONAL_USD)
            risk_usd = _env_float("RISK_USD_PER_TRADE", 2.0)
            max_notional = _env_float("MAX_NOTIONAL_USD", 100.0)
            min_notional = _env_float("MIN_NOTIONAL_USD", 10.0)
            if levels is not None and levels.get("sl") is not None:
                size = notional_from_risk(
                    price,
                    levels["sl"],
                    risk_usd=risk_usd,
                    max_notional=max_notional,
                    min_notional=min_notional,
                )
                atr_pct_v = levels.get("atr_pct")
                print(
                    f"[SIZE] risk_usd={risk_usd} atr_pct={atr_pct_v} notional={size}"
                )
                # Re-run gate with risk-sized notional
                risk_result = gate.check(candidate, size)
                flag = "ALLOW" if risk_result.get("allowed") else "DENY"
                print(
                    f"[RISK] {flag} {_sym_disp or _sym} ({_sym}) {candidate.get('type')} "
                    f"size={size} reason={risk_result.get('reason')} (post-size)"
                )
                if not bool(risk_result.get("allowed")):
                    paper_error = f"risk_deny_post_size:{risk_result.get('reason')}"
                    raise ValueError(paper_error)
            else:
                size = max_notional
                print(
                    f"[SIZE] risk_usd={risk_usd} atr_pct=n/a notional={size} "
                    f"(fallback MAX_NOTIONAL_USD; levels missing)"
                )

            book = paper_book or PaperBook(gate=gate)
            if paper_book is not None and book.gate is None:
                book.gate = gate
            open_meta = {
                "type": candidate.get("type"),
                "rsi": candidate.get("rsi"),
                "action": action,
                "rationale": agent_out.get("rationale"),
                "provisional_size_usd": provisional_size,
                "risk_usd": risk_usd,
                "timeframe": sig_tf,
                "atr_tf": atr_tf,
                "atr_kind": atr_spec.get("kind"),
                "atr_floor_pct": atr_spec.get("floor_pct"),
            }
            if levels is not None:
                open_meta.update(levels)
            position_id = open_position(
                symbol=str(candidate.get("symbol")),
                side=side,
                size_usd=size,
                price=price,
                meta=open_meta,
                gate=gate,
                book=book,
            )
            # Latest open fill id from the position record
            opens = book.list_open()
            match = next(
                (p for p in opens if p.get("position_id") == position_id),
                None,
            )
            fill_id = (match or {}).get("open_fill_id")
        except NotOnDemoError as exc:
            paper_error = f"not_on_demo:{exc}"
            print(f"[HUB] SKIP not on demo: {exc}")
        except DemoPriceMismatchError as exc:
            paper_error = f"demo_price_mismatch:{exc}"
            print(f"[HUB] SKIP price mismatch: {exc}")
        except HubTpslError as exc:
            paper_error = f"hub_tpsl_fail_closed:{exc}"
            print(f"[HUB] SKIP tpsl fail-closed: {exc}")
        except Exception as exc:  # noqa: BLE001
            paper_error = f"{type(exc).__name__}: {exc}"
            print(f"[PAPER] ERROR open failed: {paper_error}")

    now = datetime.now(timezone.utc)
    rec = {
        "ts": now.isoformat(),
        "symbol": candidate.get("symbol"),
        "type": candidate.get("type"),
        "price": candidate.get("price"),
        "rsi": candidate.get("rsi"),
        "agent": {
            "action": action,
            "size_usd": provisional_size,
            "side": agent_out.get("side"),
            "rationale": agent_out.get("rationale"),
            "rules_fired": list(agent_out.get("rules_fired") or []),
        },
        "risk": (
            {
                "allowed": bool(risk_result.get("allowed")),
                "reason": risk_result.get("reason"),
                "proposed_size_usd": size,
            }
            if risk_result is not None
            else None
        ),
        "fill_id": fill_id,
        "position_id": position_id,
        "paper_error": paper_error,
        "action": action,
        "allowed": (bool(risk_result.get("allowed")) if risk_result else None),
        "reason": (risk_result.get("reason") if risk_result else agent_out.get("rationale")),
        "proposed_size_usd": size,
    }
    rec = append_decision(rec, decisions_path, context=ctx)
    return {
        "agent": agent_out,
        "risk": risk_result,
        "decision_record": rec,
        "action": action,
        "allowed": rec["allowed"],
        "reason": rec["reason"],
        "fill_id": fill_id,
        "position_id": position_id,
        "paper_error": paper_error,
    }


def evaluate_candidate_risk(
    candidate: dict[str, Any],
    gate: RiskGate,
    *,
    proposed_size_usd: float | None = None,
    decisions_path: Path | str | None = None,
) -> dict[str, Any]:
    """Back-compat wrapper: full decide+risk+paper chain (same as evaluate_candidate)."""
    return evaluate_candidate(
        candidate,
        gate,
        proposed_size_usd=proposed_size_usd,
        decisions_path=decisions_path,
    )
