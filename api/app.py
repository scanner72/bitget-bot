"""Minimal FastAPI dashboard for paper Bitget desk (no live orders)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from exec.paper import list_open, list_open_with_pnl
from exec.account import get_account
from ingest.symbols import enrich_symbol_fields, to_bitget_id, to_display

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

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
            row["pnl_source"] = "paper_fallback"
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
    """Sum exchange unrealised PnL when any row has hub pnl_source; else None."""
    vals: list[float] = []
    any_hub = False
    for pos in positions:
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
    """Dashboard cell: local notional + exchange margin/lev/qty when present."""
    size = p.get("size_usd")
    try:
        size_s = f"${float(size):.2f}" if size is not None else _html_escape(size)
    except (TypeError, ValueError):
        size_s = _html_escape(size)
    parts = [f"notional {size_s}"]
    margin = p.get("exchange_margin_usd")
    lev = p.get("exchange_leverage")
    qty = p.get("exchange_qty")
    if margin is not None or lev is not None or qty is not None:
        bits: list[str] = []
        if margin is not None:
            try:
                bits.append(f"exch margin ${float(margin):.2f}")
            except (TypeError, ValueError):
                bits.append(f"exch margin {_html_escape(margin)}")
        if lev is not None:
            bits.append(f"{_html_escape(lev)}x")
        if qty is not None:
            try:
                qf = float(qty)
                q_s = f"{qf:.4f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                q_s = str(qty)
            bits.append(f"qty {q_s}")
        parts.append(" · ".join(bits))
    return "<br/>".join(parts)


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
    return {"ok": True, "paper": True}


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
    open_pos, total_upnl, errors = _positions_mtm()
    open_pos = _enrich_rows([_exit_fields(p) for p in open_pos])
    hub_map, hub_err = _hub_positions_by_key()
    open_pos = _enrich_with_exchange(open_pos, hub_map=hub_map, hub_err=hub_err)
    hub_total = _sum_hub_unrealised(open_pos)
    if hub_total is not None:
        total_upnl = hub_total
    out: dict[str, Any] = {
        "positions": open_pos,
        "count": len(open_pos),
        "total_unrealized_pnl": total_upnl,
    }
    if errors:
        out["mtm_errors"] = errors
    if hub_err:
        out.setdefault("mtm_errors", [])
        if isinstance(out["mtm_errors"], list):
            out["mtm_errors"].append(hub_err)
    return out


@app.get("/decisions")
def decisions(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = _enrich_rows(_tail_jsonl(DATA / "decisions.jsonl", limit))
    return {"decisions": rows, "count": len(rows)}


@app.get("/fills")
def fills(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = _enrich_rows(_tail_jsonl(DATA / "paper_fills.jsonl", limit))
    return {"fills": rows, "count": len(rows)}


@app.get("/candidates")
def candidates(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = _enrich_rows(_tail_jsonl(DATA / "candidates.jsonl", limit))
    return {"candidates": rows, "count": len(rows)}


def _html_escape(s: Any) -> str:
    t = str(s if s is not None else "")
    return (
        t.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    open_pos, _total_upnl_dash, _mtm_errs = _positions_mtm()
    open_pos = _enrich_rows([_exit_fields(p) for p in open_pos])
    hub_map, hub_err = _hub_positions_by_key()
    open_pos = _enrich_with_exchange(open_pos, hub_map=hub_map, hub_err=hub_err)
    hub_total = _sum_hub_unrealised(open_pos)
    if hub_total is not None:
        _total_upnl_dash = hub_total
    decs = _enrich_rows(_tail_jsonl(DATA / "decisions.jsonl", 20))
    risk = _risk_kill_hint()
    kill_color = "#c0392b" if risk.get("killed") else "#27ae60"
    acct = _account_snapshot(
        total_upnl=_total_upnl_dash,
        mtm_errors=_mtm_errs,
        skip_mtm_fetch=True,
    )

    def _pnl_cell(val: Any) -> str:
        if val is None:
            return "<td><em>n/a</em></td>"
        try:
            num = float(val)
        except (TypeError, ValueError):
            return f"<td>{_html_escape(val)}</td>"
        color = "#27ae60" if num >= 0 else "#c0392b"
        return f'<td style="color:{color};font-weight:600">{_html_escape(f"{num:.4f}")}</td>'

    pos_rows = ""
    if not open_pos:
        pos_rows = "<tr><td colspan='10'><em>none</em></td></tr>"
    else:
        for p in open_pos:
            pos_rows += (
                "<tr>"
                f"<td>{_html_escape(p.get('symbol_display') or p.get('symbol'))}<br/><span style='color:#9fb3c8;font-size:.75rem'>{_html_escape(p.get('symbol_id') or '')}</span></td>"
                f"<td>{_html_escape(p.get('side'))}</td>"
                f"<td>{_size_cell_html(p)}</td>"
                f"<td>{_html_escape(p.get('entry_price_display') if p.get('entry_price_display') is not None else p.get('entry_price'))}</td>"
                f"<td>{_html_escape(p.get('mark_price'))}</td>"
                + _pnl_cell(p.get("unrealized_pnl_usd"))
                + f"<td>{_html_escape(p.get('position_id'))}</td>"
                f"<td>{_html_escape(p.get('sl'))}</td>"
                f"<td>{_html_escape(p.get('tp1'))}</td>"
                f"<td>{_html_escape(p.get('tp2'))}</td>"
                "</tr>"
            )

    dec_rows = ""
    if not decs:
        dec_rows = "<tr><td colspan='5'><em>none</em></td></tr>"
    else:
        for d in reversed(decs):
            agent = d.get("agent") if isinstance(d.get("agent"), dict) else {}
            action = d.get("action") or agent.get("action")
            allowed = d.get("allowed")
            if allowed is None and isinstance(d.get("risk"), dict):
                allowed = d["risk"].get("allowed")
            dec_rows += (
                "<tr>"
                f"<td>{_html_escape(d.get('ts'))}</td>"
                f"<td>{_html_escape(d.get('symbol_display') or d.get('symbol'))}<br/><span style='color:#9fb3c8;font-size:.75rem'>{_html_escape(d.get('symbol_id') or '')}</span></td>"
                f"<td>{_html_escape(d.get('type'))}</td>"
                f"<td>{_html_escape(action)}</td>"
                f"<td>{_html_escape(allowed)}</td>"
                "</tr>"
            )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="8"/>
  <title>Bitget Desk - paper</title>
  <style>
    body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 1.5rem; background:#0f1419; color:#e7ecf1; }}
    h1 {{ font-size: 1.4rem; margin: 0 0 .5rem; }}
    .badge {{ display:inline-block; padding:.2rem .6rem; border-radius:999px; background:#1f6feb; font-size:.85rem; }}
    .card {{ background:#1a2332; border-radius:10px; padding:1rem 1.2rem; margin:1rem 0; }}
    table {{ width:100%; border-collapse: collapse; font-size:.9rem; }}
    th, td {{ text-align:left; padding:.35rem .5rem; border-bottom:1px solid #2a3548; }}
    th {{ color:#9fb3c8; font-weight:600; }}
    a {{ color:#58a6ff; }}
    code {{ background:#111820; padding:.1rem .35rem; border-radius:4px; }}
  </style>
</head>
<body>
  <h1>Bitget S2 Divergent - paper desk</h1>
  <span class="badge">paper only — no live orders</span>
  <p style="color:#9fb3c8;font-size:.8rem;margin:.35rem 0 0;">auto-refresh 8s - PnL from Bitget Demo when hub_demo</p>
  <p style="margin-top:.8rem">API:
    <a href="/health">/health</a> ·
    <a href="/positions">/positions</a> ·
    <a href="/decisions">/decisions</a> ·
    <a href="/fills">/fills</a> ·
    <a href="/candidates">/candidates</a> ·
    <a href="/equity">/equity</a> ·
    <a href="/account">/account</a>
  </p>

    <div class="card" style="border:1px solid #1f6feb;">
    <h2 style="margin-top:0;font-size:1.1rem">Paper account / Equity</h2>
    <p style="font-size:1.6rem;font-weight:700;margin:.4rem 0;color:#58a6ff;">
      Equity: {_html_escape(acct.get('equity'))} {_html_escape(acct.get('currency'))}
    </p>
    <p style="color:#9fb3c8;font-size:.9rem;margin:0;">
      start={_html_escape(acct.get('start_balance'))}
      · cash={_html_escape(acct.get('cash'))}
      · realized_pnl={_html_escape(acct.get('realized_pnl'))}
      · open_notional={_html_escape(acct.get('open_positions_notional'))}
    </p>
    <p style="color:#9fb3c8;font-size:.9rem;margin:.35rem 0 0;">
      total_uPnL=<span style="font-weight:600;color:{('#27ae60' if float(acct.get('total_unrealized_pnl') or 0) >= 0 else '#c0392b')}">{_html_escape(acct.get('total_unrealized_pnl'))}</span>
      · equity_mtm={_html_escape(acct.get('equity_mtm'))}
    </p>
    <p style="margin:.5rem 0 0;font-size:.85rem;">
      <a href="/equity">/equity</a> · <a href="/account">/account</a>
    </p>
  </div>

  <div class="card">
    <h2 style="margin-top:0;font-size:1.1rem">Risk kill</h2>
    <p style="color:{kill_color}; font-weight:600; margin:.3rem 0">{_html_escape(risk.get('hint'))}</p>
    <p style="color:#9fb3c8; font-size:.85rem; margin:0">
      daily_pnl={_html_escape(risk.get('daily_pnl'))}
      · max_daily_loss_usd={_html_escape(risk.get('max_daily_loss_usd'))}
      · date={_html_escape(risk.get('daily_date') or '-')}
    </p>
  </div>

  <div class="card">
    <h2 style="margin-top:0;font-size:1.1rem">Open positions ({len(open_pos)}) - total uPnL: {_html_escape(acct.get('total_unrealized_pnl'))}</h2>
    <table>
      <thead><tr><th>symbol</th><th>side</th><th>size (notional / exch)</th><th>entry</th><th>mark</th><th>uPnL</th><th>id</th><th>sl</th><th>tp1</th><th>tp2</th></tr></thead>
      <tbody>{pos_rows}</tbody>
    </table>
  </div>

  <div class="card">
    <h2 style="margin-top:0;font-size:1.1rem">Last decisions ({len(decs)})</h2>
    <table>
      <thead><tr><th>ts</th><th>symbol</th><th>type</th><th>action</th><th>allowed</th></tr></thead>
      <tbody>{dec_rows}</tbody>
    </table>
  </div>

  <p style="color:#9fb3c8;font-size:.85rem">
    Scan once: run <code>.venv\\Scripts\\python.exe scripts\\run_signal_loop.py --once</code>
    (POST /scan/once omitted - loop can hit Bitget public OHLCV and exceed a short API timeout).
  </p>
</body>
</html>
"""
