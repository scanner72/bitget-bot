"""Hub-first views for UI: positions and fills match Bitget Demo/live."""

from __future__ import annotations

from typing import Any

from exec.bitget_hub import ccxt_to_bitget_symbol
from exec.demo_universe import is_paper_venue
from exec.paper import enrich_position_mtm, list_open
from ingest.symbols import enrich_symbol_fields


def _f(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def bitget_to_ccxt(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return s
    if "/" in s:
        return s
    if s.endswith("USDT"):
        return f"{s[:-4]}/USDT:USDT"
    return s


def _paper_by_key() -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        opens = list_open() or []
    except Exception:
        return out
    for pos in opens:
        if not isinstance(pos, dict):
            continue
        side = str(pos.get("side") or "").lower()
        if side in {"buy"}:
            side = "long"
        elif side in {"sell"}:
            side = "short"
        try:
            bg = ccxt_to_bitget_symbol(str(pos.get("symbol") or "")).upper()
        except Exception:
            bg = ""
        if not bg or side not in {"long", "short"}:
            continue
        out[(bg, side)] = pos
    return out


def _tpsl_by_key(orders: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for it in orders or []:
        sym = str(it.get("symbol") or "").upper()
        side = str(it.get("posSide") or "").lower()
        if not sym or side not in {"long", "short"}:
            continue
        # Prefer the newest / first pending tpsl per key
        out.setdefault((sym, side), it)
    return out


def _hub_items(live: Any) -> list[dict[str, Any]]:
    if isinstance(live, dict):
        items = live.get("list") or live.get("data") or []
    else:
        items = live or []
    return [x for x in items if isinstance(x, dict)]


def _paper_live_row(paper: dict[str, Any]) -> dict[str, Any]:
    meta = paper.get("meta") if isinstance(paper.get("meta"), dict) else {}
    mark = None
    err = None
    try:
        from ingest.bitget_ohlcv import fetch_mark_price

        mark = float(fetch_mark_price(str(paper.get("symbol") or "")))
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    row = enrich_position_mtm(paper, mark_price=mark, error=err)
    qty = _f(row.get("qty"), None)
    entry = _f(row.get("entry_price"), None)
    mark_f = _f(row.get("mark_price"), None)
    px = mark_f if mark_f and mark_f > 0 else entry
    notional = None
    if qty is not None and px is not None and px > 0:
        notional = float(qty) * float(px)
    sl = row.get("sl") or meta.get("sl")
    tp1 = row.get("tp1") or meta.get("tp1")
    tp2 = row.get("tp2") or meta.get("tp2")
    row.update(
        {
            "entry_price_display": entry,
            "exchange_qty": qty,
            "exchange_notional_usd": notional,
            "pnl_source": "paper_live",
            "venue": "paper",
            "tracked": True,
            "stale": False,
            "tpsl_on_exchange": False,
            "tpsl_note": "bot paper (not on demo)",
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "bot_sl": sl,
            "bot_tp2": tp2,
            "type": meta.get("type") or row.get("type"),
            "timeframe": meta.get("timeframe") or row.get("timeframe"),
            "tp1_hit": row.get("tp1_hit") or meta.get("tp1_hit"),
            "be_timeout": row.get("be_timeout") or meta.get("be_timeout"),
            "stale_no_tp1": row.get("stale_no_tp1") or meta.get("stale_no_tp1"),
            "exec_reason": meta.get("exec_reason"),
            "fill_source": meta.get("fill_source"),
        }
    )
    return enrich_symbol_fields(row)


def list_positions_for_ui() -> dict[str, Any]:
    """Exchange positions first; paper joined for bot metadata only."""
    from exec.router import exec_mode

    mode = exec_mode()
    if mode not in {"hub_demo", "live"}:
        from exec.paper import list_open_with_pnl

        rows, total, errors = list_open_with_pnl()
        return {
            "positions": [enrich_symbol_fields(r) for r in rows],
            "count": len(rows),
            "total_unrealized_pnl": total,
            "stale_count": 0,
            "source": "paper",
            "untracked_count": 0,
            "mtm_errors": errors or [],
        }

    errors: list[str] = []
    try:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        live = client.current_positions() or {}
        items = _hub_items(live)
    except Exception as exc:  # noqa: BLE001
        return {
            "positions": [],
            "count": 0,
            "total_unrealized_pnl": None,
            "stale_count": 0,
            "untracked_count": 0,
            "source": mode,
            "mtm_errors": [f"hub_positions_fetch_failed: {type(exc).__name__}: {exc}"],
        }

    tpsl_map: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        tpsl_map = _tpsl_by_key(client.unfilled_strategy_orders(type="tpsl"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"hub_tpsl_fetch_failed: {type(exc).__name__}: {exc}")

    paper_map = _paper_by_key()
    hub_keys: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    upnl_vals: list[float] = []

    for hub in items:
        bg = str(hub.get("symbol") or "").upper()
        side = str(hub.get("posSide") or "").lower()
        qty = _f(hub.get("available"), None)
        if qty is None:
            qty = _f(hub.get("total"), None)
        if (qty or 0) <= 0:
            continue
        if not bg or side not in {"long", "short"}:
            continue
        hub_keys.add((bg, side))
        paper = paper_map.get((bg, side)) or {}
        meta = paper.get("meta") if isinstance(paper.get("meta"), dict) else {}
        tpsl = tpsl_map.get((bg, side)) or {}

        entry = _f(hub.get("avgPrice") or hub.get("openPriceAvg"), None)
        mark = _f(hub.get("markPrice"), None)
        margin = _f(hub.get("positionBalance"), None)
        lev = hub.get("leverage")
        upnl = _f(hub.get("unrealisedPnl") or hub.get("unrealizedPnl"), None)
        if upnl is not None:
            upnl_vals.append(float(upnl))
        px = mark if mark and mark > 0 else entry
        notional = None
        if qty is not None and px is not None and px > 0:
            notional = float(qty) * float(px)

        sl_ex = tpsl.get("stopLoss") or None
        tp_ex = tpsl.get("takeProfit") or None
        tpsl_on = bool(sl_ex or tp_ex)

        ccxt_sym = str(paper.get("symbol") or bitget_to_ccxt(bg))
        row: dict[str, Any] = {
            "symbol": ccxt_sym,
            "side": side,
            "size_usd": paper.get("size_usd") or notional,
            "qty": qty,
            "entry_price": entry,
            "entry_price_display": entry,
            "mark_price": mark,
            "unrealized_pnl_usd": upnl,
            "position_id": paper.get("position_id") or f"hub:{bg}:{side}",
            "opened_ts": paper.get("opened_ts"),
            "exchange_qty": qty,
            "exchange_margin_usd": margin,
            "exchange_leverage": lev,
            "exchange_entry": entry,
            "exchange_notional_usd": notional,
            "exchange_mark": mark,
            "pnl_source": "hub_demo" if mode == "hub_demo" else "hub_live",
            "venue": "hub",
            "tracked": bool(paper),
            "tpsl_on_exchange": tpsl_on,
            "hub_sl_price": sl_ex,
            "hub_tp2_price": tp_ex,
            "sl": sl_ex,
            "tp2": tp_ex,
            "tp1": paper.get("tp1") or meta.get("tp1"),
            "bot_sl": paper.get("sl") or meta.get("sl"),
            "bot_tp2": paper.get("tp2") or meta.get("tp2"),
            "type": meta.get("type") or paper.get("type"),
            "timeframe": meta.get("timeframe") or paper.get("timeframe"),
            "tp1_hit": paper.get("tp1_hit") or meta.get("tp1_hit"),
            "be_timeout": paper.get("be_timeout") or meta.get("be_timeout"),
            "stale_no_tp1": paper.get("stale_no_tp1") or meta.get("stale_no_tp1"),
            "stale": False,
        }
        if not tpsl_on:
            row["tpsl_note"] = "none on exchange"
        profit_rate = _f(hub.get("profitRate"), None)
        if profit_rate is not None:
            row["unrealized_pnl_pct"] = (
                profit_rate * 100.0 if abs(profit_rate) <= 2.0 else profit_rate
            )
        elif upnl is not None and margin:
            row["unrealized_pnl_pct"] = (upnl / float(margin)) * 100.0
        rows.append(enrich_symbol_fields(row))

    stale_n = 0
    paper_live_upnl: list[float] = []
    for key, paper in paper_map.items():
        if key in hub_keys:
            continue
        if is_paper_venue(paper):
            row = _paper_live_row(paper)
            rows.append(row)
            upnl = _f(row.get("unrealized_pnl_usd"), None)
            if upnl is not None:
                paper_live_upnl.append(float(upnl))
            continue
        stale_n += 1
        # Do not list ghosts as open; surface count only.

    untracked = sum(1 for r in rows if not r.get("tracked"))
    paper_live_n = sum(1 for r in rows if r.get("venue") == "paper")
    hub_n = sum(1 for r in rows if r.get("venue") == "hub")
    hub_upnl = float(sum(upnl_vals)) if hub_n else 0.0
    paper_upnl = float(sum(paper_live_upnl)) if paper_live_n else 0.0
    out: dict[str, Any] = {
        "positions": rows,
        "count": len(rows),
        "hub_count": hub_n,
        "paper_live_count": paper_live_n,
        "paper_live_unrealized_pnl": paper_upnl,
        "total_unrealized_pnl": hub_upnl,
        "stale_count": stale_n,
        "untracked_count": untracked,
        "source": mode,
    }
    if errors:
        out["mtm_errors"] = errors
    return out


def _fill_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        items = raw.get("list") or raw.get("fills") or []
        return [x for x in items if isinstance(x, dict)]
    return []


def list_fills_for_ui(limit: int = 50) -> dict[str, Any]:
    """Exchange fills as primary; paper exit_status joined when ids match."""
    from exec.router import exec_mode

    mode = exec_mode()
    try:
        paper_rows = _paper_fill_rows()
    except Exception:
        paper_rows = []

    paper_by_oid: dict[str, dict[str, Any]] = {}
    for pf in paper_rows:
        meta = pf.get("meta") if isinstance(pf.get("meta"), dict) else {}
        for k in (
            "hub_order_id",
            "hub_close_order_id",
            "hub_client_oid",
            "hub_close_client_oid",
            "hub_tpsl_order_id",
        ):
            oid = str(meta.get(k) or "").strip()
            if oid:
                paper_by_oid[oid] = pf

    if mode not in {"hub_demo", "live"}:
        tail = paper_rows[-limit:] if limit < len(paper_rows) else paper_rows
        return {
            "fills": [enrich_symbol_fields(r) for r in tail],
            "count": len(tail),
            "source": "paper",
        }

    try:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        raw = client.fills(category="USDT-FUTURES", limit=min(max(limit, 1), 100))
        items = _fill_items(raw)
    except Exception as exc:  # noqa: BLE001
        tail = paper_rows[-limit:] if limit < len(paper_rows) else paper_rows
        return {
            "fills": [enrich_symbol_fields(r) for r in tail],
            "count": len(tail),
            "source": "paper_fallback",
            "error": f"{type(exc).__name__}: {exc}",
        }

    rows: list[dict[str, Any]] = []
    for it in items:
        oid = str(it.get("orderId") or "")
        coid = str(it.get("clientOid") or "")
        paper = paper_by_oid.get(oid) or paper_by_oid.get(coid) or {}
        meta = paper.get("meta") if isinstance(paper.get("meta"), dict) else {}
        bg = str(it.get("symbol") or "")
        fee = None
        details = it.get("feeDetail")
        if isinstance(details, list):
            try:
                fee = sum(float(x.get("fee") or 0) for x in details if isinstance(x, dict))
            except (TypeError, ValueError):
                fee = None
        ts_ms = it.get("createdTime") or it.get("execTime")
        ts = None
        try:
            if ts_ms is not None and str(ts_ms).isdigit():
                from datetime import datetime, timezone

                ts = datetime.fromtimestamp(int(ts_ms) / 1000.0, tz=timezone.utc).isoformat()
        except Exception:
            ts = str(ts_ms) if ts_ms is not None else None
        row = {
            "ts": ts,
            "symbol": bitget_to_ccxt(bg),
            "symbol_id": bg,
            "side": it.get("side"),
            "trade_side": it.get("tradeSide"),
            "price": _f(it.get("execPrice"), None),
            "qty": _f(it.get("execQty"), None),
            "exec_value": _f(it.get("execValue"), None),
            "exec_pnl": _f(it.get("execPnl"), None),
            "fee": fee,
            "order_id": oid,
            "client_oid": coid,
            "order_type": it.get("orderType"),
            "event": it.get("tradeSide"),
            "bot_exit_status": meta.get("exit_status") or paper.get("exit_status"),
            "bot_position_id": paper.get("position_id"),
            "source": mode,
        }
        rows.append(enrich_symbol_fields(row))

    for pf in paper_rows:
        meta = pf.get("meta") if isinstance(pf.get("meta"), dict) else {}
        if str(meta.get("exec_venue") or "").lower() != "paper":
            continue
        event = str(pf.get("event") or "")
        if event not in {"open", "close"}:
            continue
        rows.append(
            enrich_symbol_fields(
                {
                    "ts": pf.get("ts"),
                    "symbol": pf.get("symbol"),
                    "side": pf.get("side"),
                    "trade_side": "open" if event == "open" else "close",
                    "price": _f(pf.get("price"), None),
                    "qty": _f(pf.get("qty"), None),
                    "exec_pnl": _f(pf.get("realized_pnl"), 0.0) if event == "close" else 0.0,
                    "event": event,
                    "bot_exit_status": meta.get("exit_status") or pf.get("exit_status"),
                    "bot_position_id": pf.get("position_id"),
                    "source": "paper_live",
                    "exec_reason": meta.get("exec_reason"),
                    "fill_source": meta.get("fill_source"),
                }
            )
        )

    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    rows = rows[:limit]
    return {"fills": rows, "count": len(rows), "source": mode}


def _paper_fill_rows() -> list[dict[str, Any]]:
    from pathlib import Path
    import json

    path = Path(__file__).resolve().parents[1] / "data" / "paper_fills.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def list_closed_trades_for_ui(limit: int = 40) -> dict[str, Any]:
    """Closed trades for history chart (v1-style): paper open+close pair.

    Overlay uses bot SL/TP; candles on the chart page are always LIVE Bitget.
    """
    import os

    tf_default = (os.getenv("TIMEFRAME") or "15m").strip() or "15m"
    opens: dict[str, dict[str, Any]] = {}
    closed: list[dict[str, Any]] = []
    for f in _paper_fill_rows():
        pid = str(f.get("position_id") or "")
        event = str(f.get("event") or "").lower()
        if event == "open" and pid:
            opens[pid] = f
            continue
        if event != "close" or not pid:
            continue
        op = opens.get(pid) or {}
        meta = f.get("meta") if isinstance(f.get("meta"), dict) else {}
        om = op.get("meta") if isinstance(op.get("meta"), dict) else {}
        venue = str(meta.get("exec_venue") or om.get("exec_venue") or "").lower()
        if venue == "paper":
            source = "paper_live"
        elif venue == "hub" or meta.get("hub_order_id") or om.get("hub_order_id"):
            source = "hub"
        else:
            source = "paper"
        entry = _f(f.get("entry_price"), None)
        if entry is None:
            entry = _f(op.get("price"), None)
        closed.append(
            enrich_symbol_fields(
                {
                    "ts": f.get("ts"),
                    "opened_ts": op.get("ts") or op.get("opened_ts"),
                    "closed_ts": f.get("ts"),
                    "position_id": pid,
                    "symbol": f.get("symbol") or op.get("symbol"),
                    "side": f.get("side") or op.get("side"),
                    "entry_price": entry,
                    "exit_price": _f(f.get("price"), None),
                    "realized_pnl": _f(f.get("realized_pnl"), 0.0),
                    "size_usd": _f(f.get("size_usd") or op.get("size_usd"), None),
                    "sl": meta.get("sl") or om.get("sl") or f.get("sl") or op.get("sl"),
                    "tp1": meta.get("tp1") or om.get("tp1") or f.get("tp1") or op.get("tp1"),
                    "tp2": meta.get("tp2") or om.get("tp2") or f.get("tp2") or op.get("tp2"),
                    "exit_status": meta.get("exit_status") or f.get("exit_status"),
                    "type": meta.get("type") or om.get("type"),
                    "timeframe": om.get("timeframe") or meta.get("timeframe") or tf_default,
                    "source": source,
                    "tick_stop": bool(meta.get("tick_stop")),
                }
            )
        )
    closed.sort(key=lambda r: str(r.get("closed_ts") or r.get("ts") or ""), reverse=True)
    closed = closed[: max(1, min(int(limit or 40), 200))]
    return {"trades": closed, "count": len(closed)}
