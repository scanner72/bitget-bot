"""Export paper / Demo fills to the Bitget S2 Trading Agent checklist log.

Reads the desk's native ``data/paper_fills.jsonl`` (optional ``decisions.jsonl``)
and writes CSV + JSONL with: timestamp, trading pair, direction, price,
quantity, account balance change, status, mode.

This log is Bitget Demo UTA / paper shadow / paper-live fallback — **not**
live mainnet. ``BITGET_ALLOW_LIVE`` stays 0.

If local ``data/`` logs are missing (they are gitignored), the in-repo sample
fixture is used so the script still runs offline.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_FILLS = ROOT / "data" / "paper_fills.jsonl"
DEFAULT_DECISIONS = ROOT / "data" / "decisions.jsonl"
SAMPLE_FILLS = ROOT / "docs" / "evidence" / "fixtures" / "paper_fills.sample.jsonl"
SAMPLE_DECISIONS = ROOT / "docs" / "evidence" / "fixtures" / "decisions.sample.jsonl"
DESK_FILLS = ROOT / "docs" / "evidence" / "fixtures" / "paper_fills.desk.jsonl"
DEFAULT_CSV = ROOT / "docs" / "evidence" / "paper_trading_log.csv"
DEFAULT_JSONL = ROOT / "docs" / "evidence" / "paper_trading_log.jsonl"
SAMPLE_CSV = ROOT / "docs" / "evidence" / "paper_trading_log.sample.csv"
SAMPLE_JSONL = ROOT / "docs" / "evidence" / "paper_trading_log.sample.jsonl"

DEFAULT_START_BALANCE = 10000.0

CHECKLIST_COLUMNS = (
    "timestamp",
    "trading_pair",
    "direction",
    "price",
    "quantity",
    "account_balance_change",
    "status",
    "mode",
)
EXTRA_COLUMNS = (
    "event",
    "size_usd",
    "realized_pnl",
    "cash_change",
    "cash_after",
    "equity_after",
    "fill_id",
    "position_id",
    "label",
    "source",
    "signal_type",
    "exit_status",
)
ALL_COLUMNS = CHECKLIST_COLUMNS + EXTRA_COLUMNS

_SECRET_KEY = re.compile(
    r"(api[_-]?key|secret|passphrase|password|token|authorization|private[_-]?key)",
    re.I,
)


def _f(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_num(value: Any, ndp: int = 10) -> str:
    if value is None or value == "":
        return ""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    if n != n:  # NaN
        return ""
    s = f"{n:.{ndp}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("meta")
    return dict(raw) if isinstance(raw, dict) else {}


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] in "{[":
        try:
            blob = json.loads(text)
        except json.JSONDecodeError:
            blob = None
        if isinstance(blob, list):
            return [x for x in blob if isinstance(x, dict)]
        if isinstance(blob, dict):
            for key in ("fills", "decisions", "trades", "list"):
                items = blob.get(key)
                if isinstance(items, list):
                    return [x for x in items if isinstance(x, dict)]
            if any(k in blob for k in ("event", "symbol", "side", "fill_id")):
                return [blob]
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def normalize_fill(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map a paper fill or GET /fills row onto a common dict. Skip junk."""
    meta = _meta(raw)
    event = str(raw.get("event") or raw.get("trade_side") or raw.get("tradeSide") or "").lower()
    if event in {"buy", "sell"}:
        event = "open"
    if event not in {"open", "close"}:
        return None
    symbol = str(raw.get("symbol") or "").strip()
    if not symbol:
        return None
    side = str(raw.get("side") or "").lower().strip()
    if side in {"buy", "long"}:
        side = "long"
    elif side in {"sell", "short"}:
        side = "short"
    else:
        return None
    price = _f(raw.get("price") if raw.get("price") is not None else raw.get("execPrice"), None)
    qty = _f(raw.get("qty") if raw.get("qty") is not None else raw.get("execQty"), None)
    size_usd = _f(raw.get("size_usd"), None)
    if size_usd is None and price and qty and price > 0 and qty > 0:
        size_usd = abs(price * qty)
    if price is None or price <= 0 or qty is None or qty <= 0:
        return None
    pnl = _f(raw.get("realized_pnl"), None)
    if pnl is None:
        pnl = _f(raw.get("exec_pnl") if raw.get("exec_pnl") is not None else raw.get("execPnl"), 0.0)
    if event == "open":
        pnl = 0.0
    return {
        "ts": str(raw.get("ts") or raw.get("timestamp") or ""),
        "symbol": symbol,
        "side": side,
        "price": float(price),
        "qty": float(qty),
        "size_usd": float(size_usd) if size_usd is not None else None,
        "event": event,
        "realized_pnl": float(pnl or 0.0),
        "fill_id": str(raw.get("fill_id") or raw.get("order_id") or raw.get("orderId") or ""),
        "position_id": str(raw.get("position_id") or raw.get("bot_position_id") or ""),
        "meta": meta,
        "raw_source": str(raw.get("source") or ""),
        "exit_status": str(meta.get("exit_status") or raw.get("bot_exit_status") or raw.get("exit_status") or ""),
    }


def infer_mode(fill: dict[str, Any]) -> str:
    meta = fill.get("meta") if isinstance(fill.get("meta"), dict) else {}
    venue = str(meta.get("exec_venue") or "").lower()
    source = str(fill.get("raw_source") or "").lower()
    if venue == "paper" or source == "paper_live":
        return "paper_live"
    if (
        venue == "hub"
        or source in {"hub_demo", "hub"}
        or meta.get("hub_order_id")
        or meta.get("hub_close_order_id")
    ):
        return "hub_demo"
    if source == "paper":
        return "paper_shadow"
    return "paper_shadow"


def keep_uta_demo_fills(raw_fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep fills for positions that hit Bitget UTA Demo. Drop paper-live fallback."""
    tagged: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for raw in raw_fills:
        row = normalize_fill(raw)
        if row is None:
            continue
        tagged.append((raw, row, infer_mode(row)))
    hub_pids = {
        str(row.get("position_id") or "")
        for _raw, row, mode in tagged
        if mode == "hub_demo" and row.get("position_id")
    }
    return [raw for raw, row, _mode in tagged if str(row.get("position_id") or "") in hub_pids]


def _decision_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for rec in rows:
        for key in (rec.get("fill_id"), rec.get("position_id")):
            k = str(key or "").strip()
            if k and k not in idx:
                idx[k] = rec
    return idx


def _signal_type(fill: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> str:
    meta = fill.get("meta") if isinstance(fill.get("meta"), dict) else {}
    if meta.get("type"):
        return str(meta.get("type"))
    for key in (fill.get("fill_id"), fill.get("position_id")):
        dec = decisions.get(str(key or ""))
        if dec and dec.get("type"):
            return str(dec.get("type"))
    return ""


def build_rows(
    fills: list[dict[str, Any]],
    *,
    decisions: list[dict[str, Any]] | None = None,
    start_balance: float = DEFAULT_START_BALANCE,
    label: str = "DEMO",
) -> list[dict[str, Any]]:
    """Walk fills in time order and reconstruct paper cash / equity."""
    indexed = _decision_index(decisions or [])
    normalized: list[dict[str, Any]] = []
    for raw in fills:
        row = normalize_fill(raw)
        if row is not None:
            normalized.append(row)
    normalized.sort(key=lambda r: (str(r.get("ts") or ""), str(r.get("fill_id") or "")))

    cash = float(start_balance)
    equity = float(start_balance)
    out: list[dict[str, Any]] = []
    for fill in normalized:
        event = fill["event"]
        size = float(fill["size_usd"] or 0.0)
        pnl = float(fill["realized_pnl"] or 0.0)
        if event == "open":
            cash_change = -size
            equity_change = 0.0
            cash -= size
        else:
            cash_change = size + pnl
            equity_change = pnl
            cash += size + pnl
            equity += pnl
        mode = infer_mode(fill)
        source = mode
        out.append(
            {
                "timestamp": fill["ts"],
                "trading_pair": fill["symbol"],
                "direction": fill["side"],
                "price": _fmt_num(fill["price"]),
                "quantity": _fmt_num(fill["qty"], 12),
                "account_balance_change": _fmt_num(equity_change, 8),
                "status": "filled",
                "mode": mode,
                "event": event,
                "size_usd": _fmt_num(size, 8),
                "realized_pnl": _fmt_num(pnl, 8),
                "cash_change": _fmt_num(cash_change, 8),
                "cash_after": _fmt_num(cash, 8),
                "equity_after": _fmt_num(equity, 8),
                "fill_id": fill["fill_id"],
                "position_id": fill["position_id"],
                "label": label,
                "source": source,
                "signal_type": _signal_type(fill, indexed),
                "exit_status": fill.get("exit_status") or "",
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ALL_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in ALL_COLUMNS})


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            clean = {k: row.get(k, "") for k in ALL_COLUMNS if not _SECRET_KEY.search(k)}
            fh.write(json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n")


def resolve_inputs(
    *,
    fills_path: Path | None,
    decisions_path: Path | None,
    from_sample: bool,
    from_desk: bool = False,
) -> tuple[Path, Path | None, str, str]:
    """Return (fills, decisions|None, label_hint, note)."""
    if from_sample:
        return SAMPLE_FILLS, SAMPLE_DECISIONS if SAMPLE_DECISIONS.exists() else None, "SIMULATED_DEMO", "fixture"
    if from_desk:
        return DESK_FILLS, None, "DEMO", "desk_fixture"
    fills = Path(fills_path) if fills_path else DEFAULT_FILLS
    decisions = Path(decisions_path) if decisions_path else DEFAULT_DECISIONS
    if fills.exists() and _load_json_records(fills):
        dec = decisions if decisions.exists() else None
        return fills, dec, "DEMO", "local_data"
    # Prefer this desk's committed fills over the 7-row SIMULATED_DEMO sample
    # so a clone without gitignored data/ does not wipe the public S2 log.
    if DESK_FILLS.exists() and _load_json_records(DESK_FILLS):
        return DESK_FILLS, None, "DEMO", "desk_fixture"
    if SAMPLE_FILLS.exists():
        return (
            SAMPLE_FILLS,
            SAMPLE_DECISIONS if SAMPLE_DECISIONS.exists() else None,
            "SIMULATED_DEMO",
            "fixture_fallback",
        )
    return fills, decisions if decisions.exists() else None, "DEMO", "missing"


def start_balance_from_env(explicit: float | None = None) -> float:
    if explicit is not None:
        return float(explicit)
    raw = (os.getenv("PAPER_START_BALANCE_USD") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_START_BALANCE


def export_log(
    *,
    fills_path: Path,
    decisions_path: Path | None,
    out_csv: Path,
    out_jsonl: Path,
    start_balance: float,
    label: str,
    write_sample: bool = False,
    demo_only: bool = False,
) -> list[dict[str, Any]]:
    fills = _load_json_records(fills_path)
    if demo_only:
        fills = keep_uta_demo_fills(fills)
    decisions = _load_json_records(decisions_path) if decisions_path else []
    rows = build_rows(fills, decisions=decisions, start_balance=start_balance, label=label)
    write_csv(out_csv, rows)
    write_jsonl(out_jsonl, rows)
    if write_sample:
        write_csv(SAMPLE_CSV, rows)
        write_jsonl(SAMPLE_JSONL, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Export paper/Demo fills to docs/evidence/paper_trading_log.csv "
            "(Bitget S2 checklist fields). Not live mainnet."
        )
    )
    ap.add_argument("--fills", type=Path, default=None, help="paper_fills.jsonl or JSON dump")
    ap.add_argument("--decisions", type=Path, default=None, help="optional decisions.jsonl")
    ap.add_argument("--out-csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out-jsonl", type=Path, default=DEFAULT_JSONL)
    ap.add_argument("--start-balance", type=float, default=None)
    ap.add_argument(
        "--label",
        default=None,
        help="Row label. Default DEMO (local data) or SIMULATED_DEMO (fixture).",
    )
    ap.add_argument(
        "--from-sample",
        action="store_true",
        help="Read docs/evidence/fixtures/*.sample.jsonl (offline, no data/).",
    )
    ap.add_argument(
        "--from-desk",
        action="store_true",
        help="Read this desk's committed fills (fixtures/paper_fills.desk.jsonl).",
    )
    ap.add_argument(
        "--demo-only",
        action="store_true",
        help="Keep only UTA Demo positions (hub_demo + shadow closes of those). Drop paper-live.",
    )
    ap.add_argument(
        "--include-paper-live",
        action="store_true",
        help="Do not drop PAPER_FALLBACK fills (overrides --from-desk demo-only default).",
    )
    ap.add_argument(
        "--write-sample",
        action="store_true",
        help="Also write paper_trading_log.sample.csv / .jsonl",
    )
    args = ap.parse_args(argv)
    if args.from_sample and args.from_desk:
        print("error: use only one of --from-sample / --from-desk")
        return 2

    fills, decisions, default_label, origin = resolve_inputs(
        fills_path=args.fills,
        decisions_path=args.decisions,
        from_sample=bool(args.from_sample),
        from_desk=bool(args.from_desk),
    )
    if args.fills is not None and not args.from_sample and not args.from_desk:
        fills = args.fills
        origin = "cli"
        default_label = "DEMO"
    if args.decisions is not None:
        decisions = args.decisions
    if not fills.exists():
        print(f"error: fills not found: {fills}")
        return 1

    label = str(args.label or default_label).strip() or default_label
    if label.upper() in {"LIVE", "MAINNET", "LIVE_MAINNET"}:
        print("error: refusing live/mainnet label; this exporter is Demo/paper only")
        return 2

    start = start_balance_from_env(args.start_balance)
    demo_only = bool(args.demo_only or args.from_desk) and not bool(args.include_paper_live)
    if args.from_sample:
        demo_only = False
    rows = export_log(
        fills_path=fills,
        decisions_path=decisions,
        out_csv=args.out_csv,
        out_jsonl=args.out_jsonl,
        start_balance=start,
        label=label,
        write_sample=bool(args.write_sample),
        demo_only=demo_only,
    )
    realized = 0.0
    for row in rows:
        if row.get("event") == "close":
            realized += float(row.get("realized_pnl") or 0)
    print(
        f"exported {len(rows)} rows from {fills} ({origin}) "
        f"label={label} start_balance={start} realized_pnl={realized:.4f}"
        f"{' demo_only=1' if demo_only else ''}"
    )
    print(f"csv   {args.out_csv}")
    print(f"jsonl {args.out_jsonl}")
    if args.write_sample:
        print(f"sample csv   {SAMPLE_CSV}")
        print(f"sample jsonl {SAMPLE_JSONL}")
    print("NOTE: Bitget Demo UTA / paper shadow — not live mainnet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
