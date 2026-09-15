# Cursor handoff — Divergent Agent Desk (Bitget S2)

Local: `C:\bitget-bot`. GitHub: `https://github.com/scanner72/bitget-bot`. Do **not** commit `.env`.

## Product

Public Bitget OHLCV → RSI / level-cross → `agent.decide` (rules or llm) → risk gate → `EXEC_MODE=hub_demo` (UTA Demo) + paper shadow → FastAPI `:8080` + Docker `api` + `desk`.

## Current desk

- `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`
- Exchange SL+TP2 on open; TP1 takes 50% then BE/trail on the runner in `risk/exits.py`; `HUB_SYNC_EXCHANGE_SL=1`
- Sizing from `.env.example`: `RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15` (code fallbacks 2/100 if unset)
- `PAPER_FALLBACK=1` — paper-live ≠ Demo equity
- `TF_BLOCKER_ENABLED=0`; pair blocker on
- BTC: `BTC_REGIME_TF=1h`, EMA50 off — `.cursor/rules/btc-filters-policy.mdc`
- `.env.example` `AGENT_MODE=rules`; running desk often `llm` (Groq `qwen/qwen3.6-27b`)
- Leave exchange leverage at Bitget default

## Do not

- Touch `C:\divergent`
- Re-enable 15m TF ban
- Call Context Sync MCP (not wired here)
