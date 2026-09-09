"""Retag open paper positions with ATR SL/TP if missing (CRCL/XAG leave SOPH alone).

Fetches TF OHLCV, computes divergent ATR levels, writes into paper_positions.json.
Skips positions that already have sl+tp1 set. Paper only.
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

from dotenv import load_dotenv

from exec.paper import PaperBook, positions_path
from ingest.bitget_ohlcv import fetch_ohlcv
from risk.atr import atr_filter_ok, compute_levels_from_df


def _already_set(pos: dict) -> bool:
    meta = pos.get("meta") if isinstance(pos.get("meta"), dict) else {}
    sl = pos.get("sl", meta.get("sl"))
    tp1 = pos.get("tp1", meta.get("tp1"))
    return sl is not None and tp1 is not None


def retag(
    *,
    symbols: list[str] | None = None,
    timeframe: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    load_dotenv(ROOT / ".env", override=False)
    tf = (timeframe or os.getenv("TIMEFRAME", "15m") or "15m").strip()
    book = PaperBook()
    opens = book.list_open()
    want = None
    if symbols:
        want = {s.strip().upper().replace("-", "/") for s in symbols if s.strip()}
    results: list[dict] = []
    for pos in opens:
        sym = str(pos.get("symbol") or "")
        pid = str(pos.get("position_id") or "")
        sym_u = sym.upper()
        if want is not None:
            # match compact or ccxt
            compact = sym_u.replace("/", "").replace(":USDT", "")
            if sym_u not in want and compact not in want and not any(
                w in sym_u or w.replace("/", "") in compact for w in want
            ):
                continue
        if _already_set(pos) and not force:
            results.append({"position_id": pid, "symbol": sym, "skipped": "already_set"})
            print(f"[retag] skip {sym} {pid}: already has sl/tp1")
            continue
        entry = float(pos.get("entry_price") or 0)
        side = str(pos.get("side") or "long")
        if entry <= 0:
            results.append({"position_id": pid, "symbol": sym, "error": "bad_entry"})
            continue
        try:
            df = fetch_ohlcv(symbol=sym, timeframe=tf, limit=80)
            levels = compute_levels_from_df(entry, side, df)
            if levels is None:
                results.append({"position_id": pid, "symbol": sym, "error": "no_atr"})
                continue
            ok, reason = atr_filter_ok(levels["atr"], entry)
            # Still attach levels even if filter would block *new* opens
            updates = dict(levels)
            updates["original_sl"] = levels["sl"]
            updates["tp1_hit"] = False
            updates["trailing_active"] = False
            updates["retag_atr_filter"] = reason
            print(
                f"[retag] {sym} {pid} entry={entry} atr={levels['atr']:.6g} "
                f"sl={levels['sl']:.6g} tp1={levels['tp1']:.6g} tp2={levels['tp2']:.6g} "
                f"atr_pct={levels['atr_pct']:.3f}% filter={reason}"
            )
            if not dry_run:
                book.update_position(pid, updates)
            results.append(
                {
                    "position_id": pid,
                    "symbol": sym,
                    "levels": levels,
                    "filter": reason,
                    "dry_run": dry_run,
                }
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[retag] ERROR {sym} {pid}: {exc}")
            results.append({"position_id": pid, "symbol": sym, "error": str(exc)})
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retag open paper positions with ATR SL/TP")
    ap.add_argument(
        "--symbols",
        default="CRCL,XAG",
        help="Comma list (default CRCL,XAG). Empty = all open.",
    )
    ap.add_argument("--timeframe", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    syms = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    if args.symbols.strip() == "":
        syms = None
    rows = retag(symbols=syms, timeframe=args.timeframe, force=args.force, dry_run=args.dry_run)
    print(json.dumps({"count": len(rows), "results": rows}, indent=2, default=str))
    print(f"positions_file={positions_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
