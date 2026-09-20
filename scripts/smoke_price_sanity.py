"""Smoke: Demo vs public price bands (BZ stocks + LTC crypto)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    os.environ.pop("SIGNAL_PRICE_MAX_DEV_PCT", None)
    os.environ.pop("RTOKEN_SIGNAL_PRICE_MAX_DEV_PCT", None)
    os.environ.pop("MARK_SANITY_MAX_DEV_PCT", None)
    os.environ.pop("RTOKEN_MARK_SANITY_MAX_DEV_PCT", None)

    from exec.router import _max_price_dev_pct, _price_scale_reason

    # Open band default 2.5% for crypto and rToken.
    _assert(abs(_max_price_dev_pct("BTC/USDT:USDT") - 2.5) < 1e-9, _max_price_dev_pct("BTC/USDT:USDT"))
    _assert(abs(_max_price_dev_pct("BZ/USDT:USDT") - 2.5) < 1e-9, _max_price_dev_pct("BZ/USDT:USDT"))
    _assert(abs(_max_price_dev_pct("LTC/USDT:USDT") - 2.5) < 1e-9, _max_price_dev_pct("LTC/USDT:USDT"))

    # BZ 4.49% and LTC 3.03% must both reject under 2.5%.
    bz = _price_scale_reason(99.04, 103.49, label="demo_mark", symbol="BZ/USDT:USDT")
    ltc = _price_scale_reason(58.02, 59.78, label="demo_mark", symbol="LTC/USDT:USDT")
    ok_crypto = _price_scale_reason(100.0, 101.0, label="demo_mark", symbol="BTC/USDT:USDT")
    _assert(bz is not None and "demo_mark" in bz, bz)
    _assert(ltc is not None and "demo_mark" in ltc, ltc)
    _assert(ok_crypto is None, f"1% crypto should allow: {ok_crypto}")
    print(f"open guard: bz_reject ltc_reject ok_1pct")

    from risk.tick_stops import _mark_sanity_dev_pct, _quote_is_sane

    _assert(abs(_mark_sanity_dev_pct("BTC/USDT:USDT") - 2.5) < 1e-9, _mark_sanity_dev_pct("BTC/USDT:USDT"))
    _assert(abs(_mark_sanity_dev_pct("BZ/USDT:USDT") - 2.5) < 1e-9, _mark_sanity_dev_pct("BZ/USDT:USDT"))

    _assert(_quote_is_sane("BZ/USDT:USDT", 103.4, 103.5) is True, "sane tick kept")
    _assert(_quote_is_sane("BZ/USDT:USDT", 99.06, 103.5) is False, "BZ stale tick rejected")
    _assert(_quote_is_sane("BZ/USDT:USDT", 99.06, 103.52) is False, "BZ vs Demo entry")
    # LTC: public close 57.99 vs Demo entry 59.78 (~3.0%) must not fabricate SL.
    _assert(_quote_is_sane("LTC/USDT:USDT", 57.99, 59.78) is False, "LTC public vs Demo entry")
    _assert(_quote_is_sane("LTC/USDT:USDT", 59.74, 59.78) is True, "LTC Demo-scale tick kept")
    _assert(_quote_is_sane("BTC/USDT:USDT", 98.5, 100.0) is True, "crypto 1.5% tick kept")
    _assert(_quote_is_sane("BTC/USDT:USDT", 80.0, 100.0) is False, "crypto 20% glitch rejected")
    print("exit guard: BZ/LTC public-vs-entry rejected; Demo-scale kept")

    from exec.account import PaperAccount
    from exec.paper import PaperBook
    from risk.tick_stops import QuoteBus, apply_tick_quotes

    with tempfile.TemporaryDirectory(prefix="price_sanity_ltc_") as td:
        tdir = Path(td)
        acct = PaperAccount.load(tdir / "acct.json", start_balance=10000.0, persist=True)
        book = PaperBook(
            fills_file=tdir / "fills.jsonl",
            positions_file=tdir / "pos.json",
            account=acct,
        )
        book.open_paper(
            "LTC/USDT:USDT",
            "long",
            100.0,
            59.78,
            meta={"exec_venue": "paper", "atr": 1.14, "sl": 58.64, "tp1": 61.49, "tp2": 62.63},
        )
        bus = QuoteBus()
        bus.set_open_symbols(["LTC/USDT:USDT"])
        bus.on_quote("LTC/USDT:USDT", 57.99, 58.10, 57.90)
        with patch.dict(os.environ, {"TICK_STOPS": "1"}, clear=False), patch(
            "ingest.candle_cache.get_cached_ohlcv",
            return_value=__import__("pandas").DataFrame(
                {"high": [58.1], "low": [57.9], "close": [58.02]}
            ),
        ):
            ev = apply_tick_quotes(bus, book=book, timeframe="15m")
        _assert(ev == [], f"LTC public tick must not close Demo-scale SL: {ev}")
        _assert(len(book.list_open()) == 1, book.list_open())
        print("tick path: LTC 57.99 vs entry 59.78 did not fabricate sl_hit")

    print("smoke_price_sanity OK: BZ + LTC Demo vs public")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
