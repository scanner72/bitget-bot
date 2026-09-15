"""Flip LEVEL_CROSS side (docs/breakout vs code/fade) and replay ATR exits.

Code today (from first commit, never changed here):
  LEVEL_CROSS_DOWN → long   (fade a support break)
  LEVEL_CROSS_UP   → short  (fade a resistance break)

Docs / detector names (breakout):
  LEVEL_CROSS_UP   → long   (close through resistance)
  LEVEL_CROSS_DOWN → short  (close through support)

Does not rewrite fills.

  python scripts/analyze_cross_sign.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from replay_tp1_fix import (  # noqa: E402
    FILLS_DEFAULT,
    fetch_ohlcv_range,
    load_fills,
    pair_trades,
    parse_ts,
    replay_position,
)
from risk.exits import ExitConfig  # noqa: E402

OUT = ROOT / "docs" / "evidence" / "cross_sign_flip.md"


def is_cross(typ: str) -> bool:
    t = str(typ or "").upper()
    return t in {"LEVEL_CROSS_UP", "LEVEL_CROSS_DOWN"}


def breakout_side(typ: str) -> str:
    t = str(typ or "").upper()
    if t == "LEVEL_CROSS_UP":
        return "long"
    if t == "LEVEL_CROSS_DOWN":
        return "short"
    raise ValueError(typ)


def main() -> int:
    fills = load_fills(FILLS_DEFAULT)
    trades = [t for t in pair_trades(fills) if is_cross(t.get("signal_type") or "")]
    cfg = ExitConfig.from_env()
    cfg.tp1_close_frac = 0.5
    now = datetime.now(timezone.utc)
    cache: dict[str, object] = {}
    rows = []

    print(f"LEVEL_CROSS round-trips: {len(trades)}")
    for i, t in enumerate(trades):
        typ = str(t.get("signal_type") or "")
        want = breakout_side(typ)
        opened = parse_ts(t["opened_ts"])
        if opened is None:
            continue
        closed = parse_ts(t.get("closed_ts"))
        hold_sec = (closed - opened).total_seconds() if closed else None
        same_bar = hold_sec is not None and hold_sec < 15 * 60
        flip = dict(t)
        flip["side"] = want
        print(
            f"[{i+1}/{len(trades)}] {t['symbol']} {typ} code={t['side']} "
            f"breakout={want} actual={t.get('actual_pnl')}",
            flush=True,
        )
        sim = {"ok": False, "error": "skipped"}
        if same_bar:
            sim = {
                "ok": True,
                "cf_pnl": None,
                "cf_legs": f"same_bar_skip({hold_sec:.0f}s)",
                "cf_status": "same_bar",
                "note": "hold < 15m; 15m flip would look ahead",
            }
        else:
            try:
                sym = str(t["symbol"])
                if sym not in cache:
                    cache[sym] = fetch_ohlcv_range(
                        sym,
                        start=opened - timedelta(days=5),
                        end=now + timedelta(minutes=15),
                    )
                sim = replay_position(
                    flip, cache[sym], cfg=cfg, floor_pct=0.005, now_cap=now
                )
            except Exception as exc:  # noqa: BLE001
                sim = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        t["breakout_side"] = want
        t["flipped"] = want != str(t.get("side") or "")
        t["flip_pnl"] = sim.get("cf_pnl") if sim.get("ok") else None
        t["flip_legs"] = sim.get("cf_legs") or sim.get("error")
        t["flip_ok"] = bool(sim.get("ok"))
        rows.append(t)
        print(f"    flip={t['flip_pnl']} {t['flip_legs']}", flush=True)

    closed = [r for r in rows if r.get("actual_pnl") is not None]
    actual = sum(float(r["actual_pnl"]) for r in closed)
    comparable = [r for r in closed if r.get("flip_pnl") is not None]
    flip_sum = sum(float(r["flip_pnl"]) for r in comparable)
    naive = sum(-float(r["actual_pnl"]) for r in closed)

    lines = [
        "# LEVEL_CROSS sign flip",
        "",
        "Detector: `LEVEL_CROSS_DOWN` = close breaks **bullish support** (breakdown);",
        "`LEVEL_CROSS_UP` = close breaks **bearish resistance** (breakout).",
        "",
        "**Code (this repo, first commit, never changed here):** fade — DOWN→long, UP→short.",
        "**Docs:** breakout — UP→long, DOWN→short.",
        "",
        "This replay uses breakout sides, same entries, current ATR exits",
        "(`ATR_FLOOR_PCT=0.5%`, `TP1_CLOSE_FRAC=0.5`). Not a Bitget fill rewrite.",
        "",
        "RSI filters are **not** re-applied (fills have no RSI). `RSI_LONG_MAX=30`",
        "would SKIP most UP→long if RSI was mid/high; oversold would SKIP some",
        "DOWN→short. So this is an upper bound on “just flip the side”.",
        "",
        f"- CROSS trades in Demo log: **{len(rows)}**",
        f"- Actual CROSS PnL (as traded, fade): **{actual:+.2f} USDT**",
        f"- Naive −actual (if path and exits were symmetric): **{naive:+.2f} USDT**",
        f"- Replay breakout side (comparable {len(comparable)}/{len(closed)}): **{flip_sum:+.2f} USDT**",
        "",
        "| Pair | Type | Code side | Breakout | Actual | Flip CF | Δ | Flip path |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for r in rows:
        act = r.get("actual_pnl")
        fl = r.get("flip_pnl")
        delta = (float(fl) - float(act)) if (fl is not None and act is not None) else None
        sym = str(r.get("symbol") or "").replace("/USDT:USDT", "")
        lines.append(
            "| {sym} | {typ} | {cs} | {bs} | {act} | {fl} | {d} | {path} |".format(
                sym=sym,
                typ=r.get("signal_type"),
                cs=r.get("side"),
                bs=r.get("breakout_side"),
                act=f"{act:+.2f}" if act is not None else "—",
                fl=f"{fl:+.2f}" if fl is not None else (r.get("flip_legs") or "—"),
                d=f"{delta:+.2f}" if delta is not None else "—",
                path=str(r.get("flip_legs") or "")[:48],
            )
        )
    lines.extend(
        [
            "",
            "Git: `LONG_TYPES` / `SHORT_TYPES` were fade on 2026-09-09 initial commit",
            "and were not flipped later in bitget-bot. A loss-driven flip, if it",
            "happened, was in Divergent v1 before the port — this desk copied fade.",
            "",
        ]
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps({"actual": actual, "naive_neg": naive, "flip_replay": flip_sum, "n": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
