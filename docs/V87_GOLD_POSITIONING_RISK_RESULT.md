# V87 — GOLD positioning: слабый результат, без перехода на Stage2

2026-09-15. Один заранее зафиксированный тест завершён. Базовый вариант дал
**1,1282% CAGR при просадке 44,1600%** — недостаточно даже для предварительного
отбора компонента. Удвоенные издержки дали один критический отказ по gross limit.
Итог всего конкурса: **INVALID_EXECUTION_NO_PROMOTION**, не подтверждение прибыли.
Не менять знак, период, размер, горизонт или правила пропусков ради повторного теста.

[Протокол](V87_GOLD_POSITIONING_RISK.md). Pre-outcome commit `165e823`.
Seal: `d1046052fd5e9de1451e7eaf5e209873e692ff9f032c7cc83b19522abb96d278`.
Canonical: `/srv/trading_lab_data/runs/v87_gold_positioning_risk_v1_d1046052fd5e`.
Metrics SHA: `3d38bc7706bfb554586495040311169ba8d911266e9ee44b6a23941fe89f3c0b`.
Unit: `trading-lab-v87-gold-risk-d1046052fd5e.service`;
invocation при запуске `5408f0fdc7d74b3a82a775ebcf073860`, PID3007091.
На14:15:56.767164UTC: PID0, exit0, inactive/dead; journal подтвердил четыре расчёта
и успешное завершение программы. Transient unit уже не сохраняет InvocationID и
ExecMainExitTimestamp в текущем show; точный момент завершения не выдумывается.
Economic compute3,896527s. Реальных брокерских сделок и fills:0.

## Все варианты и издержки

Основное правило: рост GOLD managed-money net share за13отчётов означает
SI+0.45/MIX−0.45; снижение — обратную позицию. Контроль — постоянная защитная
позиция с теми же masks.2018warmup,2019–2025evaluation, без обучения или перебора.
Строка primary/double — диагностический результат неполного исполнения, а не
валидированный stressed backtest. Даже базовый сценарий не проходит economics gates.

| Вариант | Costs | CAGR | Sharpe | MDD | Закрытые asset episodes | Costs RUB | Critical failures | Execution complete |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| primary | base | 1.1282% | 0.1517 | 44.1600% | 161 | 12840.16 | 0 | true |
| primary | double | 0.9010% | 0.1356 | 44.8684% | 161 | 25520.32 | 1 | false |
| control | base | -2.5197% | -0.1306 | 32.2064% | 66 | 4720.09 | 0 | true |
| control | double | -2.5240% | -0.1313 | 31.9037% | 66 | 9440.19 | 0 | true |

На начальный1millionRUB primary netPnL81575,10/64701,75RUB;
gross VM94415,26/90222,07RUB. Control netPnL−163376,49/−163634,63RUB;
gross VM−158656,39/−154194,44RUB. Более низкие комиссии не дают нужного запаса.
Primary лучше контроля на3,648/3,425п.п.CAGR, но абсолютная доходность, Sharpe,
просадка и худший год не проходят пороги. Это не основание продвигать контроль
или изменять размер.161 — отдельные закрытые позиции по активам, не161atomicpairs.

Filled model legs314/308 primary,187/187 control. Turnover133,281/132,296 и
47,978/47,997 стартовых капиталов. Unresolved halts0, terminal positions flat во
всех сценариях. По16factualhalt/carry marks и16cancel-no-open; liquidity cancellations
4/4 primary и3/3 control; roll-capacity cancellation1/1 primary,0/0 control.
Один critical gross rejection только primary/double; ни один из этих counters
не удалён. Maximum closing gross leverage1,0470/1,0578 primary и1,0142/1,0110 control:
signalgross0.9/ordercap1 не гарантируют непрерывный risk cap после движения цены.
Cost changes меняют integer quantities и путь капитала; варианты не отличаются
только арифметическим вычитанием дополнительной комиссии из одинаковых сделок.

## Все годы

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2019 | 1.98% | 1.77% | -10.77% | -10.86% |
| 2020 | 39.45% | 40.44% | 1.14% | 1.14% |
| 2021 | 3.16% | 2.98% | -9.78% | -9.79% |
| 2022 | -36.53% | -37.55% | 1.65% | 1.94% |
| 2023 | 7.79% | 7.17% | -1.46% | -1.54% |
| 2024 | 9.04% | 8.93% | 10.91% | 10.84% |
| 2025 | -1.18% | -0.78% | -7.50% | -7.56% |

Primary имеет5/7положительных лет, но сильный2020не компенсирует обвал2022до
нужного CAGR. Все эти годы уже использованы другими семьями: не unseen holdout.

## Источник, причинность и проверка

418GOLD reports,405полных quarterly changes с учётом warmup,
364ready source dates в evaluation с availability до2026;27отчётов дополнительно
задержаны из-за известных публикаций/исправления.2019Gold correction и shutdown/ION
timing учтены только в новом adapter; source V1 и отвергнутый V58 не переписаны.
Источник годовых архивов не доказывает отсутствие других поздних исправлений.

Каждый arm:3542asset decisions на1771датах,3324ненулевых targets,
348использованных source releases,200stale flags,16source-unavailable,0feature-unavailable.
Feature/date coverage94,3535%; это не доля исполненных paired trades.
Ни one-yearreturn, ни future label не использовались для inference eligibility.

- Local125targeted synthetic/parent tests PASS, Ruff clean.
- Дополнительно65ledger/V64/V87tests PASS; к125не складывать из-за overlap31V87tests.
- Server31V87tests PASS;12sealed file identities проверены перед запуском.
- Audit21artifact hashes, source→state→target и4metric/year/count/cash replays PASS.
- Независимый расчёт через точные Fraction:418report clocks/readiness,
  405quarterly changes/signs PASS. Audit завершён14:17:10.625606UTC.
- Canonical metrics SHA после audit прежний. Новых источников, моделей,2026outcomes,
  перезапуска collectors или реальных сделок нет.

## Объём скачанного: уточнённый состав

Замер14:18:06UTC (17:18UTC+3), bytes — `du` apparent size, включая metadata:

| Каталог | Apparent bytes | GB, decimal | Allocated bytes |
| --- | ---: | ---: | ---: |
| `/srv/trading_lab_data/data/algopack-archive` | 1808645667 | 1.809 | 2276061184 |
| Старая canonical core4 AlgoPack history | 1418832691 | 1.419 | 1443438592 |
| Весь server `data`, включая эти каталоги | 4520667040 | 4.521 | 5202214912 |
| Server `source_evidence` | 150734614 | 0.151 | 152547328 |
| Server `data` + `source_evidence` | 4671401654 | 4.671 | 5354762240 |

В14:19отдельно проверен `/data/processed/algopack`:1456918554bytes (1.457GB),
включая core4, inventory и samples. Два основных исторических AlgoPack каталога
содержат около3.27GB; это объём файлов, не дедуплицированных observations.
Совместный `du` в14:19:27 дал archive1814986143 и core41418832691bytes;
оба root обычные каталоги, не symlinks. Разница от14:18 — ongoing download.

**Поправка к прежним volume checkpoints:** фраза «весь AlgoPack, включая oldcore4»
неверно описывала состав. Массовый `algopack-archive` не включает canonical core4
history размером1.419GB в другом каталоге. Поэтому прежние1.67GB нельзя считать
всем ранее скачанным AlgoPack. Общий server data root уже включал старую историю;
его размер не нужно увеличивать второй раз. Старые замеры/протоколы сохранены.

Local `D:/Projects/trading_lab_data/data` на14:18:00UTC:
10841файл/2719842747bytes≈2.72GB. Server+local не суммировать как уникальные данные:
часть истории дублируется. Models/runs/tmp в этих market/source totals не включены.
Свободно на серверном storage806388953088bytes во время замера.

Main unit actualactive/running PID1663880, прежний invocation:
2171/26305jobs,26694139rows,28182pages,failed0/blocked0,
1587573999storedbytes completedjobs; currentEQTradeStats2025-07-30.
FUTOIV4actualactive/running PID2522946, прежний invocation:
344/2192processed days,4829656logicalrows/2532719new-rootrows,
14640resolved/173unresolvedticker-days,21dayswithgaps,7524reference-reusedpages;
50903983new-rootbytes completed days. Current2025-01-23,12/39tickers,lastcompletedGZ.
Final manifests отсутствуют у обоих. Никаких service/config/token/Windows изменений.

## Следующая разрешённая работа

Данный V87 закрыт, не rerun/retune или новая нейросеть на тех же features.
Нужен иной economic mechanism/information set. Broader conditional AlgoPack scope
изV85 пока unanswered; повторно вопрос не задавать и не подменять download permission
экономическим допуском. Скачивание продолжается независимо, gaps явно сохраняются.

ВоронкаV65–V87:25economic screens =21rejected +1incomplete(V73)
+3invalid(V74,V86,V87),0Stage2. Source-only/component follow-ups не новые screens.
Цель20–50% годовых остаётся неподтверждённой; этот результат не разрешает live trading.
