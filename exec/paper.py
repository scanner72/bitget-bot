"""Paper execution: fills + open positions, no exchange keys."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from risk.gate import RiskGate

from exec.account import PaperAccount, get_account

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILLS_PATH = ROOT / "data" / "paper_fills.jsonl"
DEFAULT_POSITIONS_PATH = ROOT / "data" / "paper_positions.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_path(name: str, default: Path) -> Path:
    load_dotenv(ROOT / ".env", override=False)
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else default


def fills_path() -> Path:
    return _env_path("PAPER_FILLS_PATH", DEFAULT_FILLS_PATH)


def positions_path() -> Path:
    return _env_path("PAPER_POSITIONS_PATH", DEFAULT_POSITIONS_PATH)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _load_positions(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or positions_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("positions") or raw.get("open") or []
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _save_positions(positions: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or positions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_ts": _utc_now().isoformat(),
        "positions": positions,
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(p)


def _qty_from_size(size_usd: float, price: float) -> float:
    px = float(price)
    if px <= 0:
        raise ValueError(f"invalid price: {price}")
    return float(size_usd) / px


def _realize_pnl(side: str, entry: float, exit_px: float, size_usd: float) -> float:
    """USD PnL from notional size (linear). long: size*(exit/entry-1); short: inverse."""
    entry = float(entry)
    exit_px = float(exit_px)
    size_usd = float(size_usd)
    if entry <= 0:
        return 0.0
    ret = (exit_px / entry) - 1.0
    s = str(side).lower().strip()
    if s in {"short", "sell"}:
        return size_usd * (-ret)
    return size_usd * ret




def unrealized_pnl_usd(side: str, entry: float, mark: float, size_usd: float) -> float:
    """Unrealized USD PnL (same linear formula as realized close)."""
    return _realize_pnl(side, entry, mark, size_usd)


def enrich_position_mtm(
    pos: dict[str, Any],
    *,
    mark_price: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Attach mark_price / unrealized_pnl_usd / unrealized_pnl_pct to a position dict.

    On failure (no mark or error note): upnl fields are null and ``mtm_error`` is set.
    Existing position fields are preserved.
    """
    out = dict(pos)
    if error or mark_price is None:
        out["mark_price"] = None
        out["unrealized_pnl_usd"] = None
        out["unrealized_pnl_pct"] = None
        out["mtm_error"] = str(error) if error else "no_mark_price"
        return out
    try:
        mark = float(mark_price)
        entry = float(pos.get("entry_price") or 0)
        size_usd = float(pos.get("size_usd") or 0)
        side = str(pos.get("side") or "long")
        if mark <= 0 or entry <= 0 or size_usd <= 0:
            out["mark_price"] = mark if mark > 0 else None
            out["unrealized_pnl_usd"] = None
            out["unrealized_pnl_pct"] = None
            out["mtm_error"] = "invalid_entry_or_size_or_mark"
            return out
        upnl = unrealized_pnl_usd(side, entry, mark, size_usd)
        pct = (upnl / size_usd) * 100.0
        out["mark_price"] = mark
        out["unrealized_pnl_usd"] = upnl
        out["unrealized_pnl_pct"] = pct
        out.pop("mtm_error", None)
        return out
    except Exception as exc:  # noqa: BLE001 — never crash callers
        out["mark_price"] = None
        out["unrealized_pnl_usd"] = None
        out["unrealized_pnl_pct"] = None
        out["mtm_error"] = str(exc)
        return out


def list_open_with_pnl(
    *,
    book: "PaperBook | None" = None,
    exchange: Any | None = None,
    price_fn: Any | None = None,
) -> tuple[list[dict[str, Any]], float | None, list[str]]:
    """List open positions enriched with mark / unrealized PnL.

    Returns (positions, total_unrealized_pnl, error_notes).
    total_unrealized_pnl is the sum of successful upnls, or None if every
    open position failed to price (or there are no opens with prices).
    ``price_fn(symbol) -> float`` overrides the live ticker (for tests).
    """
    positions = list_open(book=book) if book is None else book.list_open()
    if not positions:
        return [], 0.0, []

    if price_fn is None:
        from ingest.bitget_ohlcv import fetch_mark_price

        def _default_price(sym: str) -> float:
            return fetch_mark_price(sym, exchange=exchange)

        price_fn = _default_price

    enriched: list[dict[str, Any]] = []
    errors: list[str] = []
    total = 0.0
    priced = 0
    for pos in positions:
        sym = str(pos.get("symbol") or "")
        try:
            mark = float(price_fn(sym))
            row = enrich_position_mtm(pos, mark_price=mark)
        except Exception as exc:  # noqa: BLE001
            note = f"{sym}: {exc}"
            errors.append(note)
            row = enrich_position_mtm(pos, mark_price=None, error=note)
        enriched.append(row)
        upnl = row.get("unrealized_pnl_usd")
        if upnl is not None:
            total += float(upnl)
            priced += 1
    total_out: float | None
    if priced == 0 and positions:
        total_out = None
    else:
        total_out = total
    return enriched, total_out, errors

@dataclass
class PaperBook:
    """In-process paper book backed by JSON / JSONL on disk."""

    gate: RiskGate | None = None
    fills_file: Path | None = None
    positions_file: Path | None = None
    account: PaperAccount | None = None
    _positions: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.fills_file = Path(self.fills_file) if self.fills_file else fills_path()
        self.positions_file = (
            Path(self.positions_file) if self.positions_file else positions_path()
        )
        if self.account is None:
            self.account = get_account()
        self._positions = _load_positions(self.positions_file)

    def list_open(self) -> list[dict[str, Any]]:
        self._positions = _load_positions(self.positions_file)
        return [dict(p) for p in self._positions]

    def open_paper(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        price: float,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Open a paper position. Returns position_id. Appends fill + risk.record_open."""
        symbol = str(symbol).strip()
        side = str(side).lower().strip()
        size_usd = float(size_usd)
        price = float(price)
        if not symbol:
            raise ValueError("symbol required")
        if side not in {"long", "short", "buy", "sell"}:
            raise ValueError(f"invalid side: {side}")
        if side == "buy":
            side = "long"
        if side == "sell":
            side = "short"
        if size_usd <= 0:
            raise ValueError("size_usd must be > 0")
        if price <= 0:
            raise ValueError("price must be > 0")

        acct = self.account or get_account()
        ok, reason = acct.can_open(size_usd)
        if not ok:
            raise ValueError(reason)

        qty = _qty_from_size(size_usd, price)
        position_id = _new_id("pos")
        fill_id = _new_id("fill")
        now = _utc_now()
        iso = now.isoformat()
        meta = dict(meta or {})
        # Attach ATR SL/TP levels (from meta or caller-provided)
        from risk.atr import levels_dict_for_position

        level_keys = ("atr", "sl", "tp1", "tp2", "atr_pct", "original_sl")
        levels = levels_dict_for_position(meta)
        if "sl" in levels and "original_sl" not in meta:
            meta["original_sl"] = levels["sl"]
            levels["original_sl"] = levels["sl"]
        for k in level_keys:
            if k in levels:
                meta[k] = levels[k]
            elif k in meta and meta[k] is not None:
                try:
                    levels[k] = float(meta[k])
                except (TypeError, ValueError):
                    pass
        meta.setdefault("tp1_hit", False)
        meta.setdefault("trailing_active", False)

        fill = {
            "ts": iso,
            "fill_id": fill_id,
            "position_id": position_id,
            "event": "open",
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "qty": qty,
            "price": price,
            "realized_pnl": 0.0,
            "meta": meta,
        }
        _append_jsonl(self.fills_file, fill)

        pos = {
            "position_id": position_id,
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "qty": qty,
            "entry_price": price,
            "opened_ts": iso,
            "open_fill_id": fill_id,
            "meta": meta,
        }
        for k, v in levels.items():
            pos[k] = v
        pos["tp1_hit"] = bool(meta.get("tp1_hit", False))
        pos["trailing_active"] = bool(meta.get("trailing_active", False))
        self._positions = _load_positions(self.positions_file)
        self._positions.append(pos)
        _save_positions(self._positions, self.positions_file)

        acct.lock_open(size_usd)

        if self.gate is not None:
            self.gate.record_open(
                symbol,
                size_usd,
                meta={
                    "position_id": position_id,
                    "fill_id": fill_id,
                    "side": side,
                    "price": price,
                    **meta,
                },
                ts=now,
            )

        print(
            f"[PAPER] OPEN {position_id} {side} {size_usd} {symbol} @ {price} "
            f"fill={fill_id}"
        )
        return position_id

    def update_position(
        self,
        position_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge fields into an open position (top + meta). Persists JSON."""
        pid = str(position_id).strip()
        if not pid:
            raise ValueError("position_id required")
        self._positions = _load_positions(self.positions_file)
        idx = next(
            (i for i, row in enumerate(self._positions) if row.get("position_id") == pid),
            None,
        )
        if idx is None:
            raise KeyError(f"no open paper position for {pid!r}")
        pos = dict(self._positions[idx])
        meta = dict(pos.get("meta") or {})
        for k, v in dict(updates or {}).items():
            if k == "meta" and isinstance(v, dict):
                meta.update(v)
                continue
            pos[k] = v
            meta[k] = v
        for k in (
            "sl", "tp1", "tp2", "atr", "atr_pct", "original_sl",
            "trailing_active", "trail_price", "tp1_hit", "tp1_hit_ts",
            "be_timeout", "be_timeout_ts", "exit_status",
        ):
            if k in pos and pos[k] is not None:
                meta[k] = pos[k]
        pos["meta"] = meta
        self._positions[idx] = pos
        _save_positions(self._positions, self.positions_file)
        return dict(pos)

    def close_paper(
        self,
        position_id_or_symbol: str,
        price: float,
        *,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close by position_id or symbol. Realizes PnL; fill + risk.record_close."""
        key = str(position_id_or_symbol).strip()
        price = float(price)
        if price <= 0:
            raise ValueError("price must be > 0")

        self._positions = _load_positions(self.positions_file)
        idx = next(
            (i for i, p in enumerate(self._positions) if p.get("position_id") == key),
            None,
        )
        if idx is None:
            idx = next(
                (i for i, p in enumerate(self._positions) if p.get("symbol") == key),
                None,
            )
        if idx is None:
            raise KeyError(f"no open paper position for {key!r}")

        pos = self._positions.pop(idx)
        _save_positions(self._positions, self.positions_file)

        entry = float(pos.get("entry_price") or 0)
        size_usd = float(pos.get("size_usd") or 0)
        side = str(pos.get("side") or "long")
        symbol = str(pos.get("symbol") or "")
        qty = float(pos.get("qty") or _qty_from_size(size_usd, entry if entry else price))
        pnl = _realize_pnl(side, entry, price, size_usd)
        fill_id = _new_id("fill")
        now = _utc_now()
        iso = now.isoformat()
        close_meta = dict(meta or {})

        fill = {
            "ts": iso,
            "fill_id": fill_id,
            "position_id": pos.get("position_id"),
            "event": "close",
            "symbol": symbol,
            "side": side,
            "size_usd": size_usd,
            "qty": qty,
            "price": price,
            "entry_price": entry,
            "realized_pnl": pnl,
            "meta": close_meta,
        }
        _append_jsonl(self.fills_file, fill)

        acct = self.account or get_account()
        acct.release_close(size_usd, pnl)

        if self.gate is not None:
            self.gate.record_close(
                symbol,
                realized_pnl=pnl,
                meta={
                    "position_id": pos.get("position_id"),
                    "fill_id": fill_id,
                    "price": price,
                    **close_meta,
                },
                ts=now,
            )

        print(
            f"[PAPER] CLOSE {pos.get('position_id')} {side} {symbol} @ {price} "
            f"pnl={pnl:.4f} fill={fill_id}"
        )
        return {
            "position_id": pos.get("position_id"),
            "fill_id": fill_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "exit_price": price,
            "size_usd": size_usd,
            "qty": qty,
            "realized_pnl": pnl,
            "exit_status": close_meta.get("exit_status"),
            "remaining_size_usd": 0.0,
        }

    def reduce_paper(
        self,
        position_id_or_symbol: str,
        price: float,
        *,
        fraction: float,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close a fraction of the position; runner stays open. Full-close if leftover is dust."""
        frac = float(fraction)
        if frac <= 0:
            raise ValueError("fraction must be > 0")
        if frac >= 1.0:
            return self.close_paper(position_id_or_symbol, price, meta=meta)

        key = str(position_id_or_symbol).strip()
        price = float(price)
        if price <= 0:
            raise ValueError("price must be > 0")

        self._positions = _load_positions(self.positions_file)
        idx = next(
            (i for i, p in enumerate(self._positions) if p.get("position_id") == key),
            None,
        )
        if idx is None:
            idx = next(
                (i for i, p in enumerate(self._positions) if p.get("symbol") == key),
                None,
            )
        if idx is None:
            raise KeyError(f"no open paper position for {key!r}")

        pos = dict(self._positions[idx])
        entry = float(pos.get("entry_price") or 0)
        size_usd = float(pos.get("size_usd") or 0)
        side = str(pos.get("side") or "long")
        symbol = str(pos.get("symbol") or "")
        qty = float(pos.get("qty") or _qty_from_size(size_usd, entry if entry else price))
        close_usd = size_usd * frac
        close_qty = qty * frac
        remain_usd = size_usd - close_usd
        remain_qty = qty - close_qty
        min_left = 1.0
        try:
            min_left = max(1.0, float(os.getenv("MIN_NOTIONAL_USD") or "10"))
        except ValueError:
            min_left = 10.0
        if remain_usd < min_left or remain_qty <= 0:
            return self.close_paper(position_id_or_symbol, price, meta=meta)

        pnl = _realize_pnl(side, entry, price, close_usd)
        fill_id = _new_id("fill")
        now = _utc_now()
        iso = now.isoformat()
        close_meta = dict(meta or {})
        close_meta["partial"] = True
        close_meta["remaining_size_usd"] = remain_usd

        fill = {
            "ts": iso,
            "fill_id": fill_id,
            "position_id": pos.get("position_id"),
            "event": "close",
            "symbol": symbol,
            "side": side,
            "size_usd": close_usd,
            "qty": close_qty,
            "price": price,
            "entry_price": entry,
            "realized_pnl": pnl,
            "meta": close_meta,
        }
        _append_jsonl(self.fills_file, fill)

        pos["size_usd"] = remain_usd
        pos["qty"] = remain_qty
        meta_pos = dict(pos.get("meta") or {})
        meta_pos["size_usd"] = remain_usd
        meta_pos["qty"] = remain_qty
        meta_pos["tp1_partial"] = True
        pos["meta"] = meta_pos
        self._positions[idx] = pos
        _save_positions(self._positions, self.positions_file)

        acct = self.account or get_account()
        acct.release_close(close_usd, pnl)

        if self.gate is not None:
            self.gate.record_reduce(
                symbol,
                realized_pnl=pnl,
                remaining_size_usd=remain_usd,
                meta={
                    "position_id": pos.get("position_id"),
                    "fill_id": fill_id,
                    "price": price,
                    **close_meta,
                },
                ts=now,
            )

        print(
            f"[PAPER] REDUCE {pos.get('position_id')} {side} {symbol} @ {price} "
            f"frac={frac} pnl={pnl:.4f} left={remain_usd:.4f} fill={fill_id}"
        )
        return {
            "position_id": pos.get("position_id"),
            "fill_id": fill_id,
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "exit_price": price,
            "size_usd": close_usd,
            "qty": close_qty,
            "realized_pnl": pnl,
            "exit_status": close_meta.get("exit_status"),
            "remaining_size_usd": remain_usd,
            "remaining_qty": remain_qty,
            "partial": True,
        }


# Module-level default book (lazy); pipeline may pass an explicit gate.
_default_book: PaperBook | None = None


def _book(gate: RiskGate | None = None) -> PaperBook:
    global _default_book
    if gate is not None:
        return PaperBook(gate=gate)
    if _default_book is None:
        _default_book = PaperBook()
    return _default_book


def open_paper(
    symbol: str,
    side: str,
    size_usd: float,
    price: float,
    meta: dict[str, Any] | None = None,
    *,
    gate: RiskGate | None = None,
    book: PaperBook | None = None,
) -> str:
    b = book or _book(gate)
    if gate is not None and book is None:
        b.gate = gate
    return b.open_paper(symbol, side, size_usd, price, meta)


def close_paper(
    position_id_or_symbol: str,
    price: float,
    *,
    meta: dict[str, Any] | None = None,
    gate: RiskGate | None = None,
    book: PaperBook | None = None,
) -> dict[str, Any]:
    b = book or _book(gate)
    if gate is not None and book is None:
        b.gate = gate
    return b.close_paper(position_id_or_symbol, price, meta=meta)


def reduce_paper(
    position_id_or_symbol: str,
    price: float,
    *,
    fraction: float,
    meta: dict[str, Any] | None = None,
    gate: RiskGate | None = None,
    book: PaperBook | None = None,
) -> dict[str, Any]:
    b = book or _book(gate)
    if gate is not None and book is None:
        b.gate = gate
    return b.reduce_paper(
        position_id_or_symbol, price, fraction=fraction, meta=meta
    )


def list_open(
    *,
    book: PaperBook | None = None,
) -> list[dict[str, Any]]:
    b = book or _book()
    return b.list_open()


# --- back-compat stub API ---
@dataclass
class PaperFill:
    ts: datetime
    symbol: str
    side: str
    qty: float
    price: float
    meta: dict[str, Any] = field(default_factory=dict)


_FILLS: list[PaperFill] = []


def paper_fill(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    **meta: Any,
) -> PaperFill:
    """Legacy in-memory fill helper (kept for early stubs)."""
    fill = PaperFill(
        ts=_utc_now(),
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        meta=dict(meta),
    )
    _FILLS.append(fill)
    print(f"[PAPER] {fill.ts.isoformat()} {side} {qty} {symbol} @ {price} meta={meta}")
    return fill


def get_fills() -> list[PaperFill]:
    return list(_FILLS)
