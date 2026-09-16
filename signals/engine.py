"""Signal engine — port of divergent bot_app/core/signal_engine.py"""

from __future__ import annotations

from typing import Any

import pandas as pd
from signals.divergence.detector import RSIDivergenceDetector


def bar_ts_iso(df: pd.DataFrame, bar_index: int | None) -> str | None:
    """UTC candle time at a positional bar_index. None if the frame has no clock."""
    if bar_index is None or df is None or df.empty:
        return None
    try:
        i = int(bar_index)
    except (TypeError, ValueError):
        return None
    if i < 0 or i >= len(df):
        return None
    raw: Any = None
    if isinstance(df.index, pd.DatetimeIndex):
        raw = df.index[i]
    else:
        for col in ("timestamp", "ts", "time"):
            if col in df.columns:
                raw = df.iloc[i][col]
                break
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    ts = pd.Timestamp(raw)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _attach_bar_ts(signal: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    signal["bar_ts"] = bar_ts_iso(df, signal.get("bar_index"))
    return signal


def run_full_detection(df: pd.DataFrame, pair_config: dict) -> tuple[dict | None, bool]:
    """
    Run detection and return (signal_or_None, has_active_zones).
    Unlike get_latest_signal, always reports zone presence even when no signal fires.
    """
    config = {
        "rsi_length":        pair_config.get("rsi_length", 14),
        "rsi_mom_period":    pair_config.get("mom_period", 10),
        "lookback_left":     pair_config.get("lookback_left", 5),
        "lookback_right":    pair_config.get("lookback_right", 5),
        "min_bars_in_range": pair_config.get("min_bars", 5),
        "max_bars_in_range": pair_config.get("max_bars", 50),
    }
    detector = RSIDivergenceDetector(df.reset_index(drop=True), config=config)
    if not detector.calculate_indicators():
        return None, False

    results = detector.detect_divergences()
    if results.empty:
        return None, False

    has_zones = bool(
        results["bullish_divergence"].any() or results["bearish_divergence"].any()
    )

    # Priority 1: Level Crossings
    crossings = detector.detect_crossings(results)
    if crossings:
        cross = crossings[0]
        return _attach_bar_ts(
            {
                "type": cross["type"],
                "bar_index": cross["bar_index"],
                "price": float(df.iloc[-1]["close"]),
                "level_price": float(cross["level_price"]),
                "rsi": float(results.iloc[-1]["rsi"]),
                "df": df,
                "results": results,
            },
            df,
        ), has_zones

    # Priority 2: New Divergence
    lookback_right = config["lookback_right"]
    for _, row in results.tail(lookback_right + 2).iloc[::-1].iterrows():
        if row["bullish_divergence"]:
            return _attach_bar_ts(
                {
                    "type": "BULLISH_DIV",
                    "bar_index": int(row["bar_index"]),
                    "price": float(row["close"]),
                    "level_price": float(row["low"]),
                    "rsi": float(row["rsi"]),
                    "df": df,
                    "results": results,
                },
                df,
            ), has_zones
        if row["bearish_divergence"]:
            return _attach_bar_ts(
                {
                    "type": "BEARISH_DIV",
                    "bar_index": int(row["bar_index"]),
                    "price": float(row["close"]),
                    "level_price": float(row["high"]),
                    "rsi": float(row["rsi"]),
                    "df": df,
                    "results": results,
                },
                df,
            ), has_zones

    return None, has_zones


def get_latest_signal(df: pd.DataFrame, pair_config: dict) -> dict | None:
    """Thin wrapper around run_full_detection for callers that don't need zone info."""
    signal, _ = run_full_detection(df, pair_config)
    return signal
