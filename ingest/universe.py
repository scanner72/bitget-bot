"""Bitget USDT-M swap universe: crypto vs rToken/RWA perps (NO SPOT).

Heuristic for rToken / stock / RWA perps
---------------------------------------
Bitget swap market `info.isRwa` is the primary signal:
  - `isRwa == YES`  -> rToken / RWA basket (US stock perps like AAPL/USDT:USDT,
    ETFs, indices, tokenized equities, commodities Bitget labels as RWA)
  - `isRwa == NO`   -> crypto USDT-M linear swaps

Fallbacks when `isRwa` is missing/unknown:
  - base ends with `STOCK` (e.g. STXSTOCK, NOKSTOCK)
  - base in a curated US-equity / ETF ticker set (AAPL, NVDA, TSLA, ...)

Spot markets are never loaded (`defaultType=swap` only; `spot` filtered out).
Inverse / non-USDT-settle contracts are excluded.

Env
---
  SCAN_MODE          fixed|auto (default auto)
  SCAN_CRYPTO_TOP    N (default 20) — top crypto by 24h quoteVolume
  SCAN_RTOKEN_TOP    M (default 20) — top rToken/RWA by 24h quoteVolume
  SCAN_REFRESH_SEC   refresh interval seconds (default 300); 0 = every pass
  SYMBOLS            used when SCAN_MODE=fixed (override list)
  OHLCV_LIMIT        optional; desk may use 200 for faster auto scans
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# Curated US equity / ETF / index bases seen on Bitget stock-style perps.
# Used only as fallback when info.isRwa is absent.
KNOWN_EQUITY_BASES: frozenset[str] = frozenset(
    {
        "AAPL",
        "NVDA",
        "TSLA",
        "AMZN",
        "META",
        "GOOGL",
        "GOOG",
        "MSFT",
        "NFLX",
        "COIN",
        "MSTR",
        "HOOD",
        "AMD",
        "INTC",
        "IBM",
        "BABA",
        "PLTR",
        "GME",
        "AMC",
        "NIO",
        "BABA",
        "ORCL",
        "AVGO",
        "MU",
        "QCOM",
        "ARM",
        "ASML",
        "TSM",
        "SMCI",
        "CRWD",
        "SNOW",
        "UBER",
        "PYPL",
        "SHOP",
        "QQQ",
        "SPY",
        "IWM",
        "DIA",
        "NDX100",
        "SP500",
        "CRCL",
        "MCD",
        "COST",
        "WMT",
        "BA",
        "DIS",
        "V",
        "JPM",
        "GS",
        "BAC",
        "XOM",
        "KO",
        "PEP",
        "NKE",
        "LLY",
        "UNH",
        "MRK",
        "PDD",
        "JD",
        "FUTU",
        "RDDT",
        "APP",
        "GE",
        "MRVL",
        "CSCO",
        "SOFTBANK",
        "TENCENT",
        "XIAOMI",
        "SAMSUNG",
        "SONY",
        "OPENAI",
        "ANTHROPIC",
    }
)


@dataclass
class UniverseSnapshot:
    crypto: list[dict[str, Any]] = field(default_factory=list)
    rtoken: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: float = 0.0
    crypto_total: int = 0
    rtoken_total: int = 0

    @property
    def symbols(self) -> list[str]:
        """Union of top crypto + top rToken symbols (deduped, crypto first)."""
        seen: set[str] = set()
        out: list[str] = []
        for row in self.crypto + self.rtoken:
            sym = row["symbol"]
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
        return out


def get_bitget_swap_exchange(existing: Any | None = None) -> Any:
    """Reuse one ccxt Bitget swap client (rate-limit friendly)."""
    if existing is not None:
        return existing
    import ccxt

    return ccxt.bitget(
        {
            "enableRateLimit": True,
            "timeout": 10_000,  # ms — avoid hung UI when Bitget public API stalls
            "options": {"defaultType": "swap"},
        }
    )


def _is_usdt_linear_swap(market: dict[str, Any]) -> bool:
    if not market.get("swap"):
        return False
    if market.get("spot"):
        return False
    if market.get("active") is False:
        return False
    if not market.get("linear", True):
        return False
    settle = (market.get("settle") or market.get("quote") or "").upper()
    quote = (market.get("quote") or "").upper()
    if settle and settle != "USDT":
        return False
    if quote and quote != "USDT":
        return False
    # Unified symbol must look like BASE/USDT:USDT (perp), never spot BASE/USDT
    sym = market.get("symbol") or ""
    if ":" not in sym:
        return False
    return True


def is_rtoken_perp(market: dict[str, Any]) -> bool:
    """True if market is Bitget RWA / rToken / stock-style perp.

    Prefer `info.isRwa`; fall back to STOCK suffix / known equity bases.
    """
    info = market.get("info") or {}
    raw = info.get("isRwa")
    if raw is not None:
        s = str(raw).strip().upper()
        if s in {"YES", "TRUE", "1", "Y"}:
            return True
        if s in {"NO", "FALSE", "0", "N"}:
            return False
    base = (market.get("base") or "").upper()
    if base.endswith("STOCK"):
        return True
    if base in KNOWN_EQUITY_BASES:
        return True
    # Bitget sometimes embeds category-ish fields
    for key in ("category", "productType", "businessType", "symbolAlias"):
        val = str(info.get(key) or "").lower()
        if any(tok in val for tok in ("stock", "rtoken", "rwa", "equity", "share")):
            return True
    return False


def _quote_volume(ticker: dict[str, Any] | None) -> float:
    if not ticker:
        return 0.0
    qv = ticker.get("quoteVolume")
    if qv is not None:
        try:
            return float(qv)
        except (TypeError, ValueError):
            pass
    info = ticker.get("info") or {}
    for key in ("quoteVolume", "usdtVolume", "quoteVol", "turnoverUsdt"):
        if info.get(key) is not None:
            try:
                return float(info[key])
            except (TypeError, ValueError):
                continue
    # last resort: baseVolume * last
    try:
        bv = float(ticker.get("baseVolume") or 0)
        last = float(ticker.get("last") or ticker.get("close") or 0)
        return bv * last
    except (TypeError, ValueError):
        return 0.0


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def load_scan_env() -> dict[str, Any]:
    mode = (os.getenv("SCAN_MODE", "auto") or "auto").strip().lower()
    if mode not in {"fixed", "auto"}:
        mode = "auto"
    return {
        "mode": mode,
        "crypto_top": max(0, _env_int("SCAN_CRYPTO_TOP", 20)),
        "rtoken_top": max(0, _env_int("SCAN_RTOKEN_TOP", 20)),
        "refresh_sec": max(0.0, _env_float("SCAN_REFRESH_SEC", 300.0)),
    }


def partition_swap_markets(
    markets: dict[str, Any],
    tickers: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split USDT-M linear swaps into (crypto, rtoken) rows ranked by quoteVolume."""
    tickers = tickers or {}
    crypto_rows: list[dict[str, Any]] = []
    rtoken_rows: list[dict[str, Any]] = []
    for market in markets.values():
        if not _is_usdt_linear_swap(market):
            continue
        sym = market["symbol"]
        qv = _quote_volume(tickers.get(sym))
        row = {
            "symbol": sym,
            "base": (market.get("base") or "").upper(),
            "quote_volume": qv,
            "is_rtoken": is_rtoken_perp(market),
            "is_rwa": (market.get("info") or {}).get("isRwa"),
        }
        if row["is_rtoken"]:
            rtoken_rows.append(row)
        else:
            crypto_rows.append(row)
    crypto_rows.sort(key=lambda r: r["quote_volume"], reverse=True)
    rtoken_rows.sort(key=lambda r: r["quote_volume"], reverse=True)
    return crypto_rows, rtoken_rows


def fetch_universe(
    exchange: Any | None = None,
    *,
    crypto_top: int | None = None,
    rtoken_top: int | None = None,
    sleep_sec: float = 0.05,
) -> UniverseSnapshot:
    """Load Bitget swap markets + tickers; return top crypto and rToken baskets.

    Reuses one exchange client. Small sleep between load_markets and fetch_tickers
    is optional rate-limit padding (enableRateLimit already on).
    """
    env = load_scan_env()
    n_crypto = env["crypto_top"] if crypto_top is None else max(0, int(crypto_top))
    n_rtoken = env["rtoken_top"] if rtoken_top is None else max(0, int(rtoken_top))

    ex = get_bitget_swap_exchange(exchange)
    markets = ex.load_markets(reload=True)
    if sleep_sec > 0:
        time.sleep(sleep_sec)
    tickers = ex.fetch_tickers()
    crypto_all, rtoken_all = partition_swap_markets(markets, tickers)
    snap = UniverseSnapshot(
        crypto=crypto_all[:n_crypto],
        rtoken=rtoken_all[:n_rtoken],
        fetched_at=time.time(),
        crypto_total=len(crypto_all),
        rtoken_total=len(rtoken_all),
    )
    return snap


class UniverseCache:
    """Refresh tops every SCAN_REFRESH_SEC (0 => every call)."""

    def __init__(self, exchange: Any | None = None) -> None:
        self.exchange = get_bitget_swap_exchange(exchange)
        self._snap: UniverseSnapshot | None = None

    def get(self, *, force: bool = False) -> UniverseSnapshot:
        env = load_scan_env()
        refresh = float(env["refresh_sec"])
        now = time.time()
        if (
            not force
            and self._snap is not None
            and refresh > 0
            and (now - self._snap.fetched_at) < refresh
        ):
            return self._snap
        self._snap = fetch_universe(self.exchange)
        return self._snap


def resolve_scan_symbols(
    fixed_symbols: list[str],
    *,
    cache: UniverseCache | None = None,
    force_refresh: bool = False,
) -> tuple[list[str], str, UniverseSnapshot | None]:
    """Return (symbols, mode, snapshot|None).

    SCAN_MODE=fixed -> use `fixed_symbols` (from SYMBOLS env).
    SCAN_MODE=auto  -> union of top crypto + top rToken (refreshed per cache).
    """
    env = load_scan_env()
    mode = env["mode"]
    if mode == "fixed":
        return list(fixed_symbols), mode, None
    cache = cache or UniverseCache()
    snap = cache.get(force=force_refresh)
    return snap.symbols, mode, snap


__all__ = [
    "KNOWN_EQUITY_BASES",
    "UniverseCache",
    "UniverseSnapshot",
    "fetch_universe",
    "get_bitget_swap_exchange",
    "is_rtoken_perp",
    "load_scan_env",
    "partition_swap_markets",
    "resolve_scan_symbols",
]
