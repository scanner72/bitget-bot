# Agent notes — Bitget S2 Divergent Agent Desk

Hackathon desk: public Bitget OHLCV → signals → decide → risk → **UTA Demo** (`hub_demo`) + paper shadow → `:8080`.

**Config source of truth:** `.cursor/rules/desk-config.mdc` (user 2026-09-16). It beats v1 DB defaults and older docs.

## Do

- Keep `BITGET_ALLOW_LIVE=0`.
- Size every entry through `risk/sizing.py`; gate through `risk/gate.py`.
- Scan `TIMEFRAMES=15m,1h,4h`. Hub lev cap `HUB_LEVERAGE=20` (adaptive `35/SL%`). `PAPER_LEVERAGE=1` — `size_usd` is notional.
- Prefer `.env.example` numbers: `RISK_USD_PER_TRADE=10`, `MAX_NOTIONAL_USD=500`, `MAX_POSITIONS=15`, `MAX_SAME_DIRECTION_POSITIONS=4`, `MAX_DAILY_LOSS_USD=150`, `RSI_LONG_MAX=0`.
- Leave `TF_BLOCKER_ENABLED=0`. Pair blocker on.
- Treat paper-live as opt-in (`PAPER_FALLBACK=1`). Default `hub_demo` scans the full Demo catalog.

## Do not

- Commit secrets or `data/` runtime logs.
- Restore `RSI_LONG_MAX=30`, `TIMEFRAME=15m` only, `LEVEL_CROSS_UP` in `ALLOWED_TYPES`, or `MAX_DAILY_LOSS_USD=50`.
- Re-enable a timeframe ban.
- Invent API fields; copy `api/app.py`.
- Assume Context Sync MCP exists here. It does not.

## Stack

Python 3.11+, FastAPI, Uvicorn, CCXT, NumPy, Pandas, WebSockets. No `tests/` tree — use `scripts/smoke_*.py`.
