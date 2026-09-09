# Bitget S2 — Submission checklist

**Deadline:** 21 Sep (confirm on official Bitget hackathon page / Discord if shifted).  
**Track:** Agent Trading / Divergent Agent Desk  
**Mode:** Paper-only (`PAPER=true`). No live orders in this submission path.

---

## Repo

- [ ] GitHub remote **TBD** — replace placeholder after `git remote add` / push:
  - `https://github.com/_________________/bitget-bot`
- [ ] Repo is **public** for judges
- [ ] `.env` **not** committed (secrets / empty keys only in `.env.example`)
- [ ] README has EN+RU pitch, architecture, quickstart, API table
- [ ] Docker packaging present: `Dockerfile`, `docker-compose.yml` (optional for demo, useful for judges)
- [ ] Links from README → [`docs/DEMO.md`](DEMO.md) + this file

---

## Demo video (2–5 min)

- [ ] Record locally (OBS / Xbox Game Bar / etc.) using [`docs/DEMO.md`](DEMO.md) script
- [ ] Show: pitch → `smoke_bitget` → `run_signal_loop --once` → `http://127.0.0.1:8080` (`/health`, `/positions`, `/decisions`)
- [ ] Say clearly: **paper-only**, Agent Trading track, Docker optional
- [ ] Upload (YouTube / Loom / Drive unlisted OK if judges can open)
- [ ] Paste URL: `https://_________________`

Static artifacts for screenshots: `docs/demo_artifacts/` (`health.json`, `positions.json`, `decisions.json`, `fills.json`, `snapshot.html`).

---

## X / Twitter post (template)

Copy, fill links & handles, then post:

```
Built a paper-only Divergent Agent Desk for @Bitget #Bitget #AgentTrading #BitgetHackathon

Public OHLCV → RSI-momentum divergence → rules agent → risk gate → paper fills → FastAPI dashboard.

Repo: https://github.com/_________________/bitget-bot
Demo: https://_________________
DEMO script: docs/DEMO.md

#Web3 #TradingBot #Hackathon
```

RU variant (optional quote-tweet / reply):

```
Paper-only agent desk для Bitget S2 (Agent Trading): публичный OHLCV → дивергенции → rules + risk → paper fills → дашборд :8080.

Репо: https://github.com/_________________/bitget-bot
Видео: https://_________________
```

- [ ] Post published: `https://x.com/_________________/status/_________________`
- [ ] Hashtags used: `#Bitget` `#AgentTrading` (+ event tags if announced)

---

## Technical smoke (before submit)

- [ ] `PAPER=true`
- [ ] Smokes: `smoke_signal` → `smoke_bitget` → `smoke_risk` → `smoke_decide` → `smoke_llm_decide` → `smoke_paper`
- [ ] Desk once: `python scripts/run_signal_loop.py --once`
- [ ] API: `GET /health` → `{"ok":true,"paper":true}` (start: `.venv\Scripts\python.exe -u scripts\run_api.py`, pid → `data/api.pid`)
- [ ] Dashboard `/` + `/positions` + `/decisions` + `/fills`
- [ ] Optional: `docker compose up -d` then same URL

---

## Form / portal fields (fill when submitting)

| Field | Value |
|-------|--------|
| Project name | Divergent Agent Desk / Bitget S2 paper desk |
| Track | Agent Trading |
| GitHub | TBD |
| Demo video | TBD |
| X post | TBD |
| Contact | (your email / Discord) |
| Notes | Paper-only; public Bitget OHLCV via ccxt; no private trade keys required |

---

## Do / Don't

| Do | Don't |
|----|-------|
| Keep `PAPER=true` | Commit real API secrets |
| Leave overnight `--poll` alone if healthy | Kill poll unless necessary |
| Link README + DEMO + this checklist | Claim live trading |
| Refresh `docs/demo_artifacts/` before screenshots | Record secrets on camera |

**Status:** docs + artifacts prepared for one-pass local recording. Video file itself is **not** produced in-repo (no reliable recorder in automation).
