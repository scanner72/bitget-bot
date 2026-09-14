"""Repair open hub positions missing TPSL: rebase levels on exchange entry.

Usage:
  python scripts/repair_hub_tpsl.py
  python scripts/repair_hub_tpsl.py LTC/USDT:USDT
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    only = argv[0] if argv else None

    from exec.bitget_hub import BitgetUtaClient
    from exec.paper import PaperBook
    from exec.router import (
        _find_hub_position,
        _place_hub_tpsl,
        _recompute_levels_for_entry,
        _safe_float,
        _validate_tpsl_vs_mark,
    )

    client = BitgetUtaClient.from_env()
    book = PaperBook()
    opens = book.list_open()
    if only:
        opens = [
            p
            for p in opens
            if p.get("symbol") == only or only in str(p.get("symbol"))
        ]
    if not opens:
        print("no open paper positions to repair")
        return 0

    for pos in opens:
        sym = str(pos.get("symbol") or "")
        side = str(pos.get("side") or "short")
        pid = str(pos.get("position_id") or "")
        meta = dict(pos.get("meta") or {})
        hub = _find_hub_position(client, sym, side, retries=3, delay_sec=0.25)
        if hub is None:
            print(f"[skip] {sym} not on exchange")
            continue
        entry = _safe_float(hub.get("avgPrice") or hub.get("openPriceAvg"), None)
        mark = _safe_float(hub.get("markPrice"), None) or entry
        if entry is None or entry <= 0:
            print(f"[skip] {sym} no avgPrice")
            continue
        meta.setdefault("signal_price", pos.get("entry_price"))
        levels = _recompute_levels_for_entry(meta, entry=float(entry), side=side)
        sl_ok, tp_ok = _validate_tpsl_vs_mark(
            side, sl=levels["sl"], tp=levels["tp2"], mark=float(mark or entry)
        )
        updates = dict(levels)
        updates["original_sl"] = sl_ok if sl_ok is not None else levels["sl"]
        if sl_ok is not None:
            updates["sl"] = sl_ok
        if tp_ok is not None:
            updates["tp2"] = tp_ok
        updates["hub_entry"] = entry
        updates["hub_mark_at_repair"] = mark
        updates["entry_price"] = entry
        _place_hub_tpsl(
            client,
            sym,
            side,
            stop_loss=sl_ok,
            take_profit=tp_ok,
            meta=updates,
        )
        merged = dict(pos)
        merged["entry_price"] = entry
        for k, v in updates.items():
            merged[k] = v
        meta2 = dict(meta)
        meta2.update(updates)
        merged["meta"] = meta2
        book.update_position(pid, merged)
        print(
            f"[repair] {sym} {pid} entry={entry} mark={mark} "
            f"sl={sl_ok} tp2={tp_ok} tpsl_err={updates.get('hub_tpsl_error')}"
        )
        print(
            json.dumps(
                {
                    k: updates.get(k)
                    for k in (
                        "sl",
                        "tp1",
                        "tp2",
                        "hub_sl_price",
                        "hub_tp2_price",
                        "hub_tpsl_order_id",
                        "hub_tpsl_error",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
