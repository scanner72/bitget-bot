"""Smoke: Bitget USDT-M universe partition (crypto vs rToken). NO SPOT.

Prints counts and sample symbols; exit 0 on success.
PAPER / public data only — no API keys required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from ingest.universe import fetch_universe, load_scan_env  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    # Ensure auto defaults for smoke even if .env has fixed
    os.environ.setdefault("SCAN_MODE", "auto")
    env = load_scan_env()
    print(
        f"scan_mode={env['mode']} crypto_top={env['crypto_top']} "
        f"rtoken_top={env['rtoken_top']} refresh_sec={env['refresh_sec']}"
    )
    snap = fetch_universe(
        crypto_top=env["crypto_top"],
        rtoken_top=env["rtoken_top"],
    )
    crypto_syms = [r["symbol"] for r in snap.crypto]
    rtoken_syms = [r["symbol"] for r in snap.rtoken]
    print(f"crypto_total={snap.crypto_total} crypto_top_n={len(crypto_syms)}")
    print(f"rtoken_total={snap.rtoken_total} rtoken_top_n={len(rtoken_syms)}")
    print(f"union_n={len(snap.symbols)}")
    print("crypto_sample=", crypto_syms[:10])
    print("rtoken_sample=", rtoken_syms[:10])
    # Sanity: no spot-style symbols (must contain :USDT)
    bad = [s for s in snap.symbols if ":" not in s]
    if bad:
        print("ERROR spot-like symbols:", bad)
        return 1
    # Baskets should be disjoint
    overlap = set(crypto_syms) & set(rtoken_syms)
    if overlap:
        print("ERROR basket overlap:", sorted(overlap))
        return 1
    if snap.crypto_total < 1 or snap.rtoken_total < 1:
        print("ERROR empty partition totals")
        return 1
    print("smoke_universe OK (perps only; no spot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
