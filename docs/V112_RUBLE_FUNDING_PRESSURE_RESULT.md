# V112: COMPLETE, INVALID_EXECUTION_NO_PROMOTION

17 сентября 2026. **Доходность primary слишком мала для полезного компонента, а
контроль не проходит исполнение.** Никакого Stage2, изменения знака или подбора
порогов. Положительные около0.6% CAGR не подтверждают цель20–50%.

[Протокол](V112_RUBLE_FUNDING_PRESSURE.md): SI short0.9 при same-date RUONIA выше
ключевой ставки AND положительном банковском deficit без корсчетов, иначе cash.
Control — rate-premium-only при той же готовности всех3inputs. Full2018–2025,
initialRUB1m, idle cash interest0. Current-vintage/conditional clock, не original PIT.

## Результат

| Метрика | Primary 1× | Primary 2× | Control 1× — INVALID | Control 2× — INVALID |
|---|---:|---:|---:|---:|
| CAGR | +0.6078% | +0.5789% | −0.4008% | −0.5618% |
| Sharpe | 0.15396 | 0.14774 | 0.00321 | −0.01453 |
| MDD | 11.1566% | 11.2140% | 28.3069% | 28.4371% |
| Итоговый капитал, RUB | 1049599.09 | 1047193.07 | 968421.97 | 955987.85 |
| Gross VM PnL, RUB | 51809.07 | 51613.02 | −20488.02 | −22012.14 |
| Все modeled costs, RUB | 2209.98 | 4419.96 | 11090.01 | 22000.02 |
| Round trips | 22 | 22 | 99 | 99 |
| Положительных лет / всего | 3 / 8 | 3 / 8 | 6 / 8 | 6 / 8 |
| Худший год | −2.2051% | −2.2400% | −17.6296% | −18.0032% |
| Execution complete | да | да | **нет** | **нет** |
| Critical / unresolved / terminal carried | 0 / 0 / нет | 0 / 0 / нет | **2** / 0 / нет | **2** / 0 / нет |

Primary не проходит CAGR>=5%, Sharpe>=0.5, >=5positive years/8 и excess>=2pp.
Даже без costs gross составляет лишь около51.8kRUB на стартовый1m за восемь лет.
Низкая частота/простой cash не удаляются из CAGR. Сравнение с убыточным невалидным
контролем не доказывает ценность фильтра. Формально INVALID, не обычный валидный
экономический REJECT_STAGE1. Control не чинить ради promotion; primary не усиливать
плечом и не объединять post-hoc с прежними лидерами.

| Год | Primary 1× | Primary 2× | Control 1× — INVALID | Control 2× — INVALID |
|---|---:|---:|---:|---:|
| 2018 | 0.00% | 0.00% | −1.25% | −1.32% |
| 2019 | 0.00% | 0.00% | +2.44% | +2.21% |
| 2020 | +1.10% | +1.09% | +2.06% | +2.16% |
| 2021 | −2.21% | −2.24% | +0.78% | +0.66% |
| 2022 | +3.23% | +3.20% | −17.63% | −18.00% |
| 2023 | −1.06% | −1.12% | +2.17% | +2.00% |
| 2024 | +4.05% | +3.97% | +1.79% | +1.73% |
| 2025 | −0.11% | −0.13% | +8.65% | +8.33% |

## Покрытие и исполнение

2012stock dates,1963 admitted RUONIA observations,2015 key-rate rows. Все1963
joint states date-matched и ready;76primary short /324control short states.
2024decisions/arm,76/324 nonzero targets,75/319 used releases,2025ledger sessions.
5feature-unavailable,47stale-at-fill,1source-plan unavailable; masks пересекаются,
их нельзя складывать как число уникальных дней. Source-ready97.67787%, joint97.62846%.
2018–2019 primary cash полностью сохранён в результате.

Primary22trips = **21 фактический entry/exit episode +1roll**. Control99 =
**96episodes +3rolls**. Target episodes22/97 не равны исполненным ставкам.
Filled legs51/52 и240/234; rebalances7/8 и42/36 соответственно.
Exposed asset sessions75primary /325control, не независимые observations.

Primary: no-liquidity cancellation2March2022, позиция flat; critical/gross-limit0,
halts0, unresolved0, terminalflat. Control: capacity cancellations1–2March2022,
halt/mark/carry1March; gross-limit counter2 и critical2 в обоих costs.
В ledger critical_blocked_asset_count равен0, но aggregate execution counters
ненулевые — проверены оба источника, а не только orders или этот столбец.
Maximum close gross primary1.05462/1.05535, control1.49087/1.49771:
admission cap не гарантирует intraday/междневной leverage ceiling после переоценки.
Unresolved0 и terminalflat не отменяют critical failures. Ничего не вырезано.

## Воспроизводимость

- Pre-outcome commit `f27a98b58b69e3a2c7d85e1450fddd82479187e9`, pushed.
- Seal `2461c10932fa2cbcd85fe885690bdbe923aaaee0534827a625011d71692ea669`,
  timestamp `2026-09-17T05:27:30Z`, до полного joint numeric state и нового PnL.
- Unit `trading-lab-v112-funding-2461c10932fa.service`, invocation
  `660c66c0babc405d950c2cfcba521315`;168server tests PASS перед единственным run.
- Run `runs/v112_ruble_funding_pressure_v1_2461c10932fa`, complete05:29:14.219625UTC.
- Manifest `72c4eef1ca40b4a2887e26dec5997eb776b4f39000a75fbb989a8ec339ba7920`;
  metrics `2e2f5dadf26d7cd7d3ce9045c2d75c73c5c595629bc07841dd231d8e5c15f72c`.
- 20hashes/1963raw-to-state rows/2target replays/4cash-cost-annual-count replays и
  assessment PASS на обоих hosts. `scripts/audit_v112_ruble_funding_pressure.py`
  не повторяет симуляцию. Integrity PASS не является economic/execution PASS.
- 21run files и10source files local backups verified. V1 failed import note/script
  сохранены отдельно на обоих hosts; исходный scriptSHA39373aa1... совпадает с
  failed attempt. Данные/модели/архивы/run artifacts вне Git.
- 34new/168combined local tests PASS,168server PASS.6existing pandas FutureWarnings
  в tests; server дополнительно nonfatal pytest-cache permission warning. Его не
  скрывали, cache/permissions/environment не меняли. Ruffclean, sealed files unchanged.

**42 portfolio =32 REJECT_STAGE1 +1 REJECT_STAGE2 +1 incomplete +8 invalid**,
0activeStage2/3. Цель20–50active, не достигнута. Turn PROGRESS: завершён новый тест,
не найден полезный доходный результат. Следующий bounded шаг — [фактические продажи
валюты экспортёрами](NEXT_SOURCE_REVIEW_20260916.md), пока без rule/corpus/нового backtest.

AlgoPack независимо active:05:30UTC21356/26305jobs81.1861%,failed0/blocked0,
**15.196GBdata+source,13.209GBAlgoPack**. Local2.767GB частично дублирует server,
не суммировать как unique. FUTOI550gaps unchanged/not re-audited; mainfailed0 их не лечит.
