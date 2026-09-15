# Signals

Detector: `signals/engine.py` + `signals/divergence/detector.py`. Config: `signals/config.py`. Desk TF: **15m**.

## Types (`ALLOWED_TYPES`)

Desk trades **divergence only** (`BULLISH_DIV`, `BEARISH_DIV`). The detector still emits `LEVEL_CROSS_*` (support/resistance break); the risk gate drops them (`type_not_allowed`). Restore via `.env` if you want them back.

| Type | Meaning | Traded |
|------|---------|--------|
| `BULLISH_DIV` | Price lower low, RSI 14 higher low → long candidate | yes |
| `BEARISH_DIV` | Price higher high, RSI 14 lower high → short candidate | yes |
| `LEVEL_CROSS_UP` | Close through bearish resistance. Code would fade (short); gate drops it. | no |
| `LEVEL_CROSS_DOWN` | Close through bullish support. Code would fade (long); gate drops it. | no |

Pivots: lookback 5 bars each side (`DIV_LOOKBACK_LEFT/RIGHT`). Agent then applies `RSI_LONG_MAX=30` (no long if RSI above that), `RSI_OVERBOUGHT=70` / `RSI_OVERSOLD=30`, BTC regime/momentum, and the pair blocker.

## After ENTER

Not swing-based 2R/3R targets. Stops and targets are **ATR** (`risk/atr.py`, `risk/exits.py`):

1. Market open on Demo (`hub_demo`) or paper-live fallback.
2. Exchange strategy order: SL + TP2.
3. Local TP1 → close 50% (`TP1_CLOSE_FRAC`), SL to breakeven + trailing on the runner. The TP1 bar itself does not flatten the remainder at BE.
4. Close: TP2 (fill at TP2, not a retraced mark), trail, SL, `BE_HOURS` (`be_timeout`), dollar-stop, or time stop.

ATR floor is `ATR_FLOOR_PCT` (default 0.5% of entry). A 2% floor made 15m TP1/TP2 unreachable on quiet names.

Decide: `agent/decide.py` — `rules` or `llm`. LLM must return `{action, size_usd, side, rationale}`; otherwise `llm_fallback` + rules.
