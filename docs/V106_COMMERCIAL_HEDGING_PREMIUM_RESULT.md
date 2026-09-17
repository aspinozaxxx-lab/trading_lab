# V106 — commercial hedging premium: нет кандидата для продвижения

2026-09-17. Один economic screen завершён **01:01:14.472329 UTC**. Покупка BR при
высокой чистой короткой позиции commercial category CFTC дала лишь **+0.1664% CAGR**,
а при двойных издержках **−0.0319%**. Всего 10 завершённых сделок за пять лет.
Основные сценарии прошли research execution, но оба constant-long controls имеют
по два aggregate gross-risk flags. Поэтому формальный verdict всей проверки —
**INVALID_EXECUTION_NO_PROMOTION**, не валидный парный statistical rejection.
Сама primary слишком слаба для продвижения независимо от проблем control.

## Результаты всех сценариев

Полные 2021–2025, стартовый капитал 1 млн RUB, cash interest 0. Base: один tick
slippage и базовая комиссия; double: два ticks и двойная комиссия. Research specs
не broker-exact. Control-числа ниже только диагностические, не исполнимый доход.

| Вариант | CAGR, % | Sharpe | MDD, % | Завершённые сделки | Конечный капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, base | 0.1664 | 0.05765 | 9.4115 | 10 | 1008321.79 |
| Primary, double | -0.0319 | 0.02508 | 9.8303 | 10 | 998411.33 |
| Constant-long control, base — invalid | 12.8410 | 0.57516 | 39.9078 | 60 | 1826358.76 |
| Constant-long control, double — invalid | 12.3384 | 0.55875 | 40.8893 | 60 | 1786157.70 |

| Год | Primary base, % | Primary double, % | Control base, % | Control double, % |
| --- | ---: | ---: | ---: | ---: |
| 2021 | -1.5198 | -1.9718 | 58.4862 | 57.4386 |
| 2022 | 1.3378 | 1.3194 | 25.9352 | 25.6308 |
| 2023 | 1.0366 | 0.5230 | -4.8980 | -6.1576 |
| 2024 | 0.0000 | 0.0000 | -0.4330 | -0.1016 |
| 2025 | 0.0000 | 0.0000 | -3.3632 | -3.6715 |

У всех четырёх сценариев 2 положительных года из 5. Primary не имела ненулевых
targets в 2024–2025; нулевые годы не вырезаны из CAGR и не считаются положительными.
Primary не проходит gates по CAGR, Sharpe, >=20 сделок и >=3 положительным годам.
Её просадка, худший год и coverage проходят отдельные gates, но этого недостаточно.
Сравнение с control execution-invalid; диагностическое преимущество тоже отсутствует.
Порог 5% Stage1 был порогом отбора компонента, не заменой цели устойчивых 20–50%.
Ни эта цель, ни независимый holdout/PIT/live результат не подтверждены.

## Что проверялось и какие данные использованы

[Замороженный протокол](V106_COMMERCIAL_HEDGING_PREMIUM.md):
`(producer_short - producer_long) / open_interest > 0` и строго выше медианы
предыдущих 52 отчётов → BR long 0.9; иначе cash. Все 53 отчёта должны быть валидными;
пропуски не пропускаются при построении baseline. Никакого fit или поиска параметров.
Control — постоянная покупка на том же доступном календаре. Это commercial category,
не повтор managed-money flow/crowding V58/V59/V87. Число traders не измеряет капитал,
spreading не измеряет свободную risk capacity; эти поля не входили в numerical read.

- Source metadata: 418 WTI reports, из них 417 с availability до 2026, все 417 с
  валидными позициями. 365 ready source states, 75 long states, включая warmup;
  dominated late reports 0. Это не количество сделок или независимых тестов.
- Clock: EOD New York от max(report + 7 calendar days, pinned official override),
  затем максимум availability всех 53 dependencies. Известные shutdown/ION delays
  учтены; GOLD-specific correction к WTI не применялась. TTL 21 день от report date.
- Числовые значения источника с availability >=2026 исключены до чтения. Рыночный
  development <=2025, original source receipts/revision chain не доказаны.
  CFTC WTI → MOEX Brent — cross-benchmark proxy, а не прямое измерение Brent hedging.
- По 1271 решению на arm: decision dates 2020-12-30…2025-12-29 для исполнения
  в 2021–2025; сигнал EOD, исполнение только на следующем фактическом open.
  Ненулевых targets 86 / 1204; использованных releases 18 / 249, primary / control.
- Feature-unavailable 0, source/plan-unavailable 1, stale-at-fill 65 на каждом arm.
  Source/feature readiness 94.8859%; joint readiness 1205/1271 = 94.8072%.
  Полный календарь сохранён, недоступные периоды не удалены.

## Ledger, издержки и ограничения исполнения

| Вариант | Gross VM, RUB | Комиссия, RUB | Slippage, RUB | Все costs, RUB | Net PnL, RUB | Filled legs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary base | 14239.64 | 3400.00 | 2517.86 | 5917.86 | 8321.79 | 32 |
| Primary double | 10250.00 | 6800.00 | 5038.67 | 11838.67 | -1588.67 | 32 |
| Control base — invalid | 886752.45 | 33740.00 | 26653.69 | 60393.69 | 826358.76 | 340 |
| Control double — invalid | 905107.89 | 66520.00 | 52430.19 | 118950.19 | 786157.70 | 336 |

Double costs могут менять integer sizes и gross VM, поэтому gross разных scenarios
не обязан совпадать. Position entries / round trips: primary 10/10, control 60/60;
rolls входят в counts. Exposed asset-sessions: 86 / 1204, primary / control.

Primary оба: execution_complete=true, critical failures 0, unresolved 0,
terminal_carried=false. Все unknown price/spec/fee/liquidity, margin/participation/
gross/atomic rejection, halt, cancellation и clipping counters равны 0.
Max close gross 0.907448 / 0.915562; max participation 0.0835422%, cap 1%.
Intraday adverse drawdown 10.6750% / 10.7941%, не путать с close-to-close MDD.

Controls оба: execution_complete=false, critical failures 2 и gross-limit rejection
count 2; unresolved 0, terminal_carried=false. Max close gross 1.087928 / 1.094837.
Max participation 0.8395734%; margin/participation/atomic rejections и unknown fields 0.
Factual halt/mark/carry counters по 1, cancel-no-open 1, cancel-no-liquidity 2;
roll-capacity cancellation/clipping 0. Это агрегированные counters, не независимо
установленные две конкретные заявки или даты нарушений. Intraday adverse drawdown
41.7390% / 42.7242%. Control не ремонтируется ради продвижения слабой primary.

## Идентичность, однократный запуск и резервная копия

- Seal: `75b297c3291c677dbd9ad61420ead7b463017d0b4b7915e4b831d67000f57394`,
  зафиксирован 00:59:09 UTC; pre-outcome commit/push
  `6e0beb0625f252df9ff5a6f6175249aefbdf58f1` до новых numeric values/outcomes.
- Code SHA `9d31681d4bdf6934768e06bc3bf0dade6e13590276d33eda4487a75eebf65273`;
  config SHA `20ad92aa26fad9dc851469ec9d76e529be75269a61aa298f7bca66207e260e55`.
  Protocol/test/pinned source-clock code и parent V101 seal входят в seal.
- Run: `/srv/trading_lab_data/runs/v106_commercial_hedging_premium_v1_75b297c3291c`.
  Unit `trading-lab-v106-commercial-hedging-75b297c3291c.service`, original invocation
  `ffb6c04a8b4e4ff0ad200638c7e565f0`, PID 1560097; запуск наблюдался 01:01:11 UTC.
- Completed 01:01:14.472329 UTC. Manifest SHA
  `c756f2446a0adb511a739838c9e75d7f5c49d18414a696ae7ac444dc1782fa16`;
  metrics SHA `934d9502bc9d05aff69a3901e0c487b12578e05246f172a0896a203aa974503a`.
  Исходный journal и закрытый manifest подтверждают завершение. Поздний transient
  unit `not-found` и default Result=success сами по себе его не доказывают.
- 29 новых / 156 combined local tests PASS (5.59s), 156 server tests PASS (1.89s),
  Ruff clean. Byte/schema/date/unit preflight local/server до numerical read PASS.
- Read-only audit 01:02:41.644452 UTC: 19 artifact hashes, 417 reports и 417 source
  states, 2 target replays, 4 cash/cost/metric/annual/count replays, assessment PASS.
  Это не независимая реконструкция каждого gross-risk counter.
- Резервная копия: `D:\Projects\trading_lab_data\runs\v106_commercial_hedging_premium_v1_75b297c3291c`.
  Единственный result archive 473250 bytes, SHA
  `de74d09323baf60b2c87d8296a5ebc361edf84f1879b12eadadf93606e91f000`.
  Все 20 regular members проверены перед extraction в новый отсутствовавший root;
  19 artifact hashes + manifest проверены после extraction. Никакого overwrite.
  Archive сохранён в external `tmp/v106_commercial_hedging_75b297c3291c/result.tar.gz`.

Source уже был на сервере: новый HTTP/parser/source transfer не понадобился.
Никаких precursor failures или economic reruns V106. Code/config/protocol после
результата не менялись; все реальные данные/results остаются вне Git.

## Решение и параллельная загрузка

V106 закрыт без продвижения. Не подбирать знак, baseline, asset, TTL, leverage или
control по увиденным результатам. Воронка: **37 portfolio = 29 REJECT_STAGE1 +
1 REJECT_STAGE2 + 1 incomplete + 6 invalid**; активных Stage2/3 кандидатов 0.
V93 component отдельно, V102 source-only и failed V105 V1 не дополнительные entrants.
Goal 20–50% остаётся active / неподтверждён; новый результат — отсев, не заработок.

AlgoPack main на 01:04 UTC продолжал работать, 18730/26305 jobs (71.2032%),
168828717 rows, failed 0 / blocked 0, final manifest отсутствует. Замер data +
source_evidence: **14032314917 bytes / 14.032 GB**, включая **12070256247 bytes /
12.070 GB AlgoPack**. Apparent bytes при записи, без models/runs/tmp и прибавления
локальных копий; jobs fraction не доля конечного объёма. FUTOI прежние 550 gaps
не исчезли. Подробности в [archive status](ALGOPACK_ARCHIVE_V1_STATUS.md).

Следующий небольшой шаг — [обзор датированных публикаций платёжного баланса ЦБ](
NEXT_SOURCE_REVIEW_20260916.md): coverage, availability/revisions и сопоставимость
показателей, не новый большой parser/collector. V107/rule/seal пока нет. Broad
AlgoPack economic scope unanswered, TIC paused, рыночные outcomes 2026 защищены.
