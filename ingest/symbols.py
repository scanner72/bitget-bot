"""Map ccxt unified Bitget swap symbols to native id / human display.

Internal trading keys stay ccxt (e.g. CRCL/USDT:USDT). API/dashboard can
expose Bitget-native id and a short display label without changing exec paths.
"""

from __future__ import annotations


def to_bitget_id(ccxt_symbol: str) -> str:
    """ccxt -> Bitget native id: CRCL/USDT:USDT -> CRCLUSDT (strip /, :settle)."""
    s = (ccxt_symbol or "").strip().upper()
    if not s:
        return ""
    if ":" in s:
        s = s.split(":", 1)[0]
    return s.replace("/", "").replace("-", "")


def to_display(ccxt_symbol: str) -> str:
    """ccxt -> human label: CRCL/USDT:USDT -> CRCL-USDT Perp."""
    s = (ccxt_symbol or "").strip().upper()
    if not s:
        return ""
    market = s.split(":", 1)[0] if ":" in s else s
    if "/" in market:
        base, quote = market.split("/", 1)
        base, quote = base.strip(), quote.strip()
        if base and quote:
            return f"{base}-{quote} Perp"
    compact = market.replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC"):
        if compact.endswith(quote) and len(compact) > len(quote):
            return f"{compact[: -len(quote)]}-{quote} Perp"
    return f"{compact or s} Perp"


def enrich_symbol_fields(row: dict) -> dict:
    """Copy row; keep symbol (ccxt), add symbol_id + symbol_display when present."""
    out = dict(row)
    sym = out.get("symbol")
    if sym is None or str(sym).strip() == "":
        return out
    text = str(sym)
    out["symbol"] = text  # keep ccxt internal form
    out["symbol_id"] = to_bitget_id(text)
    out["symbol_display"] = to_display(text)
    return out
