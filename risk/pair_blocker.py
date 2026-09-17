"""Pair / timeframe performance bans — ported from divergent pair_blocker + timeframe_blocker.

Reads closed fills from paper_fills.jsonl; persists blocks in data/pair_blocks.json.
Settings via env (divergent DB defaults).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLOCKS_PATH = ROOT / "data" / "pair_blocks.json"
DEFAULT_FILLS_PATH = ROOT / "data" / "paper_fills.jsonl"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


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


@dataclass
class BlockerConfig:
    enabled: bool = True
    min_trades: int = 2
    wr_threshold: float = 30.0
    consecutive_losses: int = 2
    cooldown_hours: float = 48.0
    stats_window_days: float = 14.0
    longtail_window_days: float = 60.0
    longtail_wr_threshold: float = 20.0
    pnl_min_trades: int = 5
    pnl_cooldown_hours: float = 336.0  # 14d
    tf_enabled: bool = True
    tf_min_trades: int = 30
    tf_window_days: float = 30.0
    tf_cooldown_hours: float = 168.0  # 7d
    interval_sec: float = 600.0
    fills_path: Path = DEFAULT_FILLS_PATH
    blocks_path: Path = DEFAULT_BLOCKS_PATH
    default_timeframe: str = "15m"

    @classmethod
    def from_env(cls) -> "BlockerConfig":
        load_dotenv(ROOT / ".env", override=False)
        fills = os.getenv("PAPER_FILLS_PATH", "").strip()
        blocks = os.getenv("PAIR_BLOCKS_PATH", "").strip()
        return cls(
            enabled=_env_bool("PAIR_BLOCKER_ENABLED", True),
            min_trades=max(1, _env_int("BLOCK_MIN_TRADES", 4)),
            wr_threshold=_env_float("BLOCK_WR_THRESHOLD", 30.0),
            consecutive_losses=max(1, _env_int("BLOCK_CONSECUTIVE_LOSSES", 3)),
            cooldown_hours=max(0.0, _env_float("BLOCK_COOLDOWN_HOURS", 48.0)),
            stats_window_days=max(1.0, _env_float("BLOCK_STATS_WINDOW_DAYS", 14.0)),
            longtail_window_days=max(1.0, _env_float("BLOCK_LONGTAIL_WINDOW_DAYS", 60.0)),
            longtail_wr_threshold=_env_float("BLOCK_LONGTAIL_WR_THRESHOLD", 20.0),
            pnl_min_trades=max(1, _env_int("BLOCK_PNL_MIN_TRADES", 5)),
            pnl_cooldown_hours=max(0.0, _env_float("BLOCK_PNL_COOLDOWN_HOURS", 336.0)),
            tf_enabled=_env_bool("TF_BLOCKER_ENABLED", True),
            tf_min_trades=max(1, _env_int("TF_BLOCK_MIN_TRADES", 30)),
            tf_window_days=max(1.0, _env_float("TF_BLOCK_WINDOW_DAYS", 30.0)),
            tf_cooldown_hours=max(0.0, _env_float("TF_BLOCK_COOLDOWN_HOURS", 168.0)),
            interval_sec=max(60.0, _env_float("PAIR_BLOCKER_INTERVAL_SEC", 600.0)),
            fills_path=Path(fills) if fills else DEFAULT_FILLS_PATH,
            blocks_path=Path(blocks) if blocks else DEFAULT_BLOCKS_PATH,
            default_timeframe=(
                (os.getenv("TIMEFRAMES") or os.getenv("TIMEFRAME") or "15m")
                .split(",")[0]
                .strip()
                or "15m"
            ),
        )


def _load_blocks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pairs": {}, "timeframes": {}, "updated_ts": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"pairs": {}, "timeframes": {}, "updated_ts": None}
    if not isinstance(raw, dict):
        return {"pairs": {}, "timeframes": {}, "updated_ts": None}
    pairs = raw.get("pairs") if isinstance(raw.get("pairs"), dict) else {}
    tfs = raw.get("timeframes") if isinstance(raw.get("timeframes"), dict) else {}
    return {"pairs": dict(pairs), "timeframes": dict(tfs), "updated_ts": raw.get("updated_ts")}


def _save_blocks(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_ts"] = _utc_now().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _expire_blocks(data: dict[str, Any], now: datetime) -> None:
    for bag_key in ("pairs", "timeframes"):
        bag = data.get(bag_key) or {}
        drop = []
        for key, meta in bag.items():
            if not isinstance(meta, dict):
                drop.append(key)
                continue
            ub = _parse_ts(meta.get("unblock_at"))
            if ub is not None and ub <= now:
                drop.append(key)
        for key in drop:
            bag.pop(key, None)
        data[bag_key] = bag


def _load_closed_trades(fills_path: Path, default_tf: str) -> list[dict[str, Any]]:
    """Closed fills with realized_pnl; newest last."""
    if not fills_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in fills_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if not isinstance(o, dict):
            continue
        if str(o.get("event") or "").lower() != "close":
            continue
        sym = str(o.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            pnl = float(o.get("realized_pnl"))
        except (TypeError, ValueError):
            continue
        ts = _parse_ts(o.get("ts") or o.get("closed_ts"))
        if ts is None:
            continue
        meta = o.get("meta") if isinstance(o.get("meta"), dict) else {}
        tf = str(meta.get("timeframe") or o.get("timeframe") or default_tf).strip() or default_tf
        rows.append({"symbol": sym, "pnl": pnl, "ts": ts, "timeframe": tf})
    rows.sort(key=lambda r: r["ts"])
    return rows


def _wr_pct(wins: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(wins / total * 100.0, 1)


def _consecutive_losses(trades_desc: list[dict[str, Any]], limit: int) -> int:
    """Count consecutive losses from newest; stop early if win."""
    n = 0
    for t in trades_desc:
        if float(t["pnl"]) <= 0:
            n += 1
            if n >= limit:
                return n
        else:
            break
    return n


def run_blocker(cfg: BlockerConfig | None = None) -> dict[str, Any]:
    """Evaluate closed trades and update pair/TF blocks. Returns summary."""
    load_dotenv(ROOT / ".env", override=False)
    cfg = cfg or BlockerConfig.from_env()
    now = _utc_now()
    data = _load_blocks(cfg.blocks_path)
    _expire_blocks(data, now)

    if not cfg.enabled:
        _save_blocks(cfg.blocks_path, data)
        return {"enabled": False, "new_pair_blocks": 0, "new_tf_blocks": 0}

    trades = _load_closed_trades(cfg.fills_path, cfg.default_timeframe)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)
        by_tf[t["timeframe"]].append(t)

    pairs = data.setdefault("pairs", {})
    tfs = data.setdefault("timeframes", {})
    new_pair = 0
    new_tf = 0

    def _already(sym: str) -> bool:
        meta = pairs.get(sym)
        if not isinstance(meta, dict):
            return False
        ub = _parse_ts(meta.get("unblock_at"))
        return ub is None or ub > now

    # Primary window: WR + consecutive losses
    cutoff = now - timedelta(days=cfg.stats_window_days)
    for sym, rows in by_sym.items():
        if _already(sym):
            continue
        window = [r for r in rows if r["ts"] >= cutoff]
        if len(window) < cfg.min_trades:
            continue
        wins = sum(1 for r in window if r["pnl"] > 0)
        wr = _wr_pct(wins, len(window))
        desc = sorted(window, key=lambda r: r["ts"], reverse=True)
        consec = _consecutive_losses(desc, cfg.consecutive_losses)
        reason = None
        if wr < cfg.wr_threshold:
            reason = f"WR {wr}% < {cfg.wr_threshold}% threshold ({len(window)} trades)"
        elif consec >= cfg.consecutive_losses:
            reason = f"{consec} consecutive losses"
        if reason:
            ub = now + timedelta(hours=cfg.cooldown_hours) if cfg.cooldown_hours > 0 else None
            pairs[sym] = {
                "reason": reason,
                "blocked_at": now.isoformat(),
                "unblock_at": ub.isoformat() if ub else None,
            }
            new_pair += 1

    # Long-tail WR
    lt_cutoff = now - timedelta(days=cfg.longtail_window_days)
    for sym, rows in by_sym.items():
        if _already(sym):
            continue
        window = [r for r in rows if r["ts"] >= lt_cutoff]
        if len(window) < cfg.min_trades:
            continue
        wins = sum(1 for r in window if r["pnl"] > 0)
        wr = _wr_pct(wins, len(window))
        if wr < cfg.longtail_wr_threshold:
            ub = now + timedelta(hours=cfg.cooldown_hours) if cfg.cooldown_hours > 0 else None
            pairs[sym] = {
                "reason": (
                    f"long-tail WR {wr}% < {cfg.longtail_wr_threshold}% "
                    f"over {int(cfg.longtail_window_days)}d ({len(window)} trades)"
                ),
                "blocked_at": now.isoformat(),
                "unblock_at": ub.isoformat() if ub else None,
            }
            new_pair += 1

    # Lifetime net PnL
    for sym, rows in by_sym.items():
        if _already(sym):
            continue
        if len(rows) < cfg.pnl_min_trades:
            continue
        total_pnl = sum(float(r["pnl"]) for r in rows)
        if total_pnl < 0:
            ub = (
                now + timedelta(hours=cfg.pnl_cooldown_hours)
                if cfg.pnl_cooldown_hours > 0
                else None
            )
            pairs[sym] = {
                "reason": f"lifetime PnL ${total_pnl:.0f} < $0 over {len(rows)} trades",
                "blocked_at": now.isoformat(),
                "unblock_at": ub.isoformat() if ub else None,
            }
            new_pair += 1

    # Timeframe aggregate PnL
    if cfg.tf_enabled:
        tf_cutoff = now - timedelta(days=cfg.tf_window_days)
        for tf, rows in by_tf.items():
            meta = tfs.get(tf)
            if isinstance(meta, dict):
                ub_ex = _parse_ts(meta.get("unblock_at"))
                if ub_ex is None or ub_ex > now:
                    continue
            window = [r for r in rows if r["ts"] >= tf_cutoff]
            if len(window) < cfg.tf_min_trades:
                continue
            total_pnl = sum(float(r["pnl"]) for r in window)
            if total_pnl < 0:
                ub = (
                    now + timedelta(hours=cfg.tf_cooldown_hours)
                    if cfg.tf_cooldown_hours > 0
                    else None
                )
                tfs[tf] = {
                    "reason": (
                        f"TF PnL ${total_pnl:.0f} over {len(window)} trades "
                        f"in {int(cfg.tf_window_days)}d"
                    ),
                    "blocked_at": now.isoformat(),
                    "unblock_at": ub.isoformat() if ub else None,
                }
                new_tf += 1

    data["pairs"] = pairs
    data["timeframes"] = tfs
    _save_blocks(cfg.blocks_path, data)
    return {
        "enabled": True,
        "new_pair_blocks": new_pair,
        "new_tf_blocks": new_tf,
        "blocked_pairs": len(pairs),
        "blocked_tfs": len(tfs),
        "closed_trades": len(trades),
    }


def is_pair_blocked(symbol: str, cfg: BlockerConfig | None = None) -> tuple[bool, str]:
    """Return (blocked, reason). Expired blocks ignored."""
    cfg = cfg or BlockerConfig.from_env()
    if not cfg.enabled:
        return False, ""
    data = _load_blocks(cfg.blocks_path)
    now = _utc_now()
    _expire_blocks(data, now)
    meta = (data.get("pairs") or {}).get(str(symbol))
    if not isinstance(meta, dict):
        return False, ""
    ub = _parse_ts(meta.get("unblock_at"))
    if ub is not None and ub <= now:
        return False, ""
    return True, str(meta.get("reason") or "pair_blocked")


def is_timeframe_blocked(timeframe: str, cfg: BlockerConfig | None = None) -> tuple[bool, str]:
    cfg = cfg or BlockerConfig.from_env()
    if not cfg.enabled or not cfg.tf_enabled:
        return False, ""
    data = _load_blocks(cfg.blocks_path)
    now = _utc_now()
    _expire_blocks(data, now)
    meta = (data.get("timeframes") or {}).get(str(timeframe))
    if not isinstance(meta, dict):
        return False, ""
    ub = _parse_ts(meta.get("unblock_at"))
    if ub is not None and ub <= now:
        return False, ""
    return True, str(meta.get("reason") or "tf_blocked")
