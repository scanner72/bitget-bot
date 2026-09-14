# Cursor handoff — Divergent Agent Desk (Bitget S2)

Date: 2026-09-09 (Europe/Chisinau). Local path: `C:\bitget-bot` on DESKTOP-PC9UABS.
Do **not** commit `.env` (secrets). Demo keys live only in local env / secret store.

## Product
Bitget AI Hackathon S2 demo: **Divergent Agent Desk**.
Pipeline: Bitget public OHLCV → RSI divergence / level-cross → rules decide (optional LLM fallback) → risk gate → **EXEC_MODE=hub_demo** (UTA Demo market open/close) + paper shadow for exits/UI → FastAPI `:8080` + Docker `api` + `desk`.

## Exec / risk (current)
- `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`
- Opens/closes: UTA **market** via `exec/bitget_hub.py` + `exec/router.py`
- Exchange leverage: leave Bitget default (often 20x) — do not force 1x
- On open: exchange **SL + TP2** (`place-strategy-order` tpsl); soft TP1/BE/trail local
- After soft TP1/BE/trail: sync exchange SL (`HUB_SYNC_EXCHANGE_SL=1`)
- Price precision: per-symbol `pricePlace` (DOGE needs 5 decimals; 2dp caused stopLoss==takeProfit)
- Sizing: `notional = clamp(RISK_USD_PER_TRADE / (|entry-sl|/entry), MIN_NOTIONAL, MAX_NOTIONAL)` defaults risk=2, min=10, max=100
- UI: dashboard auto-refresh 8s; open PnL/entry/mark from Demo (`pnl_source=hub_demo`)

## Key paths
- `exec/bitget_hub.py`, `exec/router.py`, `exec/hub_balance.py`, `exec/paper.py`
- `desk/pipeline.py`, `desk/loop.py`, `risk/exits.py`, `risk/sizing.py`, `risk/gate.py`, `risk/atr.py`
- `api/app.py` (dashboard + `/positions` enrichment)
- `docs/ecosystem-integration.html` (Agent Hub deck)
- Runtime state: `data/` (gitignored)

## Roles
- **scanner (Grok Bot)**: code/infra for bitget-bot
- **Policy Trader** (sidebar teammate): ENTER/SKIP/size policy — **not wired** into desk loop yet (postponed)

## Do not touch
- Live MEXC fleet `C:\divergent` / Docker divergent-*

## Hackathon notes
- Deadline ~21 Sep; Demo via Agent Hub (`paptrading`) preferred over paper-only
- Classic mix futures may still 40014 — use UTA v3 only
- GitHub: intended `https://github.com/scanner72/bitget-bot` (push may still be pending auth)

## Recent chat decisions
1. Trade on Bitget Demo with real Demo balance in equity overlay
2. Paper book reset then observe live Demo entries
3. Exchange SL then SL+TP2 parachute if bot dies; move SL to BE after TP1
4. UI must show real exchange PnL/size fields, not paper-only estimates
5. **BTC filters aligned to `C:\divergent` (user 2026-09-10):** `BTC_REGIME_TF=1h` (chosen over live DB 4h), `BTC_EMA50_FILTER_ENABLED=0`, `BTC_MOMENTUM_PCT=1.2`. Policy notes: `.cursor/rules/btc-filters-policy.mdc`
