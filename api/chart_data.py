"""Chart payload for dashboard clicks: LIVE Bitget candles + RSI/zones + trade overlay."""

from __future__ import annotations

import math
import os
from typing import Any

import pandas as pd

from exec.hub_view import bitget_to_ccxt
from ingest.bitget_ohlcv import get_ohlcv
from signals.config import COLOR_BEARISH, COLOR_BULLISH, LINE_EXTENSION_BARS, QTY_DIVERGENCE_ZONES
from signals.divergence.detector import RSIDivergenceDetector

C_BULL = COLOR_BULLISH
C_BEAR = COLOR_BEARISH


def default_timeframe() -> str:
    return (os.getenv("TIMEFRAME") or "15m").strip() or "15m"


def normalize_chart_symbol(symbol: str) -> str:
    s = (symbol or "").strip()
    if not s:
        return s
    if "/" in s:
        return s
    return bitget_to_ccxt(s)


def _unix_ts(val: Any) -> int | None:
    try:
        ts = pd.Timestamp(val)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp())


def _build_zones(df_reset: pd.DataFrame, results: pd.DataFrame) -> list[dict[str, Any]]:
    if results is None or results.empty or df_reset is None or df_reset.empty:
        return []
    qty_zones = int(QTY_DIVERGENCE_ZONES)
    line_ext = int(LINE_EXTENSION_BARS)
    n = len(df_reset)
    try:
        bull_divs = set(results.loc[results["bullish_divergence"], "bar_index"].astype(int))
        bear_divs = set(results.loc[results["bearish_divergence"], "bar_index"].astype(int))
    except Exception:
        return []

    bar_dur = 900
    if n >= 2:
        t0 = _unix_ts(df_reset.iloc[0]["timestamp"])
        t1 = _unix_ts(df_reset.iloc[1]["timestamp"])
        if t0 is not None and t1 is not None:
            bar_dur = max(60, t1 - t0)

    bull_zones: list[dict[str, Any]] = []
    bear_zones: list[dict[str, Any]] = []
    for bar_i in range(n):
        h = float(df_reset.iloc[bar_i]["high"])
        l = float(df_reset.iloc[bar_i]["low"])
        for z in bull_zones:
            if "broken_bar" not in z and h <= z["level"]:
                z["broken_bar"] = bar_i
        for z in bear_zones:
            if "broken_bar" not in z and l >= z["level"]:
                z["broken_bar"] = bar_i
        if bar_i in bull_divs:
            bull_zones.append(
                {"created_bar": max(0, bar_i - 5), "level": float(df_reset.iloc[bar_i]["low"])}
            )
            if len(bull_zones) > qty_zones:
                bull_zones.pop(0)
        if bar_i in bear_divs:
            bear_zones.append(
                {"created_bar": max(0, bar_i - 5), "level": float(df_reset.iloc[bar_i]["high"])}
            )
            if len(bear_zones) > qty_zones:
                bear_zones.pop(0)

    last_ts = _unix_ts(df_reset.iloc[-1]["timestamp"])
    if last_ts is None:
        return []
    out: list[dict[str, Any]] = []
    for z in bull_zones + bear_zones:
        is_bull = z in bull_zones
        is_broken = "broken_bar" in z
        t_start = _unix_ts(df_reset.iloc[z["created_bar"]]["timestamp"])
        if is_broken:
            t_end = _unix_ts(df_reset.iloc[z["broken_bar"]]["timestamp"])
        else:
            t_end = last_ts + line_ext * bar_dur
        if t_start is None or t_end is None:
            continue
        out.append(
            {
                "time_start": t_start,
                "time_end": t_end,
                "level": z["level"],
                "is_bull": is_bull,
                "is_broken": is_broken,
                "color": C_BULL if is_bull else C_BEAR,
            }
        )
    return out


def build_chart_payload(
    symbol: str,
    timeframe: str | None = None,
    limit: int = 400,
) -> dict[str, Any]:
    """LIVE public Bitget OHLCV + RSI/divergence overlay for lightweight-charts."""
    sym = normalize_chart_symbol(symbol)
    tf = (timeframe or default_timeframe()).strip() or default_timeframe()
    lim = max(50, min(int(limit or 400), 1000))
    if not sym:
        return {"status": "empty", "candles": [], "error": "symbol required"}

    df = get_ohlcv(symbol=sym, timeframe=tf, limit=lim, prefer_cache=True)
    if df is None or len(df) == 0:
        return {"status": "empty", "candles": [], "symbol": sym, "timeframe": tf}

    df_reset = df.reset_index()
    if "timestamp" not in df_reset.columns:
        df_reset = df_reset.rename(columns={df_reset.columns[0]: "timestamp"})

    config = {
        "rsi_length": 14,
        "rsi_mom_period": 10,
        "lookback_left": 5,
        "lookback_right": 5,
        "min_bars_in_range": 5,
        "max_bars_in_range": 50,
    }
    detector = RSIDivergenceDetector(df_reset.copy(), config=config)
    indicators_ok = bool(detector.calculate_indicators())
    results = detector.detect_divergences() if indicators_ok else pd.DataFrame()

    candles: list[dict[str, Any]] = []
    rsi_series: list[dict[str, Any]] = []
    for i, row in df_reset.iterrows():
        ts = _unix_ts(row["timestamp"])
        if ts is None:
            continue
        candles.append(
            {
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
        if indicators_ok and detector.rsi_values is not None and i < len(detector.rsi_values):
            v = detector.rsi_values[i]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(fv):
                    rsi_series.append({"time": ts, "value": round(fv, 2)})

    markers: list[dict[str, Any]] = []
    if results is not None and not results.empty:
        for _, sig in results.iterrows():
            try:
                bi = int(sig["bar_index"])
            except (TypeError, ValueError, KeyError):
                continue
            if bi < 0 or bi >= len(df_reset):
                continue
            t = _unix_ts(df_reset.iloc[bi]["timestamp"])
            if t is None:
                continue
            if bool(sig.get("bullish_divergence")):
                markers.append(
                    {
                        "time": t,
                        "position": "belowBar",
                        "color": C_BULL,
                        "shape": "arrowUp",
                        "text": "Bull",
                    }
                )
            if bool(sig.get("bearish_divergence")):
                markers.append(
                    {
                        "time": t,
                        "position": "aboveBar",
                        "color": C_BEAR,
                        "shape": "arrowDown",
                        "text": "Bear",
                    }
                )

    zones = _build_zones(df_reset, results) if indicators_ok else []
    return {
        "status": "ok",
        "symbol": sym,
        "timeframe": tf,
        "candles": candles,
        "rsi": rsi_series,
        "markers": markers,
        "zones": zones,
        "indicators_ok": indicators_ok,
        "total": len(candles),
        "source": "bitget_live",
    }
