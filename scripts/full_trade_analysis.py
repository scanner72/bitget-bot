"""Dump full trade analysis snapshot for report."""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

DATA = ROOT / "data"


def fetch(url: str):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    fills = []
    for line in (DATA / "paper_fills.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            fills.append(json.loads(line))
        except Exception:
            pass

    opens_by_pid = {
        f.get("position_id"): f
        for f in fills
        if str(f.get("event")).lower() == "open"
    }

    def meta(f):
        return f.get("meta") if isinstance(f.get("meta"), dict) else {}

    closes = [f for f in fills if str(f.get("event")).lower() == "close"]
    opens = [f for f in fills if str(f.get("event")).lower() == "open"]

    equity = fetch("http://127.0.0.1:8080/equity")
    positions = fetch("http://127.0.0.1:8080/positions")

    rows = []
    by_sym = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0, "l": 0, "z": 0, "trades": []})
    by_exit = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    by_type = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    by_side = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    by_day = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    cum = []
    running = 0.0

    for f in sorted(closes, key=lambda x: x.get("ts") or ""):
        m = meta(f)
        op = opens_by_pid.get(f.get("position_id")) or {}
        om = meta(op)
        typ = m.get("type") or om.get("type") or "?"
        exit_st = str(m.get("exit_status") or "?")
        side = str(f.get("side") or "").lower()
        pnl = float(f.get("realized_pnl") or 0)
        size = float(f.get("size_usd") or 0)
        sym = (f.get("symbol") or "").replace("/USDT:USDT", "")
        ts = f.get("ts")
        opened = parse_ts(op.get("ts"))
        closed = parse_ts(ts)
        hold = None
        if opened and closed:
            hold = round((closed - opened).total_seconds() / 3600.0, 2)
        day = (ts or "")[:10]
        row = {
            "ts": ts,
            "day": day,
            "sym": sym,
            "side": side,
            "type": typ,
            "exit": exit_st,
            "pnl": round(pnl, 4),
            "size": round(size, 2),
            "entry": f.get("entry_price") or op.get("price"),
            "exit_px": f.get("price"),
            "hold_h": hold,
            "note": m.get("exit_note"),
        }
        rows.append(row)
        running += pnl
        cum.append({"ts": ts, "cum": round(running, 4), "pnl": round(pnl, 4), "sym": sym})
        b = by_sym[sym]
        b["pnl"] += pnl
        b["n"] += 1
        b["trades"].append(row)
        if pnl > 0:
            b["w"] += 1
        elif pnl < 0:
            b["l"] += 1
        else:
            b["z"] += 1
        by_exit[exit_st]["n"] += 1
        by_exit[exit_st]["pnl"] += pnl
        by_type[str(typ)]["n"] += 1
        by_type[str(typ)]["pnl"] += pnl
        by_side[side]["n"] += 1
        by_side[side]["pnl"] += pnl
        by_day[day]["n"] += 1
        by_day[day]["pnl"] += pnl

    open_rows = []
    if isinstance(positions, dict):
        for p in positions.get("positions") or []:
            m = p.get("meta") if isinstance(p.get("meta"), dict) else {}
            open_rows.append(
                {
                    "sym": (p.get("symbol") or "").replace("/USDT:USDT", ""),
                    "side": p.get("side"),
                    "size": p.get("size_usd"),
                    "entry": p.get("entry_price"),
                    "mark": p.get("mark_price") or p.get("exchange_mark"),
                    "upnl": p.get("unrealized_pnl_usd"),
                    "sl": p.get("sl") or m.get("sl"),
                    "tp1": p.get("tp1") or m.get("tp1"),
                    "tp2": p.get("tp2") or m.get("tp2"),
                    "type": m.get("type"),
                    "stale": p.get("stale"),
                    "pnl_source": p.get("pnl_source"),
                    "hub_tpsl_error": m.get("hub_tpsl_error"),
                    "opened": p.get("opened_ts"),
                }
            )

    pairs = []
    for sym, b in by_sym.items():
        n = b["n"]
        pairs.append(
            {
                "sym": sym,
                "n": n,
                "w": b["w"],
                "l": b["l"],
                "z": b["z"],
                "pnl": round(b["pnl"], 4),
                "avg": round(b["pnl"] / n, 4) if n else 0,
                "wr": round(100.0 * b["w"] / n, 1) if n else None,
            }
        )
    pairs.sort(key=lambda x: x["pnl"])

    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "n_opens": len(opens),
        "n_closes": len(closes),
        "realized": round(sum(r["pnl"] for r in rows), 4),
        "wins": sum(1 for r in rows if r["pnl"] > 0),
        "losses": sum(1 for r in rows if r["pnl"] < 0),
        "flats": sum(1 for r in rows if r["pnl"] == 0),
        "equity": equity,
        "positions": open_rows,
        "open_upnl": round(
            sum(float(p.get("upnl") or 0) for p in open_rows if p.get("upnl") is not None),
            4,
        ),
        "by_exit": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in by_exit.items()},
        "by_type": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in by_type.items()},
        "by_side": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in by_side.items()},
        "by_day": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in sorted(by_day.items())},
        "pairs": pairs,
        "trades": rows,
        "cum": cum,
        "worst10": sorted(rows, key=lambda r: r["pnl"])[:10],
        "best10": sorted(rows, key=lambda r: -r["pnl"])[:10],
    }
    path = DATA / "_full_trade_analysis.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", path)
    print(
        "realized",
        out["realized"],
        "W/L/Z",
        out["wins"],
        out["losses"],
        out["flats"],
        "open",
        len(open_rows),
        "upnl",
        out["open_upnl"],
    )
    eq = equity if isinstance(equity, dict) else {}
    print(
        "demo_eq",
        eq.get("demo_equity") or eq.get("equity"),
        "hub_upnl",
        eq.get("hub_unrealised_pnl") or eq.get("total_unrealized_pnl"),
    )
    for p in pairs:
        print(f"  {p['sym']}: n={p['n']} pnl={p['pnl']:+.2f} wr={p['wr']}")


if __name__ == "__main__":
    main()
