"""Paper TP/SL + risk exits (ported from divergent paper_tracker).

Statuses: sl_hit, tp1_hit (partial BE — position stays open), tp2_hit,
trailing_hit, dollar_stop, expired.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from dotenv import load_dotenv

from risk.atr import ATR_PERIOD, compute_atr, levels_dict_for_position
from risk.price_sanity import mark_sanity_dev_pct, pos_entry_price, quote_is_sane

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)

_last_exit_check_mono: float = 0.0


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


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@dataclass
class ExitConfig:
    """Env-gated exit parameters (sensible divergent defaults)."""

    be_hours: float = 8.0
    max_hold_hours: float = 48.0
    # dollar_stop / early close (0 disables)
    max_loss_pct_of_margin: float = 0.0
    dollar_stop_sl_pct_threshold: float = 0.70
    early_close_hours: float = 3.0
    early_close_loss_pct: float = 20.0
    paper_leverage: float = 1.0
    exit_check_sec: float = 0.0  # 0 = every desk pass
    enable_trailing: bool = True
    enable_stagnation: bool = False  # optional; off by default for bitget-bot
    atr_period: int = ATR_PERIOD

    @classmethod
    def from_env(cls) -> "ExitConfig":
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            be_hours=max(0.0, _env_float("BE_HOURS", _env_float("BREAKEVEN_TIMEOUT_HOURS", 8.0))),
            max_hold_hours=max(1.0, _env_float("MAX_HOLD_HOURS", 48.0)),
            max_loss_pct_of_margin=max(0.0, _env_float("MAX_LOSS_PCT_OF_MARGIN", 0.0)),
            dollar_stop_sl_pct_threshold=max(
                0.0, _env_float("DOLLAR_STOP_SL_PCT_THRESHOLD", 0.70)
            ),
            early_close_hours=max(0.0, _env_float("EARLY_CLOSE_HOURS", 3.0)),
            early_close_loss_pct=max(0.0, _env_float("EARLY_CLOSE_LOSS_PCT", 20.0)),
            paper_leverage=max(1.0, _env_float("PAPER_LEVERAGE", 1.0)),
            exit_check_sec=max(0.0, _env_float("EXIT_CHECK_SEC", 0.0)),
            enable_trailing=_env_bool("ENABLE_TRAILING", True),
            enable_stagnation=_env_bool("ENABLE_STAGNATION_EXIT", False),
            atr_period=max(2, _env_int("ATR_PERIOD", ATR_PERIOD)),
        )


def _pos_get(pos: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in pos and pos[key] is not None:
        return pos[key]
    meta = pos.get("meta") if isinstance(pos.get("meta"), dict) else {}
    if key in meta and meta[key] is not None:
        return meta[key]
    return default


def _is_long(pos: dict[str, Any]) -> bool:
    side = str(pos.get("side") or "long").lower().strip()
    return side in {"long", "buy"}


def _tp1_already_hit(pos: dict[str, Any], entry: float) -> bool:
    if bool(_pos_get(pos, "tp1_hit", False)):
        return True
    # Do NOT treat trailing_active alone as TP1 — that mislabeled loss-side
    # SL hits as trailing_hit (XAG/ETH red "trails").
    sl_raw = _pos_get(pos, "sl")
    if sl_raw is None:
        return False
    try:
        sl = float(sl_raw)
    except (TypeError, ValueError):
        return False
    # SL already parked at/beyond breakeven
    is_long = _is_long(pos)
    if is_long:
        return sl >= entry * (1.0 - 1e-9)
    return sl <= entry * (1.0 + 1e-9)


def _clamp_sl_to_breakeven(
    sl: float,
    entry: float,
    *,
    is_long: bool,
    protect: bool,
) -> float:
    """After TP1 / BE protect: never allow SL on the losing side of entry."""
    if not protect:
        return sl
    if is_long:
        return max(float(sl), float(entry))
    return min(float(sl), float(entry))


def update_trailing_sl(
    pos: dict[str, Any],
    candle_high: float,
    candle_low: float,
    df: pd.DataFrame | None,
    *,
    atr_period: int = ATR_PERIOD,
) -> dict[str, Any]:
    """Variant B trailing (donor _update_trailing_sl). Mutates a copy; returns updates.

    Activates when price moves 1x original SL distance from entry.
    Once active, SL trails by max(1.5*ATR, entry*0.005). Only profit direction.
    P1: once TP1 hit (or SL already at BE), never trail SL back through entry.
    """
    entry = float(pos.get("entry_price") or 0)
    sl = float(_pos_get(pos, "sl") or 0)
    if entry <= 0 or sl <= 0:
        return {}
    is_long = _is_long(pos)

    original_sl = _pos_get(pos, "original_sl")
    try:
        original_sl_f = float(original_sl) if original_sl is not None else None
    except (TypeError, ValueError):
        original_sl_f = None
    if original_sl_f is None:
        # Approximate: if already at BE, use atr or 2% of entry
        atr_guess = float(_pos_get(pos, "atr") or entry * 0.02)
        original_sl_f = (entry - atr_guess) if is_long else (entry + atr_guess)

    original_sl_dist = abs(entry - float(original_sl_f))
    if original_sl_dist < entry * 0.0001:
        return {}

    activation_dist = original_sl_dist
    sl_distance = original_sl_dist
    if df is not None and len(df) >= 5:
        try:
            current_atr = float((df["high"] - df["low"]).tail(atr_period).mean())
            if current_atr > entry * 0.0001:
                sl_distance = max(current_atr * 1.5, entry * 0.005)
        except Exception:
            pass

    prev_trail = _pos_get(pos, "trail_price")
    trailing_active = bool(_pos_get(pos, "trailing_active", False))
    prev_trail_f = float(prev_trail) if prev_trail is not None else None

    if is_long:
        new_trail = max(prev_trail_f, candle_high) if prev_trail_f is not None else candle_high
    else:
        new_trail = min(prev_trail_f, candle_low) if prev_trail_f is not None else candle_low

    if not trailing_active:
        if is_long and new_trail >= entry + activation_dist:
            trailing_active = True
        elif (not is_long) and new_trail <= entry - activation_dist:
            trailing_active = True

    new_sl = sl
    if trailing_active:
        if is_long:
            candidate = new_trail - sl_distance
            new_sl = max(sl, candidate)
        else:
            candidate = new_trail + sl_distance
            new_sl = min(sl, candidate)
        # P1 hard BE: once trailing is active, never allow SL on losing side of entry
        new_sl = _clamp_sl_to_breakeven(new_sl, entry, is_long=is_long, protect=True)

    updates: dict[str, Any] = {}
    epsilon = entry * 0.0000001
    if prev_trail_f is None or abs(new_trail - prev_trail_f) > epsilon:
        updates["trail_price"] = new_trail
    if trailing_active != bool(_pos_get(pos, "trailing_active", False)):
        updates["trailing_active"] = trailing_active
    if abs(new_sl - sl) > entry * 0.00001:
        updates["sl"] = new_sl
    return updates


@dataclass
class ExitEvent:
    """Result of checking one position against a candle / mark."""

    action: str  # none | update | close
    status: str | None = None
    close_price: float | None = None
    updates: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


def evaluate_exit(
    pos: dict[str, Any],
    *,
    candle_high: float | None,
    candle_low: float | None,
    mark_price: float | None,
    df: pd.DataFrame | None = None,
    cfg: ExitConfig | None = None,
    now: datetime | None = None,
) -> ExitEvent:
    """Evaluate SL/TP1/TP2/trailing/BE/dollar_stop/expired for one open position."""
    cfg = cfg or ExitConfig.from_env()
    now = now or _utc_now()
    entry = float(pos.get("entry_price") or 0)
    if entry <= 0:
        return ExitEvent(action="none", note="no_entry")

    sl_raw = _pos_get(pos, "sl")
    tp1_raw = _pos_get(pos, "tp1")
    tp2_raw = _pos_get(pos, "tp2")
    try:
        sl = float(sl_raw) if sl_raw is not None else None
    except (TypeError, ValueError):
        sl = None
    try:
        tp1 = float(tp1_raw) if tp1_raw is not None else None
    except (TypeError, ValueError):
        tp1 = None
    try:
        tp2 = float(tp2_raw) if tp2_raw is not None else None
    except (TypeError, ValueError):
        tp2 = None

    is_long = _is_long(pos)
    opened_at = _parse_ts(pos.get("opened_ts"))
    cur_price = mark_price
    if cur_price is None and df is not None and len(df) and "close" in df.columns:
        try:
            cur_price = float(df["close"].iloc[-1])
        except Exception:
            cur_price = None

    # No candle data — only expire if max hold exceeded
    if candle_high is None or candle_low is None:
        if opened_at and (now - opened_at).total_seconds() > cfg.max_hold_hours * 3600:
            return ExitEvent(
                action="close",
                status="expired",
                close_price=cur_price or entry,
                note="expired_no_data",
            )
        return ExitEvent(action="none", note="no_candle")

    sl_check = candle_low if is_long else candle_high
    tp_check = candle_high if is_long else candle_low
    updates: dict[str, Any] = {}
    status: str | None = None
    close_price: float | None = None
    tp1_hit = _tp1_already_hit(pos, entry)

    # 1) SL
    if sl is not None:
        hit_sl = (sl_check <= sl) if is_long else (sl_check >= sl)
        if hit_sl:
            is_profitable = (sl >= entry) if is_long else (sl <= entry)
            # P1: trailing_hit only when SL is actually at/beyond BE (not merely tp1 flag)
            status = "trailing_hit" if is_profitable else "sl_hit"
            # Prefer SL price for BE/trail exits so mark gap cannot invent a loss label
            close_price = sl if is_profitable else (cur_price or sl)
            return ExitEvent(action="close", status=status, close_price=close_price)

    # 2) TP2 full close
    if tp2 is not None:
        hit_tp2 = (tp_check >= tp2) if is_long else (tp_check <= tp2)
        if hit_tp2:
            return ExitEvent(
                action="close",
                status="tp2_hit",
                close_price=cur_price or tp2,
            )

    # 3) TP1 → hard BE (entry), do not close
    if tp1 is not None and not tp1_hit:
        hit_tp1 = (tp_check >= tp1) if is_long else (tp_check <= tp1)
        if hit_tp1:
            updates["sl"] = entry
            updates["tp1_hit"] = True
            updates["tp1_hit_ts"] = now.isoformat()
            # Keep original_sl for trailing activation distance
            if _pos_get(pos, "original_sl") is None and sl is not None:
                updates["original_sl"] = sl
            sl = entry
            tp1_hit = True
            # Continue — may trail / check other exits same bar

    # 4) Trailing after TP1 (or when trailing_active)
    if cfg.enable_trailing and status is None:
        # Donor runs trailing whenever not closed; activation needs original SL dist.
        # We enable updates after TP1 or if already trailing, and also allow
        # activation based on original_sl once SL was set.
        trail_src = dict(pos)
        if updates:
            # merge pending updates for trailing calc
            meta = dict(trail_src.get("meta") or {})
            for k, v in updates.items():
                trail_src[k] = v
                meta[k] = v
            trail_src["meta"] = meta
        # Only trail once TP1 hit or trailing already active (simplified faithful)
        if tp1_hit or bool(_pos_get(trail_src, "trailing_active", False)):
            t_upd = update_trailing_sl(
                trail_src,
                float(candle_high),
                float(candle_low),
                df,
                atr_period=cfg.atr_period,
            )
            if t_upd:
                # Re-clamp any SL from trail against BE when TP1 already hit
                if "sl" in t_upd and t_upd["sl"] is not None:
                    t_upd["sl"] = _clamp_sl_to_breakeven(
                        float(t_upd["sl"]),
                        entry,
                        is_long=is_long,
                        protect=bool(tp1_hit)
                        or bool(t_upd.get("trailing_active"))
                        or bool(_pos_get(trail_src, "trailing_active", False)),
                    )
                updates.update(t_upd)
                if "sl" in t_upd:
                    sl = float(t_upd["sl"])
                # Re-check trailing SL same bar
                if sl is not None:
                    sl_check2 = candle_low if is_long else candle_high
                    hit2 = (sl_check2 <= sl) if is_long else (sl_check2 >= sl)
                    if hit2:
                        is_profitable = (sl >= entry) if is_long else (sl <= entry)
                        return ExitEvent(
                            action="close",
                            status="trailing_hit" if is_profitable else "sl_hit",
                            close_price=sl if is_profitable else (cur_price or sl),
                            updates=updates,
                        )

    # 5) Breakeven after N hours without TP1
    if opened_at and tp1 is not None and not tp1_hit and cfg.be_hours > 0:
        elapsed_h = (now - opened_at).total_seconds() / 3600.0
        if elapsed_h >= cfg.be_hours and sl is not None:
            sl_at_loss = (sl < entry) if is_long else (sl > entry)
            if sl_at_loss:
                updates["sl"] = entry
                updates["be_timeout"] = True
                updates["be_timeout_ts"] = now.isoformat()
                if _pos_get(pos, "original_sl") is None:
                    updates["original_sl"] = sl
                sl = entry

    # If TP1/BE already active, hard-clamp any pending SL update to entry
    if updates.get("sl") is not None and (
        tp1_hit or updates.get("tp1_hit") or updates.get("be_timeout")
    ):
        updates["sl"] = _clamp_sl_to_breakeven(
            float(updates["sl"]), entry, is_long=is_long, protect=True
        )
        sl = float(updates["sl"])

    # 6) Early close / dollar_stop (env-gated)
    size_usd = float(pos.get("size_usd") or 0)
    lev = float(cfg.paper_leverage)
    if cur_price and size_usd > 0:
        pct = (cur_price - entry) / entry * 100.0
        if not is_long:
            pct = -pct
        unrealized = size_usd * lev * pct / 100.0

        if (
            cfg.early_close_hours > 0
            and opened_at
            and (now - opened_at).total_seconds() / 3600.0 >= cfg.early_close_hours
            and cfg.early_close_loss_pct > 0
            and unrealized < -(size_usd * cfg.early_close_loss_pct / 100.0)
        ):
            return ExitEvent(
                action="close",
                status="dollar_stop",
                close_price=cur_price,
                updates=updates,
                note="early_close",
            )

        if cfg.max_loss_pct_of_margin > 0:
            max_loss = size_usd * cfg.max_loss_pct_of_margin / 100.0
            if unrealized <= -size_usd:
                return ExitEvent(
                    action="close",
                    status="dollar_stop",
                    close_price=cur_price,
                    updates=updates,
                    note="liquidation",
                )
            if unrealized < -max_loss:
                sl_ok = True
                thr = cfg.dollar_stop_sl_pct_threshold
                if sl is not None and thr > 0 and sl > 0:
                    total_dist = abs(entry - sl)
                    moved = abs(cur_price - entry)
                    pct_to_sl = moved / total_dist if total_dist > 0 else 1.0
                    sl_ok = pct_to_sl >= thr
                if sl_ok:
                    return ExitEvent(
                        action="close",
                        status="dollar_stop",
                        close_price=cur_price,
                        updates=updates,
                        note="dollar_stop",
                    )

    # 7) Max hold expire
    if opened_at and (now - opened_at).total_seconds() > cfg.max_hold_hours * 3600:
        return ExitEvent(
            action="close",
            status="expired",
            close_price=cur_price or entry,
            updates=updates,
        )

    if updates:
        return ExitEvent(action="update", status="tp1_hit" if updates.get("tp1_hit") else None, updates=updates)
    return ExitEvent(action="none")


def should_run_exit_check(cfg: ExitConfig | None = None) -> bool:
    """Throttle by EXIT_CHECK_SEC (0 = always)."""
    global _last_exit_check_mono
    cfg = cfg or ExitConfig.from_env()
    if cfg.exit_check_sec <= 0:
        return True
    now = time.monotonic()
    if now - _last_exit_check_mono >= cfg.exit_check_sec:
        _last_exit_check_mono = now
        return True
    return False


def mark_exit_check_ran() -> None:
    global _last_exit_check_mono
    _last_exit_check_mono = time.monotonic()


def apply_exit_event(
    pos: dict[str, Any],
    ev: ExitEvent,
    *,
    book: Any,
    gate: Any | None = None,
) -> dict[str, Any] | None:
    """Persist an evaluate_exit result (update levels or close). None if action=none."""
    from exec.router import close_position

    pid = str(pos.get("position_id") or "")
    sym = str(pos.get("symbol") or "")
    if ev.action == "none":
        return None

    if ev.action == "update" and ev.updates:
        updated = apply_position_updates(pos, ev.updates)
        if "sl" in ev.updates and ev.updates.get("sl") is not None:
            try:
                from exec.router import sync_exchange_sl

                reason = "tp1_be" if ev.updates.get("tp1_hit") else (
                    "be_timeout" if ev.updates.get("be_timeout") else (
                        "trailing" if ev.updates.get("trailing_active") else "sl_update"
                    )
                )
                hub_meta = sync_exchange_sl(updated, ev.updates["sl"], reason=reason)
                if hub_meta:
                    updated = apply_position_updates(updated, hub_meta)
            except Exception as exc:  # noqa: BLE001
                print(f"[EXIT] hub SL sync skip {pid} {sym}: {exc}")
        book.update_position(pid, updated)
        note = ev.status or "levels_update"
        print(
            f"[EXIT] UPDATE {pid} {sym} {note} "
            f"sl={updated.get('sl')} tp1_hit={updated.get('tp1_hit')} "
            f"trail={updated.get('trailing_active')}"
        )
        return {
            "action": "update",
            "position_id": pid,
            "symbol": sym,
            "status": ev.status,
            "updates": dict(ev.updates),
        }

    if ev.action == "close" and ev.close_price is not None and ev.status:
        close_meta = {
            "exit_status": ev.status,
            "exit_note": ev.note,
        }
        if ev.updates:
            close_meta.update(ev.updates)
        try:
            result = close_position(
                pid,
                float(ev.close_price),
                meta=close_meta,
                gate=gate,
                book=book,
            )
            print(
                f"[EXIT] CLOSE {pid} {sym} status={ev.status} "
                f"@ {ev.close_price} pnl={result.get('realized_pnl')}"
            )
            return {
                "action": "close",
                "position_id": pid,
                "symbol": sym,
                "status": ev.status,
                "close_price": ev.close_price,
                "realized_pnl": result.get("realized_pnl"),
            }
        except Exception as exc:  # noqa: BLE001
            print(f"[EXIT] ERROR close {pid} {sym}: {exc}")
            return {
                "action": "error",
                "position_id": pid,
                "symbol": sym,
                "error": str(exc),
            }
    return None


def apply_position_updates(pos: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Merge exit updates into position top-level + meta."""
    out = dict(pos)
    meta = dict(out.get("meta") or {})
    for k, v in updates.items():
        out[k] = v
        meta[k] = v
    # keep level mirrors
    for k in ("sl", "tp1", "tp2", "atr", "atr_pct", "original_sl", "trailing_active", "trail_price", "tp1_hit"):
        if k in out and out[k] is not None:
            meta[k] = out[k]
    out["meta"] = meta
    return out


def check_open_exits(
    *,
    book: Any | None = None,
    gate: Any | None = None,
    cfg: ExitConfig | None = None,
    timeframe: str | None = None,
    ohlcv_limit: int = 50,
    fetch_ohlcv_fn: Callable[..., pd.DataFrame] | None = None,
    fetch_mark_fn: Callable[[str], float] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Desk-loop helper: check all open paper positions; update or close via PaperBook.

    Pass the same RiskGate used for opens so record_close stays in sync.
    Returns list of event dicts for logging.
    """
    from exec.paper import PaperBook

    cfg = cfg or ExitConfig.from_env()
    if not force and not should_run_exit_check(cfg):
        return []
    mark_exit_check_ran()

    if book is not None:
        b = book
        if gate is not None and getattr(b, 'gate', None) is None:
            b.gate = gate
    else:
        b = PaperBook(gate=gate)
    opens = b.list_open()
    if not opens:
        return []

    if fetch_ohlcv_fn is None:
        from ingest.bitget_ohlcv import fetch_ohlcv as fetch_ohlcv_fn  # type: ignore
    if fetch_mark_fn is None:
        from ingest.bitget_ohlcv import fetch_mark_price as fetch_mark_fn  # type: ignore

    load_dotenv(ROOT / ".env", override=False)
    tf = (timeframe or os.getenv("TIMEFRAME", "15m") or "15m").strip()
    events: list[dict[str, Any]] = []

    for pos in opens:
        pid = str(pos.get("position_id") or "")
        sym = str(pos.get("symbol") or "")
        if not pid or not sym:
            continue
        # Skip if no SL/TP attached yet
        if _pos_get(pos, "sl") is None and _pos_get(pos, "tp1") is None:
            continue

        df = None
        candle_high = candle_low = None
        mark = None
        try:
            df = fetch_ohlcv_fn(symbol=sym, timeframe=tf, limit=ohlcv_limit)
            if df is not None and len(df):
                candle_high = float(df["high"].iloc[-1])
                candle_low = float(df["low"].iloc[-1])
        except Exception as exc:  # noqa: BLE001
            logger.debug("exit ohlcv fail %s: %s", sym, exc)
        try:
            mark = float(fetch_mark_fn(sym))
        except Exception as exc:  # noqa: BLE001
            logger.debug("exit mark fail %s: %s", sym, exc)
            if df is not None and len(df):
                try:
                    mark = float(df["close"].iloc[-1])
                except Exception:
                    mark = None

        entry = pos_entry_price(pos)
        if entry is not None:
            # Same BZ case: public mark/candle ~99 vs Demo fill ~103.5. Hub TPSL
            # stays on the exchange; do not close the shadow from a wrong scale.
            bad_mark = mark is not None and not quote_is_sane(sym, mark, entry)
            bad_hi = candle_high is not None and not quote_is_sane(sym, candle_high, entry)
            bad_lo = candle_low is not None and not quote_is_sane(sym, candle_low, entry)
            if bad_mark or bad_hi or bad_lo:
                print(
                    f"[EXIT] skip mark {sym}: mark={mark} hi={candle_high} lo={candle_low} "
                    f"vs entry={entry} (> {mark_sanity_dev_pct(sym)}%)"
                )
                continue
        ev = evaluate_exit(
            pos,
            candle_high=candle_high,
            candle_low=candle_low,
            mark_price=mark,
            df=df,
            cfg=cfg,
        )
        applied = apply_exit_event(pos, ev, book=b, gate=gate)
        if applied:
            events.append(applied)

    return events
