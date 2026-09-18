# S2 validation report

Generated from committed evidence by `python scripts/generate_s2_validation.py`.
Every figure is labeled; this is an observed Demo run, not a backtest.

## Observed Bitget UTA Demo

- Period snapshot: 2026-09-09T13:20:07.412654+00:00 → 2026-09-17T14:45:46.206472+00:00 (9 calendar days)
- Current Demo equity: **9869.62 USDT**
- Return vs 10,000 start: **-1.304%** (-130.38 USDT)
- Current unrealized PnL: +0.25 USDT
- Recent exchange snapshot: 100 fills; close `exec_pnl` -16.13 USDT
- Fees across those recent fills: 39.42 USDT
- Funding: **not available in the captured fills payload; excluded**

## Observed Demo-linked strategy ledger (paper shadow)

- 138 records: 70 opens / 68 closes across 34 instruments
- W/L/flat: 20/34/14 · win rate **29.41%**
- Local realized PnL: +8.26 USDT · average close +0.12 USDT
- Profit factor: 1.070
- Reconstructed max drawdown: **0.761%**
- Daily Sharpe (annualized √365): 0.491
- Daily Sortino (annualized √365): 0.782
- One-way open notional: 25875.18 USDT (2.587× start AUM)
- Two-way logged notional: 50750.35 USDT
- Signed open slippage: mean 95.43 bps, median 54.11 bps, n=40

## Activation / volume / AUM / risk

- Activation: autonomous Docker desk running against Bitget UTA Demo; 70 observed opens.
- AI usage: 97 of the captured 100 recent decisions used the LLM path; 3 used rules fallback.
- Trading volume proxy: 50750.35 USDT two-way logged notional.
- AUM: 10,000 USDT start; 9869.62 USDT current Demo equity.
- Retention: 9 calendar days of observed records; no external-user retention claim.
- Incremental fee evidence: 39.42 USDT across the captured recent exchange fills.
- Risk: $10 risk-to-SL, $500 max notional, 15 total / 4 same-direction positions, $150 daily kill, live mainnet disabled.

## Method and limitations

1. `/equity` and `/fills` are authoritative for money.
2. Paper-shadow PnL, drawdown, Sharpe and Sortino diagnose strategy behavior and may differ from exchange PnL.
3. The sample is short; Sharpe/Sortino are exploratory and must not be presented as stable expected performance.
4. The recent exchange snapshot is capped at 100 fills.
5. Funding is excluded because it is absent from the captured payload.
