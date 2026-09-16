"""Append-only candidate JSONL with in-process + file-backed dedup."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Legacy rows used relative OHLCV window index (0-199). Never treat that as identity.
_MISSING_BAR_TS = "no_bar_ts"


def _normalize_bar_ts(value: Any) -> str | None:
    """Stable UTC candle id. Rejects relative bar_index ints like 193/194."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, datetime):
        # Unix ms/sec clocks are 10+ digits; window indexes are 0-199.
        if abs(float(value)) < 1_000_000_000:
            return None
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
        if n >= 1e12:
            dt = datetime.fromtimestamp(n / 1000.0, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(n, tz=timezone.utc)
        return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.isdigit() and len(s) < 10:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    bar_ts = _normalize_bar_ts(signal.get("bar_ts"))
    if bar_ts is None and signal.get("df") is not None:
        try:
            from signals.engine import bar_ts_iso

            bar_ts = _normalize_bar_ts(bar_ts_iso(signal["df"], bar_index))
        except Exception:  # noqa: BLE001
            bar_ts = None

    rec: dict[str, Any] = {
        "ts": now.isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "type": str(signal.get("type", "")),
        "price": _f("price"),
        "level_price": _f("level_price"),
        "rsi": _f("rsi"),
        "bar_index": bar_index,
    }
    if bar_ts:
        rec["bar_ts"] = bar_ts
    return rec


def _dedup_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    """Identity is symbol + type + candle time, not the 200-bar window index."""
    bar_ts = _normalize_bar_ts(rec.get("bar_ts"))
    if not bar_ts:
        bar_ts = _MISSING_BAR_TS
    return (str(rec.get("symbol", "")), str(rec.get("type", "")), bar_ts)


class CandidateLog:
    """JSONL candidate store with symbol+type+bar_ts dedup."""

    def __init__(self, path: Path | str, *, max_memory_keys: int = 4096) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[tuple[str, str, str]] = set()
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
                    key = _dedup_key(rec)
                    # Old rows keyed on relative bar_index (193/194). Skip so they
                    # cannot block a new candle of the same symbol+type.
                    if key[2] == _MISSING_BAR_TS:
                        continue
                    self._seen.add(key)
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
