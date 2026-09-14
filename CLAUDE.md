# Claude / Cursor notes — Divergent Agent Desk

## Run

```bash
docker compose up -d --build
docker compose logs -f desk
```

Local: `.venv` then `python scripts/run_api.py` and `python scripts/run_signal_loop.py --poll`. Smokes: `./test.sh` or `.\test.ps1`.

## Modules

- `ingest/` — public WS + REST, `TIMEFRAME=15m`
- `signals/engine.py`, `signals/divergence/` — RSI 14, div + level-cross
- `agent/decide.py` — `rules` or `llm` (Groq OpenAI-compatible)
- `risk/gate.py`, `sizing.py`, `exits.py`
- `exec/bitget_hub.py`, `paper.py`, `router.py`
- `api/app.py` — `/health` returns `ok`, not `status`

## Safety

`EXEC_MODE=hub_demo`, `BITGET_ALLOW_LIVE=0`. Never bypass the risk gate. Do not commit `.env`. Do not touch `C:\divergent`. `TF_BLOCKER_ENABLED=0`. No Context Sync tools here.
