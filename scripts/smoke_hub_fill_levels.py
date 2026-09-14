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

    print("smoke_hub_fill_levels OK", levels, sl, tp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
