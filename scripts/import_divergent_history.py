"""One-shot: import Divergent V1 paper_trades CSV into data/paper_fills.divergent.jsonl."""
from __future__ import annotations
import csv, json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r"C:\Users\User\Desktop\divergent_paper_trades.csv")
OUT = ROOT / "data" / "paper_fills.divergent.jsonl"

def open_csv(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "cp1251", "utf-8"):
        try:
            text = raw.decode(enc)
            # sanity: header contains symbol
            if "symbol" in text.splitlines()[0].lower() or "direction" in text.splitlines()[0].lower():
                return text, enc
        except Exception:
            continue
    raise SystemExit("cannot decode CSV")

def iso(ts: str) -> str:
    ts = (ts or "").strip()
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return ts

def main() -> None:
    text, enc = open_csv(SRC)
    print("encoding", enc)
    rows = list(csv.DictReader(text.splitlines()))
    fills = []
    for r in rows:
        tid = (r.get("id") or "").strip()
        sym = (r.get("symbol") or "").strip()
        side = (r.get("direction") or "").strip().lower()
        if side in ("buy", "long"):
            side = "long"
        elif side in ("sell", "short"):
            side = "short"
        else:
            continue
        try:
            entry = float(r.get("entry_price") or 0)
            qty = float(r.get("quantity") or 0)
            size = float(r.get("position_size_usd") or 0) or (entry * qty)
        except ValueError:
            continue
        opened = iso(r.get("opened_at") or "")
        closed = iso(r.get("closed_at") or "")
        sig = (r.get("signal_type") or "").strip()
        tf = (r.get("timeframe") or "").strip()
        status = (r.get("status") or "").strip()
        close_raw = r.get("close_price")
        pnl_raw = r.get("pnl_usd")
        close_px = float(close_raw) if close_raw not in (None, "") else None
        pnl = float(pnl_raw) if pnl_raw not in (None, "") else 0.0
        pos_id = f"div_v1_{tid}"
        meta_base = {
            "type": sig,
            "timeframe": tf,
            "exec_venue": "paper",
            "label": "DIVERGENT_V1_PAPER_IMPORT",
            "source": "divergent_paper_trades.csv",
            "divergent_trade_id": tid,
            "divergent_status": status,
        }
        if opened:
            fills.append({
                "ts": opened,
                "fill_id": f"{pos_id}_open",
                "position_id": pos_id,
                "event": "open",
                "symbol": sym,
                "side": side,
                "size_usd": size,
                "qty": qty,
                "price": entry,
                "realized_pnl": 0.0,
                "meta": {**meta_base, "action": "ENTER"},
            })
        if closed and close_px is not None:
            fills.append({
                "ts": closed,
                "fill_id": f"{pos_id}_close",
                "position_id": pos_id,
                "event": "close",
                "symbol": sym,
                "side": side,
                "size_usd": size,
                "qty": qty,
                "price": close_px,
                "entry_price": entry,
                "realized_pnl": pnl,
                "meta": {**meta_base, "exit_status": status},
            })
    fills.sort(key=lambda x: x.get("ts") or "")
    OUT.write_text("\n".join(json.dumps(f, ensure_ascii=False) for f in fills) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} fills={len(fills)} opens={sum(1 for f in fills if f['event']=='open')} closes={sum(1 for f in fills if f['event']=='close')} rows={len(rows)}")

if __name__ == "__main__":
    main()
