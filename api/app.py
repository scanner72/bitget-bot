"""FastAPI dashboard for Bitget S2 desk (paper shadow; Demo PnL when hub_demo)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from urllib.parse import urlencode

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse

from exec.paper import list_open, list_open_with_pnl
from exec.account import get_account
from ingest.symbols import enrich_symbol_fields, to_bitget_id, to_display

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHART_HTML = Path(__file__).resolve().parent / "static" / "chart.html"

app = FastAPI(title="Bitget S2 Divergent Agent Desk", version="0.1.0")


def _tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    """Return last limit JSON objects from a JSONL file; missing/bad -> []."""
    if limit < 1:
        return []
    if not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    if limit >= len(rows):
        return rows
    return rows[-limit:]


def _enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add symbol_id / symbol_display; keep ccxt symbol."""
    return [enrich_symbol_fields(r) if isinstance(r, dict) else r for r in rows]


def _exit_fields(pos: dict[str, Any]) -> dict[str, Any]:
    """Surface SL/TP/exit status from top-level or meta for /positions."""
    meta = pos.get("meta") if isinstance(pos.get("meta"), dict) else {}
    out = dict(pos)

    def pick(key: str):
        if key in out and out[key] is not None:
            return out[key]
        return meta.get(key)

    for key in (
        "sl", "tp1", "tp2", "atr", "atr_pct", "original_sl",
        "tp1_hit", "trailing_active", "trail_price",
        "be_timeout", "exit_status",
    ):
        val = pick(key)
        if val is not None:
            out[key] = val
    return out


def _exec_mode() -> str:
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode in {"hub_demo", "demo"}:
        return "hub_demo"
    if mode in {"live", "hub_live"}:
        return "live"
    return "paper"


def _safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _hub_positions_by_key() -> tuple[dict[tuple[str, str], dict[str, Any]], str | None]:
    """Fetch Bitget current positions once; map by (SYMBOL, posSide).

    Returns (map, error_note). Graceful on failure / non-hub modes.
    """
    mode = _exec_mode()
    if mode not in {"hub_demo", "live"}:
        return {}, None
    try:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        live = client.current_positions() or {}
        items = live.get("list") if isinstance(live, dict) else live
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for it in items or []:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper()
            side = str(it.get("posSide") or "").lower()
            if not sym or not side:
                continue
            out[(sym, side)] = it
        return out, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"hub_positions_fetch_failed: {type(exc).__name__}: {exc}"


def _enrich_with_exchange(
    positions: list[dict[str, Any]],
    hub_map: dict[tuple[str, str], dict[str, Any]] | None = None,
    hub_err: str | None = None,
) -> list[dict[str, Any]]:
    """Attach exchange_qty / margin / leverage / entry / notional when hub mode."""
    mode = _exec_mode()
    if hub_map is None:
        hub_map, hub_err = _hub_positions_by_key()

    try:
        from exec.bitget_hub import ccxt_to_bitget_symbol
    except Exception:
        ccxt_to_bitget_symbol = None  # type: ignore[assignment]

    enriched: list[dict[str, Any]] = []
    for pos in positions:
        row = dict(pos)
        size_usd = _safe_float(row.get("size_usd"), 0.0) or 0.0
        row["size_label"] = (
            f"local size_usd=${size_usd:.2f} is target notional (not exchange margin)"
        )
        if mode not in {"hub_demo", "live"}:
            enriched.append(row)
            continue

        sym_raw = str(row.get("symbol") or "")
        side = str(row.get("side") or "").lower()
        bg_sym = ""
        if ccxt_to_bitget_symbol is not None:
            try:
                bg_sym = ccxt_to_bitget_symbol(sym_raw)
            except Exception:
                bg_sym = ""
        if not bg_sym:
            bg_sym = str(row.get("symbol_id") or to_bitget_id(sym_raw) or "").upper()
        bg_sym = bg_sym.upper()

        hub = hub_map.get((bg_sym, side)) if bg_sym and side else None
        if hub is None and hub_err:
            row["exchange_enrich_error"] = hub_err
            row["pnl_source"] = "paper_fallback"
            enriched.append(row)
            continue
        if hub is None:
            # Paper open but missing on exchange — ghost until desk reconcile.
            row["pnl_source"] = "paper_fallback"
            row["stale"] = True
            row["stale_reason"] = "missing_on_exchange"
            # Do not treat paper mark PnL as live hub equity.
            row["unrealized_pnl_usd"] = None
            row["unrealized_pnl_pct"] = None
            row["pnl_note"] = "stale / awaiting reconcile"
            enriched.append(row)
            continue

        qty = _safe_float(hub.get("available"), None)
        if qty is None:
            qty = _safe_float(hub.get("total"), None)
        margin = _safe_float(hub.get("positionBalance"), None)
        lev = hub.get("leverage")
        entry = _safe_float(hub.get("avgPrice"), None)
        mark = _safe_float(hub.get("markPrice"), None)
        if mark is None:
            mark = _safe_float(row.get("mark_price"), None)
        px = mark if mark is not None and mark > 0 else entry
        notional = None
        if qty is not None and px is not None and px > 0:
            notional = float(qty) * float(px)

        row["exchange_qty"] = qty
        row["exchange_margin_usd"] = margin
        row["exchange_leverage"] = lev
        row["exchange_entry"] = entry
        row["exchange_notional_usd"] = notional
        if mark is not None:
            row["exchange_mark"] = mark

        # Override display MTM from Bitget hub (real demo/live), keep paper entry.
        paper_entry = _safe_float(row.get("entry_price"), None)
        if paper_entry is not None and "paper_entry_price" not in row:
            row["paper_entry_price"] = paper_entry

        upnl = _safe_float(hub.get("unrealisedPnl"), None)
        if upnl is None:
            upnl = _safe_float(hub.get("unrealizedPnl"), None)
        profit_rate = _safe_float(hub.get("profitRate"), None)
        upnl_pct = None
        if profit_rate is not None:
            # Bitget profitRate is usually a fraction (e.g. 0.0123); treat |x|<=2 as fraction.
            upnl_pct = profit_rate * 100.0 if abs(profit_rate) <= 2.0 else profit_rate
        elif upnl is not None and margin is not None and margin != 0:
            upnl_pct = (upnl / float(margin)) * 100.0
        elif (
            upnl is not None
            and entry is not None
            and qty is not None
            and entry > 0
            and qty != 0
        ):
            entry_notional = abs(float(qty) * float(entry))
            if entry_notional > 0:
                upnl_pct = (upnl / entry_notional) * 100.0

        if mark is not None:
            row["mark_price"] = mark
        if entry is not None:
            row["entry_price"] = entry
            row["entry_price_display"] = entry
        if upnl is not None:
            row["unrealized_pnl_usd"] = float(upnl)
        if upnl_pct is not None:
            row["unrealized_pnl_pct"] = float(upnl_pct)
        row["pnl_source"] = "hub_demo" if mode == "hub_demo" else "hub_live"
        enriched.append(row)
    return enriched


def _sum_hub_unrealised(positions: list[dict[str, Any]]) -> float | None:
    """Sum exchange unrealised PnL when any row has hub pnl_source; else None.

    paper_fallback / stale rows are excluded (not live exchange PnL).
    """
    vals: list[float] = []
    any_hub = False
    for pos in positions:
        if pos.get("stale"):
            continue
        src = str(pos.get("pnl_source") or "")
        if src not in {"hub_demo", "hub_live"}:
            continue
        any_hub = True
        v = _safe_float(pos.get("unrealized_pnl_usd"), None)
        if v is not None:
            vals.append(float(v))
    if not any_hub:
        return None
    return float(sum(vals))


def _size_cell_html(p: dict[str, Any]) -> str:
    """Primary = exchange qty/notional/margin; $size_usd is bot target only."""
    bits: list[str] = []
    qty = p.get("exchange_qty") if p.get("exchange_qty") is not None else p.get("qty")
    if qty is not None:
        try:
            qf = float(qty)
            q_s = f"{qf:.4f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            q_s = str(qty)
        bits.append(f"qty {q_s}")
    notional = p.get("exchange_notional_usd")
    if notional is not None:
        try:
            bits.append(f"notional ${float(notional):.2f}")
        except (TypeError, ValueError):
            bits.append(f"notional {_html_escape(notional)}")
    margin = p.get("exchange_margin_usd")
    lev = p.get("exchange_leverage")
    if margin is not None:
        try:
            m_s = f"${float(margin):.2f}"
        except (TypeError, ValueError):
            m_s = _html_escape(margin)
        lev_s = f" @ {_html_escape(lev)}x" if lev is not None else ""
        bits.append(f"margin {m_s}{lev_s}")
    target = p.get("size_usd")
    if target is not None:
        try:
            bits.append(f"target ${float(target):.0f}")
        except (TypeError, ValueError):
            bits.append(f"target {_html_escape(target)}")
    if not bits:
        return "<em>—</em>"
    return "<br/>".join(bits)


def _risk_kill_hint() -> dict[str, Any]:
    """Best-effort daily-loss kill hint from risk_state.json (no exchange)."""
    state_path = DATA / "risk_state.json"
    max_loss = 50.0
    try:
        from risk.gate import RiskLimits

        max_loss = float(RiskLimits.from_env().max_daily_loss_usd)
    except Exception:
        pass
    daily_pnl = 0.0
    daily_date = None
    if state_path.exists():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                daily_pnl = float(raw.get("daily_pnl") or 0)
                daily_date = raw.get("daily_date")
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    killed = daily_pnl <= -abs(max_loss)
    return {
        "daily_pnl": daily_pnl,
        "daily_date": daily_date,
        "max_daily_loss_usd": max_loss,
        "killed": killed,
        "hint": (
            f"KILL active: daily_pnl={daily_pnl:.2f} <= -{abs(max_loss):.2f}"
            if killed
            else f"OK: daily_pnl={daily_pnl:.2f} (kill at -{abs(max_loss):.2f})"
        ),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    mode = _exec_mode()
    bitget_demo_flag = (os.getenv("BITGET_DEMO") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    hub_sync = (os.getenv("HUB_SYNC_EXCHANGE_SL") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    return {
        "ok": True,
        "paper": True,  # local paper shadow book always on
        "exec_mode": mode,
        "hub_demo": mode == "hub_demo",
        "bitget_demo": bitget_demo_flag or mode == "hub_demo",
        "hub_sync_exchange_sl": hub_sync,
        "paper_fallback": (os.getenv("PAPER_FALLBACK") or "0").strip().lower()
        not in {"0", "false", "no", "off"}
        and mode == "hub_demo",
        "agent_mode": _agent_mode_name(),
        "openai_model": _agent_model_name(),
    }


def _positions_mtm() -> tuple[list[dict[str, Any]], float | None, list[str]]:
    """Open positions with mark / unrealized PnL (ticker failures -> null upnl)."""
    try:
        return list_open_with_pnl()
    except Exception as exc:  # noqa: BLE001
        try:
            open_pos = list_open()
        except Exception:
            open_pos = []
        note = f"mtm_enrich_failed: {exc}"
        enriched = []
        for pos in open_pos:
            row = dict(pos)
            row["mark_price"] = None
            row["unrealized_pnl_usd"] = None
            row["unrealized_pnl_pct"] = None
            row["mtm_error"] = note
            enriched.append(row)
        return enriched, None, [note]


def _account_snapshot(
    *,
    total_upnl: float | None = None,
    mtm_errors: list[str] | None = None,
    skip_mtm_fetch: bool = False,
) -> dict[str, Any]:
    """Paper account equity snapshot with mark-to-market unrealized PnL.

    equity / equity_mtm = cash + open_notional + total_unrealized_pnl
    (= start + realized + upnl when cash wallet is consistent).
    Pass total_upnl/mtm_errors with skip_mtm_fetch=True to reuse a prior
    _positions_mtm() call (dashboard).
    """
    try:
        acct = get_account(reload=True)
    except Exception:
        return {
            "start_balance": 10000.0,
            "cash": 10000.0,
            "realized_pnl": 0.0,
            "open_positions_notional": 0.0,
            "total_unrealized_pnl": 0.0,
            "equity": 10000.0,
            "equity_mtm": 10000.0,
            "currency": "USDT",
        }
    errors: list[str] = list(mtm_errors or [])
    if not skip_mtm_fetch:
        _positions, total_upnl, fetch_errs = _positions_mtm()
        errors = fetch_errs
    upnl_for_equity = float(total_upnl) if total_upnl is not None else 0.0
    snap = acct.snapshot(unrealized=upnl_for_equity)
    snap["total_unrealized_pnl"] = total_upnl if total_upnl is not None else 0.0
    snap["equity_mtm"] = snap["equity"]
    if total_upnl is None and errors:
        snap["total_unrealized_pnl"] = None
        snap["mtm_note"] = "; ".join(errors)
    elif errors:
        snap["mtm_note"] = "; ".join(errors)
    try:
        from exec.hub_balance import overlay_equity_snapshot

        snap = overlay_equity_snapshot(snap)
    except Exception as _hub_exc:  # noqa: BLE001
        # Fail soft: keep paper snapshot if hub overlay unavailable
        snap.setdefault("hub_overlay_error", f"{type(_hub_exc).__name__}")
    return snap


@app.get("/equity")
def equity() -> dict[str, Any]:
    return _account_snapshot()


@app.get("/account")
def account() -> dict[str, Any]:
    return _account_snapshot()


@app.get("/positions")
def positions() -> dict[str, Any]:
    from exec.hub_view import list_positions_for_ui

    return list_positions_for_ui()


@app.get("/decisions")
def decisions(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = _enrich_rows(_tail_jsonl(DATA / "decisions.jsonl", limit))
    return {"decisions": rows, "count": len(rows)}


@app.get("/fills")
def fills(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    from exec.hub_view import list_fills_for_ui

    return list_fills_for_ui(limit=limit)


@app.get("/history")
def history(limit: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
    from exec.hub_view import list_closed_trades_for_ui

    return list_closed_trades_for_ui(limit=limit)


@app.get("/chart")
def chart_page() -> FileResponse:
    if not CHART_HTML.exists():
        raise FileNotFoundError(str(CHART_HTML))
    return FileResponse(CHART_HTML, media_type="text/html")


@app.get("/api/chart/data")
def chart_data(
    symbol: str = Query(...),
    timeframe: str | None = Query(None),
    limit: int = Query(400, ge=50, le=1000),
) -> dict[str, Any]:
    from api.chart_data import build_chart_payload

    try:
        return build_chart_payload(symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "candles": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


@app.get("/candidates")
def candidates(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = _enrich_rows(_tail_jsonl(DATA / "candidates.jsonl", limit))
    return {"candidates": rows, "count": len(rows)}


def _agent_mode_name() -> str:
    from agent.decide import _agent_mode

    return _agent_mode()


def _agent_model_name() -> str:
    if _agent_mode_name() != "llm":
        return ""
    return (os.getenv("OPENAI_MODEL") or "").strip()


def _decision_rules(d: dict[str, Any]) -> list[str]:
    agent = d.get("agent") if isinstance(d.get("agent"), dict) else {}
    rf = agent.get("rules_fired") if agent.get("rules_fired") is not None else d.get("rules_fired")
    if isinstance(rf, str):
        return [rf] if rf else []
    if isinstance(rf, list):
        return [str(x) for x in rf if x is not None and str(x).strip()]
    return []


def _decision_agent_kind(d: dict[str, Any]) -> str:
    rf = _decision_rules(d)
    if "llm_fallback" in rf:
        return "fallback"
    if "llm" in rf:
        return "llm"
    return "rules"


def _decision_rationale(d: dict[str, Any], *, limit: int = 160) -> str:
    agent = d.get("agent") if isinstance(d.get("agent"), dict) else {}
    text = agent.get("rationale") or d.get("rationale") or d.get("reason") or ""
    text = " ".join(str(text).split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _agent_kind_badge(kind: str) -> str:
    k = str(kind or "rules")
    if k == "llm":
        return '<span class="tag llm" title="Groq/OpenAI-compatible decide">LLM</span>'
    if k == "fallback":
        return '<span class="tag warn" title="LLM failed; rules took over">FALLBACK</span>'
    return '<span class="tag" title="Deterministic rules">RULES</span>'


def _html_escape(s: Any) -> str:
    t = str(s if s is not None else "")
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _chart_href(
    symbol: Any,
    *,
    timeframe: Any = None,
    entry: Any = None,
    sl: Any = None,
    tp1: Any = None,
    tp2: Any = None,
    direction: Any = None,
    opened: Any = None,
    exit_px: Any = None,
    closed: Any = None,
    pnl: Any = None,
    reason: Any = None,
) -> str:
    q: dict[str, str] = {}
    if symbol:
        q["symbol"] = str(symbol)
    tf = str(timeframe or os.getenv("TIMEFRAME") or "15m").strip() or "15m"
    q["timeframe"] = tf

    def add(key: str, val: Any) -> None:
        if val is None or val == "":
            return
        q[key] = str(val)

    add("entry", entry)
    add("sl", sl)
    add("tp1", tp1)
    add("tp2", tp2)
    add("dir", direction)
    add("opened", opened)
    add("exit", exit_px)
    add("closed", closed)
    add("pnl", pnl)
    add("reason", reason)
    return "/chart?" + urlencode(q)


def _row_onclick(href: str) -> str:
    js = _html_escape(href).replace("'", "\\'")
    return f"window.open('{js}','_blank')"


def _pnl_cell(val: Any) -> str:
    if val is None:
        return "<td><em>n/a</em></td>"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return f"<td>{_html_escape(val)}</td>"
    color = "#22a06b" if num >= 0 else "#d14f4f"
    return f'<td style="color:{color};font-weight:600">{_html_escape(f"{num:.4f}")}</td>'


def _action_badge(action: Any) -> str:
    a = str(action or "").upper().strip()
    cls = {
        "ENTER": "tag enter",
        "SKIP": "tag skip",
        "REDUCE": "tag reduce",
    }.get(a, "tag")
    return f'<span class="{cls}">{_html_escape(a or "—")}</span>'


def _side_badge(side: Any) -> str:
    s = str(side or "").lower().strip()
    if s in {"long", "buy"}:
        return f'<span class="tag long">{_html_escape(s)}</span>'
    if s in {"short", "sell"}:
        return f'<span class="tag short">{_html_escape(s)}</span>'
    return f'<span class="tag">{_html_escape(side or "—")}</span>'


def _allowed_badge(allowed: Any) -> str:
    if allowed is True or str(allowed).lower() in {"true", "1", "allow", "allowed"}:
        return '<span class="tag ok">ALLOW</span>'
    if allowed is False or str(allowed).lower() in {"false", "0", "deny", "denied"}:
        return '<span class="tag bad">DENY</span>'
    return f'<span class="tag">{_html_escape(allowed if allowed is not None else "—")}</span>'


def _sync_cell_html(p: dict[str, Any]) -> str:
    if p.get("stale"):
        return (
            "<td><span class='tag bad' title='missing on exchange'>"
            "stale / awaiting reconcile</span></td>"
        )
    if str(p.get("venue") or p.get("pnl_source") or "") in {"paper", "paper_live"}:
        reason = p.get("exec_reason") or "not on demo"
        return (
            f"<td><span class='tag warn' title='{_html_escape(reason)}'>"
            "paper live</span></td>"
        )
    if p.get("tracked") is False:
        return "<td><span class='tag warn'>untracked</span></td>"
    if p.get("tpsl_on_exchange") is False:
        return "<td><span class='tag warn'>no TPSL</span></td>"
    if str(p.get("pnl_source") or "").startswith("hub"):
        return "<td><span class='tag ok'>hub</span></td>"
    return f"<td class='sub'>{_html_escape(p.get('pnl_source') or '—')}</td>"


def _pos_rows_html(open_pos: list[dict[str, Any]]) -> str:
    if not open_pos:
        return "<tr><td colspan='11'><em>none</em></td></tr>"
    rows = ""
    for p in open_pos:
        sl_disp = p.get("hub_sl_price") if p.get("hub_sl_price") is not None else p.get("sl")
        tp2_disp = p.get("hub_tp2_price") if p.get("hub_tp2_price") is not None else p.get("tp2")
        if str(p.get("venue") or "") == "paper" or str(p.get("pnl_source") or "") == "paper_live":
            sl_disp = p.get("bot_sl") if p.get("bot_sl") is not None else p.get("sl")
            tp2_disp = p.get("bot_tp2") if p.get("bot_tp2") is not None else p.get("tp2")
        elif p.get("tpsl_on_exchange") is False:
            sl_disp = p.get("tpsl_note") or "none on exchange"
            tp2_disp = "—"
        chart_sl = p.get("bot_sl") if p.get("bot_sl") is not None else p.get("sl")
        chart_tp2 = p.get("bot_tp2") if p.get("bot_tp2") is not None else p.get("tp2")
        chart_href = _chart_href(
            p.get("symbol"),
            timeframe=p.get("timeframe"),
            entry=p.get("entry_price_display") if p.get("entry_price_display") is not None else p.get("entry_price"),
            sl=chart_sl,
            tp1=p.get("tp1"),
            tp2=chart_tp2,
            direction=p.get("side"),
            opened=p.get("opened_ts"),
        )
        rows += (
            f"<tr class='row-link' title='Open LIVE chart' onclick=\"{_row_onclick(chart_href)}\">"
            f"<td>{_html_escape(p.get('symbol_display') or p.get('symbol'))}<br/><span class='sub'>{_html_escape(p.get('symbol_id') or '')}</span></td>"
            f"<td>{_side_badge(p.get('side'))}</td>"
            f"<td>{_size_cell_html(p)}</td>"
            f"<td>{_html_escape(p.get('entry_price_display') if p.get('entry_price_display') is not None else p.get('entry_price'))}</td>"
            f"<td>{_html_escape(p.get('mark_price'))}</td>"
            + _pnl_cell(p.get("unrealized_pnl_usd"))
            + f"<td class='mono'>{_html_escape(p.get('position_id'))}</td>"
            f"<td class='mono'>{_html_escape(sl_disp)}</td>"
            f"<td class='mono'>{_html_escape(p.get('tp1'))}</td>"
            f"<td class='mono'>{_html_escape(tp2_disp)}</td>"
            + _sync_cell_html(p)
            + "</tr>"
        )
    return rows


def _dec_rows_html(decs: list[dict[str, Any]]) -> str:
    if not decs:
        return "<tr><td colspan='8'><em>none</em></td></tr>"
    rows = ""
    for d in reversed(decs):
        agent = d.get("agent") if isinstance(d.get("agent"), dict) else {}
        action = d.get("action") or agent.get("action")
        allowed = d.get("allowed")
        if allowed is None and isinstance(d.get("risk"), dict):
            allowed = d["risk"].get("allowed")
        ts = str(d.get("ts") or "")
        ts_short = ts[11:19] if len(ts) >= 19 else ts
        kind = _decision_agent_kind(d)
        why = _decision_rationale(d)
        hash_full = str(d.get("hash") or "")
        hash_short = hash_full[:8] if hash_full else "—"
        sess = str(d.get("session_id") or "")
        sess_short = sess[:8] if sess else ""
        why_title = why
        if hash_full:
            why_title = f"{why} | hash={hash_full}" if why else f"hash={hash_full}"
        sess_html = (
            f"<br/><span class='sub'>{_html_escape(sess_short)}</span>"
            if sess_short
            else ""
        )
        rows += (
            "<tr>"
            f"<td class='mono'>{_html_escape(ts_short)}</td>"
            f"<td>{_html_escape(d.get('symbol_display') or d.get('symbol'))}<br/><span class='sub'>{_html_escape(d.get('symbol_id') or '')}</span></td>"
            f"<td>{_html_escape(d.get('type'))}</td>"
            f"<td>{_agent_kind_badge(kind)}</td>"
            f"<td>{_action_badge(action)}</td>"
            f"<td>{_allowed_badge(allowed)}</td>"
            f"<td class='sub' title='{_html_escape(why_title)}'>{_html_escape(why) or '—'}</td>"
            f"<td class='mono' title='{_html_escape(hash_full)} session={_html_escape(sess)}'>"
            f"{_html_escape(hash_short)}{sess_html}</td>"
            "</tr>"
        )
    return rows


def _hist_rows_html(hist_trades: list[dict[str, Any]]) -> str:
    if not hist_trades:
        return "<tr><td colspan='9'><em>none</em></td></tr>"
    rows = ""
    for t in hist_trades:
        href = _chart_href(
            t.get("symbol"),
            timeframe=t.get("timeframe"),
            entry=t.get("entry_price"),
            sl=t.get("sl"),
            tp1=t.get("tp1"),
            tp2=t.get("tp2"),
            direction=t.get("side"),
            opened=t.get("opened_ts"),
            exit_px=t.get("exit_price"),
            closed=t.get("closed_ts"),
            pnl=t.get("realized_pnl"),
            reason=t.get("exit_status"),
        )
        ts = str(t.get("closed_ts") or t.get("ts") or "")
        ts_short = ts[5:16].replace("T", " ") if len(ts) >= 16 else ts
        src = str(t.get("source") or "")
        src_cls = "tag warn" if src == "paper_live" else ("tag ok" if src == "hub" else "tag")
        rows += (
            f"<tr class='row-link' title='Open LIVE chart' onclick=\"{_row_onclick(href)}\">"
            f"<td class='mono'>{_html_escape(ts_short)}</td>"
            f"<td>{_html_escape(t.get('symbol_display') or t.get('symbol'))}</td>"
            f"<td>{_side_badge(t.get('side'))}</td>"
            f"<td class='mono'>{_html_escape(t.get('entry_price'))}</td>"
            f"<td class='mono'>{_html_escape(t.get('exit_price'))}</td>"
            + _pnl_cell(t.get("realized_pnl"))
            + f"<td class='sub'>{_html_escape(t.get('exit_status') or '—')}</td>"
            f"<td><span class='{src_cls}'>{_html_escape(src or '—')}</span></td>"
            f"<td class='sub'>{_html_escape(t.get('type') or '')}</td>"
            "</tr>"
        )
    return rows


def desk_live_state() -> dict[str, Any]:
    """HTML fragments + counts for silent dashboard refresh."""
    from datetime import datetime, timezone

    from exec.hub_view import list_closed_trades_for_ui, list_positions_for_ui

    pos_payload = list_positions_for_ui()
    open_pos = pos_payload.get("positions") or []
    hist_payload = list_closed_trades_for_ui(limit=30)
    hist_trades = hist_payload.get("trades") or []
    decs = _enrich_rows(_tail_jsonl(DATA / "decisions.jsonl", 20))
    risk = _risk_kill_hint()
    acct = _account_snapshot(
        total_upnl=pos_payload.get("total_unrealized_pnl"),
        mtm_errors=list(pos_payload.get("mtm_errors") or []),
        skip_mtm_fetch=True,
    )
    mode = _exec_mode()
    hub_sync = (os.getenv("HUB_SYNC_EXCHANGE_SL") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    pnl_vs_start = acct.get("pnl_vs_start")
    try:
        pnl_vs_start_f = float(pnl_vs_start)
    except (TypeError, ValueError):
        pnl_vs_start_f = 0.0
    pnl_vs_color = "#22a06b" if pnl_vs_start_f >= 0 else "#d14f4f"
    try:
        upnl_f = float(acct.get("total_unrealized_pnl") or 0)
    except (TypeError, ValueError):
        upnl_f = 0.0
    upnl_color = "#22a06b" if upnl_f >= 0 else "#d14f4f"
    stale_n = int(pos_payload.get("stale_count") or 0)
    paper_live_n = int(pos_payload.get("paper_live_count") or 0)
    paper_live_upnl = pos_payload.get("paper_live_unrealized_pnl")
    src = acct.get("source") or mode
    open_n = len(open_pos)
    hist_n = len(hist_trades)
    dec_n = len(decs)
    agent_mode = _agent_mode_name()
    agent_model = _agent_model_name()
    kind_counts = {"llm": 0, "fallback": 0, "rules": 0}
    for row in decs:
        k = _decision_agent_kind(row)
        kind_counts[k] = kind_counts.get(k, 0) + 1
    agent_chip_cls = "warn" if kind_counts["fallback"] else ("accent" if agent_mode == "llm" else "")
    agent_chip = f'<span class="chip {agent_chip_cls}">agent: {_html_escape(agent_mode)}</span>'
    model_chip = (
        f'<span class="chip">{_html_escape(agent_model)}</span>' if agent_model else ""
    )
    fallback_chip = (
        f'<span class="chip warn">llm fallback: {kind_counts["fallback"]}/{dec_n or 0}</span>'
        if kind_counts["fallback"]
        else ""
    )
    chips = (
        f'<span class="chip accent">mode: {_html_escape(mode)}</span>'
        f"{agent_chip}{model_chip}{fallback_chip}"
        f'<span class="chip ok">source: {_html_escape(src)}</span>'
        '<span class="chip ok">paper shadow: on</span>'
        f'<span class="chip {"ok" if hub_sync else "warn"}">sync SL: {_html_escape(str(hub_sync).lower())}</span>'
        f'<span class="chip {"ok" if not risk.get("killed") else "warn"}">risk kill: {_html_escape(str(bool(risk.get("killed"))).lower())}</span>'
        f'<span class="chip">open: {_html_escape(open_n)}</span>'
        f'<span class="chip {"warn" if paper_live_n else "ok"}">paper-live: {_html_escape(paper_live_n)}</span>'
        f'<span class="chip {"warn" if stale_n else "ok"}">paper ghosts: {_html_escape(stale_n)}</span>'
    )
    account_kpi = f"{_html_escape(acct.get('equity'))} {_html_escape(acct.get('currency'))}"
    account_meta = (
        f"source={_html_escape(src)}<br/>"
        f"start={_html_escape(acct.get('start_balance'))}<br/>"
        f"Δ vs start=<span style=\"font-weight:600;color:{pnl_vs_color}\">{_html_escape(acct.get('pnl_vs_start'))}</span><br/>"
        f"available={_html_escape(acct.get('cash'))}<br/>"
        f"realized (vs start)={_html_escape(acct.get('realized_pnl'))}<br/>"
        f"uPnL (Demo)=<span style=\"font-weight:600;color:{upnl_color}\">{_html_escape(acct.get('total_unrealized_pnl'))}</span><br/>"
        f"paper-live uPnL={_html_escape(paper_live_upnl)} (not in Demo equity)"
    )
    risk_class = "risk-bad" if risk.get("killed") else "risk-ok"
    risk_meta = (
        f"daily_pnl={_html_escape(risk.get('daily_pnl'))}<br/>"
        f"max_daily_loss_usd={_html_escape(risk.get('max_daily_loss_usd'))}<br/>"
        f"date={_html_escape(risk.get('daily_date') or '-')}"
    )
    if agent_mode == "llm" and kind_counts["llm"] and not kind_counts["fallback"]:
        agent_hint = "LLM answering (rules_fired includes llm)"
        agent_hint_class = "risk-ok"
    elif agent_mode == "llm" and kind_counts["fallback"]:
        agent_hint = "LLM errors → rules fallback"
        agent_hint_class = "risk-bad"
    elif agent_mode == "llm":
        agent_hint = "LLM on — waiting for the next candidate"
        agent_hint_class = "risk-ok"
    else:
        agent_hint = "Rules path (AGENT_MODE=rules)"
        agent_hint_class = "risk-ok"
    agent_meta = (
        f"mode={_html_escape(agent_mode)}<br/>"
        f"model={_html_escape(agent_model or '—')}<br/>"
        f"last {dec_n}: llm={kind_counts['llm']} "
        f"fallback={kind_counts['fallback']} rules={kind_counts['rules']}"
    )
    return {
        "pos_rows": _pos_rows_html(open_pos),
        "hist_rows": _hist_rows_html(hist_trades),
        "dec_rows": _dec_rows_html(decs),
        "open_n": open_n,
        "hist_n": hist_n,
        "dec_n": dec_n,
        "chips": chips,
        "account_kpi": account_kpi,
        "account_meta": account_meta,
        "risk_class": risk_class,
        "risk_hint": _html_escape(risk.get("hint")),
        "risk_meta": risk_meta,
        "agent_hint": _html_escape(agent_hint),
        "agent_hint_class": agent_hint_class,
        "agent_meta": agent_meta,
        "pos_head": f"Open positions ({open_n}) · click for LIVE chart",
        "hist_head": f"Trade history ({hist_n}) · click for LIVE chart",
        "dec_head": f"Decision timeline ({dec_n}) · SHA-256",
        "mode": mode,
        "src": src,
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    }


@app.get("/ui/live")
def ui_live() -> dict[str, Any]:
    return desk_live_state()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    live = desk_live_state()
    pos_rows = live["pos_rows"]
    hist_rows = live["hist_rows"]
    dec_rows = live["dec_rows"]
    open_n = live["open_n"]
    hist_n = live["hist_n"]
    dec_n = live["dec_n"]
    chips = live["chips"]
    account_kpi = live["account_kpi"]
    account_meta = live["account_meta"]
    risk_class = live["risk_class"]
    risk_hint = live["risk_hint"]
    risk_meta = live["risk_meta"]
    agent_hint = live["agent_hint"]
    agent_hint_class = live["agent_hint_class"]
    agent_meta = live["agent_meta"]
    pos_head = live["pos_head"]
    hist_head = live["hist_head"]
    dec_head = live["dec_head"]
    live_ts = live["ts"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Bitget Desk - Terminal</title>
  <style>
    :root {{
      --bg:#0b1118;
      --panel:#111a24;
      --panel-2:#0f1722;
      --line:#223247;
      --text:#dce6f3;
      --muted:#8ea4bc;
      --accent:#2f81f7;
      --ok:#22a06b;
      --bad:#d14f4f;
      --warn:#c58a2c;
    }}
    body {{ font-family: Inter, Segoe UI, system-ui, sans-serif; margin: 0; background:var(--bg); color:var(--text); }}
    .wrap {{ padding: 14px 16px 20px; }}
    .topbar {{
      display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:10px;
      border:1px solid var(--line); background:var(--panel); border-radius:10px; padding:10px 12px;
    }}
    .title {{ font-size: 1rem; font-weight: 650; letter-spacing: .2px; }}
    .chips, .hotkeys {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .hotkeys {{ margin-top:8px; }}
    .chip {{
      font-size:.78rem; padding:.18rem .5rem; border:1px solid var(--line); border-radius:999px;
      background:var(--panel-2); color:var(--muted);
    }}
    .chip.accent {{ color:#cfe4ff; border-color:#245ea8; background:#13315a; }}
    .chip.ok {{ color:#c4f1dc; border-color:#2c6f56; }}
    .chip.warn {{ color:#f8e5be; border-color:#73501f; }}
    .hk {{
      display:inline-flex; align-items:center; gap:6px; font-size:.78rem; color:var(--text);
      border:1px solid var(--line); background:#0d1622; border-radius:7px; padding:.28rem .55rem;
      cursor:pointer; text-decoration:none;
    }}
    .hk:hover {{ border-color:#3a5678; background:#132033; }}
    .hk kbd {{
      font:600 .68rem/1 ui-monospace, Consolas, monospace; color:#b7cceb;
      border:1px solid #36506f; background:#152338; border-radius:4px; padding:.12rem .28rem;
    }}
    .grid {{ display:grid; grid-template-columns: 2.1fr 1fr; gap:12px; }}
    .panel {{ border:1px solid var(--line); border-radius:10px; background:var(--panel); }}
    .panel-head {{
      font-size:.82rem; color:var(--muted); padding:8px 10px; border-bottom:1px solid var(--line); letter-spacing:.2px;
      text-transform: uppercase;
    }}
    .panel-body {{ padding:10px; }}
    .kpi {{ font-size:1.55rem; font-weight:700; margin: 2px 0 8px; color:#cde3ff; }}
    .meta {{ color:var(--muted); font-size:.82rem; line-height:1.45; }}
    .risk-ok {{ color:var(--ok); font-weight:600; }}
    .risk-bad {{ color:var(--bad); font-weight:600; }}
    .tabs {{
      display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px;
    }}
    .tab {{
      display:inline-flex; align-items:center; gap:6px;
      font-size:.8rem; font-weight:600; letter-spacing:.2px;
      color:var(--muted); text-decoration:none;
      border:1px solid var(--line); background:#0d1622; border-radius:8px;
      padding:.38rem .7rem; cursor:pointer;
    }}
    .tab:hover {{ border-color:#3a5678; background:#132033; color:var(--text); text-decoration:none; }}
    .tab.active {{
      color:#cfe4ff; border-color:#245ea8; background:#13315a;
    }}
    .tab .count {{
      font-size:.68rem; font-weight:700; color:#b7cceb;
      border:1px solid #36506f; background:#152338; border-radius:999px; padding:.08rem .38rem;
    }}
    .tab-pane {{ display:none; }}
    .tab-pane.active {{ display:block; }}
    .tab-pane .table-wrap {{ max-height: calc(100vh - 280px); }}
    .table-wrap {{ overflow:auto; max-height: 360px; }}
    table {{ width:100%; border-collapse: separate; border-spacing:0; font-size:.83rem; min-width: 900px; }}
    th, td {{ text-align:left; padding:.42rem .5rem; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{
      color:var(--muted); font-weight:600; font-size:.76rem; text-transform:uppercase; letter-spacing:.25px;
      position: sticky; top: 0; z-index: 2; background:#152233; box-shadow: 0 1px 0 var(--line);
    }}
    tr:hover td {{ background:#102033; }}
    tr.row-link {{ cursor: pointer; }}
    tr.row-link:hover td {{ background:#163047; }}
    .sub {{ color:var(--muted); font-size:.72rem; }}
    .mono {{ font-family: ui-monospace, Consolas, monospace; font-size:.78rem; }}
    .tag {{
      display:inline-block; font-size:.72rem; font-weight:650; letter-spacing:.3px;
      padding:.14rem .4rem; border-radius:5px; border:1px solid var(--line); background:#0e1722; color:var(--muted);
    }}
    .tag.enter {{ color:#c4f1dc; border-color:#2c6f56; background:#123528; }}
    .tag.skip {{ color:#d3deea; border-color:#3a4d63; background:#172230; }}
    .tag.reduce {{ color:#f8e5be; border-color:#73501f; background:#2b2112; }}
    .tag.long {{ color:#c4f1dc; border-color:#2c6f56; background:#123528; }}
    .tag.short {{ color:#f3c4c4; border-color:#7a3535; background:#311919; }}
    .tag.ok {{ color:#c4f1dc; border-color:#2c6f56; background:#123528; }}
    .tag.bad {{ color:#f3c4c4; border-color:#7a3535; background:#311919; }}
    .tag.llm {{ color:#cfe4ff; border-color:#245ea8; background:#13315a; }}
    .footer {{ color:var(--muted); font-size:.78rem; margin-top:10px; }}
    .hint {{ color:var(--muted); font-size:.74rem; margin:0 0 10px; }}
    a {{ color:#6daefc; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    code {{ background:#0b141f; border:1px solid var(--line); padding:.08rem .3rem; border-radius:4px; }}
    .stack {{ display:grid; gap:12px; }}
    @media (max-width: 1200px) {{
      .grid {{ grid-template-columns:1fr; }}
      .table-wrap {{ max-height: none; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <div class="title">Bitget S2 Divergent Agent Desk</div>
        <div class="meta">Execution terminal · live poll 8s · Demo PnL when hub mode · <span id="live-stamp">{_html_escape(live_ts)} UTC</span></div>
        <div class="hotkeys">
          <a class="hk" href="#" id="btn-refresh" title="Refresh data (R)"><kbd>R</kbd> Refresh</a>
          <a class="hk" href="#positions" title="Positions tab (P)"><kbd>P</kbd> Positions</a>
          <a class="hk" href="#history" title="History tab (T)"><kbd>T</kbd> History</a>
          <a class="hk" href="#decisions" title="Decisions tab (D)"><kbd>D</kbd> Decisions</a>
          <a class="hk" href="#risk" title="Jump to risk (K)"><kbd>K</kbd> Risk</a>
          <a class="hk" href="/health" target="_blank" rel="noopener" title="Open /health (H)"><kbd>H</kbd> Health</a>
          <a class="hk" href="/equity" target="_blank" rel="noopener" title="Open /equity (E)"><kbd>E</kbd> Equity</a>
        </div>
      </div>
      <div class="chips" id="chips">
        {chips}
      </div>
    </div>
    <p class="hint">Tabs: P positions · T history · D decisions. Click a position or history row for LIVE chart.</p>

    <div class="tabs" role="tablist">
      <a class="tab active" id="tab-positions" href="#positions" data-tab="positions">Open positions <span class="count" id="count-positions">{open_n}</span></a>
      <a class="tab" id="tab-history" href="#history" data-tab="history">Trade history <span class="count" id="count-history">{hist_n}</span></a>
      <a class="tab" id="tab-decisions" href="#decisions" data-tab="decisions">Decisions <span class="count" id="count-decisions">{dec_n}</span></a>
    </div>

    <div class="grid">
      <div class="stack">
        <div class="tab-pane active" id="pane-positions">
          <div class="panel" id="panel-positions">
            <div class="panel-head" id="head-positions">{_html_escape(pos_head)}</div>
            <div class="panel-body table-wrap">
              <table>
                <thead><tr><th>symbol</th><th>side</th><th>qty / notional / margin</th><th>entry</th><th>mark</th><th>uPnL</th><th>id</th><th>SL (exch)</th><th>TP1 bot</th><th>TP2 (exch)</th><th>sync</th></tr></thead>
                <tbody id="tbody-positions">{pos_rows}</tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="tab-pane" id="pane-history">
          <div class="panel" id="panel-history">
            <div class="panel-head" id="head-history">{_html_escape(hist_head)}</div>
            <div class="panel-body table-wrap">
              <table>
                <thead><tr><th>closed</th><th>symbol</th><th>side</th><th>entry</th><th>exit</th><th>pnl</th><th>status</th><th>venue</th><th>type</th></tr></thead>
                <tbody id="tbody-history">{hist_rows}</tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="tab-pane" id="pane-decisions">
          <div class="panel" id="panel-decisions">
            <div class="panel-head" id="head-decisions">{_html_escape(dec_head)}</div>
            <div class="panel-body table-wrap">
              <table style="min-width:640px;">
                <thead><tr><th>ts</th><th>symbol</th><th>type</th><th>agent</th><th>action</th><th>allowed</th><th>why</th><th>hash</th></tr></thead>
                <tbody id="tbody-decisions">{dec_rows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <div class="stack">
        <div class="panel" id="account">
          <div class="panel-head">Account / Equity (Bitget)</div>
          <div class="panel-body">
            <div class="kpi" id="account-kpi">{account_kpi}</div>
            <div class="meta" id="account-meta">
              {account_meta}
            </div>
          </div>
        </div>

        <div class="panel" id="agent">
          <div class="panel-head">Agent / LLM</div>
          <div class="panel-body">
            <div id="agent-hint" class="{agent_hint_class}">{agent_hint}</div>
            <div class="meta" id="agent-meta" style="margin-top:8px;">
              {agent_meta}
            </div>
          </div>
        </div>

        <div class="panel" id="risk">
          <div class="panel-head">Risk status</div>
          <div class="panel-body">
            <div id="risk-hint" class="{risk_class}">{risk_hint}</div>
            <div class="meta" id="risk-meta" style="margin-top:8px;">
              {risk_meta}
            </div>
          </div>
        </div>

        <div class="panel" id="ops">
          <div class="panel-head">API / Ops</div>
          <div class="panel-body meta">
            <a href="/health">/health</a> ·
            <a href="/positions">/positions</a> ·
            <a href="/decisions">/decisions</a> ·
            <a href="/fills">/fills</a> ·
            <a href="/history">/history</a> ·
            <a href="/chart?symbol=BTC/USDT:USDT&amp;timeframe=15m">/chart</a> ·
            <a href="/candidates">/candidates</a> ·
            <a href="/equity">/equity</a> ·
            <a href="/account">/account</a>
            <div class="footer" style="margin-top:8px;">
              Scan once: <code>.venv\\Scripts\\python.exe scripts\\run_signal_loop.py --once</code>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <script>
    (function () {{
      var allowed = {{ positions: 1, history: 1, decisions: 1 }};
      var pollMs = 8000;
      var inflight = false;
      function currentTab() {{
        var name = String(location.hash || '').replace('#', '');
        if (allowed[name]) return name;
        try {{
          name = String(sessionStorage.getItem('deskTab') || '');
        }} catch (e) {{
          name = '';
        }}
        return allowed[name] ? name : 'positions';
      }}
      function showTab(name) {{
        if (!allowed[name]) name = 'positions';
        document.querySelectorAll('.tab-pane').forEach(function (el) {{
          el.classList.toggle('active', el.id === 'pane-' + name);
        }});
        document.querySelectorAll('a.tab').forEach(function (el) {{
          el.classList.toggle('active', el.getAttribute('data-tab') === name);
        }});
        try {{ sessionStorage.setItem('deskTab', name); }} catch (e) {{}}
        if (location.hash !== '#' + name) {{
          history.replaceState(null, '', '#' + name);
        }}
      }}
      function patchHtml(id, html) {{
        var el = document.getElementById(id);
        if (!el || html == null) return;
        if (el.innerHTML === html) return;
        var wrap = el.closest('.table-wrap');
        var top = wrap ? wrap.scrollTop : 0;
        el.innerHTML = html;
        if (wrap) wrap.scrollTop = top;
      }}
      function patchText(id, text) {{
        var el = document.getElementById(id);
        if (!el || text == null) return;
        if (el.textContent === String(text)) return;
        el.textContent = String(text);
      }}
      function applyLive(data) {{
        patchHtml('chips', data.chips);
        patchHtml('account-kpi', data.account_kpi);
        patchHtml('account-meta', data.account_meta);
        patchHtml('risk-hint', data.risk_hint);
        var rh = document.getElementById('risk-hint');
        if (rh && data.risk_class) rh.className = data.risk_class;
        patchHtml('risk-meta', data.risk_meta);
        patchHtml('agent-hint', data.agent_hint);
        var ah = document.getElementById('agent-hint');
        if (ah && data.agent_hint_class) ah.className = data.agent_hint_class;
        patchHtml('agent-meta', data.agent_meta);
        patchHtml('tbody-positions', data.pos_rows);
        patchHtml('tbody-history', data.hist_rows);
        patchHtml('tbody-decisions', data.dec_rows);
        patchText('head-positions', data.pos_head);
        patchText('head-history', data.hist_head);
        patchText('head-decisions', data.dec_head);
        patchText('count-positions', data.open_n);
        patchText('count-history', data.hist_n);
        patchText('count-decisions', data.dec_n);
        var stamp = document.getElementById('live-stamp');
        if (stamp && data.ts) stamp.textContent = data.ts + ' UTC';
      }}
      function refreshLive() {{
        if (inflight) return Promise.resolve();
        if (document.visibilityState === 'hidden') return Promise.resolve();
        inflight = true;
        return fetch('/ui/live', {{ cache: 'no-store' }})
          .then(function (r) {{
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
          }})
          .then(applyLive)
          .catch(function () {{}})
          .then(function () {{ inflight = false; }});
      }}
      showTab(currentTab());
      window.addEventListener('hashchange', function () {{ showTab(currentTab()); }});
      document.querySelectorAll('a.tab').forEach(function (el) {{
        el.addEventListener('click', function (ev) {{
          ev.preventDefault();
          showTab(el.getAttribute('data-tab'));
        }});
      }});
      var btn = document.getElementById('btn-refresh');
      if (btn) {{
        btn.addEventListener('click', function (ev) {{
          ev.preventDefault();
          refreshLive();
        }});
      }}
      setInterval(refreshLive, pollMs);
      document.addEventListener('visibilitychange', function () {{
        if (document.visibilityState === 'visible') refreshLive();
      }});
      var map = {{
        r: function () {{ refreshLive(); }},
        p: function () {{ showTab('positions'); }},
        t: function () {{ showTab('history'); }},
        d: function () {{ showTab('decisions'); }},
        k: function () {{
          var risk = document.getElementById('risk');
          if (risk) risk.scrollIntoView();
        }},
        h: function () {{ window.open('/health', '_blank'); }},
        e: function () {{ window.open('/equity', '_blank'); }}
      }};
      document.addEventListener('keydown', function (ev) {{
        if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
        var el = ev.target;
        if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
        var fn = map[String(ev.key || '').toLowerCase()];
        if (fn) {{ ev.preventDefault(); fn(); }}
      }});
    }})();
  </script>
</body>
</html>
"""
