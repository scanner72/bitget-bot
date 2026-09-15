"""Bitget Demo UTA tradable symbols (subset of live public contracts).

Public / live ``/api/v3/market/instruments`` lists hundreds of USDT-FUTURES.
Demo (paptrading=1) returns a much smaller catalog. Scanner uses live candles;
orders that hit missing Demo pairs fail with Bitget 25100.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from exec.bitget_hub import ccxt_to_bitget_symbol


def _exec_mode() -> str:
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode in {"hub_demo", "demo"}:
        return "hub_demo"
    if mode in {"live", "hub_live"}:
        return "live"
    return "paper"

_LOCK = threading.Lock()
_CACHE_SYMS: set[str] | None = None
_CACHE_TS: float = 0.0
_CACHE_ERR: str | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _ttl_sec() -> float:
    raw = (os.getenv("DEMO_UNIVERSE_TTL_SEC") or "").strip()
    try:
        return max(30.0, float(raw)) if raw else 600.0
    except ValueError:
        return 600.0


def paper_fallback_enabled() -> bool:
    """Paper-live fills for pairs missing on Demo. Off unless PAPER_FALLBACK=1."""
    if _exec_mode() != "hub_demo":
        return False
    return _env_bool("PAPER_FALLBACK", False)


class NotOnDemoError(RuntimeError):
    """Symbol is not in the Bitget Demo USDT-FUTURES catalog."""


def is_missing_pair_error(exc: BaseException | str) -> bool:
    msg = str(exc).lower()
    return "25100" in msg or "does not exist" in msg


def is_paper_venue(pos: dict[str, Any] | None) -> bool:
    """True when the local book is the execution venue (not a hub shadow)."""
    if not isinstance(pos, dict):
        return False
    meta = pos.get("meta") if isinstance(pos.get("meta"), dict) else {}
    venue = str(meta.get("exec_venue") or pos.get("exec_venue") or "").lower()
    return venue == "paper"


def _normalize_rows(raw: Any) -> set[str]:
    if isinstance(raw, dict):
        raw = raw.get("list") or raw.get("data") or []
    out: set[str] = set()
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "online").lower()
        if status and status not in {"online", "listed", ""}:
            continue
        sym = str(row.get("symbol") or "").strip().upper()
        if sym:
            out.add(sym)
    return out


def _fetch_demo_symbols() -> set[str]:
    from exec.bitget_hub import BitgetUtaClient

    client = BitgetUtaClient.from_env()
    payload = client.request(
        "GET",
        "/api/v3/market/instruments",
        query={"category": "USDT-FUTURES"},
    )
    return _normalize_rows(payload.get("data"))


def demo_tradable_symbols(*, force: bool = False) -> set[str]:
    """Cached Demo USDT-FUTURES symbols (Bitget ids, e.g. BTCUSDT)."""
    global _CACHE_SYMS, _CACHE_TS, _CACHE_ERR
    now = time.monotonic()
    with _LOCK:
        if (
            not force
            and _CACHE_SYMS is not None
            and (now - _CACHE_TS) < _ttl_sec()
        ):
            return set(_CACHE_SYMS)
    try:
        syms = _fetch_demo_symbols()
        err = None
    except Exception as exc:  # noqa: BLE001
        syms = set(_CACHE_SYMS or ())
        err = f"{type(exc).__name__}: {exc}"
        print(f"[DEMO-UNIVERSE] fetch failed: {err}")
    with _LOCK:
        if err:
            _CACHE_ERR = err
            if _CACHE_SYMS is not None:
                return set(_CACHE_SYMS)
            return set()
        _CACHE_SYMS = set(syms)
        _CACHE_TS = time.monotonic()
        _CACHE_ERR = None
        return set(_CACHE_SYMS)


def bitget_id_to_ccxt(symbol: str) -> str:
    """BTCUSDT -> BTC/USDT:USDT. Already-unified symbols pass through."""
    s = (symbol or "").strip().upper()
    if not s:
        return s
    if "/" in s:
        return s
    if s.endswith("USDT") and len(s) > 4:
        return f"{s[:-4]}/USDT:USDT"
    return s


def demo_scan_symbols(*, public_markets: dict | None = None) -> list[str]:
    """Full Demo UTA catalog as ccxt swap ids (not public top-N intersect).

    ``public_markets`` (ccxt load_markets) drops Demo stubs with no public candles
    (BGTEST002, RWATEST01, …).
    """
    try:
        catalog = demo_tradable_symbols()
    except Exception as exc:  # noqa: BLE001
        print(f"[DEMO-UNIVERSE] scan skipped: {exc}")
        return []
    if not catalog:
        print("[DEMO-UNIVERSE] empty catalog; scan none until Demo instruments load")
        return []
    out = [bitget_id_to_ccxt(bg) for bg in catalog]
    out = [s for s in out if s]
    if public_markets:
        skipped = [s for s in out if s not in public_markets]
        out = [s for s in out if s in public_markets]
        if skipped:
            print(
                f"[DEMO-UNIVERSE] skip {len(skipped)} no public candles: "
                + ",".join(skipped)
            )
    out.sort(key=lambda s: (s != "BTC/USDT:USDT", s))
    print(f"[DEMO-UNIVERSE] scan all Demo instruments n={len(out)}")
    return out


def drop_demo_symbol(symbol: str) -> None:
    """Remove a symbol after Bitget 25100 so later ENTERs skip the hub."""
    bg = ccxt_to_bitget_symbol(symbol).upper()
    if not bg:
        return
    global _CACHE_SYMS
    with _LOCK:
        if _CACHE_SYMS is not None:
            _CACHE_SYMS.discard(bg)


def symbol_tradable_on_demo(symbol: str) -> bool | None:
    """True / False if catalog known; None if catalog could not be loaded."""
    bg = ccxt_to_bitget_symbol(symbol).upper()
    if not bg:
        return False
    try:
        catalog = demo_tradable_symbols()
    except Exception:
        return None
    if not catalog:
        return None
    return bg in catalog


def filter_to_demo_symbols(symbols: list[str]) -> list[str]:
    """Keep scan symbols that exist on Demo. Empty catalog → scan none."""
    try:
        catalog = demo_tradable_symbols()
    except Exception as exc:  # noqa: BLE001
        print(f"[DEMO-UNIVERSE] filter skipped: {exc}")
        return []
    if not catalog:
        print("[DEMO-UNIVERSE] empty catalog; scan none until Demo instruments load")
        return []
    out: list[str] = []
    for raw in symbols:
        bg = ccxt_to_bitget_symbol(str(raw or "")).upper()
        if bg and bg in catalog:
            out.append(raw)
    dropped = len(symbols) - len(out)
    if dropped:
        print(f"[DEMO-UNIVERSE] drop {dropped} not on Demo; keep {len(out)}")
    return out


def reset_demo_universe_cache_for_tests() -> None:
    global _CACHE_SYMS, _CACHE_TS, _CACHE_ERR
    with _LOCK:
        _CACHE_SYMS = None
        _CACHE_TS = 0.0
        _CACHE_ERR = None
