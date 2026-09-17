# V109 — private dealer deleveraging: REJECT_STAGE1

2026-09-17, completed **03:27:34.074418 UTC**. Joint private repo contraction
не дал пригодного доходного компонента: CAGR **+0.5629% / +0.4379%**, base/double
costs, при MDD **26.4942% / 26.5147%**. Это ниже даже 5% component gate и далеко
от цели относительно предсказуемых 20–50%. Stage2 не запускается. Не менять знак,
окно, актив, collateral/venue, lag, TTL, risk или control под результат.

## Все сценарии

[Frozen protocol](V109_PRIVATE_DELEVERAGING.md): borrowing AND lending totals ниже
собственных значений четыре weekly reports назад → SI long0.9/cash. Пять полных
отчётов в одной schema era; constant-long control с той же готовностью. Полный
2022–2025 calendar, capital1mRUB, cashinterest0; прежний EOD→next-factual-open
integer ledger. Costs: 1tick/1xfee и 2ticks/2xfee, research specs, не broker-exact.

| Сценарий | CAGR,% | Sharpe | MDD,% | Round trips | Ending cash,RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary/base | 0.5629 | 0.10587 | 26.4942 | 25 | 1022645.78 |
| Primary/double | 0.4379 | 0.09621 | 26.5147 | 25 | 1017584.76 |
| Constant-long/base | -6.4157 | -0.22361 | 54.4545 | 18 | 767583.70 |
| Constant-long/double | -6.3087 | -0.21708 | 54.2675 | 18 | 771090.37 |

| Год | Primary/base,% | Primary/double,% | Control/base,% | Control/double,% |
| --- | ---: | ---: | ---: | ---: |
| 2022 | 4.5858 | 4.5328 | -19.3700 | -18.3342 |
| 2023 | 4.7854 | 4.5310 | 27.3129 | 26.6954 |
| 2024 | -1.7800 | -1.8814 | 7.1565 | 6.8926 |
| 2025 | -4.9939 | -5.0879 | -30.2188 | -30.2801 |

Все arms положительны только в 2 из 4 лет. Primary при обоих costs не проходит
CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=3positiveyears. Coverage, >=20trips,
полные четыре года, worstyear>=−15% и excess>=2pp проходят, но относительное
превосходство над убыточным control не делает стратегию подходящей.

## Источник, решения и исполнение

209 raw Wednesday observations, 207 eligible reports до защищённой границы;
199 ready, 53 long. Initial4 и4после July2024 schema break маскируются.
Current-vintage NYFed archive и conditional observation+10days NewYorkEOD,
не original publication/receipt/revision proof. 2026market не читался; late2025
source cells с computed clock>=2026 исключены before numeric conversion.
История уже видена в других development runs, не независимый holdout.

По1016решений наarm: decision2021-12-30…2025-12-29, effective2022-01-03…
2025-12-30, initialcash/masks сохранены. Ненулевые targets252/963, primary/control;
usedreports53/198. Featureunavailable51, stale11 входят в эти51, отдельно
source/planunavailable1 на2022-03-01. Source readiness965/1016=94.98031%,
jointready964/1016=94.88189%. Последний target forced flat.

Primary:24targetepisodes+1roll, фактически24entry/exit pairs+1roll pair=25trips.
Control:3targetepisodes+16rolls, но halt gap не закрыл позицию; фактически
2entry/exit pairs+16roll pairs=18trips. Rolls не независимые прогнозы.
Primary actual exposure по годам67/67/58/62sessions, total254 против252targets;
control221/254/236/253, total964 против963targets. Не выдавать targets за fills.

Все4cases executioncomplete=true, critical0, unresolved0, terminalcarried=false.
Есть один factualhalt/mark/carry на2022-03-01 и targetcancel-noopen1 во всех4;
у primary дополнительно targetcancel-noliquidity1. Ledger pendinghalts0,
haltresolved/resolutionevents0; не описывать это как новый resolved-halt event.
Orders содержит только filled legs, но это не означает отсутствие cancel/hold.
Остальные missing price/spec/fee/liquidity, gross/margin/participation/atomic
rejections и clipping counters0. Max close gross0.90130/0.90038 primary,
0.90143/0.90605control; maximum participation0.0046080%/0.0135479% primary/control,
cap1%. Intraday adverse drawdown27.1146%/27.1351% primary, не close-to-closeMDD.

| Сценарий | Gross VM,RUB | Commission,RUB | Slippage,RUB | Total costs,RUB | Net PnL,RUB | Filled legs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary/base | 25355.79 | 2168 | 542.01 | 2710.01 | 22645.78 | 52 |
| Primary/double | 22984.78 | 4320 | 1080.03 | 5400.03 | 17584.76 | 51 |
| Control/base | -230666.34 | 1400 | 349.96 | 1749.96 | -232416.30 | 47 |
| Control/double | -225349.71 | 2848 | 711.91 | 3559.91 | -228909.63 | 49 |

Costs меняют integer sizes/rebalances; control с double costs здесь теряет меньше,
потому что меняется путь экспозиции, а не потому что повышенные fees полезны.
Primary gross до costs тоже мал относительно риска; это не только fee problem.

## Однократность, проверки и сохранность

- Seal `a489aa4513c15fd1b8aed6068878b98e2be0f625ba7e51f64aced314f8f853d1`,
  fixed03:19:13UTC; pre-outcome commit/push
  `730976cb4ad25b7b5ea26d518b1575ee914cf1c4` до новых source sums/directions/PnL.
- Code SHA `7bd8630e6ba0819d5ae5d5129bd9f81bdb5914560898ce5498f35929eba4e5e5`,
  config `0d4bf1c9d6780ff9331a02160f2c109f3a4792184a85c3aa744a17c7629a9f48`.
  Protocol/test/three source scripts и transitive V101 parent закреплены.
- Run `/srv/trading_lab_data/runs/v109_private_deleveraging_v1_a489aa4513c1`.
  Unit `trading-lab-v109-private-deleveraging-a489aa4513c1.service`, PID2060493,
  invocation `d93e0fc956724400b4bdba4398648ab3`. Start03:27:32UTC observedrunning;
  terminal journal показывает все4cases и successfuldeactivation03:27:34UTC.
- Manifest `47f4d7e2dad70fba2c8642a93f4bba480f8c90b3756a644252ff4dce15841036`,
  metrics `05ce5aa2654f50d487ed173d57a513747a3c4def9f0376df6fe1d9e14822de0c`.
- 28new/113combined local tests PASS3.27s, server113PASS1.07s до экономики;
  Ruffclean. Два old pandasFutureWarnings nan/None в synthetic V108 tests;
  такой же warning при target parquet comparisons в run/audit, failures0.
  Один economic run, без repairs/retries/config tuning после результата.
- Server audit03:29:57UTC:20artifacthashes,207raw→states,2targetreplays,
  4cash/cost/metric/annual/countreplays, metadata/quality/assessment PASS,
  15futureschecksPASS. Это не независимая реализация всего ledger engine.
- Local canonical backup
  `D:\Projects\trading_lab_data\runs\v109_private_deleveraging_v1_a489aa4513c1`.
  Archive360031bytes/SHA
  `08174fe5981442a7f42cda7d58e6f1243a80407ab87ae1dbbb1658e65730ea6b`.
  21safe regular members/freshroot/nooverwrite;20hashes+manifest verified.
  Local03:31:34UTC также PASS207states/2targets/4cashreplays и source manifests.
  Source backups14+6+4files отдельно сохранены, data/models/results внеGit.

**39 portfolio =31REJECT_STAGE1+1REJECT_STAGE2+1incomplete+6invalid**,
0activeStage2/3. Goal20–50active и не достигнут. Turn PROGRESS: завершён новый
экономический тест и отсев, не найден стабильный доход. Следующий bounded review —
SLOOS bank-credit conditions, не retune private repo; [очередь](NEXT_SOURCE_REVIEW_20260916.md).
Main archive03:28UTC active20147/26305jobs76.5900%,14.681GBdata+source,
12.704GBAlgoPack внутриtotal. Windowscollectors/credentials/mainserviceunchanged.
