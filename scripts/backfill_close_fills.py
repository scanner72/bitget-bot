"""Backfill paper close prices/PnL from Bitget Demo fills."""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

# load .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("EXEC_MODE", "hub_demo")
os.environ.setdefault("BITGET_DEMO", "1")

from exec.bitget_hub import BitgetUtaClient, ccxt_to_bitget_symbol, fill_symbol_key
from exec.reconcile import _close_from_exchange, _fills_list

FILLS = ROOT / "data" / "paper_fills.jsonl"
ACCOUNT = ROOT / "data" / "paper_account.json"
START = ROOT / "data" / "demo_start_equity.json"


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _fetch_all_close_fills(client: BitgetUtaClient, *, days: int = 90) -> list[dict]:
    """Paginate Demo fills; keep close_* tradeSide only."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    out: list[dict] = []
    cursor = None
    pages = 0
    while pages < 80:
        pages += 1
        raw = client.fills(
            category="USDT-FUTURES",
            start_time=start_ms,
            end_time=end_ms,
            limit=100,
            cursor=cursor,
        )
        items = _fills_list(raw)
        if not items:
            break
        for it in items:
            trade = str(it.get("tradeSide") or "").lower()
            if "close" in trade:
                out.append(it)
        cursor = None
        if isinstance(raw, dict):
            cursor = raw.get("cursor") or raw.get("nextCursor") or raw.get("nextFlag")
            # Bitget often nests cursor
            if not cursor:
                cursor = raw.get("nextPageCursor")
        if not cursor:
            # try from last item time window shrink
            break
        if len(items) < 100:
            break
        time.sleep(0.15)
    # Dedup by execId
    seen = set()
    uniq = []
    for it in out:
        eid = str(it.get("execId") or it.get("execLinkId") or id(it))
        if eid in seen:
            continue
        seen.add(eid)
        uniq.append(it)
    return uniq


def _match_fill_bundle(
    pos_like: dict,
    all_closes: list[dict],
) -> tuple[float | None, float | None, dict]:
    """Match close fills for one paper close using reconcile logic on a filtered set."""
    # Prefer reconcile helper with live API scoped by symbol+time
    px, extras = _close_from_exchange(pos_like, order_id=None, client=client)
    # If rejected vs entry or empty, try local pool match
    if px is not None and extras.get("close_price_source") == "hub_fill":
        pnl = extras.get("hub_exec_pnl")
        try:
            pnl_f = float(pnl) if pnl is not None else None
        except (TypeError, ValueError):
            pnl_f = None
        return float(px), pnl_f, extras

    bg = ccxt_to_bitget_symbol(str(pos_like.get("symbol") or "")).upper()
    pos_side = str(pos_like.get("side") or "").lower()
    opened = _parse_ts(pos_like.get("opened_ts"))
    closed = _parse_ts(pos_like.get("closed_ts") or pos_like.get("ts"))
    opened_ms = int(opened.timestamp() * 1000) if opened else 0
    closed_ms = int(closed.timestamp() * 1000) if closed else 0
    # window: from open-5s to close+2h
    lo = opened_ms - 5000 if opened_ms else 0
    hi = closed_ms + 2 * 3600 * 1000 if closed_ms else 10**15

    rows = []
    for it in all_closes:
        it_sym = fill_symbol_key(it.get("symbol"))
        if bg and it_sym and it_sym != bg:
            continue
        hold = str(it.get("posSide") or it.get("holdSide") or "").lower()
        if pos_side and hold and hold not in {pos_side, "net"}:
            continue
        try:
            ts = int(it.get("createdTime") or it.get("execTime") or 0)
        except (TypeError, ValueError):
            ts = 0
        if lo and ts and ts < lo:
            continue
        if hi and ts and ts > hi:
            continue
        rows.append(it)

    if not rows:
        return None, None, {"close_price_source": "backfill_no_match"}

    # Prefer fills near close time
    if closed_ms:
        rows.sort(key=lambda it: abs(int(it.get("createdTime") or 0) - closed_ms))
        # take cluster with same orderId as nearest, else all in ±30min of close
        nearest = rows[0]
        oid = str(nearest.get("orderId") or "")
        cluster = [r for r in rows if str(r.get("orderId") or "") == oid] if oid else []
        if not cluster:
            cluster = [
                r
                for r in rows
                if abs(int(r.get("createdTime") or 0) - closed_ms) <= 30 * 60 * 1000
            ] or [nearest]
    else:
        cluster = rows

    qty_sum = 0.0
    px_qty = 0.0
    pnl_sum = 0.0
    for it in cluster:
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
    extras = {
        "close_price_source": "hub_fill_backfill",
        "hub_exec_pnl": pnl_sum,
        "hub_close_qty": qty_sum,
        "hub_close_order_id": cluster[0].get("orderId"),
        "hub_close_fill_id": cluster[0].get("execId"),
        "hub_backfill_legs": len(cluster),
    }
    return px, pnl_sum, extras


def main() -> None:
    client = BitgetUtaClient.from_env()
    print("demo", client.demo)

    rows = [
        json.loads(l)
        for l in FILLS.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    # index opens by position_id for opened_ts
    opens_by_pid = {
        r.get("position_id"): r for r in rows if r.get("event") == "open" and r.get("position_id")
    }

    print("prefetch fills…")
    # Warm: use per-close API via _close_from_exchange; also build pool for fallback
    pool = _fetch_all_close_fills(client)
    print("pool_close_fills", len(pool))

    updated = 0
    skipped_ok = 0
    failed = 0
    delta_pnl = 0.0
    details = []

    for r in rows:
        if r.get("event") != "close":
            continue
        meta = dict(r.get("meta") or {})
        src = meta.get("close_price_source") or ""
        # Always refresh unknown / pending / local; keep existing hub_fill if already matching
        force = src not in {"hub_fill", "hub_fill_backfill"}
        if not force and meta.get("hub_exec_pnl") is not None:
            skipped_ok += 1
            continue

        pid = r.get("position_id")
        op = opens_by_pid.get(pid) or {}
        pos_like = {
            "symbol": r.get("symbol"),
            "side": r.get("side"),
            "entry_price": r.get("entry_price") or op.get("price"),
            "opened_ts": op.get("ts") or meta.get("opened_ts"),
            "closed_ts": r.get("ts"),
            "ts": r.get("ts"),
            "qty": r.get("qty") or op.get("qty"),
            "meta": {
                **(op.get("meta") or {}),
                **meta,
                "hub_qty": meta.get("hub_qty")
                or (op.get("meta") or {}).get("hub_qty")
                or r.get("qty"),
            },
        }

        old_px = float(r.get("price") or 0)
        old_pnl = float(r.get("realized_pnl") or 0)

        # Prefer live reconcile (symbol-scoped API)
        try:
            px, extras = _close_from_exchange(pos_like, order_id=None, client=client)
            pnl = extras.get("hub_exec_pnl")
            try:
                pnl_f = float(pnl) if pnl is not None else None
            except (TypeError, ValueError):
                pnl_f = None
            if extras.get("hub_close_price_rejected") is not None and px is None:
                try:
                    px = float(extras["hub_close_price_rejected"])
                    pnl_f = float(extras["hub_exec_pnl"]) if extras.get("hub_exec_pnl") is not None else pnl_f
                    extras = dict(extras)
                    extras["close_price_source"] = "hub_fill_backfill_relaxed"
                except (TypeError, ValueError):
                    pass
            if px is None or str(extras.get("close_price_source") or "") not in {
                "hub_fill",
                "hub_fill_backfill",
                "hub_fill_backfill_relaxed",
            }:
                px2, pnl2, extras2 = _match_fill_bundle(pos_like, pool)
                if px2 is not None:
                    px, pnl_f, extras = px2, pnl2, extras2
                elif pnl_f is None and pnl2 is not None:
                    pnl_f = pnl2
                    extras.update(extras2)
            else:
                extras = dict(extras)
                if extras.get("close_price_source") == "hub_fill":
                    extras["close_price_source"] = "hub_fill_backfill"
        except Exception as exc:  # noqa: BLE001
            px, pnl_f, extras = None, None, {"error": f"{type(exc).__name__}: {exc}"}

        if px is None or px <= 0:
            failed += 1
            details.append(
                {
                    "symbol": r.get("symbol"),
                    "ts": r.get("ts"),
                    "status": "no_match",
                    "old_px": old_px,
                    "old_pnl": old_pnl,
                    "extras": {k: extras.get(k) for k in list(extras)[:8]},
                }
            )
            time.sleep(0.08)
            continue

        new_pnl = float(pnl_f) if pnl_f is not None else old_pnl
        r["price"] = float(px)
        r["realized_pnl"] = new_pnl
        meta.update({k: v for k, v in extras.items() if v is not None})
        meta["close_price_source"] = extras.get("close_price_source") or "hub_fill_backfill"
        meta["backfill_ts"] = datetime.now(timezone.utc).isoformat()
        meta["backfill_old_price"] = old_px
        meta["backfill_old_pnl"] = old_pnl
        meta["realized_source"] = "hub_exec_pnl"
        r["meta"] = meta
        updated += 1
        delta_pnl += new_pnl - old_pnl
        details.append(
            {
                "symbol": r.get("symbol"),
                "ts": r.get("ts"),
                "status": "updated",
                "old_px": old_px,
                "new_px": float(px),
                "old_pnl": old_pnl,
                "new_pnl": new_pnl,
            }
        )
        time.sleep(0.08)

    # rewrite fills
    tmp = FILLS.with_suffix(".jsonl.tmp_backfill")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(FILLS)

    # recompute paper account from fills
    start_bal = 10000.0
    if START.exists():
        try:
            start_bal = float(json.loads(START.read_text(encoding="utf-8")).get("start_equity") or 10000)
        except Exception:
            pass
    if ACCOUNT.exists():
        try:
            prev = json.loads(ACCOUNT.read_text(encoding="utf-8"))
            start_bal = float(prev.get("start_balance") or start_bal)
        except Exception:
            pass

    realized = sum(float(r.get("realized_pnl") or 0) for r in rows if r.get("event") == "close")
    open_notional = 0.0
    # open positions file
    pos_path = ROOT / "data" / "paper_positions.json"
    if pos_path.exists():
        try:
            plist = json.loads(pos_path.read_text(encoding="utf-8")).get("positions") or []
            open_notional = sum(float(p.get("size_usd") or 0) for p in plist)
        except Exception:
            open_notional = 0.0
    cash = start_bal + realized  # simplistic: full notional model may differ
    # Prefer existing paper model: cash = equity - reserved; if account had open_notional reserved:
    # Many desks: equity = cash + open_notional + upnl; on open cash decreases by size.
    # Reconstruct from events:
    cash = float(start_bal)
    open_notional = 0.0
    for r in rows:
        size = float(r.get("size_usd") or 0)
        if r.get("event") == "open":
            cash -= size
            open_notional += size
        elif r.get("event") == "close":
            pnl = float(r.get("realized_pnl") or 0)
            cash += size + pnl
            open_notional = max(0.0, open_notional - size)
    equity = cash + open_notional
    acct = {
        "updated_ts": datetime.now(timezone.utc).isoformat(),
        "start_balance": start_bal,
        "cash": cash,
        "realized_pnl": realized,
        "open_notional": open_notional,
        "currency": "USDT",
        "equity": equity,
        "backfill_note": "rebuilt_from_paper_fills_after_hub_fill_backfill",
    }
    ACCOUNT.write_text(json.dumps(acct, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "updated": updated,
        "skipped_already_hub_fill": skipped_ok,
        "failed": failed,
        "delta_realized_pnl": round(delta_pnl, 6),
        "new_sum_realized": round(realized, 6),
        "account": acct,
        "samples": [d for d in details if d.get("status") == "updated"][:15],
        "failed_samples": [d for d in details if d.get("status") == "no_match"][:15],
    }
    outp = ROOT / "data" / "_backfill_close_report.json"
    outp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])
    print("WROTE", outp)


if __name__ == "__main__":
    main()

