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
- [x] **Paper / Demo trading log (Track 1 required):** [`docs/evidence/paper_trading_log.csv`](evidence/paper_trading_log.csv) — fields `timestamp`, `trading_pair`, `direction`, `price`, `quantity`, `account_balance_change`, plus `status` / `mode`. How to regenerate: [`docs/evidence/README.md`](evidence/README.md)

---

## Paper / Demo trading log

Track 1 prefers a public live or paper log. This desk publishes **Demo UTA + paper shadow**, not live mainnet.

| File | Use |
|------|-----|
| [`docs/evidence/paper_trading_log.csv`](evidence/paper_trading_log.csv) | Canonical log for the form / judges |
| [`docs/evidence/paper_trading_log.jsonl`](evidence/paper_trading_log.jsonl) | Same rows as JSONL |
| [`docs/evidence/paper_trading_log.sample.csv`](evidence/paper_trading_log.sample.csv) | Sanitized `SIMULATED_DEMO` snapshot (native fill format in [`fixtures/`](evidence/fixtures/)) |

Canonical log is **Bitget UTA Demo** for this S2 desk: `hub_demo` opens/closes plus paper-shadow closes of those same Demo positions. It is not paper-live fallback and not Divergent V1.

```bash
python scripts/export_paper_log.py --from-desk                    # UTA Demo only
python scripts/export_paper_log.py --from-desk --include-paper-live  # also PAPER_FALLBACK
python scripts/export_paper_log.py                                # local data/paper_fills.jsonl if present
python scripts/export_paper_log.py --from-sample --write-sample   # tiny SIMULATED_DEMO fixture
```

`account_balance_change` is reconstructed Demo-venue equity delta (`0` on open, realized PnL on close) using the same cash model as `exec/account.py`. It is not a Bitget wallet snapshot. `mode` is `hub_demo` or `paper_shadow` (local close of a Demo position). Paper-live PnL is **not** in this file.

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

Public OHLCV → RSI / level-cross → rules or LLM decide → risk gate → Bitget Demo UTA (hub_demo) + dashboard :8080

Repo: https://github.com/scanner72/bitget-bot
Demo: https://_________________

#Web3 #TradingBot #Hackathon
```

RU variant:

```
Agent desk для Bitget S2: публичный OHLCV → сигналы → rules/LLM + risk → Bitget Demo UTA (не live mainnet) → дашборд :8080.

Репо: https://github.com/scanner72/bitget-bot
Видео: https://_________________
```

- [ ] Post: `https://x.com/_________________/status/_________________`

---

## Technical smoke (before submit)

- [ ] `.env`: `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0`, `HUB_SYNC_EXCHANGE_SL=1`, `HUB_LEVERAGE=20`
- [ ] Smokes: `smoke_signal` → `smoke_bitget` → `smoke_hub_demo` → `smoke_risk` → `smoke_decide` → `smoke_paper`
- [ ] Desk once: `python scripts/run_signal_loop.py --once`
- [ ] API: `GET /health` → `exec_mode` = `hub_demo`, `bitget_demo` = true
- [ ] Dashboard `/` + `/positions` (Demo PnL) + `/decisions` + `/account` (equity overlay)
- [ ] Optional: `docker compose up -d`
- [ ] Evidence log: `python scripts/export_paper_log.py --from-desk` → [`docs/evidence/paper_trading_log.csv`](evidence/paper_trading_log.csv)

---

## Form / portal fields

| Field | Value |
|-------|--------|
| Project name | Divergent Agent Desk / Bitget S2 |
| Track | Agent Trading |
| GitHub | `https://github.com/scanner72/bitget-bot` |
| Demo video | TBD |
| X post | TBD |
| Paper / Demo trading log | `https://github.com/scanner72/bitget-bot/blob/main/docs/evidence/paper_trading_log.csv` |
| Notes | Bitget Demo UTA via Agent Hub (`paptrading`); public OHLCV via ccxt; live mainnet disabled. Log is Demo/paper, not live. |

---

## Do / Don't

| Do | Don't |
|----|-------|
| Keep `BITGET_ALLOW_LIVE=0` for demo | Commit API secrets |
| Use Demo keys in local `.env` only | Show `.env` on camera |
| Refresh `docs/demo_artifacts/` before screenshots | Claim live mainnet trading |
| Link README + DEMO + handoff | Kill healthy overnight `--poll` without reason |

**Status:** docs aligned with `hub_demo` stack. Public paper/Demo log: [`docs/evidence/paper_trading_log.csv`](evidence/paper_trading_log.csv). Video not produced in-repo.
