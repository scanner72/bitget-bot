"""Map ccxt unified Bitget swap symbols to native id / human display.

Internal trading keys stay ccxt (e.g. CRCL/USDT:USDT). API/dashboard can
expose Bitget-native id and a short display label without changing exec paths.
"""

from __future__ import annotations

import os

# Always-on trade bans (Bitget ids). USDCUSDT is a stablecoin basis pair —
# ATR/div signals there are noise; do not scan or open it.
DEFAULT_TRADE_DENY_IDS = frozenset({"USDCUSDT"})

# Meme bases on Bitget USDT-M. Contract ids may be the bare base (DOGEUSDT)
# or a size prefix/suffix (1000BONKUSDT, 1MBABYDOGEUSDT, 1000000MOGUSDT,
# SHIB1000USDT). Matching is on the base after those tokens are stripped.
# Not included: APE (NFT governance), ORDI, LUNC, and lookalikes such as
# DDOG, BAND, BANANA, GIGADEVICE, SOFTBANK.
DEFAULT_MEME_BASES = frozenset(
    {
        "DOGE",
        "SHIB",
        "PEPE",
        "BONK",
        "WIF",
        "FLOKI",
        "BOME",
        "MEME",
        "PEOPLE",
        "TURBO",
        "BRETT",
        "POPCAT",
        "MEW",
        "PNUT",
        "MOODENG",
        "FARTCOIN",
        "TRUMP",
        "MELANIA",
        "BABYDOGE",
        "DOGS",
        "NOT",
        "PENGU",
        "NEIRO",
        "NEIROCTO",
        "CAT",
        "RATS",
        "SATS",
        "CHEEMS",
        "MOG",
        "CHILLGUY",
        "WEN",
        "BAN",
        "PIPPIN",
        "TOSHI",
        "SPX",
        "ACT",
        "GOAT",
        "ELON",
        "LADYS",
        "MYRO",
        "SLERF",
        "PONKE",
        "MOTHER",
        "MICHI",
        "COQ",
        "BANANAS31",
    }
)

# Longest first so 1000000 is not consumed as 1000.
_SIZE_TOKENS = ("1000000", "100000", "10000", "1000", "1M")
_QUOTE_SUFFIXES = ("USDT", "USDC", "USD")


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


def _csv_tokens(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _env_on(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def meme_deny_enabled() -> bool:
    """MEME_DENY_ENABLED defaults on. USDCUSDT is unaffected."""
    return _env_on("MEME_DENY_ENABLED", True)


def _quote_stripped(bitget_id: str) -> str:
    for quote in _QUOTE_SUFFIXES:
        if bitget_id.endswith(quote) and len(bitget_id) > len(quote):
            return bitget_id[: -len(quote)]
    return bitget_id


def meme_core_base(symbol: str) -> str:
    """DOGEUSDT / 1000BONK/USDT:USDT / 1MBABYDOGEUSDT -> DOGE / BONK / BABYDOGE."""
    core = _quote_stripped(to_bitget_id(symbol))
    while core:
        nxt = core
        for tok in _SIZE_TOKENS:
            if nxt.startswith(tok) and len(nxt) > len(tok):
                nxt = nxt[len(tok) :]
                break
            if nxt.endswith(tok) and len(nxt) > len(tok):
                nxt = nxt[: -len(tok)]
                break
        if nxt == core:
            break
        core = nxt
    return core


def _ids_from_csv(raw: str | None) -> set[str]:
    ids: set[str] = set()
    for token in _csv_tokens(raw):
        bid = to_bitget_id(token)
        if bid:
            ids.add(bid)
    return ids


def _bases_from_csv(raw: str | None) -> set[str]:
    bases: set[str] = set()
    for token in _csv_tokens(raw):
        base = meme_core_base(token)
        if base:
            bases.add(base)
    return bases


def _permanent_deny_ids() -> set[str]:
    """USDC plus TRADE_DENY_SYMBOLS. Not cleared by MEME_DENY_ALLOW."""
    return set(DEFAULT_TRADE_DENY_IDS) | _ids_from_csv(os.getenv("TRADE_DENY_SYMBOLS"))


def trade_deny_ids() -> set[str]:
    """Explicit Bitget ids (bare ``{base}USDT`` for memes, no prefix expansion).

    ``1000`` / ``1M`` contracts are denied by :func:`is_trade_denied`, which
    strips those size tokens before comparing bases.
    """
    ids = _permanent_deny_ids()
    if not meme_deny_enabled():
        return ids
    allow = _bases_from_csv(os.getenv("MEME_DENY_ALLOW"))
    for base in set(DEFAULT_MEME_BASES) | _bases_from_csv(os.getenv("MEME_DENY_SYMBOLS")):
        if base not in allow:
            ids.add(f"{base}USDT")
    for bid in _ids_from_csv(os.getenv("MEME_DENY_SYMBOLS")):
        if meme_core_base(bid) not in allow:
            ids.add(bid)
    return ids


def is_trade_denied(symbol: str) -> bool:
    """True for USDC, configured extras, and (by default) meme-coin bases.

    ``MEME_DENY_ENABLED=0`` turns the meme list off.
    ``MEME_DENY_SYMBOLS`` adds bases or symbols. ``MEME_DENY_ALLOW`` removes
    meme bases (and their 1000/1M contracts). Neither override lifts
    ``USDCUSDT`` or ``TRADE_DENY_SYMBOLS``.
    """
    bid = to_bitget_id(symbol)
    if not bid:
        return False
    if bid in _permanent_deny_ids():
        return True
    if not meme_deny_enabled():
        return False
    base = meme_core_base(bid)
    if not base:
        return False
    if base in _bases_from_csv(os.getenv("MEME_DENY_ALLOW")):
        return False
    if base in DEFAULT_MEME_BASES or base in _bases_from_csv(os.getenv("MEME_DENY_SYMBOLS")):
        return True
    if bid in _ids_from_csv(os.getenv("MEME_DENY_SYMBOLS")):
        return True
    return False


def drop_denied_symbols(symbols: list[str]) -> list[str]:
    return [s for s in symbols if not is_trade_denied(s)]
