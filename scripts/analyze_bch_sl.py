"""Replay BCH short vs SL / BE using OHLCV highs."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.bitget_ohlcv import get_ohlcv  # noqa: E402

SYM = "BCH/USDT:USDT"
ENTRY = 226.99
ORIG_SL = 231.5298
OPEN_TS = datetime.fromisoformat("2026-09-10T21:45:09+00:00")
CLOSE_TS = datetime.fromisoformat("2026-09-11T05:46:00+00:00")
BE_HOURS = 8.0  # default guess; refine from env


def main() -> None:
    df = get_ohlcv(SYM, "15m", limit=200)
    print("bars", len(df), "cols", list(df.columns)[:10])
    # normalize ts
    if "ts" in df.columns:
        tscol = "ts"
    elif "timestamp" in df.columns:
        tscol = "timestamp"
    else:
        tscol = df.index.name or "index"
        df = df.reset_index()

    # parse
    rows = []
    for _, r in df.iterrows():
        t = r.get("ts") or r.get("timestamp") or r.get("datetime")
        if hasattr(t, "to_pydatetime"):
            t = t.to_pydatetime()
        if isinstance(t, (int, float)):
            t = datetime.fromtimestamp(t / 1000 if t > 1e12 else t, tz=timezone.utc)
        if isinstance(t, str):
            t = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        rows.append(
            {
                "ts": t,
                "o": float(r["open"]),
                "h": float(r["high"]),
                "l": float(r["low"]),
                "c": float(r["close"]),
            }
        )
    rows.sort(key=lambda x: x["ts"])

    window = [r for r in rows if OPEN_TS <= r["ts"] <= CLOSE_TS + __import__("datetime").timedelta(hours=1)]
    if not window:
        # maybe incomplete bars use open time
        window = [r for r in rows if OPEN_TS - __import__("datetime").timedelta(minutes=15) <= r["ts"] <= CLOSE_TS]
    print("window bars", len(window))
    if not window:
        print("last 5 bars:")
        for r in rows[-5:]:
            print(r)
        return

    max_h = max(r["h"] for r in window)
    min_l = min(r["l"] for r in window)
    print(f"entry={ENTRY} orig_sl={ORIG_SL}")
    print(f"window high={max_h} low={min_l}")
    print(f"high >= orig_sl? {max_h >= ORIG_SL}  delta={max_h - ORIG_SL:.4f}")
    print(f"high >= entry (BE)? {max_h >= ENTRY}")

    # first touch orig SL
    first_sl = next((r for r in window if r["h"] >= ORIG_SL), None)
    if first_sl:
        print("FIRST touch orig SL:", first_sl["ts"].isoformat(), "H", first_sl["h"], "C", first_sl["c"])
    else:
        print("NEVER touched original SL 231.53 in window")

    # path after open: any adverse move
    be_at = OPEN_TS + __import__("datetime").timedelta(hours=BE_HOURS)
    print(f"BE due at ~{be_at.isoformat()} (assuming BE_HOURS={BE_HOURS})")
    before_be = [r for r in window if r["ts"] < be_at]
    after_be = [r for r in window if r["ts"] >= be_at]
    if before_be:
        print(f"before BE: high={max(r['h'] for r in before_be)} low={min(r['l'] for r in before_be)}")
    if after_be:
        print(f"after BE: high={max(r['h'] for r in after_be)} low={min(r['l'] for r in after_be)}")

    print("\nAdverse bars (high > entry) while open:")
    for r in window:
        if r["h"] > ENTRY:
            adverse_pct = (r["h"] - ENTRY) / ENTRY * 100
            print(
                f"  {r['ts'].isoformat()} H={r['h']} C={r['c']} "
                f"vs_entry=+{adverse_pct:.3f}% vs_sl={r['h']-ORIG_SL:+.3f}"
            )

    # current mark
    last = rows[-1]
    print("\nlatest bar", last["ts"].isoformat(), "C", last["c"], "H", last["h"])


if __name__ == "__main__":
    main()
