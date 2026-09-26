"""Smoke: ccxt symbol -> Bitget id / display helpers (no network).

Also the meme-coin deny list: scan drop, pre-decide skip, risk gate, router.

Exit 0 on success.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.symbols import (  # noqa: E402
    DEFAULT_MEME_BASES,
    enrich_symbol_fields,
    is_trade_denied,
    to_bitget_id,
    to_display,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    cases = [
        ("CRCL/USDT:USDT", "CRCLUSDT", "CRCL-USDT Perp"),
        ("BTC/USDT:USDT", "BTCUSDT", "BTC-USDT Perp"),
        ("SOPH/USDT:USDT", "SOPHUSDT", "SOPH-USDT Perp"),
        ("XAG/USDT:USDT", "XAGUSDT", "XAG-USDT Perp"),
        ("AAPL/USDT:USDT", "AAPLUSDT", "AAPL-USDT Perp"),
        ("ETHUSDT", "ETHUSDT", "ETH-USDT Perp"),
        ("", "", ""),
    ]
    for src, expect_id, expect_disp in cases:
        got_id = to_bitget_id(src)
        got_disp = to_display(src)
        _assert(got_id == expect_id, f"to_bitget_id({src!r})={got_id!r} want {expect_id!r}")
        _assert(got_disp == expect_disp, f"to_display({src!r})={got_disp!r} want {expect_disp!r}")

    row = enrich_symbol_fields({"symbol": "CRCL/USDT:USDT", "side": "long"})
    _assert(row["symbol"] == "CRCL/USDT:USDT", "keep ccxt symbol")
    _assert(row["symbol_id"] == "CRCLUSDT", "symbol_id")
    _assert(row["symbol_display"] == "CRCL-USDT Perp", "symbol_display")
    _assert(row["side"] == "long", "passthrough")

    empty = enrich_symbol_fields({"side": "long"})
    _assert("symbol_id" not in empty and "symbol_display" not in empty, "no fake fields")

    from ingest.symbols import drop_denied_symbols

    clean = {
        "MEME_DENY_ENABLED": "1",
        "MEME_DENY_SYMBOLS": "",
        "MEME_DENY_ALLOW": "",
        "TRADE_DENY_SYMBOLS": "",
    }
    with patch.dict(os.environ, clean, clear=False):
        _assert(is_trade_denied("USDCUSDT") is True, "compact USDCUSDT denied")
        _assert(is_trade_denied("USDC/USDT:USDT") is True, "ccxt USDC/USDT:USDT denied")
        _assert(is_trade_denied("usdc/usdt") is True, "slash USDC/USDT denied")
        _assert(is_trade_denied("BTC/USDT:USDT") is False, "BTC still tradable")
        dropped = drop_denied_symbols(
            ["BTC/USDT:USDT", "USDC/USDT:USDT", "ETH/USDT:USDT", "DOGE/USDT:USDT"]
        )
        _assert(dropped == ["BTC/USDT:USDT", "ETH/USDT:USDT"], dropped)

        for base in sorted(DEFAULT_MEME_BASES):
            _assert(is_trade_denied(f"{base}USDT"), f"{base}USDT should be denied")
            _assert(
                is_trade_denied(f"{base}/USDT:USDT"),
                f"{base}/USDT:USDT should be denied",
            )
        prefixed = (
            "1000BONKUSDT",
            "1000PEPE/USDT:USDT",
            "1000SHIBUSDT",
            "1000FLOKIUSDT",
            "SHIB1000USDT",
            "1MBABYDOGEUSDT",
            "1000000MOGUSDT",
            "1MCHEEMSUSDT",
            "1000SATSUSDT",
            "1000RATSUSDT",
            "1000CATUSDT",
            "doge/usdt",
            "WIF/USDT:USDT",
        )
        for sym in prefixed:
            _assert(is_trade_denied(sym), f"prefixed meme not denied: {sym}")

        still_tradable = (
            "BTCUSDT",
            "ETH/USDT:USDT",
            "SOLUSDT",
            "AAPL/USDT:USDT",
            "DDOGUSDT",
            "BANDUSDT",
            "BANKUSDT",
            "BANANAUSDT",
            "GIGADEVICEUSDT",
            "SOFTBANKUSDT",
            "ORDIUSDT",
            "LUNCUSDT",
            "1000XECUSDT",
            "APEUSDT",
            "XAG/USDT:USDT",
        )
        for sym in still_tradable:
            _assert(is_trade_denied(sym) is False, f"false deny: {sym}")

        _meme_deny_overrides()
        _meme_deny_defense()

    print("smoke_symbols: ok")
    return 0


def _meme_deny_overrides() -> None:
    with patch.dict(os.environ, {"MEME_DENY_ALLOW": "DOGE,1000BONK/USDT:USDT"}, clear=False):
        _assert(is_trade_denied("DOGEUSDT") is False, "allow DOGE")
        _assert(is_trade_denied("1000DOGEUSDT") is False, "allow strips 1000DOGE")
        _assert(is_trade_denied("BONK/USDT:USDT") is False, "allow BONK via 1000 id")
        _assert(is_trade_denied("PEPEUSDT") is True, "PEPE stays denied")
        _assert(is_trade_denied("USDCUSDT") is True, "USDC not lifted by meme allow")

    with patch.dict(
        os.environ,
        {"MEME_DENY_ENABLED": "0", "MEME_DENY_ALLOW": "", "TRADE_DENY_SYMBOLS": "WLDUSDT"},
        clear=False,
    ):
        _assert(is_trade_denied("DOGE/USDT:USDT") is False, "meme list off")
        _assert(is_trade_denied("1000BONKUSDT") is False, "prefixed meme off with list")
        _assert(is_trade_denied("USDC/USDT:USDT") is True, "USDC stays when memes off")
        _assert(is_trade_denied("WLDUSDT") is True, "TRADE_DENY_SYMBOLS still applies")

    with patch.dict(
        os.environ,
        {
            "MEME_DENY_ENABLED": "1",
            "MEME_DENY_SYMBOLS": "WLD",
            "MEME_DENY_ALLOW": "WLD",
            "TRADE_DENY_SYMBOLS": "WLDUSDT",
        },
        clear=False,
    ):
        _assert(is_trade_denied("WLD/USDT:USDT") is True, "TRADE_DENY beats meme allow")
        _assert(
            is_trade_denied("1000WLDUSDT") is False,
            "TRADE_DENY id is exact; meme allow cleared the base",
        )

    with patch.dict(
        os.environ,
        {
            "MEME_DENY_ENABLED": "1",
            "MEME_DENY_SYMBOLS": "WLDUSDT",
            "MEME_DENY_ALLOW": "",
            "TRADE_DENY_SYMBOLS": "",
        },
        clear=False,
    ):
        _assert(is_trade_denied("WLDUSDT") is True, "extra meme id")
        _assert(is_trade_denied("1000WLDUSDT") is True, "extra meme base covers prefix")


def _meme_deny_defense() -> None:
    """Denied before decide, again at the gate, again at open. No network."""
    os.environ["PAIR_BLOCKER_ENABLED"] = "0"
    os.environ["TF_BLOCKER_ENABLED"] = "0"
    from desk.candidate_log import CandidateLog
    from desk.loop import LoopConfig, process_symbol
    from desk.pipeline import evaluate_candidate
    from exec.demo_universe import demo_scan_symbols
    from exec.router import open_position
    from risk.gate import RiskGate, RiskLimits, RiskState

    gate = RiskGate(
        limits=RiskLimits(
            max_notional_usd=100.0,
            max_daily_loss_usd=150.0,
            max_positions=15,
            cooldown_sec=0.0,
            allowed_types=None,
        ),
        state=RiskState(),
        persist=False,
    )
    gated = gate.check({"symbol": "PEPE/USDT:USDT", "type": "BULLISH_DIV"}, 50.0)
    _assert(
        gated["allowed"] is False and str(gated["reason"]).startswith("symbol_denied:PEPEUSDT"),
        gated,
    )
    btc = gate.check({"symbol": "BTC/USDT:USDT", "type": "BULLISH_DIV"}, 50.0)
    _assert(btc["allowed"] is True, btc)

    decided: list[str] = []

    def _fake_decide(candidate, ctx=None):  # noqa: ARG001
        decided.append(str(candidate.get("symbol")))
        return {
            "action": "SKIP",
            "size_usd": 0.0,
            "side": None,
            "rationale": "smoke",
            "rules_fired": ["smoke"],
        }

    with tempfile.TemporaryDirectory(prefix="meme_deny_") as td:
        tdir = Path(td)
        with patch("desk.pipeline.decide", _fake_decide):
            denied = evaluate_candidate(
                {
                    "symbol": "DOGE/USDT:USDT",
                    "type": "BULLISH_DIV",
                    "price": 0.1,
                    "rsi": 40.0,
                },
                gate,
                decisions_path=tdir / "decisions.jsonl",
            )
            evaluate_candidate(
                {
                    "symbol": "BTC/USDT:USDT",
                    "type": "BULLISH_DIV",
                    "price": 65000.0,
                    "rsi": 40.0,
                },
                gate,
                decisions_path=tdir / "decisions.jsonl",
            )
        _assert(decided == ["BTC/USDT:USDT"], decided)
        _assert(denied["action"] == "SKIP", denied)
        _assert(str(denied["reason"]).startswith("symbol_denied:DOGEUSDT"), denied)
        _assert(denied["risk"]["allowed"] is False, denied)

        cfg = LoopConfig(
            symbols=["PEPE/USDT:USDT"],
            candidates_path=tdir / "cand.jsonl",
            decisions_path=tdir / "decisions.jsonl",
        )

        def _no_ohlcv(*_a, **_k):
            raise AssertionError("denied symbol must not fetch candles")

        with patch("desk.loop.get_ohlcv", _no_ohlcv):
            summary = process_symbol(
                "PEPE/USDT:USDT",
                cfg,
                CandidateLog(tdir / "cand.jsonl"),
                gate,
            )
        _assert(str(summary["risk_reason"]).startswith("symbol_denied:PEPEUSDT"), summary)

    try:
        open_position(
            symbol="WIF/USDT:USDT",
            side="long",
            size_usd=10.0,
            price=1.0,
        )
    except ValueError as exc:
        _assert(str(exc).startswith("symbol_denied:WIFUSDT"), exc)
    else:
        raise AssertionError("router must reject WIF")

    with patch(
        "exec.demo_universe.demo_tradable_symbols",
        return_value={"BTCUSDT", "DOGEUSDT", "1000BONKUSDT", "ETHUSDT"},
    ):
        scan = demo_scan_symbols()
    _assert("DOGE/USDT:USDT" not in scan, scan)
    _assert("1000BONK/USDT:USDT" not in scan, scan)
    _assert(scan[0] == "BTC/USDT:USDT", scan)
    _assert("ETH/USDT:USDT" in scan, scan)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"smoke_symbols FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
