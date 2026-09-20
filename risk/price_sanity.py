"""Public-vs-Demo price bands for open (router) and exit (tick/candle) paths.

Thin Demo stock/rToken books drift from the public feed. BZ (2026-09-18) filled
at Demo 103.52 while public was ~99; a later public ~99 tick booked a phantom
paper SL. Compare exit marks to the position entry (Demo fill), not only to
the public candle — those two can agree with each other and still be on the
wrong scale.
"""
from __future__ import annotations

import os


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def mark_sanity_dev_pct(symbol: str) -> float:
    """Max allowed % deviation for an exit quote vs a trusted ref. 0 disables.

    Default 2.5%: LTC Demo entry 59.78 vs public close 57.99 (~3%) fabricated
    paper −15 while hub exec_pnl was ~−0.26. Hub TPSL stays the real exit.
    """
    base = max(0.0, _env_float("MARK_SANITY_MAX_DEV_PCT", 2.5))
    try:
        from ingest.universe import is_rtoken_symbol

        if is_rtoken_symbol(symbol):
            return max(0.0, _env_float("RTOKEN_MARK_SANITY_MAX_DEV_PCT", base))
    except Exception:  # noqa: BLE001
        return base
    return base


def quote_is_sane(symbol: str, last: float, ref: float | None) -> bool:
    """True unless last diverges from ref (candle close or entry) beyond the band."""
    band = mark_sanity_dev_pct(symbol)
    if band <= 0 or ref is None:
        return True
    try:
        ref_f = float(ref)
        px = float(last)
    except (TypeError, ValueError):
        return True
    if ref_f <= 0 or px <= 0:
        return True
    dev = abs(px / ref_f - 1.0) * 100.0
    return dev <= band


def pos_entry_price(pos: dict) -> float | None:
    try:
        entry = float(pos.get("entry_price") or 0)
    except (TypeError, ValueError):
        return None
    return entry if entry > 0 else None
