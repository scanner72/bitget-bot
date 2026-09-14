"""Overlay Bitget Demo/live UTA equity onto paper snapshots (hub_demo)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ANCHOR_PATH = ROOT / "data" / "demo_start_equity.json"

_HUB_MODES = {"hub_demo", "demo", "live", "hub_live"}
_DEMO_OVERLAY_MODES = {"hub_demo", "demo", "live", "hub_live"}


def _load_env() -> None:
    load_dotenv(ROOT / ".env", override=False)


def exec_is_hub() -> bool:
    """True when EXEC_MODE routes through Bitget hub (demo or live)."""
    _load_env()
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    return mode in _HUB_MODES


def fetch_hub_usdt() -> dict[str, Any] | None:
    """Fetch USDT snapshot from Bitget UTA; None on error (no secrets)."""
    try:
        from exec.bitget_hub import BitgetUtaClient

        return BitgetUtaClient.from_env().usdt_snapshot()
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] usdt_snapshot warn: {type(exc).__name__}: {exc}")
        return None


def demo_start_equity() -> float:
    """Stable Demo equity anchor for drawdown (not current equity)."""
    _load_env()
    raw = (os.getenv("DEMO_START_EQUITY") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    if ANCHOR_PATH.exists():
        try:
            data = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
            v = float(data.get("start_equity"))
            if v > 0:
                return v
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    start = 10000.0
    try:
        start = float(os.getenv("PAPER_START_BALANCE_USD") or 10000.0)
    except ValueError:
        start = 10000.0
    try:
        ANCHOR_PATH.parent.mkdir(parents=True, exist_ok=True)
        ANCHOR_PATH.write_text(
            json.dumps(
                {
                    "start_equity": start,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "source": "PAPER_START_BALANCE_USD",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return start


def overlay_equity_snapshot(paper_snap: dict) -> dict:
    """Merge Demo UTA equity into snapshot. Paper kept under `paper` only."""
    if not isinstance(paper_snap, dict):
        paper_snap = {}
    out = dict(paper_snap)
    _load_env()
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode not in _DEMO_OVERLAY_MODES:
        return out

    hub = fetch_hub_usdt()
    if not hub:
        return out

    equity = float(hub.get("account_equity") or hub.get("usdt_equity") or 0.0)
    available = float(hub.get("available") or hub.get("balance") or 0.0)
    usdt_equity = float(hub.get("usdt_equity") or equity)
    upnl = float(hub.get("unrealised_pnl") or 0.0)
    start = demo_start_equity()
    implied_realized = equity - start - upnl

    paper_subset = {
        k: paper_snap.get(k)
        for k in (
            "start_balance",
            "cash",
            "realized_pnl",
            "open_positions_notional",
            "equity",
            "equity_mtm",
            "total_unrealized_pnl",
            "currency",
        )
        if k in paper_snap
    }

    src = "hub_demo" if mode in {"hub_demo", "demo"} else "hub_live"
    demo = {
        "equity": equity,
        "available": available,
        "usdt_equity": usdt_equity,
        "unrealised_pnl": upnl,
        "start_equity": start,
        "pnl_vs_start": equity - start,
    }

    out["source"] = src
    out["hub_account_equity"] = equity
    out["hub_available"] = available
    out["hub_usdt_equity"] = usdt_equity
    out["hub_unrealised_pnl"] = upnl
    out["demo"] = demo
    out["paper"] = paper_subset
    out["equity"] = equity
    out["equity_mtm"] = equity
    out["cash"] = available
    out["total_unrealized_pnl"] = upnl
    out["start_balance"] = start
    out["realized_pnl"] = implied_realized
    out["pnl_vs_start"] = equity - start
    out["currency"] = "USDT"
    out["demo_equity"] = equity
    return out


def sync_paper_account_from_hub(account=None) -> dict | None:
    """Disabled: overwriting paper cash/start with Demo hid drawdown and mixed books."""
    print("[HUB] paper wallet sync skipped (Demo is UI SoT; paper stays shadow)")
    return None
