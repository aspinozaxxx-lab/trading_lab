# V108 — supply-chain pressure: REJECT_STAGE1

2026-09-17, completed **02:43:38.416300 UTC**. Новый GSCPI supply-constraint signal
не дал прибыли: CAGR **−1.5413% / −1.7797%**, base/double costs. Просадка меньше,
чем у постоянной покупки BR, но это не доходный компонент. Не менять знак, актив,
порог, окно, размер, TTL или control после результата. Stage2 не запускается.

## Все сценарии

[Frozen protocol](V108_SUPPLY_CHAIN_PRESSURE.md): long0.9/cash при GSCPI>0 и росте
к предыдущему месяцу в той же vintage. June2022–Dec2025, capital1mRUB, cashinterest0,
старый next-factual-open integer ledger. Base1tick/1xfee; double2ticks/2xfee.
История уже просмотрена в других работах, не независимый holdout; specs/fees proxy.

| Сценарий | CAGR,% | Sharpe | MDD,% | Round trips | Ending cash,RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary/base | -1.5413 | -0.11252 | 16.9334 | 15 | 945892.70 |
| Primary/double | -1.7797 | -0.13720 | 17.3909 | 15 | 937715.33 |
| Constant-long/base | -12.0005 | -0.41634 | 46.3587 | 43 | 632663.68 |
| Constant-long/double | -12.5425 | -0.43865 | 47.3719 | 43 | 618821.50 |

| Год | Primary/base,% | Primary/double,% | Control/base,% | Control/double,% |
| --- | ---: | ---: | ---: | ---: |
| 2022, только June–December | -5.2541 | -5.4287 | -20.8051 | -21.1713 |
| 2023 | -2.1300 | -2.2074 | -16.3914 | -16.9016 |
| 2024 | -1.3344 | -1.6420 | 0.0014 | -0.2508 |
| 2025 | 3.3871 | 3.0851 | -4.4526 | -5.2936 |

Primary положительна только в одном из четырёх сегментов; control1/0, base/double.
Не проходят заранее объявленные CAGR>=5%, Sharpe>=0.5, >=3positive segments.
Coverage, trades>=12, MDD<=25%, worstsegment>=−15% и excess>=2pp проходят, но
уменьшение потерь относительно control не превращается в прибыль. Ни5% component
gate, ни20–50% goal не достигнуты. Нет promotion, leverage или control substitution.

## Источник, решения и исполнение

[Source capture](GSCPI_SOURCE_FEASIBILITY_20260917.md): four GET,43ready monthly
vintages May2022–Nov2025. Eight long states: May/Nov/Dec2022, Dec2023,
Mar/Sep2024, Jun/Oct2025;13state changes, не13независимых рыночных событий.
Все пары читаются внутри одной версии, `#N/A` missing, 0valid. Поздние raw columns
и observation rows исключены before numeric feature conversion; 2026market не читался.
Conditional EOM NewYork availability не доказывает original publication/receipt
или неизменность retrospective archive columns. Это остаётся ограничением результата.

По915решений наarm, firstdecision2022-05-31, executioncalendar2022-06-01…2025-12-30,
lastdecision2025-12-29; nominal protocolend2025-12-31 включает все имеющиеся sessions.
Ненулевых targets174/913, primary/control; usedvintages8/43. Firstcalendardaymasked:
featureunavailable1 иstale1 — один и тот же день; plan/sourceunavailable0.
Source иjointreadiness914/915=99.89071%, полный календарь не урезался.
Primary exposure по годам42/22/67/43sessions; control150/254/256/253.
Terminal forced flat. Entries/round trips: 15/15 и 43/43. По полному target calendar:
primary — 7 эпизодов экспозиции и 8 смен контракта внутри позиции; control —
1 эпизод и 42 смены контракта. Rolls входят в counts: это не 15 независимых сигналов.

Все4cases: executioncomplete=true, critical0, unresolved0, terminalcarried=false.
Reported missing price/spec/fee/liquidity, gross/margin/participation/atomic rejection,
halt/cancel/clipping counters0. Max close gross primary0.929745/0.930407,
control0.975454/0.976208; maximum participation0.3176764% во всех4, cap1%.
Intraday adverse drawdown primary17.2841%/17.6630%, control47.8456%/48.6550%;
не путать с close-to-closeMDD. Research execution не broker-exact assurance.

| Сценарий | Gross VM,RUB | Commission,RUB | Slippage,RUB | Total costs,RUB | Net PnL,RUB | Filled legs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary/base | -46866.21 | 4080 | 3161.10 | 7241.10 | -54107.30 | 45 |
| Primary/double | -47805.32 | 8160 | 6319.35 | 14479.35 | -62284.67 | 46 |
| Control/base | -351517.29 | 8800 | 7019.03 | 15819.03 | -367336.32 | 141 |
| Control/double | -349778.34 | 17480 | 13920.16 | 31400.16 | -381178.50 | 142 |

Costs меняют integer sizes/rebalances, поэтому grossVM и legcounts между сценариями
не обязаны совпадать. Gross до costs тоже отрицателен: это не только fee problem.

## Однократность, audit и backup

- Seal `0fe890330c7b5732efa5badbdbdb0d26285a9789fb18c28dead3ed80794c4b36`,
  fixed02:40:02UTC. Pre-outcome commit/push
  `6a1b2ad2c1756817f6711d72d046a473edf1d4ff` до новых values/targets/outcomes.
- Code SHA `e44b0ad8984a3563744b1f2d687f9a054952d72371a0f635f7a5480a3f950831`,
  config `215b412576d1bd30bf3e9e4375a39c3200de74371bc14404b5917c3b78f8e1c8`.
  Protocol, test, source note/script и parentV101 transitive seal также закреплены.
- Run `/srv/trading_lab_data/runs/v108_supply_chain_pressure_v1_0fe890330c7b`.
  Unit `trading-lab-v108-supply-pressure-0fe890330c7b.service`, PID1910098,
  invocation `2685b0b350a446369999d930dc5e0afa`; start02:43:36UTC наблюдалсяrunning.
  Journal показывает все4cases и успешное завершение02:43:38UTC, не просто not-found.
- Manifest `634faa49b805f7c4f53978c855f730d79d82bf9fbe89993ce3bd47dcdf3fb834`,
  metrics `2208a4feb8db5a6876891518c907aae84b55a14c4d9904d178548d59ef607b03`.
- 26new/85combined localtestsPASS2.72s. Первый serverpytest:77pass/8fixture errors
  из-за root-owned parent temporary directory, не экономический/source run. Второй
  запуск в отдельном UID999-owned parent:85PASS0.93s до экономики. Oldtmp сохранён.
  Два pandasFutureWarning про nan/None parquet comparison, failures0; Ruffclean.
  Код/правило не менялись после seal; economic attempt ровно один.
- Server audit02:44:51UTC:20artifacthashes,43raw→states,2targetreplays,
  4cash/cost/metric/annual/count replays и assessmentPASS. Metadata/sourcequality
  recomputed,15futurespreflightchecksPASS. Не независимый replay всего ledger engine.
- Local canonical backup: `D:\Projects\trading_lab_data\runs\v108_supply_chain_pressure_v1_0fe890330c7b`.
  Single archive292459bytes, SHA
  `711f6462d6418bcfa5c846825c5b455c178455f2f2f28dd13ea9e1bac2b9a146`.
  21safe regular members; freshroot/nooverwrite,20hashes+manifestverified,43states/
  2targets/4cash replays также PASSлокально. Data/results/models не в Git.

**38 portfolio =30REJECT_STAGE1+1REJECT_STAGE2+1incomplete+6invalid**,0activeStage2/3.
V107source failures не дополнительные entrants. Goalactive, устойчивые20–50% не найдены.
Этот goal turn: PROGRESS — новый completed economic screen и отсев, не прибыль.
Следующий bounded review — private dealer financing, не новый GSCPI threshold;
см. [очередь](NEXT_SOURCE_REVIEW_20260916.md). Main archive продолжал безперезапуска:
02:45UTC19698/26305jobs74.8831%,14.491GBdata+source,12.519GBAlgoPackвнутриtotal.
