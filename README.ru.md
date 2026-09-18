# Bitget S2 — Divergent Agent Desk

[![CI](https://github.com/scanner72/bitget-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/scanner72/bitget-bot/actions)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[English](README.md)** · **[Русский](README.ru.md)** · [Архитектура](docs/architecture.md) · [Риск](docs/risk-engine.md) · [API](docs/api-reference.md) · [Видео](docs/DEMO.md) · [Подача](docs/SUBMISSION.md) · [Лог сделок](docs/evidence/paper_trading_log.csv) · [Кладбище идей](docs/research-graveyard.md)

Хакатон Bitget AI **S2**, трек **Agentic Trading**. Публичный OHLCV Bitget → сигналы RSI / level-cross → rules или LLM → риск-гейт → **Bitget UTA Demo** (`hub_demo`) + локальный paper shadow → дашборд FastAPI на `:8080`.

**Не live mainnet.** `BITGET_ALLOW_LIVE=0`. Дедлайн **21 Sep 2026 24:00 UTC+8**. Форма: [forms.gle/GyWZCMCPocgJdJon6](https://forms.gle/GyWZCMCPocgJdJon6) — только после GitHub + paper log + видео + поста в X.

Публичные свечи без ключей. **Ордера на Demo — ключи Bitget Demo в локальном `.env`, в git не коммитить.**

## Тезис выходных

S2: токенизированные акции и крипто-перпы торгуются **7×24**. Люди спят — стол нет.

**Утверждение:** RSI-дивергенция + `LEVEL_CROSS_DOWN` на `15m`/`1h`/`4h`, риск-гейт и сайз до стопа достаточны для автономного цикла **событие → решение → fill на Bitget Demo UTA** на выходных. Без бана ТФ, без подмешивания paper-live PnL в Demo equity, без превращения агента в research-совет или on-chain аттестацию.

rToken-перпы на выходных открыты (ATR 1h). `TIMEFRAMES=15m,1h,4h`. `RSI_LONG_MAX=0`. `TF_BLOCKER_ENABLED=0`. Что отвергли: [docs/research-graveyard.md](docs/research-graveyard.md). Проверка лога решений: `python scripts/verify_decision_log.py`.

| Слой | Этот стол |
|------|-----------|
| Исполнение | `hub_demo` — market, lev cap `HUB_LEVERAGE=20` (адаптивно 35/SL%) + биржевые SL+TP2 на UTA Demo |
| Тень | Paper: ATR TP1 → стоп в безубыток + трейл |
| Paper-live | `PAPER_FALLBACK=0` — скан всего Demo-каталога. `=1` снова включает локальный fill для имён вне Demo; **этот PnL не складывать с Demo equity** |
| ТФ | `15m,1h,4h`, `TF_BLOCKER_ENABLED=0` |
| Типы | `BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_DOWN` (`LEVEL_CROSS_UP` выключен) |
| Агент | в `.env.example` — `rules`; живой стол — `llm`, при ошибке откат на rules |

### Demo и paper-shadow

`paper-shadow` — локальное зеркало Demo-позиций для ATR-выходов, TP1/BE/trailing, риск-состояния и истории графика. Это не отдельный биржевой баланс.

1. Денежный итог: [`/equity`](http://127.0.0.1:8080/equity) — текущий Demo equity.
2. Реальные исполнения: [`/fills`](http://127.0.0.1:8080/fills?limit=100) — Bitget `exec_pnl` и комиссии.
3. Локальная история стратегии: [`/history`](http://127.0.0.1:8080/history?limit=200) и вкладка **Trade history** — расчёт из `data/paper_fills.jsonl`.

При расхождении paper `realized_pnl` и hub `exec_pnl` денежным результатом считается hub. Paper-значение в отчётах должно быть явно подписано как локальная оценка.

```bash
cp .env.example .env
# BITGET_* Demo-ключи. Опционально AGENT_MODE=llm + ключ Groq
docker compose up -d --build
# http://127.0.0.1:8080/health  →  "ok": true, "exec_mode": "hub_demo"
```

Windows: `.\start.ps1`. Смоки без сети: `.\test.ps1`. Полная таблица риска и API — в английском README и `docs/`.

Публичный лог **UTA Demo** этого стола (не live mainnet, не paper-live): [`docs/evidence/paper_trading_log.csv`](docs/evidence/paper_trading_log.csv). Поля чеклиста Track 1: timestamp, pair, direction, price, quantity, account balance change. Регенерация: `python scripts/export_paper_log.py --from-desk`.

Наблюдаемая валидация: [`docs/evidence/s2_validation.md`](docs/evidence/s2_validation.md). Готовый пятичастный текст официальной формы: [`docs/S2_FORM_COPY.md`](docs/S2_FORM_COPY.md).
