"""One-shot paper↔Bitget reconcile (close local ghosts).

Usage:
  python scripts/reconcile_once.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main() -> int:
    from exec.paper import list_open
    from exec.reconcile import reconcile_paper_with_exchange
    from risk.gate import RiskGate

    gate = RiskGate()
    before = list_open()
    print(f"paper open before: {len(before)}")
    for p in before:
        print(f"  {p.get('symbol')} {p.get('side')} {p.get('position_id')}")

    events = reconcile_paper_with_exchange(gate=gate, force=True)
    print(json.dumps(events, ensure_ascii=False, indent=2, default=str))

    after = list_open()
    print(f"paper open after: {len(after)}")
    for p in after:
        print(f"  {p.get('symbol')} {p.get('side')} {p.get('position_id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
