"""Dump compact per-pair rows for canvas embedding."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = Path(__file__).resolve().parents[1] / "data"
d = json.loads((DATA / "_per_pair_report.json").read_text(encoding="utf-8"))
rows = []
for p in sorted(d["pairs"], key=lambda x: x["pnl"]):
    sym = (p["symbol"] or "").replace("/USDT:USDT", "")
    o = p.get("open_now")
    rows.append(
        {
            "sym": sym,
            "closes": p["closes_n"],
            "opens": p["opens_n"],
            "w": p["w"],
            "l": p["l"],
            "z": p["z"],
            "pnl": p["pnl"],
            "wr": p["wr"],
            "avg_size": p["avg_size"],
            "hold": p["avg_hold_h"],
            "exits": {
                k: {"n": v["n"], "pnl": v["pnl"]} for k, v in p["exits"].items()
            },
            "types": {
                k: {"n": v["n"], "pnl": v["pnl"]} for k, v in p["types"].items()
            },
            "trades": [
                {
                    "ts": (t.get("ts") or "")[:16],
                    "side": t["side"],
                    "type": t["type"],
                    "exit": t["exit"],
                    "pnl": t["pnl"],
                    "size": t["size"],
                    "hold": t["hold_h"],
                }
                for t in p["trades"]
            ],
            "open": None
            if not o
            else {
                "side": o.get("side"),
                "size": o.get("size"),
                "entry": o.get("entry"),
                "upnl": round(float(o.get("upnl") or 0), 2),
                "type": o.get("type"),
                "be": o.get("be_timeout"),
                "sl": o.get("sl"),
                "mark": o.get("mark"),
            },
        }
    )

out = DATA / "_per_pair_compact.json"
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("ok", len(rows), "->", out)
for r in rows:
    print(
        f"{r['sym']}: pnl={r['pnl']:+.2f} C={r['closes']} W/L/Z={r['w']}/{r['l']}/{r['z']} open={r['open'] is not None}"
    )
