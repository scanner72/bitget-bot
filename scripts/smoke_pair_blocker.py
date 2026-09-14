"""Smoke: pair blocker consecutive-loss + gate deny."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from risk.gate import RiskGate, RiskLimits
from risk.pair_blocker import BlockerConfig, is_pair_blocked, run_blocker


def main() -> int:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        fills = td_path / "fills.jsonl"
        blocks = td_path / "blocks.json"
        rows = []
        # two consecutive losses on AAA
        for i, pnl in enumerate([-1.0, -2.0]):
            rows.append(
                {
                    "ts": (now - timedelta(hours=2 - i)).isoformat(),
                    "event": "close",
                    "symbol": "AAA/USDT:USDT",
                    "realized_pnl": pnl,
                    "meta": {"timeframe": "15m"},
                }
            )
        # winner on BBB
        rows.append(
            {
                "ts": now.isoformat(),
                "event": "close",
                "symbol": "BBB/USDT:USDT",
                "realized_pnl": 3.0,
                "meta": {"timeframe": "15m"},
            }
        )
        fills.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        cfg = BlockerConfig(
            enabled=True,
            min_trades=2,
            wr_threshold=30.0,
            consecutive_losses=2,
            cooldown_hours=48.0,
            stats_window_days=14.0,
            longtail_window_days=60.0,
            longtail_wr_threshold=20.0,
            pnl_min_trades=5,
            pnl_cooldown_hours=336.0,
            tf_enabled=False,
            fills_path=fills,
            blocks_path=blocks,
            default_timeframe="15m",
        )
        summary = run_blocker(cfg)
        assert summary["new_pair_blocks"] >= 1, summary
        blocked, reason = is_pair_blocked("AAA/USDT:USDT", cfg)
        assert blocked, (blocked, reason)
        ok, _ = is_pair_blocked("BBB/USDT:USDT", cfg)
        assert not ok

        # Gate should deny
        gate = RiskGate(limits=RiskLimits(cooldown_sec=0, max_positions=50))
        # Point blocker paths via env would need process env; call is_pair_blocked path
        # already verified. Simulate gate by patching blocks path through env:
        import os

        os.environ["PAIR_BLOCKS_PATH"] = str(blocks)
        os.environ["PAIR_BLOCKER_ENABLED"] = "1"
        out = gate.check(
            {"symbol": "AAA/USDT:USDT", "type": "BEARISH_DIV", "timeframe": "15m"},
            50.0,
        )
        assert out["allowed"] is False and str(out["reason"]).startswith("pair_blocked"), out
        print("smoke_pair_blocker OK", summary, out["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
