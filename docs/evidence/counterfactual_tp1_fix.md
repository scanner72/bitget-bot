# Counterfactual PnL — TP1 50% + ATR floor 0.5%

Replay of this desk’s closed Demo/paper-shadow round-trips with the
post-fix exit rules (`ATR_FLOOR_PCT=0.005`, `TP1_CLOSE_FRAC=0.5`).
Same entries (time, side, size, fill price). New ATR levels from 15m
Bitget candles before the open; then `evaluate_exit` bar-by-bar.

This does **not** rewrite `data/` fills. SUI paper-live is reconstructed
(not in the Demo evidence log); notional assumed **$100**.
Holds shorter than one 15m bar keep actual PnL (no look-ahead).
ATR is capped at the desk filter `ATR_PCT_MAX=6%`.

- Closed trades in log: **35**
- Actual realized (log): **+0.41 USDT**
- Counterfactual realized+MTM on those: **+22.71 USDT**
- Delta: **+22.30 USDT**

| Pair | Side | Size | Actual | CF | Δ | Actual exit | CF exit | TP1 take |
|---|---|---:|---:|---:|---:|---|---|---|
| SKHY | short | 100 | -1.92 | -3.30 | -1.38 | sl_hit | sl_hit@195.72(-3.30) | no |
| DOGE | short | 100 | +2.29 | +1.35 | -0.94 | trailing_hit | tp2_hit@0.09004(+1.35) | no |
| MSTR | long | 100 | -2.39 | -1.75 | +0.64 | sl_hit | sl_hit@134.17(-1.75) | no |
| NEAR | short | 100 | +1.79 | +1.79 | +0.00 | trailing_hit | same_bar_keep_actual(339s) | no |
| XAG | short | 100 | -0.48 | -0.24 | +0.24 | trailing_hit | sl_hit@67.36(-0.24) | no |
| PEPE | long | 100 | -2.10 | +1.23 | +3.33 | sl_hit | tp1_hit@3.61181e-06(+0.77)+trailing_hit@3.58972e | yes |
| LINK | long | 100 | -1.88 | -0.68 | +1.20 | sl_hit | sl_hit@11.844(-0.68) | no |
| ADA | long | 100 | -2.70 | -0.09 | +2.60 | sl_hit | sl_hit@0.2149(-0.09) | no |
| XRP | long | 100 | -1.17 | +0.79 | +1.96 | sl_hit | tp1_hit@1.41891(+0.45)+trailing_hit@1.41579(+0.3 | yes |
| ETH | long | 100 | -0.58 | -0.57 | +0.01 | trailing_hit | sl_hit@2464.5(-0.57) | no |
| KORU | long | 100 | -1.93 | -1.96 | -0.03 | sl_hit | sl_hit@23.186(-1.96) | no |
| NVDA | long | 100 | +0.00 | -0.54 | -0.54 | trailing_hit | sl_hit@222.61(-0.54) | no |
| DOGE | long | 100 | +0.00 | -0.78 | -0.78 | trailing_hit | sl_hit@0.08564(-0.78) | no |
| TSLA | long | 100 | +0.00 | -0.52 | -0.52 | trailing_hit | sl_hit@365.65(-0.52) | no |
| HYPE | long | 100 | +0.00 | +1.03 | +1.03 | trailing_hit | tp1_hit@84.1729(+0.61)+trailing_hit@83.8763(+0.4 | yes |
| XAU | long | 100 | +0.00 | +0.59 | +0.59 | trailing_hit | tp1_hit@4432.35(+0.38)+trailing_hit@4417.39(+0.2 | yes |
| BTC | long | 100 | +0.00 | +0.44 | +0.44 | trailing_hit | tp1_hit@78413.8(+0.38)+trailing_hit@77926(+0.06) | yes |
| SNDK | long | 100 | +0.00 | +1.11 | +1.11 | trailing_hit | tp1_hit@1757(+0.48)+tp2_hit@1761.96(+0.62) | yes |
| PEPE | short | 100 | +2.86 | +0.64 | -2.22 | trailing_hit | tp1_hit@3.45529e-06(+0.38)+trailing_hit@3.46327e | yes |
| LINK | short | 100 | +2.62 | +0.57 | -2.05 | trailing_hit | tp1_hit@11.7691(+0.37)+trailing_hit@11.812(+0.19 | yes |
| NVDA | short | 100 | +2.04 | +0.70 | -1.34 | trailing_hit | tp1_hit@221.903(+0.38)+trailing_hit@222.108(+0.3 | yes |
| 龙虾 | short | 473 | -11.31 | +1.05 | +12.36 | sl_hit | sl_hit@0.039138(+1.05) | no |
| AAPL | short | 500 | +0.00 | -3.62 | -3.62 | trailing_hit | sl_hit@326.75(-3.62) | no |
| UNI | short | 500 | +0.00 | +8.06 | +8.06 | trailing_hit | tp1_hit@5.947(+4.66)+trailing_hit@5.97771(+3.39) | yes |
| BCH | short | 500 | +0.00 | +6.95 | +6.95 | trailing_hit | tp1_hit@224.78(+2.43)+tp2_hit@222.89(+4.52) | yes |
| GOOGL | short | 500 | +0.00 | +0.00 | +0.00 | trailing_hit | be_timeout@332.31(-0.00) | no |
| AVAX | short | 500 | +8.54 | +6.24 | -2.30 | exchange_closed | tp1_hit@7.524(+2.83)+tp2_hit@7.506(+3.42) | yes |
| SHIB | short | 500 | +1.86 | +6.65 | +4.80 | exchange_closed | tp1_hit@5.06e-06(+2.40)+tp2_hit@5.022e-06(+4.26) | yes |
| SAMSUNG | short | 500 | -0.83 | -1.42 | -0.59 | exchange_closed | sl_hit@194.15(-1.42) | no |
| LTC | short | 500 | +15.17 | +5.44 | -9.73 | exchange_closed | tp1_hit@52.8506(+1.87)+tp2_hit@52.49(+3.57) | yes |
| BTC | long | 100 | +0.31 | +0.31 | +0.00 | exchange_closed | same_bar_keep_actual(83s) | no |
| 龙虾 | short | 277 | +0.43 | +0.43 | +0.00 | sl_hit | same_bar_keep_actual(2s) | no |
| TRX | short | 500 | +0.00 | -2.80 | -2.80 | trailing_hit | sl_hit@0.34132(-2.80) | no |
| COIN | short | 500 | -10.21 | -5.92 | +4.30 | sl_hit | sl_hit@177.85(-5.92) | no |
| HOOD | long | 500 | — | +3.39 | — | still_open | trailing_hit@114.561(+3.39) | no |
| SUI | long | 100 | +0.00 | +1.53 | +1.53 | trailing_hit | tp1_hit@0.7374(+0.57)+tp2_hit@0.742939(+0.95) | yes |

## Zero-PnL closes (the 8h BE flats)

13 closes had actual PnL 0 (`trailing_hit` at entry after `BE_HOURS`).
Same entries under the fix: **+11.44 USDT** (was +0.00).

| Pair | Side | Size | CF PnL | CF path | TP1 |
|---|---|---:|---:|---|---|
| NVDA | long | 100 | -0.54 | sl_hit@222.61(-0.54) | no |
| DOGE | long | 100 | -0.78 | sl_hit@0.08564(-0.78) | no |
| TSLA | long | 100 | -0.52 | sl_hit@365.65(-0.52) | no |
| HYPE | long | 100 | +1.03 | tp1_hit@84.1729(+0.61)+trailing_hit@83.8763(+0.43) | yes |
| XAU | long | 100 | +0.59 | tp1_hit@4432.35(+0.38)+trailing_hit@4417.39(+0.21) | yes |
| BTC | long | 100 | +0.44 | tp1_hit@78413.8(+0.38)+trailing_hit@77926(+0.06) | yes |
| SNDK | long | 100 | +1.11 | tp1_hit@1757(+0.48)+tp2_hit@1761.96(+0.62) | yes |
| AAPL | short | 500 | -3.62 | sl_hit@326.75(-3.62) | no |
| UNI | short | 500 | +8.06 | tp1_hit@5.947(+4.66)+trailing_hit@5.97771(+3.39) | yes |
| BCH | short | 500 | +6.95 | tp1_hit@224.78(+2.43)+tp2_hit@222.89(+4.52) | yes |
| GOOGL | short | 500 | +0.00 | be_timeout@332.31(-0.00) | no |
| TRX | short | 500 | -2.80 | sl_hit@0.34132(-2.80) | no |
| SUI | long | 100 | +1.53 | tp1_hit@0.7374(+0.57)+tp2_hit@0.742939(+0.95) | yes |

All rows (incl. still-open MTM) CF total: **+26.10 USDT**.

`exchange_closed` rows are what local ATR exits would have done if the
hub flatten had not already closed the Demo position.

