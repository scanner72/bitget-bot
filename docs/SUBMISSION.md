# Bitget S2 — Submission checklist

**Deadline:** 21 Sep (confirm on official Bitget hackathon page / Discord if shifted).  
**Track:** Agent Trading / Divergent Agent Desk  
**Mode:** `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0` — Bitget UTA Demo (`paptrading`) + paper shadow. **Not live mainnet.**

---

## Repo

- [ ] GitHub public: `https://github.com/scanner72/bitget-bot` (or your fork)
- [ ] `.env` **not** committed (Demo keys only in local env / `.env.example` placeholders)
- [ ] README EN+RU pitch, architecture, hub_demo quickstart, API table
- [ ] Docker: `Dockerfile`, `docker-compose.yml` (optional for judges)
- [ ] Links: [`docs/DEMO.md`](DEMO.md) + this file + [`docs/CURSOR_HANDOFF.md`](CURSOR_HANDOFF.md)

---

## Demo video (2–5 min)

- [ ] Record using [`docs/DEMO.md`](DEMO.md)
- [ ] Show: pitch → `smoke_bitget` + `smoke_hub_demo` → `run_signal_loop --once` → `:8080` (`/health`, `/positions`, `/decisions`)
- [ ] Say clearly: **Bitget Demo UTA**, not live mainnet; Agent Trading track; Docker optional
- [ ] Upload URL: `https://_________________`

Artifacts: `docs/demo_artifacts/` (`health.json`, `positions.json`, …).

---

## X / Twitter post (template)

```
Built a Divergent Agent Desk for @Bitget #Bitget #AgentTrading #BitgetHackathon

Public OHLCV → RSI divergence → rules agent → risk gate → Bitget Demo UTA (hub_demo) + dashboard :8080

Repo: https://github.com/scanner72/bitget-bot
Demo: https://_________________

#Web3 #TradingBot #Hackathon
```

RU variant:

```
Agent desk для Bitget S2: публичный OHLCV → сигналы → rules + risk → Bitget Demo UTA (не live mainnet) → дашборд :8080.

Репо: https://github.com/scanner72/bitget-bot
Видео: https://_________________
```

- [ ] Post: `https://x.com/_________________/status/_________________`

---

## Technical smoke (before submit)

- [ ] `.env`: `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`, `HUB_SYNC_EXCHANGE_SL=1`
- [ ] Smokes: `smoke_signal` → `smoke_bitget` → `smoke_hub_demo` → `smoke_risk` → `smoke_decide` → `smoke_paper`
- [ ] Desk once: `python scripts/run_signal_loop.py --once`
- [ ] API: `GET /health` → `exec_mode` = `hub_demo`, `bitget_demo` = true
- [ ] Dashboard `/` + `/positions` (Demo PnL) + `/decisions` + `/account` (equity overlay)
- [ ] Optional: `docker compose up -d`

---

## Form / portal fields

| Field | Value |
|-------|--------|
| Project name | Divergent Agent Desk / Bitget S2 |
| Track | Agent Trading |
| GitHub | `https://github.com/scanner72/bitget-bot` |
| Demo video | TBD |
| X post | TBD |
| Notes | Bitget Demo UTA via Agent Hub (`paptrading`); public OHLCV via ccxt; live mainnet disabled |

---

## Do / Don't

| Do | Don't |
|----|-------|
| Keep `BITGET_ALLOW_LIVE=0` for demo | Commit API secrets |
| Use Demo keys in local `.env` only | Show `.env` on camera |
| Refresh `docs/demo_artifacts/` before screenshots | Claim live mainnet trading |
| Link README + DEMO + handoff | Kill healthy overnight `--poll` without reason |

**Status:** docs aligned with `hub_demo` stack (commit `7473d5a`+). Video not produced in-repo.
