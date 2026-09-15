# Agent notes — Bitget S2 Divergent Agent Desk

Hackathon desk: public Bitget OHLCV → signals → decide → risk → **UTA Demo** (`hub_demo`) + paper shadow → `:8080`.

## Do

- Keep `BITGET_ALLOW_LIVE=0`.
- Size every entry through `risk/sizing.py`; gate through `risk/gate.py`.
- Hub opens at `HUB_LEVERAGE=20` (exchange). Leave `PAPER_LEVERAGE=1` — `size_usd` is notional.
- Prefer `.env.example` numbers (`RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15`) over stale code fallbacks.
- Leave `TF_BLOCKER_ENABLED=0`. Pair blocker on.
- Treat paper-live fills as a separate book from Demo equity.

## Do not

- Commit secrets or `data/` runtime logs.
- Re-enable a 15m timeframe ban.
- Invent API fields; copy `api/app.py`.
- Assume Context Sync MCP exists here. It does not.

## Stack

Python 3.11+, FastAPI, Uvicorn, CCXT, NumPy, Pandas, WebSockets. No `tests/` tree — use `scripts/smoke_*.py`.
