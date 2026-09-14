"""Risk gate: notional, daily loss, positions, cooldown, type filter.

Paper-only ? no exchange calls. State lives in memory and optionally
`data/risk_state.json`.
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
DEFAULT_STATE_PATH = ROOT / "data" / "risk_state.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today() -> str:
    return _utc_now().date().isoformat()


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(float(v))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _env_types(name: str = "ALLOWED_TYPES") -> set[str] | None:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return None
    parts = [p.strip().upper() for p in str(v).split(",") if p.strip()]
    return set(parts) if parts else None


def _parse_ts(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


@dataclass
class RiskLimits:
    max_notional_usd: float = 100.0
    max_daily_loss_usd: float = 50.0
    max_positions: int = 15
    one_position_per_symbol: bool = True
    cooldown_sec: float = 900.0
    allowed_types: set[str] | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "max_notional_usd": self.max_notional_usd,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_positions": self.max_positions,
            "one_position_per_symbol": self.one_position_per_symbol,
            "cooldown_sec": self.cooldown_sec,
            "allowed_types": sorted(self.allowed_types) if self.allowed_types else None,
        }

    @classmethod
    def from_env(cls) -> "RiskLimits":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            max_notional_usd=_env_float("MAX_NOTIONAL_USD", 100.0),
            max_daily_loss_usd=_env_float("MAX_DAILY_LOSS_USD", 50.0),
            max_positions=max(0, _env_int("MAX_POSITIONS", 15)),
            one_position_per_symbol=_env_bool("ONE_POSITION_PER_SYMBOL", True),
            cooldown_sec=max(0.0, _env_float("COOLDOWN_SEC", 900.0)),
            allowed_types=_env_types("ALLOWED_TYPES"),
        )


@dataclass
class OpenPosition:
    symbol: str
    size_usd: float
    opened_ts: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "size_usd": self.size_usd,
            "opened_ts": self.opened_ts,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OpenPosition":
        return cls(
            symbol=str(d.get("symbol", "")),
            size_usd=float(d.get("size_usd", 0) or 0),
            opened_ts=str(d.get("opened_ts") or _utc_now().isoformat()),
            meta=dict(d.get("meta") or {}),
        )


@dataclass
class RiskState:
    """Mutable risk book: open paper positions, daily PnL, last trade ts."""

    open_positions: list[OpenPosition] = field(default_factory=list)
    daily_pnl: float = 0.0
    daily_date: str = field(default_factory=_utc_today)
    last_trade_ts: dict[str, str] = field(default_factory=dict)

    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.open_positions}

    def roll_day_if_needed(self) -> None:
        today = _utc_today()
        if self.daily_date != today:
            self.daily_date = today
            self.daily_pnl = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_positions": [p.to_dict() for p in self.open_positions],
            "daily_pnl": self.daily_pnl,
            "daily_date": self.daily_date,
            "last_trade_ts": dict(self.last_trade_ts),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RiskState":
        if not d:
            return cls()
        positions = [
            OpenPosition.from_dict(p)
            for p in (d.get("open_positions") or [])
            if isinstance(p, dict)
        ]
        last = d.get("last_trade_ts") or {}
        if not isinstance(last, dict):
            last = {}
        st = cls(
            open_positions=positions,
            daily_pnl=float(d.get("daily_pnl", 0) or 0),
            daily_date=str(d.get("daily_date") or _utc_today()),
            last_trade_ts={str(k): str(v) for k, v in last.items()},
        )
        st.roll_day_if_needed()
        return st


class RiskGate:
    """Env-configurable paper risk gate."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        state: RiskState | None = None,
        *,
        state_path: Path | str | None = None,
        persist: bool = True,
        account: Any = None,
    ) -> None:
        self.limits = limits or RiskLimits.from_env()
        if state_path is None:
            load_dotenv(ROOT / ".env", override=False)
            env_path = os.getenv("RISK_STATE_PATH", "").strip()
            state_path = Path(env_path) if env_path else DEFAULT_STATE_PATH
        self.state_path = Path(state_path) if state_path else None
        self.persist = bool(persist and self.state_path is not None)
        self.account = account
        if state is not None:
            self.state = state
        elif self.persist and self.state_path and self.state_path.exists():
            self.state = self._load_state()
        else:
            self.state = RiskState()
        self.state.roll_day_if_needed()

    def _load_state(self) -> RiskState:
        assert self.state_path is not None
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return RiskState.from_dict(raw if isinstance(raw, dict) else {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return RiskState()

    def save_state(self) -> None:
        if not self.persist or self.state_path is None:
            return
        self.state.roll_day_if_needed()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2)
        tmp.write_text(payload + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def snapshot_limits(self) -> dict[str, Any]:
        pub = self.limits.to_public()
        self.state.roll_day_if_needed()
        pub["open_positions"] = len(self.state.open_positions)
        pub["daily_pnl"] = self.state.daily_pnl
        pub["daily_date"] = self.state.daily_date
        return pub

    def check(
        self,
        candidate: dict[str, Any] | None,
        proposed_size_usd: float,
        *,
        account: Any = None,
    ) -> dict[str, Any]:
        """Return {allowed, reason, limits} for a candidate + size."""
        self.state.roll_day_if_needed()
        limits_snap = self.snapshot_limits()
        if not candidate:
            return {"allowed": False, "reason": "no_candidate", "limits": limits_snap}

        symbol = str(candidate.get("symbol") or "").strip()
        ctype = str(candidate.get("type") or "").strip().upper()
        size = float(proposed_size_usd or 0.0)

        if not symbol:
            return {"allowed": False, "reason": "missing_symbol", "limits": limits_snap}

        allowed_types = self.limits.allowed_types
        if allowed_types is not None and ctype and ctype not in allowed_types:
            return {
                "allowed": False,
                "reason": f"type_not_allowed:{ctype}",
                "limits": limits_snap,
            }

        max_loss = abs(self.limits.max_daily_loss_usd)
        if self.state.daily_pnl <= -max_loss:
            return {
                "allowed": False,
                "reason": "daily_loss_kill",
                "limits": limits_snap,
            }

        if size <= 0:
            return {"allowed": False, "reason": "invalid_size", "limits": limits_snap}

        if size > self.limits.max_notional_usd:
            return {
                "allowed": False,
                "reason": "max_notional",
                "limits": limits_snap,
            }

        if len(self.state.open_positions) >= self.limits.max_positions:
            return {
                "allowed": False,
                "reason": "max_positions",
                "limits": limits_snap,
            }

        if self.limits.one_position_per_symbol and symbol in self.state.open_symbols():
            return {
                "allowed": False,
                "reason": "one_pos_per_symbol",
                "limits": limits_snap,
            }

        last_raw = self.state.last_trade_ts.get(symbol)
        last_ts = _parse_ts(last_raw)
        if last_ts is not None and self.limits.cooldown_sec > 0:
            elapsed = _utc_now().timestamp() - last_ts
            if elapsed < self.limits.cooldown_sec:
                remaining = int(self.limits.cooldown_sec - elapsed)
                return {
                    "allowed": False,
                    "reason": f"cooldown:{remaining}s",
                    "limits": limits_snap,
                }

        # Divergent pair / timeframe performance bans
        try:
            from risk.pair_blocker import is_pair_blocked, is_timeframe_blocked

            blocked, block_reason = is_pair_blocked(symbol)
            if blocked:
                return {
                    "allowed": False,
                    "reason": f"pair_blocked:{block_reason}",
                    "limits": limits_snap,
                }
            tf = str(
                (candidate or {}).get("timeframe")
                or os.getenv("TIMEFRAME", "15m")
                or "15m"
            ).strip()
            tf_blocked, tf_reason = is_timeframe_blocked(tf)
            if tf_blocked:
                return {
                    "allowed": False,
                    "reason": f"tf_blocked:{tf_reason}",
                    "limits": limits_snap,
                }
        except Exception:
            pass

        # Cash wallet: deny if paper account cannot cover size_usd
        acct = account if account is not None else self.account
        if acct is None:
            try:
                from exec.account import get_account

                acct = get_account()
            except Exception:
                acct = None
        if acct is not None:
            can, cash_reason = acct.can_open(size)
            if not can:
                return {
                    "allowed": False,
                    "reason": cash_reason,
                    "limits": limits_snap,
                }

        return {"allowed": True, "reason": "ok", "limits": limits_snap}

    def record_open(
        self,
        symbol: str,
        size_usd: float,
        *,
        meta: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> OpenPosition:
        """Book a paper open (for later paper-exec step)."""
        self.state.roll_day_if_needed()
        now = ts or _utc_now()
        iso = now.isoformat()
        pos = OpenPosition(
            symbol=str(symbol),
            size_usd=float(size_usd),
            opened_ts=iso,
            meta=dict(meta or {}),
        )
        self.state.open_positions.append(pos)
        self.state.last_trade_ts[str(symbol)] = iso
        self.save_state()
        return pos

    def sync_opens_from_paper(self, positions: list[dict[str, Any]]) -> int:
        """Replace risk open book with live paper positions (repair drift after exits)."""
        self.state.roll_day_if_needed()
        rebuilt: list[OpenPosition] = []
        for p in positions or []:
            sym = str(p.get('symbol') or '').strip()
            if not sym:
                continue
            meta = dict(p.get('meta') or {})
            if p.get('position_id') is not None:
                meta.setdefault('position_id', p.get('position_id'))
            if p.get('side') is not None:
                meta.setdefault('side', p.get('side'))
            rebuilt.append(
                OpenPosition(
                    symbol=sym,
                    size_usd=float(p.get('size_usd') or 0),
                    opened_ts=str(p.get('opened_ts') or _utc_now().isoformat()),
                    meta=meta,
                )
            )
            if p.get('opened_ts'):
                self.state.last_trade_ts[sym] = str(p.get('opened_ts'))
        self.state.open_positions = rebuilt
        self.save_state()
        return len(rebuilt)

    def record_close(
        self,
        symbol: str,
        realized_pnl: float,
        *,
        meta: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> bool:
        """Close first matching open paper position; update daily PnL."""
        del meta  # reserved for later paper step
        self.state.roll_day_if_needed()
        symbol = str(symbol)
        idx = next(
            (i for i, p in enumerate(self.state.open_positions) if p.symbol == symbol),
            None,
        )
        if idx is None:
            return False
        self.state.open_positions.pop(idx)
        self.state.daily_pnl += float(realized_pnl)
        now = ts or _utc_now()
        self.state.last_trade_ts[symbol] = now.isoformat()
        self.save_state()
        return True


# Back-compat thin wrappers for the old stub API
@dataclass
class _LegacyRiskState:
    open_symbols: set[str] = field(default_factory=set)
    daily_pnl: float = 0.0
    max_notional: float = 100.0
    max_daily_loss: float = 50.0


RiskStateLegacy = _LegacyRiskState  # alias if anything imported old name


def allow_entry(
    symbol: str,
    notional: float,
    state: Any = None,
    **kwargs: Any,
) -> tuple[bool, str]:
    """Legacy (allowed, reason) helper used by early stubs."""
    gate = RiskGate(persist=False, state_path=None)
    if state is not None:
        # Accept old RiskState-like objects
        open_syms = getattr(state, "open_symbols", None)
        if open_syms is not None:
            for sym in open_syms:
                gate.state.open_positions.append(
                    OpenPosition(symbol=sym, size_usd=0.0, opened_ts=_utc_now().isoformat())
                )
        if hasattr(state, "daily_pnl"):
            gate.state.daily_pnl = float(state.daily_pnl)
        if hasattr(state, "max_notional"):
            gate.limits.max_notional_usd = float(state.max_notional)
        if hasattr(state, "max_daily_loss"):
            gate.limits.max_daily_loss_usd = float(state.max_daily_loss)
    cand = {"symbol": symbol, "type": kwargs.get("type", "BULLISH_DIV")}
    out = gate.check(cand, float(notional))
    return bool(out["allowed"]), str(out["reason"])
