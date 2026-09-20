# DEMO 90 секунд — judge cut (против AfterHours / CROSSFIRE / Decis)

Полный сценарий 2–3 мин: [`DEMO.md`](DEMO.md).  
Этот файл — **жёсткий монтаж ~90 с** под судей и X. Один дубль, крупный шрифт, ключи не в кадре.

**Перед Rec:** API `:8080`, `.env` = `hub_demo` + Demo keys, вкладки `/` `/health` `/decisions` `/equity`, артефакты `docs/demo_artifacts/`.

---

## Тайминг

| Сек | Кадр | Что говоришь (RU) |
|-----|------|-------------------|
| **0–12** | Титул / README weekend thesis | «Divergent Agent Desk, Bitget S2, трек Agentic Trading. Рынки и rToken не спят — стол тоже. Это не research-чат вроде Decis и не human-approve слой.» |
| **12–28** | `/health` крупно | «Исполнение только Bitget UTA Demo: `exec_mode=hub_demo`, live mainnet выключен. Честный контур: Demo деньги отдельно от paper-shadow.» |
| **28–48** | Терминал: `run_signal_loop.py --once` или свежий лог `[HUB] OPEN` | «Цикл: публичные свечи → RSI / level-cross → rules или LLM → risk-gate → market open на Demo с биржевым SL и TP2.» |
| **48–68** | `/decisions` + строка с `manifest_hash` / hash | «Каждое решение в JSONL с session, context и SHA-256. Не multi-agent дебаты и не on-chain аттест — проверяемый локальный манифест. `verify_decision_log.py`.» |
| **68–82** | Dashboard `/` + `/equity` | «ПослеHours-нарратив есть у многих. У нас fill на Demo и equity с биржи как источник правды по деньгам — не cinema ради cinema.» |
| **82–90** | Репо URL на экране | «GitHub scanner72/bitget-bot. Paper log и validation в docs/evidence. Docker optional. Спасибо.» |

---

## EN voiceover (если ролик на английском)

0–12: Divergent Agent Desk, Bitget S2 Agentic Trading. Markets don’t sleep — neither does this desk. Not a research workstation. Not AI-propose / human-approve.

12–28: Execution is Bitget UTA Demo only. `hub_demo`. Live mainnet blocked. Demo equity is money truth; paper shadow is strategy diagnostics.

28–48: Public candles → RSI / level-cross → rules or LLM → hard risk gate → Demo market open with exchange SL+TP2.

48–68: Every decision is hashed JSONL — session, context, manifest. No debate council. Verify with `verify_decision_log.py`.

68–82: Same weekend thesis as AfterHours-style pitches — plus a real Demo fill and exchange equity on screen.

82–90: github.com/scanner72/bitget-bot — evidence CSV + validation linked in the README.

---

## Чеклист кадра (обязательно попасть)

- [ ] Слово **Demo** / `hub_demo` на экране  
- [ ] Хотя бы один **hash** / `manifest_hash`  
- [ ] `/equity` или fills с биржи  
- [ ] Явно: **не live mainnet**  
- [ ] URL репо в конце  

## Не делать

- Не показывать `.env` и ключи  
- Не обещать прибыльность; можно мельком честный observed equity из validation  
- Не уводить в 3-минутный tour API — для X нужен этот 90с cut; полный — в `DEMO.md`
