"""Smoke: live Bitget public OHLCV -> run_full_detection -> print summary.

PAPER-only. Uses public market data (no API keys).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.bitget_ohlcv import DEFAULT_SYMBOL, DEFAULT_TIMEFRAME, fetch_ohlcv  # noqa: E402
from signals.engine import get_latest_signal, run_full_detection  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test Bitget public OHLCV + signal core")
    ap.add_argument("--symbol", default=DEFAULT_SYMBOL, help="ccxt symbol, e.g. BTC/USDT:USDT")
    ap.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="OHLCV timeframe, e.g. 15m")
    ap.add_argument("--bars", type=int, default=300, help="Number of bars to fetch")
    args = ap.parse_args()

    print(f"Fetching Bitget public OHLCV symbol={args.symbol} tf={args.timeframe} limit={args.bars}")
    df = fetch_ohlcv(symbol=args.symbol, timeframe=args.timeframe, limit=args.bars)
    last_close = float(df["close"].iloc[-1])
    print(f"bars={len(df)} last_close={last_close} index_tz={df.index.tz}")

    pair_config = {
        "rsi_length": 14,
        "mom_period": 10,
        "lookback_left": 5,
        "lookback_right": 5,
        "min_bars": 5,
        "max_bars": 50,
    }

    signal, has_zones = run_full_detection(df, pair_config)
    latest = get_latest_signal(df, pair_config)

    print(f"has_zones={has_zones}")
    if signal is None:
        print("candidate=EMPTY")
    else:
        cand_type = signal.get("type")
        print(f"candidate={cand_type}")
        slim = {k: v for k, v in signal.items() if k not in ("df", "results")}
        print(f"detection_result={slim}")
    print(f"get_latest_signal_type={None if latest is None else latest.get('type')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
