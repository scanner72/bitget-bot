"""Smoke: synthetic (or CSV) OHLCV -> run_full_detection -> print candidate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from signals.engine import run_full_detection, get_latest_signal  # noqa: E402


def synthetic_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.004, size=n)
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.0005, 0.008, size=n))
    low = close * (1 - rng.uniform(0.0005, 0.008, size=n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.uniform(10, 100, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for need in ("open", "high", "low", "close"):
        if need not in cols:
            raise SystemExit(f"CSV missing column: {need}")
        rename[cols[need]] = need
    if "volume" in cols:
        rename[cols["volume"]] = "volume"
    df = df.rename(columns=rename)
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return df[keep].astype(float)


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke-test divergence signal core")
    ap.add_argument("--csv", type=Path, default=None, help="Optional OHLCV CSV path")
    ap.add_argument("--bars", type=int, default=300, help="Synthetic bar count")
    args = ap.parse_args()

    if args.csv and args.csv.exists():
        df = load_csv(args.csv)
        print(f"Loaded CSV {args.csv} rows={len(df)}")
    else:
        df = synthetic_ohlcv(n=args.bars)
        print(f"Synthetic OHLCV bars={len(df)} (no CSV)")

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

    print(f"has_active_zones={has_zones}")
    if signal is None:
        print("detection_result=EMPTY (no candidate on latest bars)")
    else:
        slim = {k: v for k, v in signal.items() if k not in ("df", "results")}
        print(f"detection_result={slim}")
    print(f"get_latest_signal_type={None if latest is None else latest.get('type')}")


if __name__ == "__main__":
    main()
