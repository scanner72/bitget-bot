"""Explain paper vs demo equity gap."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DATA = Path(__file__).resolve().parents[1] / "data"
d = json.loads((DATA / "_full_trade_analysis.json").read_text(encoding="utf-8"))

print("DEMO equity", d["equity"].get("demo_equity"))
print("PAPER equity", d["equity"]["paper"]["equity"])
print("PAPER realized", d["realized"])
print()
print("exchange_closed trades:")
for t in d["trades"]:
    if t["exit"] == "exchange_closed":
        print(t)
print()
print("sl_hit total", d["by_exit"].get("sl_hit"))
print("If drop exchange_closed from realized:", round(d["realized"] - d["by_exit"]["exchange_closed"]["pnl"], 4))
print("If also remove LOBSTER:", round(d["realized"] - d["by_exit"]["exchange_closed"]["pnl"] + 11.3129, 4))

# fills for exchange_closed
print("\nraw fills exchange_closed:")
for line in (DATA / "paper_fills.jsonl").read_text(encoding="utf-8").splitlines():
    if "exchange_closed" not in line:
        continue
    f = json.loads(line)
    print(
        f.get("ts"),
        f.get("symbol"),
        "entry",
        f.get("entry_price"),
        "exit",
        f.get("price"),
        "pnl",
        f.get("realized_pnl"),
        "size",
        f.get("size_usd"),
    )
