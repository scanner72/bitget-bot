# Signals

Detector: `signals/engine.py` + `signals/divergence/detector.py`. Config: `signals/config.py`. Desk TFs: **15m, 1h, 4h**.

## Types (`ALLOWED_TYPES`)

Live desk allows three. `LEVEL_CROSS_UP` still exists in the detector but is **not** in `ALLOWED_TYPES`.

| Type | Side | On desk |
|------|------|---------|
| `BULLISH_DIV` | long | yes |
| `BEARISH_DIV` | short | yes |
| `LEVEL_CROSS_DOWN` | long (fade through bullish-div support) | yes |
| `LEVEL_CROSS_UP` | short | no |

Pivots: lookback 5 bars each side (`DIV_LOOKBACK_LEFT/RIGHT`). Agent applies `RSI_OVERBOUGHT=70` / `RSI_OVERSOLD=30`. **`RSI_LONG_MAX=0` (off)** — do not skip longs for mid RSI. Then BTC regime/momentum, correlation guard (max 4 same direction), and the pair blocker.

## After ENTER

Not swing-based 2R/3R targets. Stops and targets are **ATR** (`risk/atr.py`, `risk/exits.py`):

1. Market open on Demo (`hub_demo`) at `HUB_LEVERAGE=20`. Names missing from the Demo catalog are skipped (`PAPER_FALLBACK=0`).
2. Exchange strategy order: SL + TP2.
3. Local TP1 → SL to breakeven + trailing; size stays open.
4. Close: TP2, trail, SL, dollar-stop, or time stop.

Decide: `agent/decide.py` — `rules` or `llm`. LLM must return `{action, size_usd, side, rationale}`; otherwise `llm_fallback` + rules.
