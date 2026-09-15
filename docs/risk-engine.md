# Risk engine

Code: `risk/gate.py`, `risk/sizing.py`, `risk/exits.py`, `risk/atr.py`. Values below are **this desk’s `.env.example`**. If a var is unset, some code paths still fall back to risk `$2` / max notional `$100`.

## Limits

| Control | Env | Desk |
|---------|-----|------|
| Dollar risk if SL hits | `RISK_USD_PER_TRADE` | `10` |
| Max notional | `MAX_NOTIONAL_USD` | `500` |
| Min notional | `MIN_NOTIONAL_USD` | `10` |
| Daily loss halt (UTC day) | `MAX_DAILY_LOSS_USD` | `50` |
| Max open positions | `MAX_POSITIONS` | `15` |
| One position per symbol | `ONE_POSITION_PER_SYMBOL` | true |
| Re-entry cooldown | `COOLDOWN_SEC` | `900` |
| Signal types | `ALLOWED_TYPES` | `BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_UP,LEVEL_CROSS_DOWN` |
| Longs only if RSI ≤ | `RSI_LONG_MAX` | `30` |
| RSI skip extremes | `RSI_OVERBOUGHT` / `RSI_OVERSOLD` | `70` / `30` |
| Dollar stop | `MAX_LOSS_PCT_OF_MARGIN` | `40` |
| Hub leverage | `HUB_LEVERAGE` | `20` (exchange). `PAPER_LEVERAGE` stays `1` — `size_usd` is already notional |
| Pair blocker | `PAIR_BLOCKER_ENABLED` | `1` |
| Timeframe blocker | `TF_BLOCKER_ENABLED` | `0` — do not enable; 15m is the only TF |

State: `data/risk_state.json`, `data/pair_blocks.json` (gitignored).

## Sizing

```
dist = |entry - sl| / entry
notional = clamp(RISK_USD_PER_TRADE / dist, MIN_NOTIONAL_USD, MAX_NOTIONAL_USD)
```

Example: entry 60 000, SL 1% away, risk `$10` → raw `$1000` → cap `$500`. Hub opens set Bitget leverage to `HUB_LEVERAGE` (default **20**) before the market order — same notional, less margin. `PAPER_LEVERAGE` is only the paper dollar-stop multiplier and stays `1`.

## ATR exits (paper shadow + exchange parachute)

On open: `ATR = mean(high-low).tail(14)`, floor `max(atr, entry * 0.02)`.

- Long: SL = entry − 1×ATR, TP1 = +1.5×ATR, TP2 = +2.5×ATR (short mirrored).
- Skip open if `atr_pct` &lt; 0.3% or &gt; 6%.
- Exchange gets **SL + TP2** on open (`HUB_SYNC_EXCHANGE_SL=1` also pushes SL after BE/trail).
- **TP1** does not flatten 50%. It marks `tp1_hit`, moves SL to breakeven, starts trail; position stays open until TP2, trail, SL, dollar-stop, or time stop (`BE_HOURS`, `MAX_HOLD_HOURS`, `EARLY_CLOSE_*`).
- Tick path: `TICK_STOPS=1` evaluates open positions on each WS quote; 30s loop is backup.

## BTC / pair policy

See `.cursor/rules/btc-filters-policy.mdc`. Regime TF **1h**, EMA50 off, both sides on. Pair blocker stays. Do not re-enable a 15m TF ban.
