"""Smoke Bitget public WS: bootstrap + candle/ticker updates for a few symbols."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest import candle_cache
from ingest.bitget_ws import BitgetPublicWs


def main() -> int:
    symbols = [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "TSLA/USDT:USDT",  # rToken smoke
    ]
    closed: list[str] = []

    def on_close(sym: str) -> None:
        closed.append(sym)
        print(f"bar_close {sym}")

    candle_cache.clear_all()
    ws = BitgetPublicWs(
        timeframe="15m",
        on_bar_close=on_close,
        subscribe_ticker=True,
        bootstrap_limit=50,
        bootstrap_rate=5.0,
        max_channels_per_conn=40,
    )
    print("bootstrap…")
    ws.set_symbols(symbols, bootstrap=True)
    # Background bootstrap — wait until all three are cached
    deadline_boot = time.time() + 60.0
    while time.time() < deadline_boot:
        ok = all(
            candle_cache.get_cached_ohlcv(s, "15m", min_bars=10) is not None
            for s in symbols
        )
        if ok:
            break
        time.sleep(0.5)
    for sym in symbols:
        df = candle_cache.get_cached_ohlcv(sym, "15m", min_bars=10)
        assert df is not None and len(df) >= 10, f"bootstrap missing {sym}"
        print(f"  cached {sym} bars={len(df)} mark={candle_cache.get_cached_mark(sym)}")

    print("starting WS (wait up to 45s for ticker/candle msgs)…")
    ws.start()
    deadline = time.time() + 45.0
    saw_msg = False
    while time.time() < deadline:
        if ws.healthy:
            saw_msg = True
            break
        time.sleep(0.5)
    stats = candle_cache.cache_stats()
    print(
        f"healthy={ws.healthy} shards={ws.connected_shards} "
        f"cache={stats} closed_events={len(closed)}"
    )
    ws.stop()
    if not saw_msg:
        print("FAIL: no WS messages received")
        return 1
    print("smoke_ws OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
