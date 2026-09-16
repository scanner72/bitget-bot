"""Verify SHA-256 decision JSONL (canonical JSON, ``hash`` field excluded).

Default target is the committed hashed fixture. Exit 0 on success.

  python scripts/verify_decision_log.py
  python scripts/verify_decision_log.py docs/evidence/fixtures/decisions.hashed.jsonl
  python scripts/verify_decision_log.py --write-fixture
  python scripts/verify_decision_log.py --allow-legacy data/decisions.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.decision_log import (  # noqa: E402
    reset_session_id,
    seal_decision,
    verify_jsonl,
    verify_record,
)

DEFAULT_FIXTURE = ROOT / "docs" / "evidence" / "fixtures" / "decisions.hashed.jsonl"
SAMPLE = ROOT / "docs" / "evidence" / "fixtures" / "decisions.sample.jsonl"


def _isolate_fixture_env() -> None:
    os.environ["EXEC_MODE"] = "paper"
    os.environ["AGENT_MODE"] = "rules"
    os.environ.pop("AGENT_LLM", None)
    os.environ["TIMEFRAME"] = "15m"
    os.environ["RISK_USD_PER_TRADE"] = "10"
    os.environ["MAX_NOTIONAL_USD"] = "500"
    os.environ["MIN_NOTIONAL_USD"] = "10"
    os.environ["MAX_POSITIONS"] = "15"
    os.environ["HUB_LEVERAGE"] = "20"
    os.environ["BTC_REGIME_TF"] = "1h"
    os.environ["BTC_REGIME_ENABLED"] = "1"
    os.environ["BTC_EMA50_FILTER_ENABLED"] = "0"
    os.environ["TF_BLOCKER_ENABLED"] = "0"
    os.environ["PAIR_BLOCKER_ENABLED"] = "1"
    os.environ["PAPER_FALLBACK"] = "0"
    os.environ["BITGET_ALLOW_LIVE"] = "0"
    os.environ["BITGET_DEMO"] = "1"
    os.environ["ALLOWED_TYPES"] = (
        "BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_UP,LEVEL_CROSS_DOWN"
    )
    os.environ["RSI_LONG_MAX"] = "30"
    os.environ["ALLOW_LONG"] = "1"
    os.environ["ALLOW_SHORT"] = "1"


def write_fixture(src: Path, dest: Path, *, session_id: str = "fixture-session") -> int:
    _isolate_fixture_env()
    reset_session_id(session_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    prev = ""
    n = 0
    with dest.open("w", encoding="utf-8") as out:
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            sealed = seal_decision(
                row,
                prev_hash=prev,
                session_id=session_id,
                context={
                    "timeframe": "15m",
                    "exec_mode": "paper",
                    "agent_mode": "rules",
                    "session_id": session_id,
                },
            )
            out.write(json.dumps(sealed, ensure_ascii=False, separators=(",", ":")) + "\n")
            prev = sealed["hash"]
            n += 1
    return n


def _tamper_check(path: Path) -> None:
    """Prove a one-byte edit of the first row fails verification."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise AssertionError("tamper check: empty log")
    row = json.loads(lines[0])
    row["price"] = float(row.get("price") or 0) + 1.0
    problems = verify_record(row, prev_hash=str(row.get("prev_hash") or ""))
    if not any("hash mismatch" in p for p in problems):
        raise AssertionError(f"tamper check did not catch edit: {problems}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify hashed decision JSONL")
    ap.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="JSONL to verify (default: hashed fixture)",
    )
    ap.add_argument(
        "--write-fixture",
        action="store_true",
        help=f"seal {SAMPLE.name} → {DEFAULT_FIXTURE.name}",
    )
    ap.add_argument(
        "--allow-legacy",
        action="store_true",
        help="skip rows that have no hash (runtime history)",
    )
    ap.add_argument(
        "--no-tamper-check",
        action="store_true",
        help="do not mutate a copy of row 0 as a negative test",
    )
    args = ap.parse_args(argv)

    if args.write_fixture:
        n = write_fixture(SAMPLE, DEFAULT_FIXTURE)
        print(f"wrote {n} hashed rows -> {DEFAULT_FIXTURE}")
        args.path = DEFAULT_FIXTURE

    path = args.path
    if not path.is_file():
        print(f"FAIL missing file: {path}", file=sys.stderr)
        return 1

    result = verify_jsonl(
        path,
        allow_legacy=args.allow_legacy,
        require_session=not args.allow_legacy,
    )
    if not result["ok"]:
        print(f"FAIL {path} rows={result['rows']}")
        for err in result["errors"][:20]:
            print(f"  {err}", file=sys.stderr)
        if len(result["errors"]) > 20:
            print(f"  … {len(result['errors']) - 20} more", file=sys.stderr)
        return 1

    if not args.no_tamper_check and result["rows"] and not args.allow_legacy:
        _tamper_check(path)

    extra = f" legacy={result['legacy']}" if result["legacy"] else ""
    print(f"OK {path} rows={result['rows']}{extra} hashes+chain+manifest match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
