"""Paper account: cash wallet + equity (start + realized + unrealized).

Cash model (futures-style notional lock for MVP):
  - open: require cash >= size_usd; cash -= size_usd
  - close: cash += size_usd + realized_pnl
  - equity = cash + open_notional (mark=entry => MTM = size_usd)
    which equals start_balance + realized_pnl when marks are at entry.

Persists to data/paper_account.json. Paper-only; no exchange.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCOUNT_PATH = ROOT / "data" / "paper_account.json"
DEFAULT_START_BALANCE = 10000.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def account_path() -> Path:
    load_dotenv(ROOT / ".env", override=False)
    raw = os.getenv("PAPER_ACCOUNT_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_ACCOUNT_PATH


def start_balance_from_env() -> float:
    load_dotenv(ROOT / ".env", override=False)
    return max(0.0, _env_float("PAPER_START_BALANCE_USD", DEFAULT_START_BALANCE))


@dataclass
class PaperAccount:
    """Cash wallet paper account backed by JSON on disk."""

    start_balance: float = DEFAULT_START_BALANCE
    cash: float = DEFAULT_START_BALANCE
    realized_pnl: float = 0.0
    open_notional: float = 0.0
    currency: str = "USDT"
    path: Path | None = None
    persist: bool = True
    _dirty: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path) if self.path else account_path()
        self.start_balance = float(self.start_balance)
        self.cash = float(self.cash)
        self.realized_pnl = float(self.realized_pnl)
        self.open_notional = float(self.open_notional)

    # --- persistence ---

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        *,
        start_balance: float | None = None,
        persist: bool = True,
    ) -> "PaperAccount":
        p = Path(path) if path else account_path()
        sb = float(start_balance) if start_balance is not None else start_balance_from_env()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return cls(
                        start_balance=float(raw.get("start_balance", sb) or sb),
                        cash=float(raw.get("cash", sb) or sb),
                        realized_pnl=float(raw.get("realized_pnl", 0) or 0),
                        open_notional=float(raw.get("open_notional", 0) or 0),
                        currency=str(raw.get("currency") or "USDT"),
                        path=p,
                        persist=persist,
                    )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        acct = cls(
            start_balance=sb,
            cash=sb,
            realized_pnl=0.0,
            open_notional=0.0,
            path=p,
            persist=persist,
        )
        if persist:
            acct.save()
        return acct

    def save(self) -> None:
        if not self.persist or self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_ts": _utc_now().isoformat(),
            "start_balance": self.start_balance,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "open_notional": self.open_notional,
            "currency": self.currency,
            "equity": self.equity(),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # --- derived ---

    def equity(self, *, unrealized: float | None = None) -> float:
        """equity = cash + MTM of opens. MVP mark=entry => unrealized=0 on top of open_notional.

        With mark=entry, position MTM value = size_usd (= open_notional total),
        so equity = cash + open_notional = start_balance + realized_pnl.
        Optional unrealized adds mark-to-market delta on top of entry notionals.
        """
        mtm = float(self.open_notional)
        if unrealized is not None:
            mtm = mtm + float(unrealized)
        return float(self.cash) + mtm

    def snapshot(self, *, unrealized: float | None = None) -> dict[str, Any]:
        return {
            "start_balance": self.start_balance,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "open_positions_notional": self.open_notional,
            "equity": self.equity(unrealized=unrealized),
            "currency": self.currency,
        }

    # --- cash wallet ops ---

    def can_open(self, size_usd: float) -> tuple[bool, str]:
        size = float(size_usd)
        if size <= 0:
            return False, "invalid_size"
        if self.cash + 1e-12 < size:
            return False, "insufficient_cash"
        return True, "ok"

    def lock_open(self, size_usd: float) -> None:
        """Reserve size_usd from cash into open_notional. Raises on insufficient cash."""
        size = float(size_usd)
        ok, reason = self.can_open(size)
        if not ok:
            raise ValueError(reason)
        self.cash -= size
        self.open_notional += size
        self.save()

    def release_close(self, size_usd: float, realized_pnl: float) -> None:
        """Release locked notional and apply realized PnL to cash."""
        size = float(size_usd)
        pnl = float(realized_pnl)
        # Clamp open_notional so bad state never goes negative
        release = min(size, self.open_notional) if self.open_notional > 0 else size
        self.open_notional = max(0.0, self.open_notional - release)
        self.cash += size + pnl
        self.realized_pnl += pnl
        self.save()

    def reset(self, start_balance: float | None = None) -> None:
        sb = float(start_balance) if start_balance is not None else start_balance_from_env()
        self.start_balance = sb
        self.cash = sb
        self.realized_pnl = 0.0
        self.open_notional = 0.0
        self.save()


# Module-level default account (lazy)
_default_account: PaperAccount | None = None


def get_account(
    *,
    path: Path | str | None = None,
    account: PaperAccount | None = None,
    reload: bool = False,
) -> PaperAccount:
    """Return shared PaperAccount, or the explicit instance if provided."""
    global _default_account
    if account is not None:
        return account
    if path is not None:
        return PaperAccount.load(path)
    if _default_account is None or reload:
        _default_account = PaperAccount.load()
    return _default_account


def reset_default_account() -> None:
    global _default_account
    _default_account = None
