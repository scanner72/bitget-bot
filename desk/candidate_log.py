"""Append-only candidate JSONL with in-process + file-backed dedup."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def candidate_from_signal(
    signal: dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    ts: datetime | None = None,
) -> dict[str, Any]:
    """Build a slim JSONL record from engine signal dict (drop df/results)."""
    now = ts or datetime.now(timezone.utc)
    bar_index = signal.get("bar_index")
    try:
        bar_index = int(bar_index) if bar_index is not None else None
    except (TypeError, ValueError):
        bar_index = None

    def _f(key: str) -> float | None:
        v = signal.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "ts": now.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "type": str(signal.get("type", "")),
        "price": _f("price"),
        "level_price": _f("level_price"),
        "rsi": _f("rsi"),
        "bar_index": bar_index,
    }


def _dedup_key(rec: dict[str, Any]) -> tuple[str, str, int | str | None]:
    bar = rec.get("bar_index")
    if bar is None:
        bar = rec.get("bar_ts") or rec.get("ts")
    return (str(rec.get("symbol", "")), str(rec.get("type", "")), bar)


class CandidateLog:
    """JSONL candidate store with symbol+type+bar_index dedup."""

    def __init__(self, path: Path | str, *, max_memory_keys: int = 4096) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[tuple[str, str, int | str | None]] = set()
        self._max_memory_keys = max_memory_keys
        self._load_existing_keys()

    def _load_existing_keys(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._seen.add(_dedup_key(rec))
        except OSError:
            return
        self._trim()

    def _trim(self) -> None:
        if len(self._seen) <= self._max_memory_keys:
            return
        keys = list(self._seen)
        self._seen = set(keys[-self._max_memory_keys :])

    def is_duplicate(self, rec: dict[str, Any]) -> bool:
        return _dedup_key(rec) in self._seen

    def append(self, rec: dict[str, Any]) -> bool:
        """Append record if not a duplicate. True if written."""
        key = _dedup_key(rec)
        if key in self._seen:
            return False
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self._seen.add(key)
        self._trim()
        return True

    def append_many(self, records: Iterable[dict[str, Any]]) -> int:
        n = 0
        for rec in records:
            if self.append(rec):
                n += 1
        return n
