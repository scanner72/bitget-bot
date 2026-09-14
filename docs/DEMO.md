# DEMO — сценарий записи (2–3 мин) | Bitget S2

**Трек:** Agent Trading / Divergent Agent Desk  
**Режим:** `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `BITGET_ALLOW_LIVE=0` — Bitget UTA Demo (`paptrading`) + paper shadow для soft exits/UI.  
**Цель записи:** один проход без монтажа: pitch → smoke → loop once → dashboard с Demo PnL.

Перед записью (один раз, вне кадра или в начале):

```powershell
cd C:\bitget-bot
.venv\Scripts\activate
# .env: EXEC_MODE=hub_demo, BITGET_DEMO=1, Demo API keys (не показывать на камере)
# API (если ещё не слушает 8080):
.venv\Scripts\python.exe -u scripts\run_api.py
# Overnight poll (--poll) можно НЕ трогать — оставьте фоновый процесс.
```

Браузер заранее: вкладки `http://127.0.0.1:8080/` , `/health` , `/positions` , `/decisions`.  
Артефакты для скриншотов: `docs/demo_artifacts/` (JSON + `snapshot.html`).

---

## 0:00–1:00 — Pitch (~60 с)

Говорите по пунктам (RU, можно вкраплениями EN):

1. **Что это:** Divergent Agent Desk для Bitget S2 — публичный OHLCV → RSI/level-cross → decide (`rules` или `llm`, fallback на rules) → risk-gate → **Bitget Demo UTA** market open/close + paper shadow (TP1→BE/trail) → FastAPI dashboard.
2. **Трек:** Agent Trading / Divergent Agent Desk. **Live mainnet не в scope** — только Demo (`paptrading`); `BITGET_ALLOW_LIVE=0`.
3. **Стек:** public WS candles (`MARKET_DATA_MODE=ws`) + REST bootstrap → `signals/` → `desk` loop → `agent.decide` → `risk.gate` → `exec.router` → `exec.bitget_hub` + `exec.paper` → `api` `:8080` (исполнение остаётся REST).
4. **Риски:** risk-to-SL sizing (`RISK_USD_PER_TRADE`), exchange SL+TP2 при open, sync SL после TP1; daily loss kill / max positions / cooldown — env + `decisions.jsonl`.
5. **Docker опционален:** `docker compose up -d`; для записи достаточно `.venv`.

Фраза-якорь: *«Bitget Demo UTA. Публичные свечи. Полный агентный цикл с exchange SL-парашютом. Live mainnet выключен.»*

---

## 1:00–2:30 — Live demo (90–120 с)

### A. Smoke Bitget (~20–30 с)

```powershell
.venv\Scripts\python.exe scripts\smoke_bitget.py
.venv\Scripts\python.exe scripts\smoke_hub_demo.py
```

Показать: public OHLCV OK; Demo credentials / UTA client OK (без вывода ключей).

### B. Один проход desk (~20–30 с)

```powershell
.venv\Scripts\python.exe scripts\run_signal_loop.py --once
```

Показать логи: `[HUB] OPEN`, `[HUB] TPSL`, `[SIZE] risk_usd=...`, строки в `data/decisions.jsonl`.  
Публичный лог для судей (не live mainnet, не V1): [`docs/evidence/paper_trading_log.csv`](evidence/paper_trading_log.csv) — `python scripts/export_paper_log.py --from-desk`.  
**Не останавливайте** фоновый `--poll`, если он уже крутится.

### C. Dashboard API (~40–60 с)

| URL | Что сказать |
|-----|-------------|
| `http://127.0.0.1:8080/health` | `exec_mode: hub_demo`, `bitget_demo: true` |
| `http://127.0.0.1:8080/` | HTML desk, auto-refresh 8s, PnL с Demo |
| `http://127.0.0.1:8080/positions` | `pnl_source=hub_demo`, exchange entry/mark/margin |
| `http://127.0.0.1:8080/decisions` | agent + risk decisions |
| `http://127.0.0.1:8080/account` | Demo equity overlay |

Скриншот-хелпер: `docs/demo_artifacts/snapshot.html`.

### D. Закрытие (~10 с)

- Повторить: **Bitget Demo UTA**, не live mainnet, трек **Agent Trading**, репо + `docs/SUBMISSION.md`.
- Docker optional для судей.

---

## Чеклист перед Rec

- [ ] `.env`: `EXEC_MODE=hub_demo`, `BITGET_DEMO=1`, `HUB_SYNC_EXCHANGE_SL=1`
- [ ] Demo API keys заполнены (не на экране)
- [ ] API на 8080
- [ ] `docs/demo_artifacts/*.json` свежие
- [ ] Терминал крупный шрифт; `/health` уже открыт

**Видео mp4 здесь не пишем** — сценарий для локальной записи (OBS / Win+G / Zoom).

---

## EN TL;DR (для описания ролика)

Bitget S2 Divergent Agent Desk (Agent Trading): public OHLCV → signals → rules agent → risk gate → **Bitget Demo UTA** execution + paper shadow exits → FastAPI `:8080`. Exchange SL+TP2 on open; soft TP1/BE/trail local. Docker optional. Live mainnet blocked (`BITGET_ALLOW_LIVE=0`).
