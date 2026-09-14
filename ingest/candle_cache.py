"""In-memory OHLCV + mark cache for Bitget public WS / REST bootstrap."""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd

from ingest.bitget_ohlcv import OHLCV_COLUMNS

_LOCK = threading.RLock()
# (ccxt_symbol, timeframe) -> DataFrame
_CANDLES: dict[tuple[str, str], pd.DataFrame] = {}
# ccxt_symbol -> mark/last price
_MARKS: dict[str, float] = {}


def _key(symbol: str, timeframe: str) -> tuple[str, str]:
    return str(symbol).strip(), str(timeframe).strip()


def clear_all() -> None:
    with _LOCK:
        _CANDLES.clear()
        _MARKS.clear()


def set_ohlcv(symbol: str, timeframe: str, df: pd.DataFrame) -> None:
    """Replace cache for symbol/tf (REST bootstrap)."""
    if df is None or len(df) == 0:
        return
    out = df[list(OHLCV_COLUMNS)].astype(float).copy()
    if getattr(out.index, "tz", None) is None:
        out.index = pd.to_datetime(out.index, utc=True)
    else:
        out.index = out.index.tz_convert("UTC")
    out.index.name = "timestamp"
    k = _key(symbol, timeframe)
    with _LOCK:
        _CANDLES[k] = out
        try:
            _MARKS[str(symbol)] = float(out["close"].iloc[-1])
        except Exception:
            pass


def get_cached_ohlcv(
    symbol: str,
    timeframe: str,
    *,
    min_bars: int = 1,
) -> pd.DataFrame | None:
    k = _key(symbol, timeframe)
    with _LOCK:
        df = _CANDLES.get(k)
        if df is None or len(df) < min_bars:
            return None
        return df.copy()


def get_cached_mark(symbol: str) -> float | None:
    with _LOCK:
        v = _MARKS.get(str(symbol))
        if v is None:
            return None
        try:
            px = float(v)
        except (TypeError, ValueError):
            return None
        return px if px > 0 else None


def set_mark(symbol: str, price: float) -> None:
    try:
        px = float(price)
    except (TypeError, ValueError):
        return
    if px <= 0:
        return
    with _LOCK:
        _MARKS[str(symbol)] = px


def apply_candle_update(
    symbol: str,
    timeframe: str,
    *,
    ts_ms: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> bool:
    """Upsert forming candle. True when a new bar period starts (prior bar closed)."""
    ts = pd.to_datetime(int(ts_ms), unit="ms", utc=True)
    row = {
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
    }
    k = _key(symbol, timeframe)
    bar_closed = False
    with _LOCK:
        df = _CANDLES.get(k)
        if df is None or len(df) == 0:
            df = pd.DataFrame([row], index=pd.DatetimeIndex([ts], name="timestamp"))
            _CANDLES[k] = df
        else:
            last_ts = df.index[-1]
            if ts > last_ts:
                bar_closed = True
                df = pd.concat(
                    [
                        df,
                        pd.DataFrame(
                            [row], index=pd.DatetimeIndex([ts], name="timestamp")
                        ),
                    ]
                )
                if len(df) > 500:
                    df = df.iloc[-500:]
                _CANDLES[k] = df
            elif ts == last_ts:
                for col, val in row.items():
                    df.iloc[-1, df.columns.get_loc(col)] = val
                _CANDLES[k] = df
        _MARKS[str(symbol)] = float(close)
    return bar_closed


def cache_stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "candle_keys": len(_CANDLES),
            "marks": len(_MARKS),
        }
