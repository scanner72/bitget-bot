"""ATR helpers for paper SL/TP sizing (ported from divergent stream_manager)."""

from __future__ import annotations

import os
from typing import Any, Mapping

import pandas as pd

# Donor defaults
ATR_PERIOD = 14
# 2% floor pushed 15m TP1/TP2 so far that quiet names (SUI 2026-09-15)
# never tagged TP, then BE_HOURS closed at entry with 0 PnL.
ATR_FLOOR_PCT = 0.005  # max(atr, entry * floor); override ATR_FLOOR_PCT
SL_ATR_MULT = 1.0
TP1_ATR_MULT = 1.5
TP2_ATR_MULT = 2.5
ATR_PCT_MIN = 0.3  # percent
ATR_PCT_MAX = 6.0  # percent


def resolve_atr_floor_pct(floor_pct: float | None = None) -> float:
    """ATR floor as a fraction of entry. Env ATR_FLOOR_PCT wins when floor_pct is None."""
    if floor_pct is not None:
        try:
            return max(0.0, float(floor_pct))
        except (TypeError, ValueError):
            return float(ATR_FLOOR_PCT)
    raw = os.getenv("ATR_FLOOR_PCT")
    if raw is None or str(raw).strip() == "":
        return float(ATR_FLOOR_PCT)
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(ATR_FLOOR_PCT)


def compute_atr(
    df: pd.DataFrame | None,
    *,
    period: int = ATR_PERIOD,
    entry: float | None = None,
    floor_pct: float | None = None,
) -> float | None:
    """Mean(high-low).tail(period); optionally floor to entry*floor_pct.

    Returns None if df is insufficient. Matches divergent stream_manager.
    """
    floor = resolve_atr_floor_pct(floor_pct)
    if df is None or len(df) < 1:
        return None
    if "high" not in df.columns or "low" not in df.columns:
        return None
    try:
        atr = float((df["high"] - df["low"]).tail(int(period)).mean())
    except Exception:
        return None
    if atr != atr or atr <= 0:  # NaN / non-positive
        atr = 0.0
    if entry is not None and entry > 0 and floor > 0:
        atr = max(atr, float(entry) * floor)
    elif atr <= 0:
        return None
    return atr


def atr_pct(atr: float, entry: float) -> float:
    """ATR as percent of entry."""
    entry = float(entry)
    if entry <= 0:
        return 0.0
    return float(atr) / entry * 100.0


def atr_filter_ok(
    atr: float,
    entry: float,
    *,
    min_pct: float = ATR_PCT_MIN,
    max_pct: float = ATR_PCT_MAX,
) -> tuple[bool, str]:
    """Skip open if atr_pct < min or > max. Returns (ok, reason)."""
    pct = atr_pct(atr, entry)
    if pct < float(min_pct):
        return False, f"atr_pct_low:{pct:.3f}<{min_pct}"
    if pct > float(max_pct):
        return False, f"atr_pct_high:{pct:.3f}>{max_pct}"
    return True, "ok"


def levels_from_atr(
    entry: float,
    side: str,
    atr: float,
    *,
    sl_mult: float = SL_ATR_MULT,
    tp1_mult: float = TP1_ATR_MULT,
    tp2_mult: float = TP2_ATR_MULT,
) -> dict[str, float]:
    """Long: SL=entry-1*ATR, TP1=+1.5, TP2=+2.5; short mirrored."""
    entry = float(entry)
    atr = float(atr)
    s = str(side).lower().strip()
    is_long = s in {"long", "buy"}
    if is_long:
        sl = entry - atr * sl_mult
        tp1 = entry + atr * tp1_mult
        tp2 = entry + atr * tp2_mult
    else:
        sl = entry + atr * sl_mult
        tp1 = entry - atr * tp1_mult
        tp2 = entry - atr * tp2_mult
    return {
        "atr": atr,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr_pct": atr_pct(atr, entry),
    }


def compute_levels_from_df(
    entry: float,
    side: str,
    df: pd.DataFrame | None,
    *,
    period: int = ATR_PERIOD,
    floor_pct: float | None = None,
    sl_mult: float = SL_ATR_MULT,
    tp1_mult: float = TP1_ATR_MULT,
    tp2_mult: float = TP2_ATR_MULT,
) -> dict[str, float] | None:
    """Compute atr + SL/TP1/TP2 from OHLCV df. None if atr unavailable."""
    atr = compute_atr(df, period=period, entry=entry, floor_pct=floor_pct)
    if atr is None or atr <= 0:
        return None
    return levels_from_atr(
        entry, side, atr, sl_mult=sl_mult, tp1_mult=tp1_mult, tp2_mult=tp2_mult
    )


def levels_dict_for_position(levels: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize level fields for position top-level + meta."""
    out: dict[str, Any] = {}
    for key in ("atr", "sl", "tp1", "tp2", "atr_pct"):
        if key in levels and levels[key] is not None:
            try:
                out[key] = float(levels[key])
            except (TypeError, ValueError):
                pass
    return out
