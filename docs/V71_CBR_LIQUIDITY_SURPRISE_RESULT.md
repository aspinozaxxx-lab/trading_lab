# V71 — ошибка прогноза ликвидности ЦБ: REJECT_STAGE1

Завершено2026-09-13. Один новый механизм, одна primary и один контроль, два costs.
[Протокол](V71_CBR_LIQUIDITY_SURPRISE.md) и [input-scope R1](V71_SCOPE_REPAIR_R1.md).
Непредвиденный government-account приток → long SI, отток → short SI; контроль —
направление самого фактического вклада. Период2021–2025 — уже открытая development
history, не независимый holdout. **Прибыль не найдена, цель20–50% не достигнута.**

## Экономический результат

| Arm / costs | CAGR | Sharpe | MDD | Закрытые эпизоды | Исполненные legs | Прибыльные годы |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary base | -8,1877% | -0,3619 | 41,8831% | 121 | 264 | 1/5 |
| Primary double | -8,1629% | -0,3608 | 41,7189% | 121 | 256 | 1/5 |
| Control base | -20,6766% | -1,1688 | 68,9795% | 132 | 236 | 0/5 |
| Control double | -20,8825% | -1,1779 | 69,4454% | 132 | 241 | 0/5 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | -11,4394% | -11,7453% | -13,4867% | -13,7218% |
| 2022 | 5,2840% | 5,3949% | -39,4435% | -39,9215% |
| 2023 | -8,9795% | -9,4192% | -10,7539% | -10,7913% |
| 2024 | -15,2884% | -15,3209% | -30,9759% | -31,8773% |
| 2025 | -9,1451% | -8,3253% | -2,3645% | -1,2594% |

Начальный капитал1 000 000руб. Полный PnL за весь период, не годовая прибыль:

| Arm / costs | Gross VM PnL,руб. | Все затраты,руб. | Net PnL,руб. | Остаток,руб. |
| --- | ---: | ---: | ---: | ---: |
| Primary base | -333789,45 | 13029,97 | -346819,42 | 653180,58 |
| Primary double | -319998,18 | 25939,94 | -345938,12 | 654061,88 |
| Control base | -675344,90 | 9559,95 | -684904,85 | 315095,15 |
| Control double | -669921,31 | 19039,90 | -688961,21 | 311038,79 |

Отрицательный результат возникает уже до затрат. Ошибка прогноза существенно лучше
actual-only контроля, но это сравнение двух убыточных вариантов, не alpha admission.
Один положительный2022 год не компенсирует остальные четыре отрицательных года.
Base/double — отдельные integer/cash-dependent ledgers: дополнительные затраты меняют
размеры дальнейших позиций и количество legs. Поэтому небольшой прирост double net
относительно base не ошибка суммирования и не «польза комиссий»; оба глубоко отрицательны.

## Coverage, clocks и риск

458 прогнозов всего; 255 публикаций2021–2025, из них254 периода целиком до2026.
214 ready/254 =84,2520%;22 irregular,18 с неполным набором рабочих дат,1 будущий
forecast period outside window. Missing не заполнены; будущие actual/market2026
не читались. Методика сопоставления фиксировалась до результата: среднее накопленных
вкладов пяти рабочих дней напечатанного периода, не простая сумма и не усреднение
семи календарных дней. Сверены [таблица прогноза](https://www.cbr.ru/statistics/pffl/),
[определения факта](https://www.cbr.ru/statistics/flikvid/definitions/) и
[методика ЦБ, раздел3.1 и пример1](https://www.cbr.ru/Content/Document/File/17135/DKP_limit.pdf).
Это development convention с current-vintage источниками, не доказательство точного
исторического market consensus или неизменности первоначальных публикаций.

Оба arm:1271 decisions,1056 ненулевых targets,214 использованных releases.
Feature unavailable198, source unavailable1, stale40 — пересекающиеся категории,
не складывать. В каждом ledger1271 сессия,1057 exposed sessions: один дополнительный
carry относится к factual halt. По121 входу/выходу primary, по132 control.
Все4 executions complete, critical failures0, unresolved halt0, terminal flat.
При этом один factual halt/mark/carry и один target cancellation из-за missing open
есть в каждом scenario; они не удалены из календаря и отчёта.

Target gross1 — ограничение намерения/входа, не гарантия постоянного intraday gross≤1:
maximum close gross1,07573/1,08044 primary и1,12679/1,13225 control после изменения
цен/капитала. Maximum actual modeled participation0,015714% primary и0,010588%
control, ниже fixed1% cap. Брокерские fees/margin/BBO не доказаны; это прежний
research-proxy ledger без collateral interest и без допуска к реальным сделкам.

## Отсев

Во всех4 сценариях техническая полнота, terminal flat и coverage достаточны.
Primary в обоих costs проваливает CAGR≥5%, Sharpe≥0,5, MDD≤25%, positive years≥4/5,
worst year≥−15%. Trade count и превосходство контроля≥2п.п. проходят, но не заменяют
остальные gates. **REJECT_STAGE1, Stage2=0, historical20/50=false, goal_verified=false.**

V18 forecast-sign и V19 daily Minfin FX persistence не повторялись. V71 — отдельное
сопоставление прогноза с реализованным периодом. Его знак, агрегацию, week filter,
TTL, контроль и leverage после результата не менять. Не продвигать контроль.
V65–V71: **13 отсеянных гипотез,0 Stage2**. R1 не добавляет гипотезу в этот счёт.

## Provenance и завершение

- V1 pre-outcome push `f6cffe8dd6fe70e0364468d252753ce86e301235`.
  Config SHA `77896703660b749fa309882a9090e0e4a211e286a0acad186a771e2462ccdc66`;
  seal `ed9b8bc813579e2af40f0039b1f6044428129c73b3a0c796fdc4ca780b6f2e4a`.
  Failed parent: `/srv/trading_lab_data/runs/v71_cbr_liquidity_surprise_v1_ed9b8bc81357`.
  Только inputs/states, до первой portfolio simulation; exact join остановил full-market
  specs против уже отфильтрованных SI observations. Никаких economic outputs/PnL.
- R1 pre-first-simulation push `8f447cb`.
  Config SHA `c38c1879742d2d9dd8ee1f823e8f643232a0e3c68c6f89d61dd31b687b5d5334`;
  seal `e9ac4c0832cdb9e999745816a459b0081a79260ddeac2bcc8f42e504b5c4526b`.
  Исправлен только specs scope; exact join, V1 code/economics/gates сохранены.
- Единственный завершённый economic run:
  `/srv/trading_lab_data/runs/v71_cbr_liquidity_surprise_r1_e9ac4c0832cd`.
  Metrics SHA `d4749f1aefeec4e40f386f29cccfff0c7274907925f388e28d57946c179857f4`;
  identity SHA `5b7e861e269d4602e4632b1e916f0cc42aee9f387fb8efb8604b00fb9855dc89`.
- Economic runtime2,122537s. Local7repair+20V71+11shared+2encoding =40 PASS;
  server27 PASS за0,19s до экономического запуска. Ruff/diff PASS.
- Audit17/17 child hashes, source-state replay,4 metric/count/cost/cash replays PASS.
  Inputs/states bytes совпадают с frozen failed parent; его два файла неизменны.
  Canonical не перезаписывался, повторных portfolio simulations не было.
- Data/raw/run artifacts вне Git, authoritative на gpu-mlserver. Локальные задачи,
  collectors schedules и старый paper bootstrap не менялись. Защищённые2026
  prices/returns/labels/PnL не использовались.

Следующий допустимый шаг — новый содержательный механизм/information set на имеющихся
данных; не retuning V71 и не ещё один диагностический прогон уже убыточной семьи.
