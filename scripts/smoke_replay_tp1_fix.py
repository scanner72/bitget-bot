"""Offline smoke for scripts/replay_tp1_fix.py (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from replay_tp1_fix import self_test  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(self_test())
