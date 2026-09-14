"""Reconcile local paper opens with Bitget hub positions.

In hub_demo/live the exchange is source-of-truth for \"is open\".
If paper still has a position that is gone on Bitget (TP2 parachute, SL,
manual close), close the paper shadow without sending another reduce-only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

from exec.paper import PaperBook, close_paper
from exec.router import exec_mode
from exec.demo_universe import is_paper_venue

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def reconcile_enabled() -> bool:
    load_dotenv(ROOT / ".env", override=False)
    mode = exec_mode()
    # Default on for hub modes; off for pure paper.
    default = mode in {"hub_demo", "live"}
    return _env_bool("RECONCILE_ENABLED", default)


def reconcile_grace_sec() -> float:
    load_dotenv(ROOT / ".env", override=False)
    return max(0.0, _env_float("RECONCILE_GRACE_SEC", 60.0))


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _hub_open_keys() -> tuple[set[tuple[str, str]], str | None]:
    """Return {(BITGET_SYMBOL, posSide), ...} currently open on exchange."""
    try:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        live = client.current_positions() or {}
        items = live.get("list") if isinstance(live, dict) else live
        keys: set[tuple[str, str]] = set()
        for it in items or []:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "").upper()
            side = str(it.get("posSide") or "").lower()
            if not sym or not side:
                continue
            # Skip flat leftovers if API returns zero size
            total = it.get("total")
            avail = it.get("available")
            try:
                size = float(total if total is not None else (avail or 0))
            except (TypeError, ValueError):
                size = 0.0
            if size <= 0:
                continue
            keys.add((sym, side))
        return keys, None
    except Exception as exc:  # noqa: BLE001
        return set(), f"{type(exc).__name__}: {exc}"


def _paper_key(pos: dict[str, Any]) -> tuple[str, str] | None:
    from exec.bitget_hub import ccxt_to_bitget_symbol

    sym_raw = str(pos.get("symbol") or "")
    side = str(pos.get("side") or "").lower()
    if not sym_raw or side not in {"long", "short"}:
        return None
    try:
        bg = ccxt_to_bitget_symbol(sym_raw)
    except Exception:
        bg = ""
    if not bg:
        return None
    return (bg.upper(), side)


def _fills_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        items = raw.get("list") or raw.get("fills") or []
        return [x for x in items if isinstance(x, dict)]
    return []


def _close_from_exchange(pos: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    """Price/PnL from Bitget close fills; empty extras if unavailable."""
    extras: dict[str, Any] = {}
    try:
        from exec.bitget_hub import BitgetUtaClient, ccxt_to_bitget_symbol

        client = BitgetUtaClient.from_env()
        bg = ccxt_to_bitget_symbol(str(pos.get("symbol") or ""))
        raw = client.fills(category="USDT-FUTURES", symbol=bg, limit=100)
        items = _fills_list(raw)
    except Exception as exc:  # noqa: BLE001
        extras["hub_fill_lookup_error"] = f"{type(exc).__name__}: {exc}"
        return None, extras

    opened = _parse_ts(pos.get("opened_ts"))
    opened_ms = int(opened.timestamp() * 1000) if opened else 0
    close_rows: list[dict[str, Any]] = []
    for it in items:
        trade = str(it.get("tradeSide") or "").lower()
        if "close" not in trade:
            continue
        try:
            ts = int(it.get("createdTime") or it.get("execTime") or 0)
        except (TypeError, ValueError):
            ts = 0
        if opened_ms and ts and ts + 5000 < opened_ms:
            continue
        close_rows.append(it)
    if not close_rows:
        return None, extras

    qty_sum = 0.0
    px_qty = 0.0
    pnl_sum = 0.0
    last = close_rows[0]
    for it in close_rows:
        try:
            ts = int(it.get("createdTime") or 0)
            last_ts = int(last.get("createdTime") or 0)
            if ts >= last_ts:
                last = it
        except (TypeError, ValueError):
            pass
        q = 0.0
        p = 0.0
        try:
            q = float(it.get("execQty") or 0)
            p = float(it.get("execPrice") or 0)
        except (TypeError, ValueError):
            continue
        if q > 0 and p > 0:
            qty_sum += q
            px_qty += p * q
        try:
            pnl_sum += float(it.get("execPnl") or 0)
        except (TypeError, ValueError):
            pass
    px = (px_qty / qty_sum) if qty_sum > 0 else None
    if px is None:
        try:
            px = float(last.get("execPrice") or 0) or None
        except (TypeError, ValueError):
            px = None
    extras["hub_close_order_id"] = last.get("orderId")
    extras["hub_close_fill_id"] = last.get("execId")
    extras["hub_exec_pnl"] = pnl_sum
    extras["hub_close_qty"] = qty_sum
    return px, extras


def _close_price(pos: dict[str, Any]) -> float:
    """Exchange close fill first; then mark; then entry."""
    px, extras = _close_from_exchange(pos)
    pos["_reconcile_fill_meta"] = extras
    if px is not None and px > 0:
        return float(px)
    entry = float(pos.get("entry_price") or 0) or 0.0
    sym = str(pos.get("symbol") or "")
    try:
        from ingest.bitget_ohlcv import get_mark_price

        mark = float(get_mark_price(sym))
        if mark > 0:
            extras["close_price_source"] = "mark"
            return mark
    except Exception:
        pass
    meta = pos.get("meta") if isinstance(pos.get("meta"), dict) else {}
    for k in ("mark_price", "trail_price"):
        try:
            v = float(pos.get(k) or meta.get(k) or 0)
            if v > 0:
                extras["close_price_source"] = k
                return v
        except (TypeError, ValueError):
            continue
    extras["close_price_source"] = "entry"
    return entry if entry > 0 else 0.0


def reconcile_paper_with_exchange(
    *,
    book: PaperBook | None = None,
    gate: Any | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Close paper shadows missing on Bitget. Returns event dicts."""
    load_dotenv(ROOT / ".env", override=False)
    mode = exec_mode()
    if mode not in {"hub_demo", "live"}:
        return []
    if not force and not reconcile_enabled():
        return []

    b = book or PaperBook(gate=gate)
    if gate is not None and getattr(b, "gate", None) is None:
        b.gate = gate

    opens = b.list_open()
    if not opens:
        return []

    hub_keys, hub_err = _hub_open_keys()
    if hub_err is not None:
        print(f"[RECONCILE] skip fetch failed: {hub_err}")
        return [
            {
                "action": "error",
                "error": hub_err,
                "note": "hub_positions_fetch_failed",
            }
        ]

    grace = reconcile_grace_sec()
    now = now or _utc_now()
    events: list[dict[str, Any]] = []

    for pos in opens:
        key = _paper_key(pos)
        if key is None:
            continue
        if key in hub_keys:
            continue
        if is_paper_venue(pos):
            events.append(
                {
                    "action": "skip_paper_live",
                    "position_id": pos.get("position_id"),
                    "symbol": pos.get("symbol"),
                    "note": "exec_venue=paper (not on demo)",
                }
            )
            continue

        opened = _parse_ts(pos.get("opened_ts"))
        if opened is not None and grace > 0:
            age = (now - opened).total_seconds()
            if age < grace:
                events.append(
                    {
                        "action": "skip_grace",
                        "position_id": pos.get("position_id"),
                        "symbol": pos.get("symbol"),
                        "age_sec": round(age, 1),
                        "grace_sec": grace,
                    }
                )
                continue

        px = _close_price(pos)
        fill_meta = pos.pop("_reconcile_fill_meta", None) or {}
        if px <= 0:
            events.append(
                {
                    "action": "error",
                    "position_id": pos.get("position_id"),
                    "symbol": pos.get("symbol"),
                    "error": "no_close_price",
                }
            )
            continue

        pid = str(pos.get("position_id") or "")
        try:
            result = close_paper(
                pid,
                px,
                meta={
                    "exit_status": "exchange_closed",
                    "exit_note": "missing_on_exchange",
                    "exec_mode": mode,
                    "reconcile": True,
                    **{k: v for k, v in fill_meta.items() if v is not None},
                },
                gate=gate,
                book=b,
            )
            print(
                f"[RECONCILE] CLOSE {pid} {pos.get('symbol')} "
                f"@ {px} pnl={result.get('realized_pnl')} "
                f"(missing on exchange)"
            )
            events.append(
                {
                    "action": "close",
                    "position_id": pid,
                    "symbol": pos.get("symbol"),
                    "side": pos.get("side"),
                    "close_price": px,
                    "realized_pnl": result.get("realized_pnl"),
                    "status": "exchange_closed",
                }
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[RECONCILE] ERROR close {pid} {pos.get('symbol')}: {exc}")
            events.append(
                {
                    "action": "error",
                    "position_id": pid,
                    "symbol": pos.get("symbol"),
                    "error": str(exc),
                }
            )

    return events
