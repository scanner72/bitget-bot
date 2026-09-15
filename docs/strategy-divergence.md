# Signals

Detector: `signals/engine.py` + `signals/divergence/detector.py`. Config: `signals/config.py`. Desk TF: **15m**.

## Types (`ALLOWED_TYPES`)

| Type | Meaning |
|------|---------|
| `BULLISH_DIV` | Price lower low, RSI 14 higher low → long candidate |
| `BEARISH_DIV` | Price higher high, RSI 14 lower high → short candidate |
| `LEVEL_CROSS_UP` | Level-cross long |
| `LEVEL_CROSS_DOWN` | Level-cross short |

Pivots: lookback 5 bars each side (`DIV_LOOKBACK_LEFT/RIGHT`). Agent then applies `RSI_LONG_MAX=30` (no long if RSI above that), `RSI_OVERBOUGHT=70` / `RSI_OVERSOLD=30`, BTC regime/momentum, and the pair blocker.

## After ENTER

Not swing-based 2R/3R targets. Stops and targets are **ATR** (`risk/atr.py`, `risk/exits.py`):

1. Market open on Demo (`hub_demo`) at `HUB_LEVERAGE=20`, or paper-live fallback.
2. Exchange strategy order: SL + TP2.
3. Local TP1 → SL to breakeven + trailing; size stays open.
4. Close: TP2, trail, SL, dollar-stop, or time stop.

Decide: `agent/decide.py` — `rules` or `llm`. LLM must return `{action, size_usd, side, rationale}`; otherwise `llm_fallback` + rules.
