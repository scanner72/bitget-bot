# Claude / Cursor notes — Divergent Agent Desk

Live numbers: `.cursor/rules/desk-config.mdc` (overrides v1 and older notes).

## Run

```bash
docker compose up -d --build
docker compose logs -f desk
```

Local: `.venv` then `python scripts/run_api.py` and `python scripts/run_signal_loop.py --poll`. Smokes: `./test.sh` or `.\test.ps1`.

## Modules

- `ingest/` — public WS + REST, `TIMEFRAMES=15m,1h,4h`
- `signals/engine.py`, `signals/divergence/` — RSI 14, div + level-cross
- `agent/decide.py` — `rules` or `llm` (Groq OpenAI-compatible). `RSI_LONG_MAX=0`
- `risk/gate.py` (`MAX_SAME_DIRECTION_POSITIONS=4`), `sizing.py`, `exits.py`
- `exec/bitget_hub.py`, `paper.py`, `router.py`
- `api/app.py` — `/health` returns `ok`, not `status`

## Safety

`EXEC_MODE=hub_demo`, `BITGET_ALLOW_LIVE=0`. Never bypass the risk gate. Do not commit `.env`. Do not touch `C:\divergent`. `TF_BLOCKER_ENABLED=0`. Price sanity: open/exit 2.5% vs Demo entry (`risk/price_sanity.py`) — LTC/BZ drift. No Context Sync tools here.
