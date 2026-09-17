# Cursor handoff — Divergent Agent Desk (Bitget S2)

Local: `C:\bitget-bot`. GitHub: `https://github.com/scanner72/bitget-bot`. Do **not** commit `.env`.

## Product

Public Bitget OHLCV → RSI / level-cross → `agent.decide` (rules or llm) → risk gate → `EXEC_MODE=hub_demo` (UTA Demo) + paper shadow → FastAPI `:8080` + Docker `api` + `desk`.

## Current desk

- `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`
- Exchange SL+TP2 on open; soft TP1/BE/trail in `risk/exits.py`; `HUB_SYNC_EXCHANGE_SL=1`
- Sizing from `.env.example`: `RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15`, `MAX_SAME_DIRECTION_POSITIONS=4`, `MAX_DAILY_LOSS_USD=150`
- `TIMEFRAMES=15m,1h,4h`. `RSI_LONG_MAX=0`. `ALLOWED_TYPES=BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_DOWN`
- `PAPER_FALLBACK=0` — scan and trade **Demo catalog only**. Opt-in `=1` is paper-live (not Demo equity)
- `TF_BLOCKER_ENABLED=0`; pair blocker on
- BTC: `BTC_REGIME_TF=4h`, EMA50 off — `.cursor/rules/desk-config.mdc` wins over v1
- `.env.example` `AGENT_MODE=rules`; running desk often `llm`
- `HUB_LEVERAGE=20` is the cap; adaptive `max(2, min(20, int(35/SL%)))`. `PAPER_LEVERAGE` stays 1 (size_usd is notional)
- rToken/stocks: ATR on `1h`, no 2% floor, skip if ATR &lt; 0.5% (`RTOKEN_ATR_*`)

## Accounting source of truth

- `/equity` top-level Demo values are authoritative for the wallet.
- `/fills` `exec_pnl` + `fee` are authoritative for executions.
- `/history` and `data/paper_fills.jsonl` are paper-shadow reconstruction for exit logic/UI and may differ.
- Never report paper-shadow PnL as Demo PnL without comparison and an explicit label.

## Do not

- Touch `C:\divergent`
- Re-enable a TF ban, restore `RSI_LONG_MAX=30`, or add `LEVEL_CROSS_UP` back without being asked
- Call Context Sync MCP (not wired here)
