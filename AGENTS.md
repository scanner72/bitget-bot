# Agent notes — Bitget S2 Divergent Agent Desk

Hackathon desk: public Bitget OHLCV → signals → decide → risk → **UTA Demo** (`hub_demo`) + paper shadow → `:8080`.

## Do

- Keep `BITGET_ALLOW_LIVE=0`.
- Size every entry through `risk/sizing.py`; gate through `risk/gate.py`.
- Prefer `.env.example` numbers (`RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15`, daily `$50` on `$10k`).
- Leave `TF_BLOCKER_ENABLED=0`. Pair blocker on. `LEVEL_CROSS_DOWN` long only; `LEVEL_CROSS_UP` off.
- `AGENT_MODE=llm` is veto-only: rules first, model may SKIP, cannot originate ENTER.
- Treat paper-live fills as a separate book from Demo equity (`PAPER_FALLBACK` is on purpose).

## Do not

- Commit secrets or `data/` runtime logs.
- Re-enable a 15m timeframe ban.
- Invent API fields; copy `api/app.py`.
- Assume Context Sync MCP exists here. It does not.

## Stack

Python 3.11+, FastAPI, Uvicorn, CCXT, NumPy, Pandas, WebSockets. No `tests/` tree — use `scripts/smoke_*.py`.
