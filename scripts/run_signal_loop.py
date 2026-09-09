"""CLI: candle -> signal -> candidate JSONL loop (paper / public OHLCV).

Examples:
  ONCE=1 SYMBOLS=BTC/USDT:USDT,ETH/USDT:USDT python scripts/run_signal_loop.py
  python scripts/run_signal_loop.py --once
  POLL_SEC=60 python scripts/run_signal_loop.py --poll
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.loop import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
