# DEMO — сценарий записи (2–3 мин) | Bitget S2

**Трек:** Agent Trading / Divergent Agent Desk  
**Режим:** `PAPER=true` only — без live-ордеров, без приватных ключей Bitget для публичного OHLCV.  
**Цель записи:** один проход без монтажа: pitch → smoke → loop once → dashboard.

Перед записью (один раз, вне кадра или в начале):

```powershell
cd C:\bitget-bot
.venv\Scripts\activate
# API (если ещё не слушает 8080):
.venv\Scripts\python.exe -u scripts\run_api.py
# Overnight poll (--poll) можно НЕ трогать — оставьте фоновый процесс.
```

Браузер заранее: вкладки `http://127.0.0.1:8080/` , `/health` , `/positions` , `/decisions`.  
Артефакты для скриншотов: `docs/demo_artifacts/` (JSON + `snapshot.html`).

---

## 0:00–1:00 — Pitch (~60 с)

Говорите по пунктам (RU, можно вкраплениями EN):

1. **Что это:** paper-only agent desk для Bitget S2 — публичный OHLCV → детект RSI-momentum дивергенций → rules-агент (ENTER/SKIP/REDUCE) → risk-gate → paper fills → FastAPI dashboard.
2. **Трек:** Agent Trading / Divergent Agent Desk. Live-торговля **не** в scope; всё на paper-состоянии в `data/`.
3. **Стек:** ccxt (Bitget public) → `signals/` → `desk` loop → `agent.decide` → `risk.gate` → `exec.paper` → `api` на `:8080`.
4. **Риски:** лимиты notional / daily loss kill / max positions / cooldown / one-per-symbol — всё в env, решения в `decisions.jsonl`.
5. **Docker опционален:** `docker compose up -d` поднимает api + desk; для демо достаточно локального `.venv`.

Фраза-якорь: *«Paper only. Публичные свечи Bitget. Полный агентный цикл без live-ордеров.»*

---

## 1:00–2:30 — Live demo (90–120 с)

### A. Smoke Bitget (~20–30 с)

В терминале:

```powershell
.venv\Scripts\python.exe scripts\smoke_bitget.py
```

Показать: публичный OHLCV тянется, символы/таймфрейм ок. (Опционально быстро: `smoke_signal` / `smoke_paper` — если время есть.)

### B. Один проход desk (~20–30 с)

```powershell
.venv\Scripts\python.exe scripts\run_signal_loop.py --once
```

Показать хвост логов / появление строк в `data/` (candidates / decisions).  
**Не останавливайте** уже идущий `python -u run_signal_loop --poll`, если он крутится overnight — для демо достаточно `--once` в отдельном окне.

### C. Dashboard API (~40–60 с)

Открыть в браузере (или curl):

| URL | Что сказать |
|-----|-------------|
| `http://127.0.0.1:8080/health` | `ok` + `paper: true` — paper-only |
| `http://127.0.0.1:8080/` | HTML desk: decisions / positions |
| `http://127.0.0.1:8080/positions` | открытые paper-позиции |
| `http://127.0.0.1:8080/decisions` | хвост решений агента + risk |
| `http://127.0.0.1:8080/fills` | paper fills (если есть) |

Скриншот-хелпер: открыть `docs/demo_artifacts/snapshot.html` (статичный снимок JSON).

### D. Закрытие (~10 с)

- Повторить: **paper-only**, трек **Agent Trading**, репо + этот DEMO-скрипт.  
- Docker — optional для судей (`Dockerfile` / `compose` в корне).  
- Ссылка на README и `docs/SUBMISSION.md`.

---

## Чеклист перед Rec

- [ ] `PAPER=true` в `.env`
- [ ] API на 8080 (pid в `data/api.pid` если стартовали скриптом)
- [ ] Poll overnight не убит без нужды
- [ ] `docs/demo_artifacts/*.json` свежие
- [ ] Терминал крупный шрифт; браузер на health уже открыт
- [ ] Секреты не на экране (`.env` не показывать)

**Видео mp4 здесь не пишем** — этот файл = сценарий на один проход записи у вас локально (OBS / Win+G / Zoom и т.п.).

---

## EN TL;DR (для судей в описании ролика)

Paper-only RSI-momentum divergence agent desk for Bitget (Agent Trading): public OHLCV → signals → rules agent → risk gate → paper fills → FastAPI `:8080`. Docker optional. No live orders.
