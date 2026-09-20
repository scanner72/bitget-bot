"""Backfill paper closes from Bitget /position/history-position (Demo)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("EXEC_MODE", "hub_demo")
os.environ.setdefault("BITGET_DEMO", "1")

from exec.bitget_hub import BitgetUtaClient, ccxt_to_bitget_symbol

FILLS = ROOT / "data" / "paper_fills.jsonl"
ACCOUNT = ROOT / "data" / "paper_account.json"
START = ROOT / "data" / "demo_start_equity.json"
REPORT = ROOT / "data" / "_backfill_close_report.json"


def _f(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def fetch_history(client: BitgetUtaClient) -> list[dict]:
    out = []
    cursor = None
    for _ in range(60):
        q = {"category": "USDT-FUTURES", "limit": "100"}
        if cursor:
            q["cursor"] = str(cursor)
        raw = client.request("GET", "/api/v3/position/history-position", query=q)
        data = raw.get("data") or {}
        batch = data.get("list") or []
        out.extend(batch)
        cursor = (
            data.get("cursor")
            or data.get("nextCursor")
            or data.get("nextPageCursor")
        )
        if not batch or not cursor:
            break
        time.sleep(0.12)
    # dedup positionId
    seen = set()
    uniq = []
    for it in out:
        pid = str(it.get("positionId") or "")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        uniq.append(it)
    return uniq


def score_match(paper_close: dict, open_row: dict, hist: dict) -> float | None:
    """Lower is better. None = incompatible."""
    want = ccxt_to_bitget_symbol(str(paper_close.get("symbol") or "")).upper()
    if fill_sym := str(hist.get("symbol") or "").upper():
        if want and fill_sym != want:
            return None
    side = str(paper_close.get("side") or "").lower()
    hside = str(hist.get("posSide") or "").lower()
    if side and hside and side != hside:
        return None

    entry = _f(paper_close.get("entry_price") or open_row.get("price"))
    hop = _f(hist.get("openPriceAvg"))
    if entry and hop and entry > 0:
        if abs(hop - entry) / entry > 0.015:  # 1.5%
            return None

    opened = _parse_ts(open_row.get("ts"))
    closed = _parse_ts(paper_close.get("ts"))
    h_open = _f(hist.get("createdTime"))
    h_close = _f(hist.get("updatedTime"))
    if not closed or not h_close:
        return None

    close_ms = _ms(closed)
    # close time must be within 2h
    if abs(h_close - close_ms) > 2 * 3600 * 1000:
        return None
    # if we have open time, require hist open within 30m of paper open
    if opened and h_open:
        open_ms = _ms(opened)
        if abs(h_open - open_ms) > 30 * 60 * 1000:
            return None

    # qty check soft
    pq = _f(paper_close.get("qty") or (open_row.get("meta") or {}).get("hub_qty") or open_row.get("qty"))
    hq = _f(hist.get("closeTotalPos") or hist.get("openTotalPos"))
    qty_pen = 0.0
    if pq and hq and pq > 0:
        ratio = hq / pq
        if ratio < 0.5 or ratio > 2.0:
            return None
        qty_pen = abs(1.0 - ratio) * 1000.0

    entry_pen = 0.0
    if entry and hop:
        entry_pen = abs(hop - entry) / entry * 1e6
    time_pen = abs(h_close - close_ms) / 1000.0  # seconds
    open_pen = 0.0
    if opened and h_open:
        open_pen = abs(h_open - _ms(opened)) / 1000.0
    return time_pen + open_pen * 0.5 + entry_pen + qty_pen


def main() -> None:
    client = BitgetUtaClient.from_env()
    print("demo", client.demo)
    hist = fetch_history(client)
    print("history_positions", len(hist))

    rows = [
        json.loads(l)
        for l in FILLS.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    opens = {
        r["position_id"]: r
        for r in rows
        if r.get("event") == "open" and r.get("position_id")
    }
    closes = [r for r in rows if r.get("event") == "close"]

    used = set()
    updated = 0
    skipped = 0
    failed = 0
    delta = 0.0
    samples = []
    failed_samples = []

    # sort closes oldest first for stable assignment
    closes_sorted = sorted(closes, key=lambda r: str(r.get("ts") or ""))

    for r in closes_sorted:
        meta = dict(r.get("meta") or {})
        src = meta.get("close_price_source") or ""
        # still refresh unknown; keep true hub_fill from live path if already good
        if src in {"hub_fill", "hub_fill_backfill", "hub_hist_backfill"} and meta.get(
            "hub_position_id"
        ):
            skipped += 1
            continue
        if src == "hub_fill" and meta.get("hub_exec_pnl") is not None:
            # already exchange-aligned from live close
            skipped += 1
            continue

        op = opens.get(r.get("position_id")) or {}
        candidates = []
        for h in hist:
            pid = str(h.get("positionId") or "")
            if pid and pid in used:
                continue
            sc = score_match(r, op, h)
            if sc is None:
                continue
            candidates.append((sc, h))
        candidates.sort(key=lambda x: x[0])
        if not candidates:
            failed += 1
            failed_samples.append(
                {
                    "symbol": r.get("symbol"),
                    "ts": r.get("ts"),
                    "entry": r.get("entry_price"),
                    "old_px": r.get("price"),
                    "old_pnl": r.get("realized_pnl"),
                }
            )
            continue

        sc, h = candidates[0]
        # reject ambiguous: second within 5s of best
        if len(candidates) > 1 and candidates[1][0] - sc < 5:
            # still ok if entry uniquely matches better
            pass

        pid = str(h.get("positionId") or "")
        if pid:
            used.add(pid)

        old_px = _f(r.get("price"), 0.0) or 0.0
        old_pnl = _f(r.get("realized_pnl"), 0.0) or 0.0
        new_px = _f(h.get("closePriceAvg"))
        cum = _f(h.get("cumRealisedPnl"))
        net = _f(h.get("netProfit"))
        if new_px is None or new_px <= 0:
            failed += 1
            continue

        # Prefer cumRealisedPnl (matches fill execPnl); keep net for equity bridge
        new_pnl = cum if cum is not None else (net if net is not None else old_pnl)

        r["price"] = new_px
        r["realized_pnl"] = new_pnl
        meta.update(
            {
                "close_price_source": "hub_hist_backfill",
                "realized_source": "hub_cum_realised_pnl",
                "hub_position_id": pid,
                "hub_open_price_avg": _f(h.get("openPriceAvg")),
                "hub_close_price_avg": new_px,
                "hub_cum_realised_pnl": cum,
                "hub_net_profit": net,
                "hub_open_fee": _f(h.get("openFeeTotal")),
                "hub_close_fee": _f(h.get("closeFeeTotal")),
                "hub_funding": _f(h.get("totalFunding")),
                "hub_close_qty": _f(h.get("closeTotalPos")),
                "backfill_ts": datetime.now(timezone.utc).isoformat(),
                "backfill_old_price": old_px,
                "backfill_old_pnl": old_pnl,
                "backfill_score": round(sc, 3),
            }
        )
        r["meta"] = meta
        updated += 1
        delta += new_pnl - old_pnl
        samples.append(
            {
                "symbol": r.get("symbol"),
                "ts": r.get("ts"),
                "old_px": old_px,
                "new_px": new_px,
                "old_pnl": old_pnl,
                "new_pnl": new_pnl,
                "net_profit": net,
                "score": round(sc, 3),
            }
        )

    # rewrite fills preserving order
    tmp = FILLS.with_suffix(".jsonl.tmp_hist_backfill")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(FILLS)

    # account: use start from demo_start; rebuild cash via size model but realized from backfill
    start_bal = 10000.0
    if START.exists():
        try:
            start_bal = float(
                json.loads(START.read_text(encoding="utf-8")).get("start_equity")
                or 10000
            )
        except Exception:
            pass

    realized_cum = sum(
        float(r.get("realized_pnl") or 0) for r in rows if r.get("event") == "close"
    )
    realized_net = 0.0
    for r in rows:
        if r.get("event") != "close":
            continue
        m = r.get("meta") or {}
        if m.get("hub_net_profit") is not None:
            realized_net += float(m["hub_net_profit"])
        else:
            realized_net += float(r.get("realized_pnl") or 0)

    cash = float(start_bal)
    open_notional = 0.0
    for r in rows:
        size = float(r.get("size_usd") or 0)
        if r.get("event") == "open":
            cash -= size
            open_notional += size
        elif r.get("event") == "close":
            m = r.get("meta") or {}
            # equity-accurate: return size + netProfit (fees included)
            pnl = (
                float(m["hub_net_profit"])
                if m.get("hub_net_profit") is not None
                else float(r.get("realized_pnl") or 0)
            )
            cash += size + pnl
            open_notional = max(0.0, open_notional - size)

    acct = {
        "updated_ts": datetime.now(timezone.utc).isoformat(),
        "start_balance": start_bal,
        "cash": cash,
        "realized_pnl": realized_cum,
        "realized_net_profit": realized_net,
        "open_notional": open_notional,
        "currency": "USDT",
        "equity": cash + open_notional,
        "backfill_note": "history-position backfill; equity uses netProfit when present",
    }
    ACCOUNT.write_text(json.dumps(acct, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "updated": updated,
        "skipped_already_good": skipped,
        "failed": failed,
        "delta_cum_realised": round(delta, 6),
        "sum_cum_realised": round(realized_cum, 6),
        "sum_net_profit": round(realized_net, 6),
        "hist_used": len(used),
        "hist_total": len(hist),
        "account": acct,
        "samples": samples[:20],
        "failed_samples": failed_samples[:20],
        # sanity: BZ / LTC known cases
        "sanity": [
            s
            for s in samples
            if str(s.get("symbol", "")).startswith(("BZ/", "LTC/", "ETH/"))
        ][:10],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:5000])
    print("WROTE", REPORT)


if __name__ == "__main__":
    main()
