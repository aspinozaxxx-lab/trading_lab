# V110: COMPLETE, INVALID_EXECUTION_NO_PROMOTION

17 сентября 2026. **Пригодный источник дохода не найден.** Primary сам по себе
убыточен при обоих costs, а base control не проходит execution gate. Формальный
вердикт всего сравнения — INVALID, не обычный экономический PASS/REJECT с валидным
контролем. Stage2 не запускается, знак/лаг/актив/контроль не перенастраиваются.

[Протокол](V110_BANK_CREDIT_SQUEEZE.md): ужесточение стандартов C&I кредитования
и ослабление спроса на кредиты → BR short0.9/cash. Constant-short control,
2018–2025, прежний integer ledger, initial RUB1m, idle cash interest0.
История уже видена; conditional current-vintage clock, не независимый holdout/PIT.

## Результат

| Метрика | Primary 1× | Primary 2× | Control 1× — INVALID | Control 2× |
|---|---:|---:|---:|---:|
| CAGR | −3.9315% | −4.4744% | −12.4800% | −12.3474% |
| Sharpe | −0.17175 | −0.21031 | −0.25949 | −0.25947 |
| MDD | 50.1576% | 51.3802% | 86.6384% | 85.3190% |
| Итоговый капитал, RUB | 725832.50 | 693702.87 | 344732.73 | 348926.87 |
| Gross VM PnL, RUB | −244438.73 | −247486.98 | −596351.61 | −535770.06 |
| Все modeled costs, RUB | 29728.78 | 58810.15 | 58915.66 | 115303.07 |
| Round trips | 47 | 47 | 96 | 96 |
| Положительных лет / всего | 3 / 8 | 3 / 8 | 3 / 8 | 3 / 8 |
| Худший год | −27.4640% | −28.1069% | −41.1741% | −41.2914% |
| Execution complete | да | да | **нет** | да |
| Critical / unresolved / terminal carried | 0 / 0 / нет | 0 / 0 / нет | **2** / 0 / нет | 0 / 0 / нет |

Primary не проходит CAGR, Sharpe, drawdown, positive-years, worst-year gates.
Gross результат до costs тоже отрицателен. Превосходство относительно теряющего
деньги, частично невалидного контроля не является прибылью. Разница числа контрактов
и траектории equity при costs объясняет, почему double control теряет немного меньше
base; это не улучшение стратегии и не основание выбрать другой сценарий.

| Год | Primary 1× | Primary 2× | Control 1× — INVALID | Control 2× |
|---|---:|---:|---:|---:|
| 2018 | 0.00% | 0.00% | +12.72% | +12.21% |
| 2019 | −8.14% | −8.63% | −30.63% | −31.73% |
| 2020 | +9.38% | +8.22% | +16.86% | +13.55% |
| 2021 | −27.46% | −28.11% | −41.17% | −41.29% |
| 2022 | +3.34% | +3.44% | −36.16% | −31.41% |
| 2023 | +10.84% | +9.88% | +10.01% | +12.12% |
| 2024 | −4.40% | −4.99% | −3.12% | −5.13% |
| 2025 | −9.04% | −9.64% | −5.75% | −6.36% |

## Покрытие, число ставок и исполнение

33 quarterly states, все ready,14 short. 2024 решения на arm,884/2022 nonzero
targets,2025 ledger sessions. Source readiness100%, joint plan readiness99.95059%:
один unavailable plan сохранён в знаменателе. Ни feature-missing, ни stale targets.
2018 cash не удалён из годовых показателей.

Primary47trips = **5 entry/exit episodes +42 rolls**, не47 независимых ставок.
Control96trips = **1 фактический episode +95 rolls**. Два target episodes контроля
разделяет masked target во время halt, а не фактическое закрытие старой позиции.
Base/double filled legs: primary368/379, control740/738; rebalances274/285 и548/546.

Base control: gross-limit counter2 делает execution incomplete по frozen assessor.
Ledger показывает capacity cancellations1–2March2022, factual halt/carry1March;
double control cancellation/hold только1March, gross counter0. Aggregate counters
не обязаны появляться отдельными rejected order rows: проверены и ledger, и metrics.
Не удалять эти дни, не чинить контроль ради promotion. Unresolved0, terminal flat
во всех четырёх случаях не отменяют два critical failures.
Максимальный close gross leverage primary1.00091/1.01675, control1.61640/1.29675:
admission cap не означает непрерывную гарантию gross<=1 между переоценками.
Никаких выводов о broker-exact исполнении.

## Воспроизводимость и сохранение

- Pre-outcome commit `96af9e66813494e2c89fc2e7a8355af2c160f122`, pushed.
- Seal `841f92dd136ac3f0eb3fc7276913b174c04f6887c524b2610a22a1c75ce1fd71`,
  timestamp04:21:30UTC, до первого экономического прогона.
- Unit `trading-lab-v110-credit-841f92dd136a.service`, invocation
  `80452a6b57fd4b91bd5655fc7a947e99`;125server tests PASS перед run.
- Run `runs/v110_bank_credit_squeeze_v1_841f92dd136a`, complete04:22:53.591193UTC.
- Manifest `8a065f06bc964b489f65c63dd289b47978272ba05f0eb49284afd1f7f5fd9352`;
  metrics `879758e9f65f41ba0db5f91ab3ae66f5dabf2c919e89a4c5fa6968eb1141ffdd`.
- 20artifact hashes,33raw-to-state rows,2target replays,4cash/cost/annual/count
  replays и frozen assessment PASS на обоих hosts. Это integrity PASS, не profit PASS.
- Canonical21files скопированы в `D:\Projects\trading_lab_data\runs`, SHA проверены.
  Source5files и оба FRED failed roots по4files тоже скопированы/проверены; PDF/HTML
  failed backups сохранены ранее. Данные, модели и run artifacts не попали в Git.
- 41новый /125combined local tests PASS,125server PASS, Ruff clean. Четыре existing
  pandas null-comparison FutureWarnings не скрыты. Единственный economic run,
  последующий audit не повторяет симуляцию и не изменяет frozen files.

Портфельный счётчик: **40 =31REJECT_STAGE1 +1REJECT_STAGE2 +1incomplete +7invalid**.
0activeStage2/3. Goal20–50% active, не достигнут. Turn PROGRESS: гипотеза доведена
до результата и сохранена, а не полезный финансовый результат.

AlgoPack продолжает отдельно: снимок04:24UTC20,686/26,305jobs78.6390%, failed0,
blocked0. Server14.919GB data+source, в том числе12.936GB AlgoPack; local2.765GB
частично копии, не прибавлять как unique. FUTOI550gaps unchanged/not re-audited.
