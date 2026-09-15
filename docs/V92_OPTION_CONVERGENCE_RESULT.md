# V92 — REJECT_STAGE1: проверенный вариант reported-OI convergence убыточен

Единственный presealed economic run completed **2026-09-15T21:59:00.059635UTC**,
service success/exit0 и все artifact hashes проверены21:59:49UTC.
Это настоящий historical research screen2021–2025, не подготовка и не synthetic test.
Исследуется дневное приближение к страйку перед экспирацией, не last-minute expiry pinning.

## Экономический результат

| Arm/cost | CAGR | Sharpe | MDD | Завершённых position episodes | Net PnL,RUB | Costs,RUB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary,base | −2.5590% | −0.4104 | 19.8280% | 931 | −121243.97 | 55645.61 |
| Primary,double | −3.9205% | −0.6721 | 24.1129% | 903 | −180777.75 | 105842.09 |
| Control,base | +2.5334% | +0.4605 | 7.8667% | 1186 | +132848.07 | 83204.32 |
| Control,double | +0.9952% | +0.1997 | 9.3208% | 1184 | +50609.97 | 161249.11 |

Primary — к большему call+put OI у двух соседних reported strikes. Control — к ближайшему
из той же пары, без OI magnitude selection. Даже control не достигает5% component gate,
тем более20–50% цели; его запрещено выбирать для promotion по этому результату.

Начальный капитал каждого сценария1млн RUB. Итог primary878756.03/819222.25,
control1132848.07/1050609.97. Primary gross VM PnL на фактических размерах тоже отрицателен
(−65598.36/−74935.66RUB): провал не сводится только к комиссиям. Это decomposition,
не отдельный zero-cost portfolio. Изменение числа эпизодов при double costs связано с
отдельной траекторией капитала и integer sizing, а не подбором другой стратегии.

| Год | Primary,base | Primary,double | Control,base | Control,double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | −3.2173% | −3.8403% | −3.1852% | −4.7812% |
| 2022 | −11.0761% | −11.8841% | +12.0255% | +11.0800% |
| 2023 | −1.3391% | −2.4255% | +2.8232% | +1.9953% |
| 2024 | +5.0691% | +2.7294% | −0.1840% | −1.6997% |
| 2025 | −1.5009% | −3.5453% | +1.7705% | −0.9287% |

У primary только1positive year при обоих costs; worst year−11.0761%/−11.8841%.
Full1271sessions и5084asset decisions наarm сохранены, nonzero targets1918primary/
1954control. Filled legs1490/1445primary,1814/1806control; это не то же самое, что
position episodes: reversal может закрыть и открыть эпизод одним net order.

## Данные, исполнение и gates

Источник прошёл заранее заданный coverage gate: **842/1044releases=80.6513%**, не
subset с удобной экспирацией. Все1327744source rows сохранены, empty markers0,
source-side conflicts0. Decision-ready1985/5084 включает19exact-strike flat;
READY1966, outside window1296, unresolved reported metadata945, fill reaches expiry545,
unbracketed price147, stale62, no positive OI45, invalid plan32, no source20,
missing close4, no mapped expiry2, zero bracket OI1.

Все4ledgers execution_complete=true, critical_failure_count=0,
unresolved_halt_count=0, terminal_carried=false. По одному factual halt и двум
target cancellations (нетopen/нетliquidity) сохранено в каждом сценарии, не удалено.
Maximum participation0.04548%≤1%; max close gross0.6574/0.6758primary,
0.7667/0.7423control. Intraday adverse drawdown20.1621%/24.5064%primary,
8.0928%/9.4483%control. Fees/specs/margin всё ещё historical research proxies, не broker exact.

Таким образом, это **экономический отказ REJECT_STAGE1**, не INVALID из-за сломанного
исполнения и не INCOMPLETE из-за coverage. Failed primary gates на обоих costs:
CAGR,Sharpe,positive years,преимущество надcontrol. Нет Stage2,нет live/demo,
historical20/50 flags false,goal_verified=false.

Воронка: **26 portfolio-screen hypotheses =22rejected+1incomplete+3invalid,0Stage2**;
V93 отдельный слабый/incomplete component diagnostic, не ещё один portfolio test.

## Идентичность и сохранение

- Run `/srv/trading_lab_data/runs/v92_option_convergence_screen_v1_0ded143d5a19`.
- Manifest `0a3db3c967191d76824e77184f2d50e51103911a4a9dfc2e387cd1f4bb409ddb`.
- Metrics `7779fe317877f9395e5be48f451f47b83b2328e5b9f26fac5959fe97d43bb1b1`.
- Admission `0ded143d5a190710c66a7e80d2f40728425bab052e1db43b122dd118b1251472`,
  pre-run commit`0b1cf60` pushed/deployed до первого V92 OI/price read.
- Code seal `1afd2aa17647767be4f7c503f75133e1ee40777f66add7607a3d626b626b0707`;
  frozen V90 rules и old ledger не менялись. [Полный source/mapping closure](V92_OPTION_CONVERGENCE_MAPPING_RESULT.md).
- Unit `trading-lab-v92-option-screen-0ded143d5a19.service`, invocation
  `9d08024b0eae4d03bca7d6dc34f97cbf`, one-shot,Restart=no,no credential EnvironmentFile.
- Сохранены inputs,signal_state,release_quality,2targets,4ledger/4orders/4positions,
  metrics и manifest. Данные/модели не добавлялись в Git, canonical не перезаписывался.

Первый текстовый пункт `metrics.limitations` скопирован из frozen pre-run config и
говорит о pending run. Это историческая формулировка дизайна; actual terminal unit,
датированный metrics и final manifest выше доказывают, что run уже завершён. Остальные
ограничения — current-vintage weekly subset,not original PIT/full market/dealer exposure,
proxy execution,protected2026 — остаются в силе. Разработка не unseen holdout.

Дальше — другой независимый механизм или новая разрешённая информация. Не повторять
V88–V92 collection/mapping/audits/run, не flip-ить primary, не продвигать control,
не выбирать удачный asset/year/окно/плечо и не чинить metadata ради улучшения этого run.
