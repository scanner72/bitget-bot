"""Overlay Bitget Demo/live UTA equity onto paper snapshots (hub_demo)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

_HUB_MODES = {"hub_demo", "demo", "live", "hub_live"}
_DEMO_OVERLAY_MODES = {"hub_demo", "demo"}


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


def overlay_equity_snapshot(paper_snap: dict) -> dict:
    """Merge Demo UTA equity into paper account snapshot for UI/API."""
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

    demo = {
        "equity": equity,
        "available": available,
        "usdt_equity": usdt_equity,
        "unrealised_pnl": upnl,
    }

    out["source"] = "hub_demo"
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
    out["currency"] = "USDT"
    # Display start as demo equity when overlaying for UI
    out["start_balance"] = equity
    out["demo_equity"] = equity
    return out


def sync_paper_account_from_hub(account=None) -> dict | None:
    """Align paper wallet start/cash with Demo available (keep opens/realized)."""
    if not exec_is_hub():
        return None
    _load_env()
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode not in _DEMO_OVERLAY_MODES and mode not in {"hub_live", "live"}:
        return None

    hub = fetch_hub_usdt()
    if not hub:
        return None

    try:
        from exec.account import PaperAccount, get_account
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] paper load warn: {type(exc).__name__}: {exc}")
        return None

    acct = account if account is not None else get_account(reload=True)
    if not isinstance(acct, PaperAccount):
        acct = get_account(reload=True)

    available = float(hub.get("available") or 0.0)
    equity = float(hub.get("account_equity") or hub.get("usdt_equity") or 0.0)
    cash_src = available if available > 0 else equity

    # Prefer recomputing open_notional from paper opens when easy
    try:
        from exec.paper import list_open

        opens = list_open() or []
        open_notional = 0.0
        for pos in opens:
            if isinstance(pos, dict):
                open_notional += float(pos.get("size_usd") or 0.0)
        acct.open_notional = max(0.0, open_notional)
    except Exception:
        pass

    acct.start_balance = equity if equity > 0 else cash_src
    acct.cash = cash_src
    acct.currency = "USDT"
    acct.save()

    print(
        f"[HUB] synced paper wallet from Demo available={available:.4f} equity={equity:.4f}"
    )
    return acct.snapshot()
