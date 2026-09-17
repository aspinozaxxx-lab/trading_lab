# V111: COMPLETE, REJECT_STAGE1

17 сентября 2026. **Пригодный источник дохода не найден.** Покупка индексного
фьючерса MIX при неположительной избыточной премии корпоративного кредитного риска
(EBP), иначе cash, оказалась убыточной и хуже постоянного long-контроля.
Все четыре сценария execution-complete: отрицательный вывод здесь экономический,
а не следствие невалидного контроля. Stage2 не запускается; правило не настраивать.

[Замороженный протокол](V111_CREDIT_RISK_APPETITE.md): target 0.9, full 2018–2025,
RUB 1m initial capital, idle cash interest 0, прежний integer futures ledger.
История уже видена; current-vintage EBP с условным publication clock, не original
PIT и не независимый holdout. Известные whole-history revisions остаются ограничением.

## Экономический результат

| Метрика | Primary 1× | Primary 2× | Control 1× | Control 2× |
|---|---:|---:|---:|---:|
| CAGR | −2.8632% | −2.0091% | +0.5906% | +0.4552% |
| Sharpe | −0.04466 | −0.02527 | 0.14184 | 0.13565 |
| MDD | 45.8246% | 41.1052% | 52.5396% | 52.5165% |
| Итоговый капитал, RUB | 792880.84 | 850315.31 | 1048172.05 | 1036951.91 |
| Gross VM PnL, RUB | −199438.88 | −134484.15 | 59292.38 | 58392.58 |
| Все modeled costs, RUB | 7680.28 | 15200.54 | 11120.34 | 21440.67 |
| Round trips | 34 | 34 | 33 | 33 |
| Положительных лет / всего | 4 / 8 | 4 / 8 | 5 / 8 | 5 / 8 |
| Худший год | −31.2526% | −26.5856% | −38.9307% | −39.2099% |
| Execution complete | да | да | да | да |
| Critical / unresolved / terminal carried | 0 / 0 / нет | 0 / 0 / нет | 0 / 0 / нет | 0 / 0 / нет |

Primary не проходит CAGR, Sharpe, MDD, positive-years, worst-year и control-excess
gates. Gross до costs тоже отрицателен. 1× означает 1 tick и базовую комиссию,
2× — 2 ticks и двойную комиссию, не удвоение риска или leverage.

Double primary теряет меньше, но это не польза от высоких издержек. При одинаковых
замороженных targets costs меняют equity и целочисленное число контрактов.
Сохранённые positions различаются на 57 датах: первая — 24 февраля 2022,
3 контракта у base против 2 у double. В control 45 таких дат, первая 5 ноября 2019.
Сравнение сделано read-only по сохранённым positions, без новой симуляции и без
выбора удачного cost-сценария. Оба primary всё равно убыточны.

| Год | Primary 1× | Primary 2× | Control 1× | Control 2× |
|---|---:|---:|---:|---:|
| 2018 | +10.12% | +9.96% | +8.50% | +8.35% |
| 2019 | +10.39% | +10.31% | +23.86% | +24.06% |
| 2020 | −13.65% | −13.77% | +9.27% | +9.23% |
| 2021 | +10.00% | +9.97% | +16.23% | +16.78% |
| 2022 | −31.25% | −26.59% | −38.93% | −39.21% |
| 2023 | +16.79% | +15.73% | +35.24% | +34.50% |
| 2024 | −1.57% | −0.67% | −12.91% | −13.16% |
| 2025 | −13.11% | −12.40% | −14.62% | −14.83% |

## Покрытие и исполнение

96 monthly states, все ready, 71 long. 2024 решения на arm, 1478 primary / 2008
control nonzero targets, 2025 ledger sessions. Source readiness 100%; joint
readiness **99.25889%**: 15 unavailable source-plan dates сохранены в знаменателе.
Feature-missing 0, stale-at-fill 0. Нулевой interest на cash не подменён carry.

Primary 34 round trips = **11 фактических entry/exit episodes + 23 rolls**,
а не 34 независимых сигнала. Control 33 = **1 episode + 32 rolls**.
12/2 target episodes включают разрыв из-за masked targets во время halt, не
обязательное фактическое закрытие позиции. Filled legs primary 75/71, control
100/91; rebalances 7/3 и 34/25 соответственно.

Во всех четырёх сценариях factual halt/event/mark/carry 15, cancellation из-за
missing open 15, no-liquidity 1. Roll-capacity cancellations primary 7, control 15.
Ledger сохраняет 23/31 capacity-or-halt days; 15 halt days — 1–23 марта 2022.
Эти периоды не удалены. Gross-limit counter 0, critical 0, unresolved 0,
terminal flat. Maximum close gross primary 0.90084/0.89996, control 0.90159/0.90125:
admission cap не является непрерывной гарантией intraday gross-risk.
Это модель исполнения, не подтверждённые индивидуальные broker terms.

## Воспроизводимость и сохранение

- Pre-outcome commit `b3e2676adc230dbdfa94463e4eb211f4480f410e`, pushed.
- Seal `6cfca6c74c62336fd19be9e3324ae34cb54a24d056e7b89438870c1f9ca7cd19`,
  timestamp `2026-09-17T04:46:27Z`, до первого просмотра состояний и нового PnL.
- Unit `trading-lab-v111-credit-6cfca6c74c62.service`, invocation
  `7334907dabe6435692aa1271d4ed8a04`; 134 server tests PASS перед run.
- Run `runs/v111_credit_risk_appetite_v1_6cfca6c74c62`, completed
  `2026-09-17T04:48:18.441606Z`.
- Manifest `5955c86fb46068b4c0f8e4d75c2e724acc3e3ff7c62ab8e598944c3041b7ebc9`;
  metrics `9646f0218765e3bd2385f22860a874a6404ffb74a38d96a45ffcffd311103fb7`.
- 20 artifact hashes, 96 raw-to-state rows, 2 target replays, 4 cash/cost/annual/
  count replays и frozen assessment PASS на server и local. Проверка
  `scripts/audit_v111_credit_risk_appetite.py` не повторяет экономическую симуляцию.
- Canonical 21 files скопированы в `D:\Projects\trading_lab_data\runs`, SHA verified.
  Source 6 files тоже сохранены локально вне Git. Исходный failed source manifest
  с ошибкой формата даты сохранён; corrected offline parser не скачивал CSV повторно.
- 35 новых / 134 combined local tests PASS, 134 server PASS, Ruff clean. Четыре
  existing pandas null-comparison FutureWarnings сохранены, не скрыты.
  Единственный economic run; sealed code/config/tests/protocol/source script неизменны.

Портфельный счётчик: **41 = 32 REJECT_STAGE1 + 1 REJECT_STAGE2 + 1 incomplete +
7 invalid**, 0 active Stage2/3. Цель 20–50% active и не достигнута. PROGRESS означает
завершённый тест и отсев гипотезы, а не полученную полезную прибыль.

AlgoPack продолжает независимо: снимок 04:56 UTC — 21007/26305 jobs, 79.8593%,
failed 0 / blocked 0, **15.054 GB data+source, включая 13.070 GB AlgoPack**.
Local 2.766 GB частично дублирует server. FUTOI 550 gaps unchanged/not re-audited;
main failed 0 их не устраняет. Details в [archive status](ALGOPACK_ARCHIVE_V1_STATUS.md).
