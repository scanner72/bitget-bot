# LEVEL_CROSS sign flip

Detector: `LEVEL_CROSS_DOWN` = close breaks **bullish support** (breakdown);
`LEVEL_CROSS_UP` = close breaks **bearish resistance** (breakout).

**Code (this repo, first commit, never changed here):** fade — DOWN→long, UP→short.
**Docs:** breakout — UP→long, DOWN→short.

This replay uses breakout sides, same entries, current ATR exits
(`ATR_FLOOR_PCT=0.5%`, `TP1_CLOSE_FRAC=0.5`). Not a Bitget fill rewrite.

RSI filters are **not** re-applied (fills have no RSI). `RSI_LONG_MAX=30`
would SKIP most UP→long if RSI was mid/high; oversold would SKIP some
DOWN→short. So this is an upper bound on “just flip the side”.

- CROSS trades in Demo log: **9**
- Actual CROSS PnL (as traded, fade): **-12.25 USDT**
- Naive −actual (if path and exits were symmetric): **+12.25 USDT**
- Replay breakout side (comparable 8/9): **+2.74 USDT**

| Pair | Type | Code side | Breakout | Actual | Flip CF | Δ | Flip path |
|---|---|---|---|---:|---:|---:|---|
| SKHY | LEVEL_CROSS_UP | short | long | -1.92 | +3.30 | +5.21 | tp2_hit@195.72(+3.30) |
| MSTR | LEVEL_CROSS_DOWN | long | short | -2.39 | -1.07 | +1.33 | sl_hit@138.02(-1.07) |
| XAG | LEVEL_CROSS_UP | short | long | -0.48 | +1.10 | +1.58 | tp1_hit@67.704(+0.38)+tp2_hit@68.18(+0.73) |
| PEPE | LEVEL_CROSS_DOWN | long | short | -2.10 | -1.13 | +0.97 | sl_hit@3.597e-06(-1.13) |
| ADA | LEVEL_CROSS_DOWN | long | short | -2.70 | -0.46 | +2.23 | sl_hit@0.2161(-0.46) |
| XRP | LEVEL_CROSS_DOWN | long | short | -1.17 | -0.82 | +0.35 | sl_hit@1.4177(-0.82) |
| KORU | LEVEL_CROSS_DOWN | long | short | -1.93 | +2.21 | +4.13 | tp1_hit@23.186(+0.98)+tp2_hit@23.0688(+1.23) |
| XAU | LEVEL_CROSS_DOWN | long | short | +0.00 | -0.39 | -0.39 | sl_hit@4415.99(-0.39) |
| 龙虾 | LEVEL_CROSS_UP | short | long | +0.43 | same_bar_skip(2s) | — | same_bar_skip(2s) |

Git: `LONG_TYPES` / `SHORT_TYPES` were fade on 2026-09-09 initial commit
and were not flipped later in bitget-bot. A loss-driven flip, if it
happened, was in Divergent v1 before the port — this desk copied fade.

