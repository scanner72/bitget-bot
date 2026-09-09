"""Smoke: open tiny Demo market then close via router (needs EXEC_MODE=hub_demo)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# load .env if present (simple)
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ["EXEC_MODE"] = "hub_demo"
os.environ["BITGET_DEMO"] = "1"

from exec.bitget_hub import BitgetUtaClient, ccxt_to_bitget_symbol
import json
import urllib.request
from exec.router import open_position, close_position, exec_mode

SYMBOL = os.getenv("SMOKE_SYMBOL", "SOL/USDT:USDT")
SIZE_USD = float(os.getenv("SMOKE_SIZE_USD", "80"))


def main() -> None:
    print("exec_mode", exec_mode())
    client = BitgetUtaClient.from_env()
    print("demo", client.demo, "symbol", ccxt_to_bitget_symbol(SYMBOL))
    assets = client.account_assets()
    print("assets_ok", bool(assets))

    # mark approx via place far? use a mid from public ticker if needed
    # For smoke use last price from UTA is heavy; use env or 100 placeholder for qty only —
    # router uses price only for qty = size/price; market ignores limit price.
    price = float(os.getenv("SMOKE_PRICE", "0") or 0)
    if price <= 0:
        sym = ccxt_to_bitget_symbol(SYMBOL)
        url = f"https://api.bitget.com/api/v2/mix/market/ticker?productType=USDT-FUTURES&symbol={sym}"
        raw = json.loads(urllib.request.urlopen(url, timeout=15).read().decode())
        price = float(raw["data"][0]["lastPr"])
        print("mark", price)
    pid = open_position(
        symbol=SYMBOL,
        side="long",
        size_usd=SIZE_USD,
        price=price,
        meta={"smoke": True, "reason": "smoke_router_demo"},
        gate=None,
    )
    print("opened_paper_id", pid)
    closed = close_position(pid, price, meta={"smoke": True})
    print("closed", closed.get("position_id"), "pnl", closed.get("pnl"))
    print("SMOKE_ROUTER_OK")


if __name__ == "__main__":
    main()
