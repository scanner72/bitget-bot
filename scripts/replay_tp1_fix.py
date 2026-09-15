"""Counterfactual replay of closed desk trades under the TP1 50% + 0.5% ATR floor.

Reads docs/evidence/fixtures/paper_fills.desk.jsonl (actual Demo/paper-shadow
round-trips), rebuilds ATR levels with ATR_FLOOR_PCT=0.005, then walks 15m
Bitget candles through risk.exits.evaluate_exit (TP1_CLOSE_FRAC=0.5).

Does not rewrite runtime fills. Output is a what-if table.

  python scripts/replay_tp1_fix.py
  python scripts/replay_tp1_fix.py --self-test   # offline, no network
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ATR_FLOOR_PCT", "0.005")
os.environ.setdefault("TP1_CLOSE_FRAC", "0.5")
os.environ.setdefault("BE_HOURS", "8")
os.environ.setdefault("ENABLE_TRAILING", "true")
os.environ.setdefault("MIN_NOTIONAL_USD", "10")
os.environ.setdefault("MAX_LOSS_PCT_OF_MARGIN", "40")
os.environ.setdefault("DOLLAR_STOP_SL_PCT_THRESHOLD", "0")

from exec.paper import _realize_pnl  # noqa: E402
from risk.atr import ATR_PCT_MAX, compute_atr, levels_from_atr  # noqa: E402
from risk.exits import ExitConfig, apply_position_updates, evaluate_exit  # noqa: E402

FILLS_DEFAULT = ROOT / "docs" / "evidence" / "fixtures" / "paper_fills.desk.jsonl"
OUT_JSON = ROOT / "docs" / "evidence" / "counterfactual_tp1_fix.json"
OUT_CSV = ROOT / "docs" / "evidence" / "counterfactual_tp1_fix.csv"
OUT_MD = ROOT / "docs" / "evidence" / "counterfactual_tp1_fix.md"

# Paper-live SUI was not in the Demo evidence log. Size is unknown; PnL scales
# linearly — report uses $100 notional (same as most early Demo rows).
SUI_EXTRA = {
    "position_id": "sui_paper_live_2026-09-14",
    "symbol": "SUI/USDT:USDT",
    "side": "long",
    "size_usd": 100.0,
    "entry": 0.72904578,
    "opened_ts": "2026-09-14T16:30:00+00:00",
    "closed_ts": "2026-09-15T00:30:00+00:00",
    "actual_pnl": 0.0,
    "actual_status": "trailing_hit",
    "actual_exit": 0.72904578,
    "signal_type": "LEVEL_CROSS_UP",
    "source": "paper_live_reconstructed",
}


def parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def load_fills(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def pair_trades(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    opens: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    for f in fills:
        pid = str(f.get("position_id") or "")
        event = str(f.get("event") or "").lower()
        if event == "open":
            opens[pid] = f
            continue
        if event != "close" or not pid:
            continue
        op = opens.get(pid) or {}
        om = op.get("meta") if isinstance(op.get("meta"), dict) else {}
        cm = f.get("meta") if isinstance(f.get("meta"), dict) else {}
        trades.append(
            {
                "position_id": pid,
                "symbol": f.get("symbol") or op.get("symbol"),
                "side": str(f.get("side") or op.get("side") or "long").lower(),
                "size_usd": float(f.get("size_usd") or op.get("size_usd") or 0),
                "entry": float(op.get("price") or f.get("entry_price") or 0),
                "opened_ts": op.get("ts"),
                "closed_ts": f.get("ts"),
                "actual_pnl": float(f.get("realized_pnl") or 0),
                "actual_status": str(cm.get("exit_status") or ""),
                "actual_exit": float(f.get("price") or 0),
                "signal_type": cm.get("type") or om.get("type") or "",
                "source": f.get("source") or op.get("source") or "",
            }
        )
    open_only = {pid: op for pid, op in opens.items() if pid not in {t["position_id"] for t in trades}}
    for pid, op in open_only.items():
        om = op.get("meta") if isinstance(op.get("meta"), dict) else {}
        trades.append(
            {
                "position_id": pid,
                "symbol": op.get("symbol"),
                "side": str(op.get("side") or "long").lower(),
                "size_usd": float(op.get("size_usd") or 0),
                "entry": float(op.get("price") or 0),
                "opened_ts": op.get("ts"),
                "closed_ts": None,
                "actual_pnl": None,
                "actual_status": "still_open",
                "actual_exit": None,
                "signal_type": om.get("type") or "",
                "source": op.get("source") or "",
            }
        )
    return trades


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = out.index
    if getattr(idx, "tz", None) is None:
        out.index = idx.tz_localize("UTC")
    else:
        out.index = idx.tz_convert("UTC")
    return out.sort_index()


def fetch_ohlcv_range(
    symbol: str,
    *,
    start: datetime,
    end: datetime,
    timeframe: str = "15m",
    limit: int = 200,
    pause_sec: float = 0.12,
) -> pd.DataFrame:
    from ingest.bitget_ohlcv import get_shared_exchange

    ex = get_shared_exchange()
    cursor = int(start.timestamp() * 1000)
    until_ms = int(end.timestamp() * 1000)
    rows: list[list[Any]] = []
    seen_last = -1
    while cursor <= until_ms:
        raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
        time.sleep(pause_sec)
        if not raw:
            break
        rows.extend(raw)
        last = int(raw[-1][0])
        if last <= seen_last:
            break
        seen_last = last
        cursor = last + 1
        if len(raw) < limit:
            break
        if last >= until_ms:
            break
    if not rows:
        raise RuntimeError(f"empty OHLCV for {symbol}")
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def replay_position(
    trade: dict[str, Any],
    df: pd.DataFrame,
    *,
    cfg: ExitConfig | None = None,
    floor_pct: float = 0.005,
    now_cap: datetime | None = None,
) -> dict[str, Any]:
    cfg = cfg or ExitConfig.from_env()
    df = _ensure_utc_index(df)
    opened = parse_ts(trade["opened_ts"])
    if opened is None:
        return {"ok": False, "error": "bad_opened_ts"}
    entry = float(trade["entry"])
    side = str(trade["side"])
    size0 = float(trade["size_usd"])
    if entry <= 0 or size0 <= 0:
        return {"ok": False, "error": "bad_entry_or_size"}

    before = df[df.index < opened]
    if len(before) < 5:
        return {"ok": False, "error": f"atr_lookback_short:{len(before)}"}
    atr = compute_atr(before, period=14, entry=entry, floor_pct=floor_pct)
    if atr is None or atr <= 0:
        return {"ok": False, "error": "no_atr"}
    # Trades that already opened passed atr_pct <= 6%. Do not replay a 26%
    # illiquid wick as if that had been the SL distance.
    atr_cap = entry * (float(ATR_PCT_MAX) / 100.0)
    if atr > atr_cap:
        atr = atr_cap
    levels = levels_from_atr(entry, side, atr)

    pos: dict[str, Any] = {
        "position_id": trade["position_id"],
        "symbol": trade["symbol"],
        "side": side,
        "size_usd": size0,
        "entry_price": entry,
        "opened_ts": opened.isoformat(),
        "atr": levels["atr"],
        "sl": levels["sl"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "atr_pct": levels["atr_pct"],
        "original_sl": levels["sl"],
        "tp1_hit": False,
        "trailing_active": False,
        "meta": dict(levels),
    }
    pos["meta"]["original_sl"] = levels["sl"]
    pos["meta"]["tp1_hit"] = False

    remaining = size0
    realized = 0.0
    events: list[dict[str, Any]] = []
    min_left = 10.0
    after = df[df.index > opened]
    if after.empty:
        return {"ok": False, "error": "no_bars_after_entry", "levels": levels}

    cap = now_cap or datetime.now(timezone.utc)
    exit_status = None
    exit_px = None
    bars = 0
    still_open = True

    for ts, row in after.iterrows():
        if ts.to_pydatetime() > cap:
            break
        bars += 1
        hi = float(row["high"])
        lo = float(row["low"])
        cl = float(row["close"])
        hist = df.loc[:ts]
        ev = evaluate_exit(
            pos,
            candle_high=hi,
            candle_low=lo,
            mark_price=cl,
            df=hist,
            cfg=cfg,
            now=ts.to_pydatetime(),
        )
        if ev.updates:
            pos = apply_position_updates(pos, ev.updates)

        if ev.action == "partial_close" and ev.close_price is not None:
            frac = float(ev.fraction or 0.5)
            take = remaining * frac
            left = remaining - take
            px = float(ev.close_price)
            if left < min_left:
                pnl = _realize_pnl(side, entry, px, remaining)
                realized += pnl
                events.append(
                    {
                        "ts": ts.isoformat(),
                        "status": ev.status,
                        "action": "close_dust",
                        "px": px,
                        "size": remaining,
                        "pnl": pnl,
                    }
                )
                remaining = 0.0
                exit_status = ev.status
                exit_px = px
                still_open = False
                break
            pnl = _realize_pnl(side, entry, px, take)
            realized += pnl
            remaining = left
            pos["size_usd"] = remaining
            events.append(
                {
                    "ts": ts.isoformat(),
                    "status": ev.status,
                    "action": "partial_close",
                    "px": px,
                    "size": take,
                    "pnl": pnl,
                    "remaining": remaining,
                }
            )
            continue

        if ev.action == "close" and ev.close_price is not None:
            px = float(ev.close_price)
            pnl = _realize_pnl(side, entry, px, remaining)
            realized += pnl
            events.append(
                {
                    "ts": ts.isoformat(),
                    "status": ev.status,
                    "action": "close",
                    "px": px,
                    "size": remaining,
                    "pnl": pnl,
                }
            )
            remaining = 0.0
            exit_status = ev.status
            exit_px = px
            still_open = False
            break

    mtm = 0.0
    last_px = float(after["close"].iloc[-1]) if len(after) else entry
    if still_open and remaining > 0:
        last_bar = after[after.index <= cap]
        if len(last_bar):
            last_px = float(last_bar["close"].iloc[-1])
        mtm = _realize_pnl(side, entry, last_px, remaining)
        exit_status = "open_mtm"
        exit_px = last_px

    legs = "+".join(
        f"{e['status']}@{e['px']:.6g}({e['pnl']:+.2f})" for e in events
    ) or exit_status or "?"
    return {
        "ok": True,
        "levels": levels,
        "cf_pnl": round(realized + mtm, 6),
        "cf_realized": round(realized, 6),
        "cf_mtm": round(mtm, 6),
        "cf_status": exit_status,
        "cf_exit": exit_px,
        "cf_legs": legs,
        "tp1_taken": any(e.get("status") == "tp1_hit" for e in events),
        "events": events,
        "bars": bars,
        "remaining": remaining,
        "atr": levels["atr"],
        "atr_pct": levels["atr_pct"],
        "tp1": levels["tp1"],
        "tp2": levels["tp2"],
        "sl": levels["sl"],
    }


def _fmt_pnl(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v):+.2f}"


def write_report(rows: list[dict[str, Any]], path_md: Path, path_json: Path, path_csv: Path) -> None:
    closed = [r for r in rows if r.get("actual_status") != "still_open"]
    actual_sum = sum(float(r["actual_pnl"] or 0) for r in closed if r.get("actual_pnl") is not None)
    cf_sum = sum(float(r["cf_pnl"] or 0) for r in rows if r.get("ok"))
    cf_closed = sum(float(r["cf_pnl"] or 0) for r in closed if r.get("ok"))
    lines = [
        "# Counterfactual PnL — TP1 50% + ATR floor 0.5%",
        "",
        "Replay of this desk’s closed Demo/paper-shadow round-trips with the",
        "post-fix exit rules (`ATR_FLOOR_PCT=0.005`, `TP1_CLOSE_FRAC=0.5`).",
        "Same entries (time, side, size, fill price). New ATR levels from 15m",
        "Bitget candles before the open; then `evaluate_exit` bar-by-bar.",
        "",
        "This does **not** rewrite `data/` fills. SUI paper-live is reconstructed",
        "(not in the Demo evidence log); notional assumed **$100**.",
        "Holds shorter than one 15m bar keep actual PnL (no look-ahead).",
        "ATR is capped at the desk filter `ATR_PCT_MAX=6%`.",
        "",
        f"- Closed trades in log: **{len(closed)}**",
        f"- Actual realized (log): **{_fmt_pnl(actual_sum)} USDT**",
        f"- Counterfactual realized+MTM on those: **{_fmt_pnl(cf_closed)} USDT**",
        f"- Delta: **{_fmt_pnl(cf_closed - actual_sum)} USDT**",
        "",
        "| Pair | Side | Size | Actual | CF | Δ | Actual exit | CF exit | TP1 take |",
        "|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    csv_rows: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "").replace("/USDT:USDT", "")
        actual = r.get("actual_pnl")
        cf = r.get("cf_pnl") if r.get("ok") else None
        delta = (float(cf) - float(actual)) if (cf is not None and actual is not None) else None
        lines.append(
            "| {sym} | {side} | {size:.0f} | {actual} | {cf} | {delta} | {ast} | {cst} | {tp1} |".format(
                sym=sym,
                side=r.get("side"),
                size=float(r.get("size_usd") or 0),
                actual=_fmt_pnl(actual),
                cf=_fmt_pnl(cf) if r.get("ok") else (r.get("error") or "fail"),
                delta=_fmt_pnl(delta),
                ast=r.get("actual_status") or "",
                cst=(r.get("cf_legs") or r.get("cf_status") or "")[:48],
                tp1="yes" if r.get("tp1_taken") else "no",
            )
        )
        csv_rows.append(
            {
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "size_usd": r.get("size_usd"),
                "entry": r.get("entry"),
                "opened_ts": r.get("opened_ts"),
                "actual_pnl": actual,
                "actual_status": r.get("actual_status"),
                "cf_pnl": cf,
                "cf_status": r.get("cf_status"),
                "cf_legs": r.get("cf_legs"),
                "delta": delta,
                "tp1_taken": r.get("tp1_taken"),
                "tp1": r.get("tp1"),
                "tp2": r.get("tp2"),
                "error": r.get("error"),
                "source": r.get("source"),
            }
        )
    zero = [
        r
        for r in closed
        if r.get("actual_pnl") is not None and abs(float(r["actual_pnl"])) < 1e-9
    ]
    z_act = sum(float(r["actual_pnl"] or 0) for r in zero)
    z_cf = sum(float(r["cf_pnl"] or 0) for r in zero if r.get("ok"))
    lines.extend(
        [
            "",
            "## Zero-PnL closes (the 8h BE flats)",
            "",
            f"{len(zero)} closes had actual PnL 0 (`trailing_hit` at entry after `BE_HOURS`).",
            f"Same entries under the fix: **{_fmt_pnl(z_cf)} USDT** (was {_fmt_pnl(z_act)}).",
            "",
            "| Pair | Side | Size | CF PnL | CF path | TP1 |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for r in zero:
        sym = str(r.get("symbol") or "").replace("/USDT:USDT", "")
        lines.append(
            "| {sym} | {side} | {size:.0f} | {cf} | {cst} | {tp1} |".format(
                sym=sym,
                side=r.get("side"),
                size=float(r.get("size_usd") or 0),
                cf=_fmt_pnl(r.get("cf_pnl") if r.get("ok") else None),
                cst=(r.get("cf_legs") or r.get("cf_status") or "")[:56],
                tp1="yes" if r.get("tp1_taken") else "no",
            )
        )
    lines.extend(
        [
            "",
            f"All rows (incl. still-open MTM) CF total: **{_fmt_pnl(cf_sum)} USDT**.",
            "",
            "`exchange_closed` rows are what local ATR exits would have done if the",
            "hub flatten had not already closed the Demo position.",
            "",
        ]
    )
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path_json.write_text(
        json.dumps(
            {
                "asof": datetime.now(timezone.utc).isoformat(),
                "actual_closed_pnl": actual_sum,
                "cf_closed_pnl": cf_closed,
                "delta": cf_closed - actual_sum,
                "trades": rows,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    with path_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["symbol"])
        w.writeheader()
        w.writerows(csv_rows)


def self_test() -> int:
    """Offline: TP1 50% then TP2 on synthetic 15m bars."""
    idx = pd.date_range("2026-09-01 00:00", periods=30, freq="15min", tz="UTC")
    # Quiet ATR ~1 on a 100 entry → floor 0.5 → atr=0.5? mean(high-low)=1
    rows = []
    for i in range(20):
        rows.append((100.0, 100.05, 99.95, 100.0, 1.0))  # range 0.1 → floor 0.5% wins
    # entry at bar 20 05:00
    rows.append((100.0, 100.2, 99.9, 100.0, 1.0))
    # TP1 100.75 (atr floored 0.5 * 1.5) — push to 101 then TP2 101.25
    rows.append((100.0, 100.8, 99.95, 100.6, 1.0))  # TP1
    rows.append((100.6, 101.4, 100.5, 101.3, 1.0))  # TP2
    while len(rows) < 30:
        rows.append((101.3, 101.4, 101.2, 101.3, 1.0))
    df = pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [r[4] for r in rows],
        },
        index=idx,
    )
    trade = {
        "position_id": "t1",
        "symbol": "TEST/USDT:USDT",
        "side": "long",
        "size_usd": 100.0,
        "entry": 100.0,
        "opened_ts": idx[19].isoformat(),
    }
    cfg = ExitConfig(be_hours=8, enable_trailing=True, tp1_close_frac=0.5, max_loss_pct_of_margin=0.0)
    sim = replay_position(trade, df, cfg=cfg, floor_pct=0.005)
    if not sim.get("ok"):
        raise AssertionError(sim)
    if not sim.get("tp1_taken"):
        raise AssertionError(sim)
    if sim.get("cf_status") != "tp2_hit":
        raise AssertionError(sim)
    # 50% at ~100.8 + 50% at TP2 ~101.25 → about +1.025
    if float(sim["cf_pnl"]) < 0.8:
        raise AssertionError(sim)
    fills = [
        {
            "ts": "2026-09-09T13:00:00+00:00",
            "position_id": "p1",
            "event": "open",
            "symbol": "DOGE/USDT:USDT",
            "side": "long",
            "size_usd": 100,
            "price": 0.1,
            "meta": {"type": "BULLISH_DIV"},
        },
        {
            "ts": "2026-09-09T21:00:00+00:00",
            "position_id": "p1",
            "event": "close",
            "symbol": "DOGE/USDT:USDT",
            "side": "long",
            "size_usd": 100,
            "price": 0.1,
            "realized_pnl": 0,
            "meta": {"exit_status": "trailing_hit", "type": "BULLISH_DIV"},
        },
    ]
    paired = pair_trades(fills)
    if len(paired) != 1 or paired[0]["actual_pnl"] != 0:
        raise AssertionError(paired)
    print("replay_tp1_fix self-test OK", sim["cf_pnl"], sim["cf_legs"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fills", type=Path, default=FILLS_DEFAULT)
    ap.add_argument("--no-sui", action="store_true")
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    fills = load_fills(args.fills)
    trades = pair_trades(fills)
    if not args.no_sui:
        trades.append(dict(SUI_EXTRA))

    cfg = ExitConfig.from_env()
    cfg.tp1_close_frac = 0.5
    now = datetime.now(timezone.utc)
    cache: dict[str, pd.DataFrame] = {}
    results: list[dict[str, Any]] = []

    for i, t in enumerate(trades):
        opened = parse_ts(t["opened_ts"])
        if opened is None:
            t.update({"ok": False, "error": "bad_ts"})
            results.append(t)
            continue
        closed_at = parse_ts(t.get("closed_ts"))
        hold_sec = None
        if closed_at is not None:
            hold_sec = (closed_at - opened).total_seconds()
        start = opened - timedelta(days=5)
        end = now + timedelta(minutes=15)
        sym = str(t["symbol"])
        print(f"[{i+1}/{len(trades)}] {sym} {t['side']} {opened.isoformat()} size={t['size_usd']}", flush=True)
        if hold_sec is not None and hold_sec < 15 * 60 and t.get("actual_pnl") is not None:
            sim = {
                "ok": True,
                "cf_pnl": float(t["actual_pnl"]),
                "cf_realized": float(t["actual_pnl"]),
                "cf_mtm": 0.0,
                "cf_status": t.get("actual_status") or "same_bar",
                "cf_exit": t.get("actual_exit"),
                "cf_legs": f"same_bar_keep_actual({hold_sec:.0f}s)",
                "tp1_taken": False,
                "events": [],
                "bars": 0,
                "note": "hold < 15m: 15m replay would look ahead; keep actual PnL",
            }
        else:
            try:
                if sym not in cache:
                    cache[sym] = fetch_ohlcv_range(sym, start=start, end=end)
                sim = replay_position(t, cache[sym], cfg=cfg, floor_pct=0.005, now_cap=now)
            except Exception as exc:  # noqa: BLE001
                sim = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        t.update(sim)
        act = t.get("actual_pnl")
        cf = t.get("cf_pnl")
        print(
            f"    actual={act} {t.get('actual_status')}  cf={cf} {t.get('cf_legs') or t.get('error')}",
            flush=True,
        )
        results.append(t)

    write_report(results, args.out_md, args.out_json, args.out_csv)
    print(f"wrote {args.out_md}")
    print(f"wrote {args.out_csv}")
    print(f"wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
