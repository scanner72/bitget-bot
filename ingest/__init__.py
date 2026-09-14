"""Bitget OHLCV + swap universe ingest (public ccxt). NO SPOT."""

from ingest.bitget_ohlcv import (
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    fetch_ohlcv,
    get_mark_price,
    get_ohlcv,
    get_shared_exchange,
    set_shared_exchange,
)
from ingest.universe import (
    UniverseCache,
    UniverseSnapshot,
    fetch_universe,
    resolve_scan_symbols,
)

__all__ = [
    "DEFAULT_SYMBOL",
    "DEFAULT_TIMEFRAME",
    "UniverseCache",
    "UniverseSnapshot",
    "fetch_ohlcv",
    "fetch_universe",
    "get_mark_price",
    "get_ohlcv",
    "get_shared_exchange",
    "resolve_scan_symbols",
    "set_shared_exchange",
]
