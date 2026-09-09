"""Bitget public OHLCV ingest via ccxt (USDT-M swap). No API keys required.

NO SPOT — defaultType=swap only. Crypto USDT-M and rToken/RWA perps share this path.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# ccxt unified symbol for Bitget USDT-M perpetual
DEFAULT_SYMBOL = "BTC/USDT:USDT"
DEFAULT_TIMEFRAME = "15m"
OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

_SHARED_EXCHANGE: Any | None = None


def get_shared_exchange() -> Any:
    """Process-wide Bitget swap client (rate-limit friendly reuse)."""
    global _SHARED_EXCHANGE
    if _SHARED_EXCHANGE is None:
        from ingest.universe import get_bitget_swap_exchange

        _SHARED_EXCHANGE = get_bitget_swap_exchange()
    return _SHARED_EXCHANGE


def set_shared_exchange(exchange: Any | None) -> None:
    """Inject a shared client (e.g. from universe scan) for the desk loop."""
    global _SHARED_EXCHANGE
    _SHARED_EXCHANGE = exchange


def fetch_ohlcv(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = 200,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    password: Optional[str] = None,
    exchange: Any | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV from Bitget public API (swap / USDT-M) via ccxt.

    Returns a DataFrame with DatetimeIndex (UTC) and columns:
    open, high, low, close, volume — schema expected by signals.engine.

    Public market data does not need credentials. Keys are accepted for
    forward compatibility but are unused for this paper/smoke path.
    Symbol format: ccxt unified, e.g. BTC/USDT:USDT (perp), ETH/USDT:USDT,
    AAPL/USDT:USDT (rToken/stock perp). Spot symbols are not supported.
    Pass ``exchange`` (or use set_shared_exchange) to reuse one client.
    """
    # Public OHLCV: intentionally do not load .env keys for this step
    _ = (api_key, api_secret, password)

    ex = exchange if exchange is not None else get_shared_exchange()
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        raise RuntimeError(f"Empty OHLCV from Bitget for {symbol} {timeframe}")

    df = pd.DataFrame(raw, columns=["timestamp", *OHLCV_COLUMNS])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[list(OHLCV_COLUMNS)].astype(float)
    df.index.name = "timestamp"
    return df


def fetch_mark_price(
    symbol: str,
    exchange: Any | None = None,
) -> float:
    """Fetch mark or last price for a Bitget USDT-M swap via ccxt ticker.

    Prefers mark / markPrice, then last / close. Reuses get_shared_exchange()
    when ``exchange`` is omitted. Raises RuntimeError if no positive price.
    """
    ex = exchange if exchange is not None else get_shared_exchange()
    ticker = ex.fetch_ticker(symbol)
    info = ticker.get("info") or {}
    candidates = (
        ticker.get("mark"),
        ticker.get("last"),
        ticker.get("close"),
        info.get("markPrice"),
        info.get("markPx"),
        info.get("lastPr"),
        info.get("last"),
        info.get("close"),
    )
    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            px = float(raw)
        except (TypeError, ValueError):
            continue
        if px > 0:
            return px
    raise RuntimeError(f"No mark/last price for {symbol!r}")

