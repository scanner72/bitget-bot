"""Smoke: candidate dedup uses candle time, not relative bar_index."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.candidate_log import CandidateLog, _dedup_key, candidate_from_signal
from scripts.smoke_signal import synthetic_ohlcv
from signals.engine import bar_ts_iso, run_full_detection


def _fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")


def main() -> None:
    same = {
        "symbol": "ETH/USDT:USDT",
        "type": "BULLISH_DIV",
        "bar_ts": "2026-09-15T18:00:00Z",
        "bar_index": 193,
    }
    same_alias = {
        **same,
        "bar_ts": "2026-09-15T18:00:00+00:00",
        "bar_index": 194,
    }
    later = {
        "symbol": "ETH/USDT:USDT",
        "type": "BULLISH_DIV",
        "bar_ts": "2026-09-15T19:15:00Z",
        "bar_index": 193,
    }
    if _dedup_key(same) != _dedup_key(same_alias):
        _fail("Z and +00:00 bar_ts must be the same key")
    if _dedup_key(same) == _dedup_key(later):
        _fail("different candle times must not collide")
    legacy = {"symbol": "ETH/USDT:USDT", "type": "BULLISH_DIV", "bar_index": 193}
    if _dedup_key(legacy)[2] == _dedup_key(same)[2]:
        _fail("relative bar_index must not equal a real bar_ts")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidates.jsonl"
        path.write_text(
            '{"ts":"2026-09-10T00:00:00+00:00","symbol":"ETH/USDT:USDT",'
            '"type":"BULLISH_DIV","bar_index":193}\n',
            encoding="utf-8",
        )
        clog = CandidateLog(path)
        if clog.is_duplicate(same):
            _fail("legacy bar_index=193 row blocked a new candle bar_ts")
        if not clog.append(same):
            _fail("first bar_ts row should write")
        if clog.append(same_alias):
            _fail("same candle with alias tz should dedup")
        if not clog.append(later):
            _fail("new candle should write")

    df = synthetic_ohlcv(n=200, seed=7)
    stamped = bar_ts_iso(df, 193)
    if not stamped or not stamped.endswith("Z"):
        _fail(f"bar_ts_iso missing/invalid: {stamped!r}")
    if stamped == bar_ts_iso(df, 194):
        _fail("adjacent bars must have different bar_ts")

    signal, _ = run_full_detection(
        df,
        {
            "rsi_length": 14,
            "mom_period": 10,
            "lookback_left": 5,
            "lookback_right": 5,
            "min_bars": 5,
            "max_bars": 50,
        },
    )
    if signal is not None:
        rec = candidate_from_signal(signal, symbol="ETH/USDT:USDT", timeframe="15m")
        if not rec.get("bar_ts"):
            _fail(f"candidate missing bar_ts: {rec}")
        expected = bar_ts_iso(df, rec.get("bar_index"))
        if rec["bar_ts"] != expected:
            _fail(f"candidate bar_ts {rec['bar_ts']!r} != {expected!r}")

    print("smoke_candidate_log: ok")


if __name__ == "__main__":
    main()
