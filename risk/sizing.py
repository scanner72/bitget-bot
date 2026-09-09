"""Position notional from risk distance to stop-loss."""

from __future__ import annotations


def notional_from_risk(
    entry: float,
    sl: float,
    *,
    risk_usd: float,
    max_notional: float,
    min_notional: float = 10.0,
) -> float:
    """Target notional so approx loss at SL equals risk_usd, clamped to [min, max].

    dist = |entry-sl|/entry (fractional distance to stop).
    size = risk_usd / dist when dist > 0; otherwise max_notional.
    """
    dist = abs(float(entry) - float(sl)) / float(entry)
    if dist <= 1e-12:
        return float(max_notional)
    size = float(risk_usd) / dist
    return max(float(min_notional), min(float(max_notional), size))
