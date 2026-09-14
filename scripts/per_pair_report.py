"""Build per-pair trading report from paper fills + hub positions."""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_hub_positions():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/positions", timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("hub positions failed:", e)
        return None


def main():
    fills = []
    for line in (DATA / "paper_fills.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            fills.append(json.loads(line))
        except Exception:
            pass

    opens_by_pid = {}
    for f in fills:
        if str(f.get("event")).lower() == "open":
            opens_by_pid[f.get("position_id")] = f

    def meta(f):
        return f.get("meta") if isinstance(f.get("meta"), dict) else {}

    def typ(f):
        m = meta(f)
        t = m.get("type") or f.get("type")
        if t:
            return str(t)
        op = opens_by_pid.get(f.get("position_id"))
        if op:
            return str(meta(op).get("type") or "?")
        return "?"

    def exit_st(f):
        return str(meta(f).get("exit_status") or "?")

    closes = [f for f in fills if str(f.get("event")).lower() == "close"]

    hub = fetch_hub_positions()
    live = []
    if isinstance(hub, dict):
        live = hub.get("positions") or hub.get("open") or []
        if not live and isinstance(hub.get("items"), list):
            live = hub["items"]
    elif isinstance(hub, list):
        live = hub

    pos_raw = json.loads((DATA / "paper_positions.json").read_text(encoding="utf-8"))
    file_live = pos_raw.get("positions") or pos_raw.get("open") or []
    if not live:
        live = file_live

    by = defaultdict(
        lambda: {
            "closes": [],
            "opens_n": 0,
            "pnl": 0.0,
            "w": 0,
            "l": 0,
            "z": 0,
            "sides": defaultdict(int),
            "exits": defaultdict(lambda: {"n": 0, "pnl": 0.0}),
            "types": defaultdict(lambda: {"n": 0, "pnl": 0.0}),
            "sizes": [],
            "hold_h": [],
        }
    )

    for f in fills:
        if str(f.get("event")).lower() == "open":
            by[f.get("symbol")]["opens_n"] += 1

    for f in closes:
        sym = f.get("symbol")
        p = float(f.get("realized_pnl") or 0)
        b = by[sym]
        side = str(f.get("side") or "").lower()
        es = exit_st(f)
        t = typ(f)
        size = float(f.get("size_usd") or 0)
        op = opens_by_pid.get(f.get("position_id"))
        opened = parse_ts(op.get("ts")) if op else None
        closed = parse_ts(f.get("ts"))
        hold = None
        if opened and closed:
            hold = (closed - opened).total_seconds() / 3600.0
            b["hold_h"].append(hold)
        row = {
            "ts": f.get("ts"),
            "side": side,
            "type": t,
            "exit": es,
            "pnl": round(p, 4),
            "size": round(size, 2),
            "hold_h": None if hold is None else round(hold, 2),
            "entry": f.get("entry_price") or (op or {}).get("price"),
            "exit_px": f.get("price"),
            "position_id": f.get("position_id"),
        }
        b["closes"].append(row)
        b["pnl"] += p
        b["sizes"].append(size)
        b["sides"][side] += 1
        b["exits"][es]["n"] += 1
        b["exits"][es]["pnl"] += p
        b["types"][t]["n"] += 1
        b["types"][t]["pnl"] += p
        if p > 0:
            b["w"] += 1
        elif p < 0:
            b["l"] += 1
        else:
            b["z"] += 1

    open_now = {}
    for p in live:
        if not isinstance(p, dict):
            continue
        sym = p.get("symbol")
        if not sym:
            continue
        m = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        open_now[sym] = {
            "side": p.get("side"),
            "size": p.get("size_usd") or p.get("notional_usd"),
            "entry": p.get("entry_price") or p.get("avg_entry"),
            "upnl": p.get("unrealized_pnl_usd") or p.get("unrealized_pnl"),
            "type": m.get("type") or p.get("type"),
            "opened": p.get("opened_ts") or p.get("opened_at") or p.get("ts"),
            "sl": m.get("sl") or p.get("sl"),
            "tp1_hit": m.get("tp1_hit"),
            "trailing": m.get("trailing_active"),
            "be_timeout": m.get("be_timeout"),
            "mark": p.get("mark_price") or p.get("last_price"),
        }

    pairs = []
    for sym, b in by.items():
        if not sym:
            continue
        n = len(b["closes"])
        avg = b["pnl"] / n if n else 0
        wr = 100.0 * b["w"] / n if n else None
        avg_hold = sum(b["hold_h"]) / len(b["hold_h"]) if b["hold_h"] else None
        avg_size = sum(b["sizes"]) / len(b["sizes"]) if b["sizes"] else None
        pairs.append(
            {
                "symbol": sym,
                "opens_n": b["opens_n"],
                "closes_n": n,
                "w": b["w"],
                "l": b["l"],
                "z": b["z"],
                "pnl": round(b["pnl"], 4),
                "avg": round(avg, 4),
                "wr": None if wr is None else round(wr, 1),
                "sides": dict(b["sides"]),
                "exits": {
                    k: {"n": v["n"], "pnl": round(v["pnl"], 4)}
                    for k, v in sorted(b["exits"].items())
                },
                "types": {
                    k: {"n": v["n"], "pnl": round(v["pnl"], 4)}
                    for k, v in sorted(b["types"].items())
                },
                "avg_size": None if avg_size is None else round(avg_size, 2),
                "avg_hold_h": None if avg_hold is None else round(avg_hold, 2),
                "trades": sorted(b["closes"], key=lambda x: x["ts"] or ""),
                "open_now": open_now.get(sym),
            }
        )

    for sym, o in open_now.items():
        if not any(p["symbol"] == sym for p in pairs):
            pairs.append(
                {
                    "symbol": sym,
                    "opens_n": 1,
                    "closes_n": 0,
                    "w": 0,
                    "l": 0,
                    "z": 0,
                    "pnl": 0.0,
                    "avg": 0.0,
                    "wr": None,
                    "sides": {},
                    "exits": {},
                    "types": {},
                    "avg_size": o.get("size"),
                    "avg_hold_h": None,
                    "trades": [],
                    "open_now": o,
                }
            )

    pairs.sort(key=lambda p: (p["pnl"], p["closes_n"]))

    # summary slices
    winners = [p for p in pairs if p["pnl"] > 0]
    losers = [p for p in pairs if p["pnl"] < 0]
    flat = [p for p in pairs if p["pnl"] == 0 and p["closes_n"]]
    open_only = [p for p in pairs if p.get("open_now")]

    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "n_pairs": len(pairs),
        "n_closes": sum(p["closes_n"] for p in pairs),
        "n_opens": sum(p["opens_n"] for p in pairs),
        "total_realized_pnl": round(sum(p["pnl"] for p in pairs), 4),
        "n_winners": len(winners),
        "n_losers": len(losers),
        "n_flat": len(flat),
        "n_open": len(open_only),
        "hub_snapshot": hub if isinstance(hub, dict) else {"positions": hub},
        "pairs": pairs,
        "top_winners": sorted(winners, key=lambda p: -p["pnl"])[:10],
        "top_losers": sorted(losers, key=lambda p: p["pnl"])[:10],
    }

    out_path = DATA / "_per_pair_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", out_path)
    print(
        "pairs",
        len(pairs),
        "closes",
        out["n_closes"],
        "realized",
        out["total_realized_pnl"],
        "open",
        len(open_only),
    )
    for p in pairs:
        on = " OPEN" if p.get("open_now") else ""
        upnl = ""
        if p.get("open_now") and p["open_now"].get("upnl") is not None:
            upnl = f" upnl={float(p['open_now']['upnl']):+.2f}"
        print(
            f"{p['symbol']}: closes={p['closes_n']} opens={p['opens_n']} "
            f"W/L/Z={p['w']}/{p['l']}/{p['z']} pnl={p['pnl']:+.2f} wr={p['wr']} "
            f"avg_size={p['avg_size']} hold_h={p['avg_hold_h']}{on}{upnl}"
        )


if __name__ == "__main__":
    main()
