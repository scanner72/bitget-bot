# x0tta6b pack — verification

Fail the pass if any box is false.

## Facts vs code

- [ ] Badge versions only if pinned in `requirements.txt` / lockfile
- [ ] Config tables = `.env.example` live values, not commented legacy or another repo
- [ ] If gitignored `.env` differs (e.g. `AGENT_MODE=llm`), README says so
- [ ] Mermaid matches real modules (`agent/decide.py`, `risk/gate.py`, `exec/router.py`, …)
- [ ] Timeframes / RSI / position caps match config (`TIMEFRAME=15m`, `RSI_LONG_MAX`, `MAX_POSITIONS`)
- [ ] No “no keys required” when default exec places exchange orders
- [ ] No competitor matrix, OS fluff matrix, or “Why vs grid bots” essay

## API

- [ ] Every documented path exists
- [ ] Example JSON keys copied from handlers
- [ ] Collection routes are objects (`{positions, count}`, `{decisions, count}`), not fake arrays

## Scripts / CI

- [ ] Every smoke in `test.*` / CI exists
- [ ] Failed smoke → non-zero exit
- [ ] `docker compose up -d --build`
- [ ] Docker detect uses native exit code
- [ ] Health polled on the real success field (`ok` on this desk)
- [ ] No `deploy-remote.*`, `CODE_OF_CONDUCT.md`, `docs/agents-setup.md`
- [ ] No `pytest tests/` unless `tests/` exists
- [ ] CI smokes do not need Demo keys or a live LLM

## Docs hygiene

- [ ] `README.ru.md` is a real short translation
- [ ] `DEMO` / `SUBMISSION` / `CURSOR_HANDOFF` still linked if present
- [ ] No Context Sync MCP invoke unless that MCP is in the workspace
- [ ] `SECURITY.md` has no invented email
- [ ] Agent files do not invent module paths (`signals/engine.py`, not `momentum_divergence.py`)
