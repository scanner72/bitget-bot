"""Unit checks for fill-based TPSL helpers (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    from exec.router import _recompute_levels_for_entry, _validate_tpsl_vs_mark

    # Short: SL above entry, TP below
    levels = _recompute_levels_for_entry(
        {"atr": 1.0}, entry=54.65, side="short"
    )
    _assert(levels["sl"] > 54.65, levels)
    _assert(levels["tp2"] < 54.65, levels)

    # Mark already above provisional SL — bump SL above mark
    sl, tp = _validate_tpsl_vs_mark(
        "short", sl=54.315, tp=50.0, mark=54.58, buffer_pct=0.05
    )
    _assert(sl is not None and sl > 54.58, (sl, tp))
    _assert(tp is not None and tp < 54.58, (sl, tp))

    # Long opposite
    sl2, tp2 = _validate_tpsl_vs_mark(
        "long", sl=100.0, tp=90.0, mark=95.0, buffer_pct=0.05
    )
    _assert(sl2 is not None and sl2 < 95.0, (sl2, tp2))
    _assert(tp2 is not None and tp2 > 95.0, (sl2, tp2))

    # Rounding can land on mark without a tick bump (25592 short SL > mark).
    # mark=59.78, buffer floor ≈ 59.80989 → round 2dp = 59.81 still OK;
    # mark=10.00, SL=10.004 with 2dp → 10.00 == mark → must bump to 10.01.
    sl3, tp3 = _validate_tpsl_vs_mark(
        "short", sl=10.004, tp=9.50, mark=10.00, buffer_pct=0.05, decimals=2
    )
    _assert(sl3 is not None and sl3 > 10.00, (sl3, tp3))
    _assert(tp3 is not None and tp3 < 10.00, (sl3, tp3))
    _assert(abs(sl3 - round(sl3, 2)) < 1e-12, sl3)

    # Long SL must stay strictly below mark after 2dp round.
    sl4, tp4 = _validate_tpsl_vs_mark(
        "long", sl=99.996, tp=100.004, mark=100.00, buffer_pct=0.05, decimals=2
    )
    _assert(sl4 is not None and sl4 < 100.00, (sl4, tp4))
    _assert(tp4 is not None and tp4 > 100.00, (sl4, tp4))

    print("smoke_hub_fill_levels OK", levels, sl, tp, sl3, tp3, sl4, tp4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
