# V98 — положительный development result, но REJECT_STAGE1

Один фиксированный тест завершён **2026-09-16T20:09:55.089920UTC**.
Двухдневное удержание MIX вокруг плановых объявлений FOMC дало положительный
результат и обошло контроль, однако доходность и Sharpe ниже заранее установленных
порогов. Это не решение задачи предсказуемых 20–50% годовых и не Stage2-кандидат.

## Все варианты

2018–2025, 2 025 торговых сессий, начальный капитал 1 млн RUB, без дохода свободных
денег. Дневной исследовательский учёт с proxy specifications, не broker-exact PnL
и не независимый holdout. Окно включает само объявление и последующее движение;
результат не подтверждает и не опровергает точный внутридневной pre-FOMC drift.

| Вариант | CAGR | Sharpe | MDD | Завершённые сделки | Итоговый капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, обычные издержки | +1.6317% | 0.49037 | 9.3581% | 61 | 1138037.15 |
| Primary, двойные издержки | +1.4782% | 0.44361 | 9.7594% | 61 | 1124382.09 |
| Контроль, обычные издержки | +0.0265% | 0.02707 | 11.6596% | 63 | 1002122.76 |
| Контроль, двойные издержки | −0.3694% | −0.07272 | 12.0192% | 63 | 970867.72 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | +2.0955% | +1.9035% | +1.2180% | +1.0260% |
| 2019 | +2.8165% | +2.6334% | +2.2333% | +2.0475% |
| 2020 | +6.3560% | +6.2187% | −0.2450% | −0.4166% |
| 2021 | −2.8511% | −2.9805% | −0.3710% | −0.4977% |
| 2022 | −5.9617% | −6.1626% | +9.7596% | +7.4397% |
| 2023 | −0.2409% | −0.4066% | −1.4849% | −1.5996% |
| 2024 | +4.2189% | +4.1028% | −3.6746% | −3.7859% |
| 2025 | +7.3207% | +7.2277% | −6.4456% | −6.5661% |

Primary: gross VM 151877.19/151902.17 RUB, издержки 13840.04/27520.08 RUB,
net 138037.15/124382.09 RUB. Контроль: gross VM 16842.84/−332.10 RUB,
издержки 14720.08/28800.18 RUB, net 2122.76/−29132.28 RUB. Сценарии costs могут
изменять последующий integer size, поэтому gross PnL не обязан совпадать.

## Полнота, исполнение и отсев

- По 2 024 решения на вариант. Primary: 112 ненулевых сигналов и сессий с позицией;
  control: 123/123. Использовано 61/63 event IDs. `used_releases=8` обозначает
  восемь годовых source URL, а не восемь сделок.
- Feature-unavailable 0; source-plan-unavailable 15 у обоих; stale-at-fill 3/1.
  Primary ready coverage 99.8518%, не доказательство исходной доставки каждого
  документа в реальном времени и не тождество с execution coverage.
- Отмена заседания убрала два будущих primary window decisions; прошлое контрольное
  окно сохранено (cancelled-window decisions 0). Emergency meeting не стало
  заранее известным торговым сигналом.
- Все четыре ledgers execution_complete=true, critical=0, unresolved_halt=0,
  terminal_carried=false. Missing contract/open/settle/spec/fee/margin/liquidity
  counters равны нулю; незакрытых позиций нет.
- Primary: 122 filled legs при обоих costs; control: 127/127. В контроле по одному
  participation clip и roll-capacity cancellation. Эти операции не исключены.
- Максимальное участие 0.27624% primary / 0.68729% control, ниже лимита 1%.
  Максимальный close gross: 0.89295/0.89302 primary, 0.90423/0.88842 control.
  Intraday adverse drawdown: 12.8506%/13.1250% primary, 12.3340%/12.7110% control;
  отдельно от close MDD, использованной в отборе.

Провалены CAGR>=5% и Sharpe>=0.5 при обоих costs. Остальные gates пройдены:
не менее 30 сделок, пять положительных лет из восьми, все годы, worst year,
просадка, превосходство над контролем, coverage и execution. Вердикт остаётся
**REJECT_STAGE1**. Положительный знак не даёт разрешения поднимать плечо, менять
окно/актив/годы или выбирать press-conference subset после результата.

Воронка: **31 portfolio hypothesis = 27 rejected + 1 incomplete + 3 invalid;
0 Stage2**. V93 отдельно как component diagnostic. Исходные документы и четыре
сценария не считаются дополнительными гипотезами. Следующее независимое направление
для source feasibility — [H.4.1, банковская долларовая ликвидность](H41_LIQUIDITY_FEASIBILITY_20260916.md),
не ещё одно окно FOMC. Broader AlgoPack economic scope по-прежнему unanswered.

## Источник и воспроизводимость

[Frozen protocol](V98_FOMC_EVENT_PREMIUM.md), pre-outcome push `6278e732f56975a07b7c1d97e0a91f2f3abab7e4`.
Config SHA `759d2300a791beb3ecf6c281a34da34c44c08052d25270a9aec692263d2ca5f8`,
seal `e3cc42f2df14d599f3355ee3f2dc173da824add7202cc240cf5ef959bb7ea673`.
13 новых / 79 combined synthetic tests PASS 4.79s; server 13/13 PASS 0.18s,
UID999, isolated pytest root, Ruff clean. Frozen files не менялись после seal.

Источник COMPLETE **20:07:24.241971UTC**: 10 public GETs, 64 плановые даты,
одна документированная отмена, без HTTP/parser failures. Canonical source:
`/srv/trading_lab_data/source_evidence/v98_fomc/e3cc42f2df14`.

- Manifest SHA `e1bf18bb17af7a8d679a4e27932bb105848715720669161382d3b7910c903bbd`.
- Events SHA `6b1eedddc4074b32200e36dffe8991f398cb09637d1d24f3067fc8db789789e9`.
- PDF SHA `a8e9f41d40455cc97d012f288dbd0911474c7c6096974252aa8b56c7ea0eea38`,
  85003 bytes. Page5 прочитана и визуально проверена; навык PDF помог отличить
  публичную отмену от поздней публикации частного протокола. PDF не редактировался.
- Все 23 source artifacts проверены 20:08:39UTC и runner перед market reads;
  original_receipt_verified=false, economic_admission=false у source manifest.
  End-of-public-day lag не является доказательством exact original upload time.
- Source unit `trading-lab-v98-fomc-source-e3cc42f2df14.service`, invocation
  `35fc7a328e4742da8185b65b716e40d6`, terminal success; не перезапускать.

Economic unit `trading-lab-v98-fomc-economic-e3cc42f2df14.service`, invocation
`21a12bbee282471db3a1ea07c120b424`, launched 20:09:51.701542UTC, terminal success.
Source manifest SHA был указан до numerical reads. Canonical:
`/srv/trading_lab_data/runs/v98_fomc_event_premium_v1_e3cc42f2df14`.
Run manifest SHA `7afb81822b77a3fee08d85a73341d9088aab9ca20ee1d6c5e25b1da33e26b08a`,
metrics SHA `a01c58f24ee8cb641714058b95465ca271c8d88a9fec6230997d37bc36d301a8`.
В 20:10:44UTC проверены все 17 artifact hashes, terminal journal, четыре
performance/annual replays из сохранённых ledgers, causal source clocks и граница
<=2025. Повторного economic run, новых AlgoPack reads, broker/demo/live не было.

Скачивание AlgoPack не прерывалось. На 20:12:34UTC: 12.742 GB data+source,
включая 10.863 GB AlgoPack; основной архив 15569/26305 jobs, failed0/blocked0.
Данные/источники отдельно от models/runs/tmp и локальных дубликатов.
