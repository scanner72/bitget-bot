"""Signal engine — port of divergent bot_app/core/signal_engine.py"""

import pandas as pd
from signals.divergence.detector import RSIDivergenceDetector


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
        return {
            "type": cross["type"],
            "bar_index": cross["bar_index"],
            "price": float(df.iloc[-1]["close"]),
            "level_price": float(cross["level_price"]),
            "rsi": float(results.iloc[-1]["rsi"]),
            "df": df,
            "results": results,
        }, has_zones

    # Priority 2: New Divergence
    lookback_right = config["lookback_right"]
    for _, row in results.tail(lookback_right + 2).iloc[::-1].iterrows():
        if row["bullish_divergence"]:
            return {
                "type": "BULLISH_DIV",
                "bar_index": int(row["bar_index"]),
                "price": float(row["close"]),
                "level_price": float(row["low"]),
                "rsi": float(row["rsi"]),
                "df": df,
                "results": results,
            }, has_zones
        if row["bearish_divergence"]:
            return {
                "type": "BEARISH_DIV",
                "bar_index": int(row["bar_index"]),
                "price": float(row["close"]),
                "level_price": float(row["high"]),
                "rsi": float(row["rsi"]),
                "df": df,
                "results": results,
            }, has_zones

    return None, has_zones


def get_latest_signal(df: pd.DataFrame, pair_config: dict) -> dict | None:
    """Thin wrapper around run_full_detection for callers that don't need zone info."""
    signal, _ = run_full_detection(df, pair_config)
    return signal
