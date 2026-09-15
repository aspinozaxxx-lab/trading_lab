# V86 — STEO forecast revisions: INVALID_EXECUTION_NO_PROMOTION

2026-09-15. Один зафиксированный конкурс выполнен. Нет кандидата Stage2 и нет
подтверждения цели20–50%. Основной вариант убыточен уже до комиссий; три из четырёх
arm/cost сценариев не прошли execution gate. Это не повод подбирать другой знак,
квартал, период, масштаб или costs на той же истории.

[Протокол](V86_STEO_ECONOMIC_V1.md), [source/design](V86_STEO_FORECAST_REVISIONS.md).
Pre-outcome commit **10f607a**, seal
`a8e5c82fdf2afd95c7bfb4dbccf43128b98e1c29e1a6891cca339d73b94c561e`.
Canonical: `/srv/trading_lab_data/runs/v86_steo_revisions_v1_a8e5c82fdf2a`.
Metrics SHA: `565e4bb0540db2f0d1ec528365ffc5f9ba3c9a2ea9ebb47bfe06c595e7ae53f9`.
Unit `trading-lab-v86-steo-economic-a8e5c82fdf2a.service`,
invocation`ab0c6edc18114f50963e49521295b391`; terminal PID0/exit0/inactive/dead
подтверждён при чтении13:47UTC. Это завершение программы, не execution admission.
Economic compute3,582039s; source handling отдельно. Actual broker trades/fills0.

## Результат всех сценариев

Числа для не прошедших execution сценариев — только диагностический output модели,
не валидированная доходность. Closing gross exposure тоже может превышать target после
движения рынка: target0.9 и order capacity cap не гарантируют непрерывный gross cap1.

| Вариант | Costs | CAGR | Sharpe | MDD | Closed episodes | Costs RUB | Critical/gross rejects | Execution complete |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| primary | base | -8.78% | -0.130 | 81.14% | 151 | 75500.03 | 0/0 | true |
| primary | double | -9.21% | -0.143 | 82.45% | 151 | 145717.59 | 2/2 | false |
| control | base | 1.30% | 0.203 | 73.43% | 95 | 60766.13 | 2/2 | false |
| control | double | 0.43% | 0.177 | 73.81% | 95 | 118414.16 | 1/1 | false |

Primary base/double netPnL −520264,77/−538067,53RUB на начальный1million;
grossVM −444764,74/−392349,93RUB. Поэтому только более низкие комиссии не устраняют убыток.
Filled research legs603/574primary и421/432control; orders_not_filled rows0 во всех
четырёх parquet. Последнее не отменяет aggregate gross-rejection counters: нельзя
выводить отсутствие execution failures только из persisted order rows.
Unresolved halts0, final positions flat во всех4; по1cancel_no_open и1cancel_no_liquidity.
Maximum closing gross leverage primary1,419897/1,534094;control1,103966/1,067776.
В обоих primary costs положительны4из8лет, хуже gate5; worst year2020≈−56…−57%.

## Все календарные годы

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | 13.34% | 12.32% | -19.99% | -20.69% |
| 2019 | 31.25% | 28.82% | 31.89% | 30.78% |
| 2020 | -56.40% | -57.41% | -41.53% | -41.74% |
| 2021 | -21.59% | -22.41% | 56.53% | 54.31% |
| 2022 | -24.31% | -24.60% | 44.32% | 41.93% |
| 2023 | -1.87% | -1.69% | -17.00% | -17.07% |
| 2024 | 5.93% | 9.44% | -0.06% | -0.33% |
| 2025 | 19.89% | 19.09% | -4.10% | -5.42% |

## Покрытие и проверка

97monthly sources,96possible adjacent-edition revisions,94ready; monthly source is
not2024 independent observations. Per arm2024decisions/2024dates,1980nonzero targets,
94used releases,42feature-unavailable,4stale flags (overlapping),1source-unavailable.
Ready feature/date coverage97,924901%;2025physical forecasts for2026Q1 were published
before protected boundary, not2026actual prices or outcomes.

October2022 notice has no unique accepted Released date: October and dependent
November2022 unavailable. Не чинить этот mask ради post-outcome rerun.
20editions fromMay2024 have duplicated world-production codes; all selected values
agreed. No duplicated row was chosen by outcome.

- Local86source/economic/parent testsPASS; separate44ledger/execution/economic testsPASS
  (overlapping cohorts, **не складывать как130unique**); Ruff clean.
- Server14source/21economic testsPASS.
- Replay20artifact hashes,raw source/state/target,4annual/metric/count/fee/cash checksPASS.
- Independent raw XML audit97hashes,94same-quarter revision/signs,1245scalar reads,
  117duplicate comparisonsPASS; maximum Decimal arithmetic difference0.
- Existing replay emits2pandas null-representation FutureWarnings (None vsNaN).
  No values changed, no normalization patch or canonical rerun.
- Original public revision-chain/PIT proof remainsfalse; dated archive file clocks and
  notice clocks are conservative assumptions, not a vendor no-revision guarantee.

## Что дальше разрешено

Закрыть именно это фиксированное правило, не менять его по outcomes и не обучать
сложную модель только для спасения проигравшего результата. Не повторять canonical run
или collection. Следующая гипотеза должна иметь иной механизм/информацию либо отдельно
обоснованную модель исполнения. Расширенный AlgoPack conditional-history scope изV85
всё ещё не подтверждён пользователем; скачивание при этом разрешено и продолжается.

ВоронкаV65–V86: **24economic screens =21rejected +1incomplete(V73) +2invalid(V74,V86),
0Stage2**. Source-only V83/V85 и component follow-ups V81/V82/V84 не новые screens.

## Объём данных: фактический замер13:47UTC

- AlgoPack archive: **1670849835apparent bytes (1,671GB)**,
  **2094641152allocated bytes (2,095GB)**; compressed raw+metadata, включая old roots.
- Server `data`:4380590905bytes; `source_evidence`:150734614bytes.
  Вместе **4531325519bytes (4,531GB)**; includes AlgoPack, excludes models/runs/tmp.
  Allocated respectively5017866240/152547328bytes; sum5170413568bytes.
- Local data: last measured12:41UTC2719842747bytes/10841files. Это отдельный снимок;
  server/local не складывать как уникальный корпус из-за дублей.
- Main archive unit actual active/runningPID1663880:1963/26305jobs,
  24634122rows/25973pages,failed0/blocked0;currentEQOrderStats2025-08-14.
- FUTOI V4 actual active/runningPID2522946:294/2192processed days,
  4261365logicalrows,13125resolved/68unresolved ticker-days,6days_with_gaps.
  7524pagesreference-reused; do not double-count as new physical raw.
- Both final manifests absent. Services not restarted/changed; no Windows collector,
  paid subscription action, token read,2026outcome or real trade.
