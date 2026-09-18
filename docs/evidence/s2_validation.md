# S2 validation report

Generated from committed evidence by `python scripts/generate_s2_validation.py`.
Every figure is labeled; this is an observed Demo run, not a backtest.

## Observed Bitget UTA Demo

- Period snapshot: 2026-09-09T13:20:07.412654+00:00 → 2026-09-18T03:49:44.516233+00:00 (10 calendar days)
- Current Demo equity: **9880.54 USDT**
- Return vs 10,000 start: **-1.195%** (-119.46 USDT)
- Current unrealized PnL: +0.08 USDT
- Recent exchange snapshot: 100 fills; close `exec_pnl` +41.64 USDT
- Fees across those recent fills: 42.57 USDT
- Funding: **not available in the captured fills payload; excluded**

## Observed Demo-linked strategy ledger (paper shadow)

- 148 records: 75 opens / 73 closes across 35 instruments
- W/L/flat: 22/34/17 · win rate **30.14%**
- Local realized PnL: +27.05 USDT · average close +0.37 USDT
- Profit factor: 1.228
- Reconstructed max drawdown: **0.761%**
- Daily Sharpe (annualized √365): 1.515
- Daily Sortino (annualized √365): 2.430
- One-way open notional: 28375.18 USDT (2.837× start AUM)
- Two-way logged notional: 55750.35 USDT
- Signed open slippage: mean 92.60 bps, median 57.38 bps, n=45

## Activation / volume / AUM / risk

- Activation: autonomous Docker desk running against Bitget UTA Demo; 75 observed opens.
- AI usage: 100 of the captured 100 recent decisions used the LLM path; 0 used rules fallback.
- Trading volume proxy: 55750.35 USDT two-way logged notional.
- AUM: 10,000 USDT start; 9880.54 USDT current Demo equity.
- Retention: 10 calendar days of observed records; no external-user retention claim.
- Incremental fee evidence: 42.57 USDT across the captured recent exchange fills.
- Risk: $10 risk-to-SL, $500 max notional, 15 total / 4 same-direction positions, $150 daily kill, live mainnet disabled.

## Method and limitations

1. `/equity` and `/fills` are authoritative for money.
2. Paper-shadow PnL, drawdown, Sharpe and Sortino diagnose strategy behavior and may differ from exchange PnL.
3. The sample is short; Sharpe/Sortino are exploratory and must not be presented as stable expected performance.
4. The recent exchange snapshot is capped at 100 fills.
5. Funding is excluded because it is absent from the captured payload.
