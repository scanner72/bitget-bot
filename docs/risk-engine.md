# Risk engine

Code: `risk/gate.py`, `risk/sizing.py`, `risk/exits.py`, `risk/atr.py`. Values below are **this desk’s `.env.example`**. If a var is unset, some code paths still fall back to risk `$2` / max notional `$100`.

## Limits

| Control | Env | Desk |
|---------|-----|------|
| Dollar risk if SL hits | `RISK_USD_PER_TRADE` | `10` |
| Max notional | `MAX_NOTIONAL_USD` | `500` |
| Min notional | `MIN_NOTIONAL_USD` | `10` |
| Daily loss halt (UTC day) | `MAX_DAILY_LOSS_USD` | `150` |
| Max open positions | `MAX_POSITIONS` | `15` |
| Same-direction cap | `MAX_SAME_DIRECTION_POSITIONS` | `4` |
| One position per symbol | `ONE_POSITION_PER_SYMBOL` | true |
| Re-entry cooldown | `COOLDOWN_SEC` | `900` |
| Signal types | `ALLOWED_TYPES` | `BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_DOWN` |
| Long RSI zone | `RSI_LONG_MAX` | `0` (off) |
| RSI skip extremes | `RSI_OVERBOUGHT` / `RSI_OVERSOLD` | `70` / `30` |
| Dollar stop | `MAX_LOSS_PCT_OF_MARGIN` | `40` |
| Hub leverage | `HUB_LEVERAGE` | cap `20`; adaptive `max(2, min(cap, int(35/SL%)))`. `PAPER_LEVERAGE` stays `1` |
| Pair blocker | `PAIR_BLOCKER_ENABLED` | `1` |
| Timeframe blocker | `TF_BLOCKER_ENABLED` | `0` |
| Timeframes | `TIMEFRAMES` | `15m,1h,4h` |

State: `data/risk_state.json`, `data/pair_blocks.json` (gitignored).

## Sizing

```
dist = |entry - sl| / entry
notional = clamp(RISK_USD_PER_TRADE / dist, MIN_NOTIONAL_USD, MAX_NOTIONAL_USD)
```

Example: entry 60 000, SL 1% away, risk `$10` → raw `$1000` → cap `$500`. Hub opens set Bitget leverage to adaptive `max(2, min(HUB_LEVERAGE, int(35/SL%)))` (cap **20**) — same notional, SL ≈ 35% of margin. `PAPER_LEVERAGE` is only the paper dollar-stop multiplier and stays `1`.

## ATR exits (paper shadow + exchange parachute)

On open: `ATR = mean(high-low).tail(14)`.

- **Crypto:** floor `max(atr, entry * 0.02)`, skip if `atr_pct` &lt; 0.3% or &gt; 6%, ATR on the **signal** TF.
- **rToken / stocks** (`is_rtoken_symbol`): `RTOKEN_ATR_TF=1h`, `RTOKEN_ATR_FLOOR_PCT=0` (no 2% inflate), skip if `atr_pct` &lt; 0.5%. Quiet mega-caps do not open with an unreachable 2–3% TP.
- Exchange gets **SL + TP2** on open (`HUB_SYNC_EXCHANGE_SL=1` also pushes SL after BE/trail).
- **TP1** does not flatten 50%. It marks `tp1_hit`, moves SL to breakeven, starts trail; position stays open until TP2, trail, SL, dollar-stop, or time stop (`BE_HOURS`, `MAX_HOLD_HOURS`, `EARLY_CLOSE_*`).
- Tick path: `TICK_STOPS=1` evaluates open positions on each WS quote; 30s loop is backup.

## BTC / pair policy

See `.cursor/rules/desk-config.mdc`. Regime TF **4h**, EMA50 off, both sides on. `RSI_LONG_MAX=0`. Pair blocker stays. `TF_BLOCKER_ENABLED=0`. Correlation guard: max 4 positions in the same direction.
