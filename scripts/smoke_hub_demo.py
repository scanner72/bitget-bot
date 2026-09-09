"""Smoke Bitget UTA Demo: assets -> far limit -> cancel. No secrets printed."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# load .env if present without dumping
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# also try sibling demo env on this machine / user home
for extra in (
    Path.home() / "bitget-demo.env",
    Path(r"C:\Users\scann\bitget-demo.env"),
    Path(r"C:\Users\User\bitget-demo.env"),
):
    if extra.exists():
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("EXEC_MODE", "hub_demo")
os.environ.setdefault("BITGET_DEMO", "1")

from exec.bitget_hub import BitgetUtaClient  # noqa: E402


def main() -> int:
    client = BitgetUtaClient.from_env()
    print(f"demo={client.demo}")
    assets = client.account_assets().get("data") or {}
    print(
        "equity_usdt=",
        assets.get("usdtEquity"),
        "accountEquity=",
        assets.get("accountEquity"),
    )
    pos = client.current_positions("USDT-FUTURES")
    if isinstance(pos, dict):
        print("positions_keys=", sorted(pos.keys())[:12])
    elif isinstance(pos, list):
        print("positions_n=", len(pos))
    else:
        print("positions_type=", type(pos).__name__)

    placed = client.place_perp_limit(
        "BTC/USDT:USDT",
        "long",
        qty="0.01",
        price="1000",
    )
    oid = placed.get("orderId")
    print("placed_order=", bool(oid))
    if not oid:
        print("FAIL: no orderId")
        return 1
    client.cancel_order(
        category="USDT-FUTURES",
        symbol="BTCUSDT",
        order_id=str(oid),
    )
    print("cancelled_ok")
    print("smoke_hub_demo OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
