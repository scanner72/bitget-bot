"""Generate reproducible observed S2 validation metrics from public artifacts."""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
ARTIFACTS = ROOT / "docs" / "demo_artifacts"
CSV_PATH = EVIDENCE / "paper_trading_log.csv"
NATIVE_PATH = EVIDENCE / "fixtures" / "paper_fills.desk.jsonl"
OUT_JSON = EVIDENCE / "s2_validation.json"
OUT_MD = EVIDENCE / "s2_validation.md"
START_BALANCE = 10_000.0


def f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def iso_day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def round_metric(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def main() -> int:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"error: no rows in {CSV_PATH}")
        return 1

    closes = [row for row in rows if row.get("event") == "close"]
    opens = [row for row in rows if row.get("event") == "open"]
    pnls = [f(row.get("realized_pnl")) for row in closes]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flats = [p for p in pnls if p == 0]

    first_day = iso_day(rows[0]["timestamp"])
    last_day = iso_day(rows[-1]["timestamp"])
    daily_pnl: dict[date, float] = defaultdict(float)
    for row in closes:
        daily_pnl[iso_day(row["timestamp"])] += f(row.get("realized_pnl"))
    days: list[date] = []
    cursor = first_day
    while cursor <= last_day:
        days.append(cursor)
        cursor += timedelta(days=1)
    daily_returns = [daily_pnl[day] / START_BALANCE for day in days]
    mean_return = statistics.fmean(daily_returns)
    stdev = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    downside = math.sqrt(
        statistics.fmean(min(ret, 0.0) ** 2 for ret in daily_returns)
    )
    sharpe = mean_return / stdev * math.sqrt(365.0) if stdev > 0 else None
    sortino = mean_return / downside * math.sqrt(365.0) if downside > 0 else None

    equity_curve = [START_BALANCE]
    running = START_BALANCE
    for pnl in pnls:
        running += pnl
        equity_curve.append(running)
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    native = load_jsonl(NATIVE_PATH)
    slippage_bps: list[float] = []
    for row in native:
        if row.get("event") != "open":
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        signal = f(meta.get("signal_price"))
        entry = f(row.get("price"))
        side = str(row.get("side") or "").lower()
        if signal <= 0 or entry <= 0:
            continue
        cost = (entry - signal) / signal if side == "long" else (signal - entry) / signal
        slippage_bps.append(cost * 10_000.0)

    equity = load_json(ARTIFACTS / "equity.json")
    fill_payload = load_json(ARTIFACTS / "fills.json")
    exchange_fills = fill_payload.get("fills") or []
    exchange_closes = [
        row for row in exchange_fills
        if str(row.get("trade_side") or row.get("event") or "").startswith("close")
    ]
    exchange_exec_pnl = sum(f(row.get("exec_pnl")) for row in exchange_closes)
    exchange_fees = sum(abs(f(row.get("fee"))) for row in exchange_fills)
    fill_times = sorted(str(row.get("ts") or "") for row in exchange_fills if row.get("ts"))

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    open_notional = sum(f(row.get("size_usd")) for row in opens)
    two_way_notional = sum(f(row.get("size_usd")) for row in rows)
    unique_pairs = len({row.get("trading_pair") for row in rows})

    decision_payload = load_json(ARTIFACTS / "decisions.json")
    recent_decisions = decision_payload.get("decisions") or []
    llm_decisions = 0
    fallback_decisions = 0
    for row in recent_decisions:
        agent = row.get("agent") if isinstance(row.get("agent"), dict) else {}
        fired = [str(value) for value in agent.get("rules_fired") or []]
        if "llm" in fired:
            llm_decisions += 1
        if "llm_fallback" in fired:
            fallback_decisions += 1

    result = {
        "labels": {
            "exchange": "observed Bitget UTA Demo",
            "strategy": "observed Demo-linked paper shadow",
            "funding": "not available / excluded",
        },
        "period": {
            "first": rows[0]["timestamp"],
            "last": rows[-1]["timestamp"],
            "calendar_days": len(days),
        },
        "exchange_snapshot": {
            "demo_equity_usdt": round_metric(f(equity.get("demo_equity") or equity.get("equity"))),
            "pnl_vs_start_usdt": round_metric(f(equity.get("pnl_vs_start"))),
            "return_pct": round_metric(f(equity.get("pnl_vs_start")) / START_BALANCE * 100.0),
            "unrealized_pnl_usdt": round_metric(f(equity.get("hub_unrealised_pnl"))),
            "recent_fill_count": len(exchange_fills),
            "recent_fill_period": [fill_times[0], fill_times[-1]] if fill_times else [],
            "recent_close_exec_pnl_usdt": round_metric(exchange_exec_pnl),
            "recent_fill_fees_usdt": round_metric(exchange_fees),
        },
        "strategy_ledger": {
            "rows": len(rows),
            "opens": len(opens),
            "closes": len(closes),
            "unique_pairs": unique_pairs,
            "wins": len(wins),
            "losses": len(losses),
            "flats": len(flats),
            "win_rate_pct": round_metric(len(wins) / len(closes) * 100.0 if closes else 0.0),
            "realized_pnl_usdt": round_metric(sum(pnls)),
            "average_close_pnl_usdt": round_metric(statistics.fmean(pnls) if pnls else 0.0),
            "profit_factor": round_metric(gross_profit / gross_loss if gross_loss > 0 else None),
            "max_drawdown_pct": round_metric(max_drawdown * 100.0),
            "daily_sharpe_annualized_365": round_metric(sharpe),
            "daily_sortino_annualized_365": round_metric(sortino),
            "one_way_open_notional_usdt": round_metric(open_notional),
            "two_way_logged_notional_usdt": round_metric(two_way_notional),
            "turnover_one_way_x_start_aum": round_metric(open_notional / START_BALANCE),
            "mean_signed_open_slippage_bps": round_metric(
                statistics.fmean(slippage_bps) if slippage_bps else None
            ),
            "median_signed_open_slippage_bps": round_metric(
                statistics.median(slippage_bps) if slippage_bps else None
            ),
            "slippage_sample_opens": len(slippage_bps),
        },
        "risk_controls": {
            "risk_usd_per_trade": 10,
            "max_notional_usd": 500,
            "max_positions": 15,
            "max_same_direction_positions": 4,
            "max_daily_loss_usd": 150,
            "live_mainnet_enabled": False,
        },
        "agent_evidence": {
            "recent_decisions": len(recent_decisions),
            "llm_decisions": llm_decisions,
            "llm_fallback_decisions": fallback_decisions,
        },
        "limitations": [
            "Demo equity and exchange fills are authoritative for money; paper-shadow metrics are strategy diagnostics.",
            "Sharpe/Sortino use daily paper-shadow returns over a short observed window and are exploratory, not a backtest claim.",
            "The fills endpoint snapshot contains the most recent 100 exchange fills, not guaranteed lifetime history.",
            "Funding payments are not present in the captured fills payload and are excluded.",
            "No out-of-sample claim is made; the Agentic Trading run record is an observed Demo run.",
            "Exchange-side Demo: external batch closes may appear only via reconcile (missing_on_exchange, no hub_close_client_oid); desk books them from hub fills.",
            "Exchange-side Demo: Bitget TPSL 25591/25592 on shorts is mitigated by mark-side clamp + fail-closed flatten; USDCUSDT is deny-listed.",
        ],
        "exchange_side_observations": [
            {
                "id": "external_batch_closes",
                "observed": "Demo positions closed externally in batches; local journal booked via reconcile missing_on_exchange without hub_close_client_oid.",
                "mitigated": "exec/reconcile.py flats local ghosts and backfills hub fills/PnL; /equity+/fills remain money SoT.",
            },
            {
                "id": "tpsl_25591_25592",
                "observed": "Bitget place-strategy-order rejected short TP/SL on the wrong side of mark (HTTP 400 codes 25591/25592), leaving unprotected opens.",
                "mitigated": "Tick-aware SL/TP clamp vs venue mark before place; hub_tpsl_error fail-closes (flatten) the new hub open.",
            },
            {
                "id": "usdc_junk_pair",
                "observed": "USDC/USDT:USDT produced noise BULLISH_DIV opens.",
                "mitigated": "DEFAULT_TRADE_DENY_IDS includes USDCUSDT; TRADE_DENY_SYMBOLS extends the same deny path at scan, gate, and router.",
            },
        ],
    }

    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ex = result["exchange_snapshot"]
    st = result["strategy_ledger"]
    ai = result["agent_evidence"]
    md = f"""# S2 validation report

Generated from committed evidence by `python scripts/generate_s2_validation.py`.
Every figure is labeled; this is an observed Demo run, not a backtest.

## Observed Bitget UTA Demo

- Period snapshot: {result['period']['first']} → {result['period']['last']} ({result['period']['calendar_days']} calendar days)
- Current Demo equity: **{ex['demo_equity_usdt']:.2f} USDT**
- Return vs 10,000 start: **{ex['return_pct']:.3f}%** ({ex['pnl_vs_start_usdt']:+.2f} USDT)
- Current unrealized PnL: {ex['unrealized_pnl_usdt']:+.2f} USDT
- Recent exchange snapshot: {ex['recent_fill_count']} fills; close `exec_pnl` {ex['recent_close_exec_pnl_usdt']:+.2f} USDT
- Fees across those recent fills: {ex['recent_fill_fees_usdt']:.2f} USDT
- Funding: **not available in the captured fills payload; excluded**

## Observed Demo-linked strategy ledger (paper shadow)

- {st['rows']} records: {st['opens']} opens / {st['closes']} closes across {st['unique_pairs']} instruments
- W/L/flat: {st['wins']}/{st['losses']}/{st['flats']} · win rate **{st['win_rate_pct']:.2f}%**
- Local realized PnL: {st['realized_pnl_usdt']:+.2f} USDT · average close {st['average_close_pnl_usdt']:+.2f} USDT
- Profit factor: {st['profit_factor']:.3f}
- Reconstructed max drawdown: **{st['max_drawdown_pct']:.3f}%**
- Daily Sharpe (annualized √365): {st['daily_sharpe_annualized_365']:.3f}
- Daily Sortino (annualized √365): {st['daily_sortino_annualized_365']:.3f}
- One-way open notional: {st['one_way_open_notional_usdt']:.2f} USDT ({st['turnover_one_way_x_start_aum']:.3f}× start AUM)
- Two-way logged notional: {st['two_way_logged_notional_usdt']:.2f} USDT
- Signed open slippage: mean {st['mean_signed_open_slippage_bps']:.2f} bps, median {st['median_signed_open_slippage_bps']:.2f} bps, n={st['slippage_sample_opens']}

## Activation / volume / AUM / risk

- Activation: autonomous Docker desk running against Bitget UTA Demo; {st['opens']} observed opens.
- AI usage: {ai['llm_decisions']} of the captured {ai['recent_decisions']} recent decisions used the LLM path; {ai['llm_fallback_decisions']} used rules fallback.
- Trading volume proxy: {st['two_way_logged_notional_usdt']:.2f} USDT two-way logged notional.
- AUM: 10,000 USDT start; {ex['demo_equity_usdt']:.2f} USDT current Demo equity.
- Retention: {result['period']['calendar_days']} calendar days of observed records; no external-user retention claim.
- Incremental fee evidence: {ex['recent_fill_fees_usdt']:.2f} USDT across the captured recent exchange fills.
- Risk: $10 risk-to-SL, $500 max notional, 15 total / 4 same-direction positions, $150 daily kill, live mainnet disabled.

## Method and limitations

1. `/equity` and `/fills` are authoritative for money.
2. Paper-shadow PnL, drawdown, Sharpe and Sortino diagnose strategy behavior and may differ from exchange PnL.
3. The sample is short; Sharpe/Sortino are exploratory and must not be presented as stable expected performance.
4. The recent exchange snapshot is capped at 100 fills.
5. Funding is excluded because it is absent from the captured payload.
6. External Demo batch closes may be booked only via reconcile (`missing_on_exchange`); hub fills still supply PnL.
7. Short TPSL mark-side rejects (25591/25592) are clamped then fail-closed; `USDCUSDT` is deny-listed.

## Exchange-side Demo observations

Observed / mitigated (see also [`docs/DEMO.md`](../DEMO.md)):

"""
    for obs in result.get("exchange_side_observations") or []:
        md += (
            f"- **{obs['id']}** — observed: {obs['observed']} "
            f"Mitigated: {obs['mitigated']}\n"
        )
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(
        f"Demo return={ex['return_pct']:.3f}% shadow closes={st['closes']} "
        f"WR={st['win_rate_pct']:.2f}% maxDD={st['max_drawdown_pct']:.3f}%"
    )
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
