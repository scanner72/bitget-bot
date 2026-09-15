# Cursor handoff — Divergent Agent Desk (Bitget S2)

Local: `C:\bitget-bot`. GitHub: `https://github.com/scanner72/bitget-bot`. Do **not** commit `.env`.

## Product

Public Bitget OHLCV → RSI divergence → `agent.decide` (rules or llm) → risk gate → `EXEC_MODE=hub_demo` (UTA Demo) + paper shadow → FastAPI `:8080` + Docker `api` + `desk`.

## Current desk

- `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`
- Exchange SL+TP2 on open; TP1 takes 50% then BE/trail on the runner; `BE_HOURS` without TP1 closes at mark (`stale_no_tp1`); `HUB_SYNC_EXCHANGE_SL=1`
- Sizing from `.env.example`: `RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15`, daily kill `$50` on `$10k` start (`PAPER_START_BALANCE_USD`)
- `PAPER_FALLBACK=1` — paper-live **is** part of the strategy; that PnL ≠ Demo equity
- `TF_BLOCKER_ENABLED=0`; pair blocker on; `ALLOWED_TYPES` DIV + fade `LEVEL_CROSS_DOWN` long (`LEVEL_CROSS_UP` off); rToken scan stays (`SCAN_RTOKEN_TOP=30`)
- BTC: `BTC_REGIME_TF=1h`, EMA50 off — `.cursor/rules/btc-filters-policy.mdc`
- `.env.example` `AGENT_MODE=rules`. `llm` = rules first, model may only SKIP. Freeze extras until S2 deadline **21 Sep 2026**
- Leave exchange leverage at Bitget default

## Do not

- Touch `C:\divergent`
- Re-enable 15m TF ban
- Call Context Sync MCP (not wired here)
