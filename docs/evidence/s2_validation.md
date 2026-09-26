# S2 validation report

Generated from committed evidence by `python scripts/generate_s2_validation.py`.
Every figure is labeled; this is an observed Demo run, not a backtest.

## Observed Bitget UTA Demo

- Period snapshot: 2026-09-09T13:20:07.412654+00:00 → 2026-09-21T11:05:35.749268+00:00 (13 calendar days)
- Current Demo equity: **9842.65 USDT**
- Return vs 10,000 start: **-1.573%** (-157.35 USDT)
- Current unrealized PnL: +0.94 USDT
- Recent exchange snapshot: 100 fills; close `exec_pnl` +5.93 USDT
- Fees across those recent fills: 41.64 USDT
- Funding: **not available in the captured fills payload; excluded**

## Observed Demo-linked strategy ledger (paper shadow)

- 231 records: 116 opens / 115 closes across 39 instruments
- W/L/flat: 30/85/0 · win rate **26.09%**
- Local realized PnL: -65.33 USDT · average close -0.57 USDT
- Profit factor: 0.758
- Reconstructed max drawdown: **1.803%**
- Daily Sharpe (annualized √365): -2.231
- Daily Sortino (annualized √365): -3.080
- One-way open notional: 48677.98 USDT (4.868× start AUM)
- Two-way logged notional: 96855.97 USDT
- Signed open slippage: mean 121.52 bps, median 82.86 bps, n=86

## Activation / volume / AUM / risk

- Activation: autonomous Docker desk running against Bitget UTA Demo; 116 observed opens.
- AI usage: 96 of the captured 100 recent decisions used the LLM path; 4 used rules fallback.
- Trading volume proxy: 96855.97 USDT two-way logged notional.
- AUM: 10,000 USDT start; 9842.65 USDT current Demo equity.
- Retention: 13 calendar days of observed records; no external-user retention claim.
- Incremental fee evidence: 41.64 USDT across the captured recent exchange fills.
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

- **external_batch_closes** — observed: Demo positions closed externally in batches; local journal booked via reconcile missing_on_exchange without hub_close_client_oid. Mitigated: exec/reconcile.py flats local ghosts and backfills hub fills/PnL; /equity+/fills remain money SoT.
- **tpsl_25591_25592** — observed: Bitget place-strategy-order rejected short TP/SL on the wrong side of mark (HTTP 400 codes 25591/25592), leaving unprotected opens. Mitigated: Tick-aware SL/TP clamp vs venue mark before place; hub_tpsl_error fail-closes (flatten) the new hub open.
- **usdc_junk_pair** — observed: USDC/USDT:USDT produced noise BULLISH_DIV opens. Mitigated: DEFAULT_TRADE_DENY_IDS includes USDCUSDT; TRADE_DENY_SYMBOLS extends the same deny path at scan, gate, and router.
