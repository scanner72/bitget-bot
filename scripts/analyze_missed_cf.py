"""Counterfactual PnL for missed entries (ENTER deny / SKIP) over last N hours."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.decide import LONG_TYPES, SHORT_TYPES
from risk.atr import atr_pct, compute_atr, levels_from_atr

HOURS = float(os.getenv("MISS_HOURS", "24"))
OUT = ROOT / "data" / "_missed_cf.json"


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def side_from_type(t: str) -> str | None:
    t = str(t or "").upper()
    if t in LONG_TYPES:
        return "long"
    if t in SHORT_TYPES:
        return "short"
    return None


def load_decisions(since: datetime) -> list[dict]:
    path = ROOT / "data" / "decisions.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get("ts")
        if not ts:
            continue
        try:
            t = parse_ts(ts)
        except Exception:
            continue
        if t < since:
            continue
        rows.append(d)
    return rows


def missed_entries(rows: list[dict]) -> list[dict]:
    out = []
    for d in rows:
        agent = d.get("agent") if isinstance(d.get("agent"), dict) else {}
        action = str(d.get("action") or agent.get("action") or "").upper()
        allowed = d.get("allowed")
        if allowed is None and isinstance(d.get("risk"), dict):
            allowed = d["risk"].get("allowed")
        reason = None
        if isinstance(d.get("risk"), dict):
            reason = d["risk"].get("reason")
        reason = reason or d.get("reason") or agent.get("rationale") or ""
        rules = list(agent.get("rules_fired") or [])
        typ = str(d.get("type") or "")
        side = agent.get("side") or side_from_type(typ)
        price = d.get("price")
        try:
            price_f = float(price) if price is not None else None
        except Exception:
            price_f = None
        if not side or not price_f or price_f <= 0:
            continue
        kind = None
        if action == "SKIP":
            kind = "skip"
            tag = "long_veto" if "long_veto" in rules or "long veto" in str(reason).lower() else "skip"
        elif action == "ENTER" and not allowed:
            kind = "deny"
            tag = str(reason or "deny").split(":")[0][:60]
        else:
            continue
        out.append(
            {
                "ts": d.get("ts"),
                "symbol": d.get("symbol"),
                "type": typ,
                "side": str(side).lower(),
                "price": price_f,
                "kind": kind,
                "tag": tag,
                "size_usd": float(
                    (d.get("risk") or {}).get("proposed_size_usd")
                    or agent.get("size_usd")
                    or 100.0
                ),
            }
        )
    return out


def simulate_trade(symbol: str, side: str, entry: float, entry_ts: datetime, size_usd: float) -> dict:
    """Replay ATR SL/TP1(BE)/TP2/trail-ish with subsequent 15m candles until now."""
    from ingest.bitget_ohlcv import fetch_ohlcv

    # Need history before entry for ATR + after for path
    df = fetch_ohlcv(symbol=symbol, timeframe="15m", limit=200)
    if df is None or len(df) < 30:
        return {"ok": False, "error": "no_ohlcv"}

    # Ensure tz-aware index
    idx = df.index
    if getattr(idx, "tz", None) is None:
        df = df.tz_localize("UTC")
    else:
        df = df.tz_convert("UTC")

    # bars at/after entry
    after = df[df.index >= entry_ts]
    before = df[df.index < entry_ts]
    if len(before) < 14:
        before = df.iloc[: max(14, len(df) // 2)]
    atr = compute_atr(before if len(before) >= 14 else df.iloc[:20], period=14, entry=entry)
    if atr is None or atr <= 0:
        return {"ok": False, "error": "no_atr"}
    levels = levels_from_atr(entry, side, atr)
    sl = float(levels["sl"])
    tp1 = float(levels["tp1"])
    tp2 = float(levels["tp2"])
    original_sl = sl
    tp1_hit = False
    trailing = False
    trail_ext = None
    is_long = side == "long"

    if after.empty:
        # use last close MTM
        last = float(df["close"].iloc[-1])
        pnl = size_usd * ((last - entry) / entry) * (1 if is_long else -1)
        return {
            "ok": True,
            "status": "open_mtm",
            "pnl": pnl,
            "exit_px": last,
            "atr": atr,
            "atr_pct": atr_pct(atr, entry),
            "bars": 0,
        }

    exit_status = None
    exit_px = None
    bars = 0
    for ts, row in after.iterrows():
        bars += 1
        hi = float(row["high"])
        lo = float(row["low"])
        cl = float(row["close"])
        sl_check = lo if is_long else hi
        tp_check = hi if is_long else lo

        # SL
        hit_sl = (sl_check <= sl) if is_long else (sl_check >= sl)
        if hit_sl:
            profitable = (sl >= entry) if is_long else (sl <= entry)
            exit_status = "trailing_hit" if profitable else "sl_hit"
            exit_px = sl if profitable else cl
            break

        # TP2
        hit_tp2 = (tp_check >= tp2) if is_long else (tp_check <= tp2)
        if hit_tp2:
            exit_status = "tp2_hit"
            exit_px = tp2
            break

        # TP1 -> BE
        if not tp1_hit:
            hit_tp1 = (tp_check >= tp1) if is_long else (tp_check <= tp1)
            if hit_tp1:
                tp1_hit = True
                sl = entry

        # Simple trail after TP1: activate at 1x original SL dist, trail 1.5 ATR
        if tp1_hit:
            dist = abs(entry - original_sl)
            if is_long:
                trail_ext = hi if trail_ext is None else max(trail_ext, hi)
                if trail_ext >= entry + dist:
                    trailing = True
                if trailing:
                    cand = trail_ext - max(atr * 1.5, entry * 0.005)
                    sl = max(sl, entry, cand)  # hard BE
            else:
                trail_ext = lo if trail_ext is None else min(trail_ext, lo)
                if trail_ext <= entry - dist:
                    trailing = True
                if trailing:
                    cand = trail_ext + max(atr * 1.5, entry * 0.005)
                    sl = min(sl, entry, cand)

        # max hold 48h ~ 192 bars of 15m
        if bars >= 192:
            exit_status = "expired"
            exit_px = cl
            break

    if exit_status is None:
        last = float(after["close"].iloc[-1])
        exit_status = "open_mtm"
        exit_px = last

    pnl = size_usd * ((float(exit_px) - entry) / entry) * (1 if is_long else -1)
    return {
        "ok": True,
        "status": exit_status,
        "pnl": pnl,
        "exit_px": float(exit_px),
        "atr": atr,
        "atr_pct": atr_pct(atr, entry),
        "bars": bars,
        "tp1_hit": tp1_hit,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


def main() -> int:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=HOURS)
    rows = load_decisions(since)
    missed = missed_entries(rows)
    print(f"window_h={HOURS} decisions={len(rows)} missed={len(missed)}")

    results = []
    errors = Counter()
    for i, m in enumerate(missed):
        try:
            entry_ts = parse_ts(m["ts"])
            sim = simulate_trade(m["symbol"], m["side"], m["price"], entry_ts, m["size_usd"])
        except Exception as exc:  # noqa: BLE001
            sim = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not sim.get("ok"):
            errors[str(sim.get("error") or "err")] += 1
            m["sim"] = sim
            results.append(m)
            continue
        m["sim"] = sim
        results.append(m)
        if (i + 1) % 10 == 0:
            print(f"  simulated {i+1}/{len(missed)}")

    ok = [r for r in results if r.get("sim", {}).get("ok")]
    pnls = [float(r["sim"]["pnl"]) for r in ok]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    zeros = [p for p in pnls if p == 0]

    by_tag = defaultdict(lambda: {"n": 0, "pnl": 0.0, "w": 0, "l": 0})
    by_type = defaultdict(lambda: {"n": 0, "pnl": 0.0, "w": 0, "l": 0})
    by_status = Counter()
    for r in ok:
        p = float(r["sim"]["pnl"])
        by_status[r["sim"]["status"]] += 1
        for bag, key in ((by_tag, r["tag"]), (by_type, r["type"])):
            b = bag[key]
            b["n"] += 1
            b["pnl"] += p
            if p > 0:
                b["w"] += 1
            elif p < 0:
                b["l"] += 1

    summary = {
        "asof": now.isoformat(),
        "hours": HOURS,
        "missed_total": len(missed),
        "simulated_ok": len(ok),
        "sim_errors": dict(errors),
        "wins": len(wins),
        "losses": len(losses),
        "zeros": len(zeros),
        "winrate": (len(wins) / len(ok) * 100.0) if ok else None,
        "pnl_sum": sum(pnls) if pnls else 0.0,
        "avg_pnl": (sum(pnls) / len(pnls)) if pnls else None,
        "by_tag": {k: dict(v) for k, v in sorted(by_tag.items(), key=lambda kv: kv[1]["pnl"])},
        "by_type": {k: dict(v) for k, v in sorted(by_type.items(), key=lambda kv: kv[1]["pnl"])},
        "by_status": dict(by_status),
        "best5": sorted(ok, key=lambda r: r["sim"]["pnl"], reverse=True)[:5],
        "worst5": sorted(ok, key=lambda r: r["sim"]["pnl"])[:5],
    }
    OUT.write_text(json.dumps({"summary": summary, "rows": results}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
