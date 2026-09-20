"""BTC regime / momentum / EMA50 filters — ported from divergent runner.check_btc_filters."""

from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv

ROOT = __file__
_CACHE: dict[str, Any] = {
    "regime": ("neutral", 0.0),
    "mom": (0.0, 0.0),
    "ema50": ("unknown", 0.0),
}
_TTL = 300.0


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip()


def _btc_symbol() -> str:
    return _env_str("BTC_FILTER_SYMBOL", "BTC/USDT:USDT")


def _ema(series, period: int) -> float | None:
    if series is None or len(series) < period:
        return None
    # Simple EMA over close
    k = 2.0 / (period + 1)
    val = float(series.iloc[0])
    for x in series.iloc[1:]:
        val = float(x) * k + val * (1.0 - k)
    return val


def _get_btc_regime() -> str:
    now = time.time()
    val, ts = _CACHE["regime"]
    if now - ts < _TTL:
        return str(val)
    try:
        from ingest.bitget_ohlcv import fetch_ohlcv

        tf = _env_str("BTC_REGIME_TF", "4h")
        df = fetch_ohlcv(symbol=_btc_symbol(), timeframe=tf, limit=220)
        ema = _ema(df["close"], 200)
        last = float(df["close"].iloc[-1])
        if ema is None:
            regime = "neutral"
        elif last >= ema:
            regime = "bullish"
        else:
            regime = "bearish"
    except Exception:
        regime = "neutral"
    _CACHE["regime"] = (regime, now)
    return regime


def _get_btc_momentum() -> float:
    now = time.time()
    val, ts = _CACHE["mom"]
    if now - ts < _TTL:
        return float(val)
    try:
        from ingest.bitget_ohlcv import fetch_ohlcv

        hours = max(1.0, _env_float("BTC_MOMENTUM_HOURS", 4.0))
        # Use 1h bars for momentum window
        bars = max(2, int(hours) + 1)
        df = fetch_ohlcv(symbol=_btc_symbol(), timeframe="1h", limit=max(bars + 2, 10))
        n = min(len(df) - 1, int(hours))
        if n < 1:
            chg = 0.0
        else:
            a = float(df["close"].iloc[-(n + 1)])
            b = float(df["close"].iloc[-1])
            chg = ((b - a) / a * 100.0) if a else 0.0
    except Exception:
        chg = 0.0
    _CACHE["mom"] = (chg, now)
    return float(chg)


def _get_btc_ema50_state() -> str:
    now = time.time()
    val, ts = _CACHE["ema50"]
    if now - ts < _TTL:
        return str(val)
    try:
        from ingest.bitget_ohlcv import fetch_ohlcv

        df = fetch_ohlcv(symbol=_btc_symbol(), timeframe="1h", limit=80)
        ema = _ema(df["close"], 50)
        last = float(df["close"].iloc[-1])
        if ema is None:
            state = "unknown"
        elif last >= ema:
            state = "above"
        else:
            state = "below"
    except Exception:
        state = "unknown"
    _CACHE["ema50"] = (state, now)
    return state


def check_btc_filters(direction: str, symbol: str = "") -> tuple[bool, str]:
    """Return (allowed, reason). True = trade OK.

    Regime policy (auto side switch):
    - short only when BTC regime is bearish (not neutral/bullish)
    - long blocked when BTC regime is bearish
    Optional env BTC_SHORT_ONLY_BEARISH=0 restores old symmetric veto
    (block short only in bullish, allow short in neutral).
    """
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if not _env_bool("BTC_FILTERS_ENABLED", True):
        return True, "ok"

    side = str(direction or "").lower().strip()
    if side in {"buy"}:
        side = "long"
    if side in {"sell"}:
        side = "short"
    if side not in {"long", "short"}:
        return True, "ok"

    if _env_bool("BTC_REGIME_ENABLED", True):
        try:
            regime = _get_btc_regime()
            strict_short = _env_bool("BTC_SHORT_ONLY_BEARISH", True)
            if side == "long" and regime == "bearish":
                return False, "btc_regime:bearish_block_long"
            if side == "short":
                if strict_short:
                    # Option 2: shorts only in confirmed bearish BTC
                    if regime != "bearish":
                        return False, f"btc_regime:{regime}_block_short_strict"
                elif regime == "bullish":
                    return False, "btc_regime:bullish_block_short"
        except Exception:
            # Fail-closed for shorts if regime cannot be read
            if side == "short" and _env_bool("BTC_SHORT_ONLY_BEARISH", True):
                return False, "btc_regime:unknown_block_short_strict"

    # Momentum
    mom_thr = _env_float("BTC_MOMENTUM_PCT", 1.2)
    if mom_thr > 0:
        try:
            mom = _get_btc_momentum()
            if side == "short" and mom >= mom_thr:
                return False, f"btc_momentum:rally_{mom:.1f}pct"
            if side == "long" and mom <= -mom_thr:
                return False, f"btc_momentum:dump_{mom:.1f}pct"
        except Exception:
            pass

    # EMA50
    if _env_bool("BTC_EMA50_FILTER_ENABLED", False):
        try:
            state = _get_btc_ema50_state()
            if side == "short" and state == "above":
                return False, "btc_ema50:above_block_short"
            if side == "long" and state == "below":
                return False, "btc_ema50:below_block_long"
        except Exception:
            pass

    _ = symbol  # reserved for per-symbol overrides
    return True, "ok"