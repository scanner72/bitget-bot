# Bitget S2 — Divergent Agent Desk

[![CI](https://github.com/scanner72/bitget-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/scanner72/bitget-bot/actions)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[English](README.md)** · **[Русский](README.ru.md)** · [Архитектура](docs/architecture.md) · [Риск](docs/risk-engine.md) · [API](docs/api-reference.md) · [Видео](docs/DEMO.md) · [Подача](docs/SUBMISSION.md) · [Лог сделок](docs/evidence/paper_trading_log.csv)

Хакатон Bitget AI **S2**, трек **Agentic Trading**. Публичный OHLCV Bitget → сигналы RSI / level-cross → rules или LLM → риск-гейт → **Bitget UTA Demo** (`hub_demo`) + локальный paper shadow → дашборд FastAPI на `:8080`.

**Не live mainnet.** `BITGET_ALLOW_LIVE=0`. Дедлайн **21 Sep 2026 24:00 UTC+8**. Форма: [forms.gle/GyWZCMCPocgJdJon6](https://forms.gle/GyWZCMCPocgJdJon6) — только после GitHub + paper log + видео + поста в X.

Публичные свечи без ключей. **Ордера на Demo — ключи Bitget Demo в локальном `.env`, в git не коммитить.**

| Слой | Этот стол |
|------|-----------|
| Исполнение | `hub_demo` — market **20×** (`HUB_LEVERAGE`) + биржевые SL+TP2 на UTA Demo |
| Тень | Paper: ATR TP1 → стоп в безубыток + трейл |
| Paper-live | `PAPER_FALLBACK=1` — нет пары на Demo → локальный fill; **этот PnL не складывать с Demo equity** |
| ТФ | только `15m`, `TF_BLOCKER_ENABLED=0` |
| Агент | в `.env.example` — `rules`; живой стол — `llm` (Groq), при ошибке откат на rules |

```bash
cp .env.example .env
# BITGET_* Demo-ключи. Опционально AGENT_MODE=llm + ключ Groq
docker compose up -d --build
# http://127.0.0.1:8080/health  →  "ok": true, "exec_mode": "hub_demo"
```

Windows: `.\start.ps1`. Смоки без сети: `.\test.ps1`. Полная таблица риска и API — в английском README и `docs/`.

Публичный лог **UTA Demo** этого стола (не live mainnet, не paper-live): [`docs/evidence/paper_trading_log.csv`](docs/evidence/paper_trading_log.csv). Поля чеклиста Track 1: timestamp, pair, direction, price, quantity, account balance change. Регенерация: `python scripts/export_paper_log.py --from-desk`.
