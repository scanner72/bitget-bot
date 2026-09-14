---
name: x0tta6b-design-standard
description: Polishes a repo for GitHub with bilingual README, mermaid from real code, short agent rules, start/test scripts, CI smokes, MIT/CONTRIBUTING/SECURITY. Use when the user asks to оформить репозиторий, apply x0tta6b, polish README, or align docs/launchers/CI with the live Bitget desk — not the original marketing pack.
---

# x0tta6b Design Standard (desk edition)

GitHub polish for a **running** project. Numbers, endpoints, defaults, and stack claims come from this repo’s code. Marketing templates from other repos are not a source of truth.

Canonical application: this repository after the live-desk pass (README + `docs/` + `start.*` + `test.*` + `.github/workflows/ci.yml`). Do not re-apply the bloated `8af6658` pack.

Then verify with [CHECKLIST.md](CHECKLIST.md).

## When to use

- User says оформить репозиторий, x0tta6b, design standard, polish README, add CI/launchers/governance.
- Docs drifted from `.env.example` / route handlers.

## When not to use

- Changing trading, risk, or exec logic.
- Replacing accurate domain/hackathon docs with a “Why vs competitors” page.
- Adding Context Sync, `deploy-remote`, `CODE_OF_CONDUCT.md`, or `docs/agents-setup.md`.

## File pack

Keep existing domain docs. Do not delete `docs/DEMO.md`, `docs/SUBMISSION.md`, `docs/CURSOR_HANDOFF.md`, or `.cursor/rules/`.

| File | Role |
|------|------|
| `README.md` | Pitch, mermaid, live config table, docker + venv quickstart, real API table, hackathon links |
| `README.ru.md` | Short real RU translation + same facts, not a second English dump |
| `docs/architecture.md` | Same mermaid + real directories and ports |
| `docs/api-reference.md` | JSON keys copied from handlers |
| Extra `docs/*` | Only for subsystems that exist (`risk-engine`, signals) |
| `.cursorrules`, `AGENTS.md`, `CLAUDE.md` | Short stack + safety. No MCP tools that are not in this workspace |
| `start.ps1` / `start.sh` / `start.bat` | Compose `--build`, Docker via **exit code**, `/health` poll |
| `test.ps1` / `test.sh` | Offline smokes that exist; non-zero on fail |
| `.github/workflows/ci.yml` | Those smokes + `docker compose config` |
| `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md` | Real owner year; GitHub vuln reporting only |

**Never add:** competitor matrices, `deploy-remote.*`, `CODE_OF_CONDUCT.md`, `docs/agents-setup.md`, Context Sync `context_search` / `context_save` headers, invented API JSON, emoji “LIVE” banners, fake `pytest tests/` if that dir is empty.

Style: light badges (CI, language, Docker, license). No unpinned version numbers (`FastAPI 0.115+` when `requirements.txt` has bare `fastapi`). Facts over marketing. Few or no emojis in scripts (Windows `.bat` mangles them).

## Workflow

```
- [ ] Inventory (compose, routes, .env.example, scripts/, requirements)
- [ ] README/docs from inventory
- [ ] Launchers/CI against real script names
- [ ] Keep hackathon docs; link them
- [ ] Run CHECKLIST.md
```

### 1. Inventory

- `requirements.txt` — badge a version only if pinned
- `.env.example` — desk defaults (not commented legacy lines, not another repo’s `$2/$100/8`)
- Live `.env` (gitignored) — mention if it differs (e.g. `AGENT_MODE=llm` vs example `rules`)
- Route handlers — real keys (`ok` vs `status`; objects vs arrays)
- `docker-compose.yml` — services, ports, `container_name`
- `scripts/smoke_*.py` — only files that exist; skip ones that need keys/network in CI
- Domain docs judges need (track, exec mode, demo vs live)

### 2. README

```markdown
# <Product>

[badges: CI if workflow exists, Python 3.11+, Docker, MIT]

**[English](README.md)** · **[Русский](README.ru.md)** · docs links

<2–3 sentence pitch: what it does, exec mode, not live if demo>

## What actually runs   (table from .env.example + live notes)
## Mermaid              (real call graph)
## Risk / config        (from .env.example; note code fallbacks if different)
## Quick start          docker compose up -d --build; then venv
## API                  one-line table of real paths
## Layout               directories that exist
## Hackathon / extra    only if those docs exist
```

No “Why vs 3Commas”, no OS capability matrix, no “no keys required” if default exec places Demo orders.

### 3. API docs

Copy handler returns. Example for this desk: `GET /health` → `ok`, `paper`, `exec_mode`, `hub_demo`, `bitget_demo`, `hub_sync_exchange_sl`, `paper_fallback`. `/positions` is `{positions, count, source, ...}`, not a bare array.

### 4. Launchers

- `docker compose up -d --build`
- Docker detect: native exit code (`cmd /c "docker info >nul 2>&1"` / `docker info >/dev/null`), not PowerShell `try/catch` around redirected `docker info`
- Missing `.env` → copy `.env.example` once; never overwrite
- Python fallback: `.venv` if present; `ArgumentList` is an array (`"scripts/run_signal_loop.py", "--poll"`)
- Poll `GET /health` until the **real** success field (`ok` here). Exit 1 if timeout. Do not claim up after `sleep`
- `start.sh` Python fallback: `mkdir -p data` before `nohup` logs

### 5. CI and tests

- Branches: `main` and `master` if both exist
- `pip install -r requirements.txt` then listed smokes; `set -e` / stop on `$LASTEXITCODE`
- `docker compose config` after `cp .env.example .env`
- No `pytest tests/` unless `tests/` exists
- Smokes in the suite must isolate env (`RSI_LONG_MAX` etc.) so a live `.env` cannot fail them
- Do not put `smoke_bitget` / `smoke_hub_demo` / live LLM in CI

### 6. Agent files (this desk)

Keep short. Required lines when the repo is bitget-bot:

- `EXEC_MODE=hub_demo`, `BITGET_ALLOW_LIVE=0`
- Never bypass `risk/gate.py`
- Do not commit `.env` or `data/`
- `TF_BLOCKER_ENABLED=0`; pair blocker stays; `BTC_REGIME_TF=1h`
- Paper-live PnL is not Demo equity
- Do not assume Context Sync MCP exists

On other repos: same idea — real paths, real safety, no fake MCP.

### 7. Governance

- MIT with the GitHub owner and year
- `SECURITY.md`: GitHub private vulnerability reporting. No invented `@product.dev` mail
- `.gitignore` claims must match the file (this desk: `.env` and `data/`, not `.env*`)

## Anti-patterns

- Copying risk tables from another project
- Competitor checkmark matrices
- “No API keys” + `hub_demo` orders
- LLM as a dotted optional line while the running desk is `AGENT_MODE=llm`
- Fake `/health` (`status`, `agent_mode`, `timestamp`) or `confidence` on decisions
- `test.ps1` with `$ErrorActionPreference = Continue` and a green “complete”
- `deploy-remote` default host `10.10.10.11` packing `.env`
- Context Sync headers in `.cursorrules` / `AGENTS.md`

## After applying

Say what changed, what was deleted, which domain docs stayed. Do not commit unless asked.
