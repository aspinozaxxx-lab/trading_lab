# V72 — текстовые сигналы ЦБ: REJECT_STAGE1

Завершено 2026-09-14. [Зафиксированный протокол](V72_CBR_POLICY_GUIDANCE.md):
явное будущее повышение ставки → short MIX и SI; снижение → long обоих. Контроль —
направление уже принятого решения в headline. 2018–2025 — уже открытая development
history, не независимый holdout. Прибыль не найдена; цель20–50% не достигнута.

## Экономический результат

| Arm / costs | CAGR | Sharpe | MDD | Закрытые эпизоды | Исполненные legs | Прибыльные годы |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary base | -3,3803% | -0,5653 | 31,5134% | 90 | 195 | 3/8 |
| Primary double | -3,4961% | -0,5838 | 31,6906% | 90 | 192 | 2/8 |
| Control base | -5,1005% | -0,8603 | 39,8864% | 88 | 188 | 1/8 |
| Control double | -5,2541% | -0,8833 | 40,3378% | 88 | 199 | 1/8 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | -4,8528% | -4,9458% | -0,7999% | -0,8939% |
| 2019 | 0,0510% | -0,0752% | -0,4926% | -0,5839% |
| 2020 | 7,1486% | 7,0677% | 4,2841% | 3,9807% |
| 2021 | -3,6396% | -3,6988% | -3,5609% | -3,6562% |
| 2022 | -15,0209% | -15,1720% | -24,2982% | -24,8251% |
| 2023 | -9,6652% | -9,8171% | -6,9672% | -6,9932% |
| 2024 | -1,6220% | -1,4999% | -2,7759% | -3,1096% |
| 2025 | 2,3575% | 1,9745% | -3,1717% | -2,8293% |

Начальный капитал1 000 000руб. Полный результат за восемь лет, не годовая прибыль:

| Arm / costs | Gross VM PnL,руб. | Все затраты,руб. | Net PnL,руб. | Остаток,руб. |
| --- | ---: | ---: | ---: | ---: |
| Primary base | -233491,84 | 6730,02 | -240221,86 | 759778,14 |
| Primary double | -234066,13 | 13400,05 | -247466,17 | 752533,83 |
| Control base | -335400,11 | 6400,02 | -341800,13 | 658199,87 |
| Control double | -337383,40 | 12880,04 | -350263,44 | 649736,56 |

Primary теряет капитал ещё до комиссий и проскальзывания. Превосходство CAGR над
контролем 1,7202/1,7580 процентного пункта при1×/2×costs
меньше зафиксированных2pp и не делает убыточный вариант прибыльным. Провалены CAGR,
Sharpe, MDD, число положительных лет, worst-year и meaningful-excess gates.
Количество эпизодов и техническая полнота проходят, но не дают economic PASS.
Различающиеся legs/gross PnL при двух costs отражают отдельные cash-dependent integer
размеры; затраты не вычитаются из одной неизменной траектории позиций постфактум.

## Источник, coverage и исполнение

[Пресс-служба Банка России](https://www.cbr.ru/dkp/mp_dec/):68релизов2018–2025,
8/8/8/8/11/9/8/8 по годам, включая внеочередные. Source V2:77raw hashes и68text
replays PASS;40date-only footer clocks сохранены как неизвестное время, не historical
midnight receipt. Доступность по-прежнему23:59:59Moscow. Известны headline/body68/68,
но это readability, не100% точности текстовой интерпретации или доказательство PIT.

Фиксированный словарь выделил22explicit-hike,20explicit-cut,26no-explicit-direction;
ambiguous0, unknown headline/body0. Последние26 — flat, не утверждение «политика нейтральна».
Headline:19повышений,22снижения,27сохранений. Будущие текстовые прогнозы внутри старых
релизов не являются прочитанными будущими рыночными outcomes.

Оба arm:4048asset decisions на2024decision dates,2025ledger sessions. Primary:
788nonzero targets,42использованных релиза,788exposed asset sessions. Control:
771nonzero targets,41релиз,770exposed asset sessions. По90/88закрытых asset/contract
эпизодов — не90/88независимых новостей, в counts входят отдельные инструменты и rolls.
52feature-unavailable,16missing-plan,2764stale-at-fill target rows в каждом arm; reasons
могут пересекаться, не складывать их как непересекающиеся категории.

Все4ledgers execution complete, critical0, unresolved0, terminalflat. У primary нет
halt/cancel events; у каждого control один target_cancel_no_liquidity, не удалённый из
учёта. Maximum participation0,6024% при cap1%; maximum close gross primary
0,998831/0,999680, control0,975489/0,976301. Часы source→EOD decision→strict-next open
и source→state→target воспроизведены. Входы/исполнение всё ещё research proxies.

## Provenance и проверка

- Economic pre-outcome push: `dddfd09`.
- Config SHA: `86787fcb307a7ba77d4d066a8ede53a55408f188a88e4e29fa8418d28058e0c5`.
- Economic seal: `8d7b732d7a475a573dc7e7b459b80149c82b645682c792892598045a2b5c90da`.
- Canonical: `/srv/trading_lab_data/runs/v72_cbr_policy_guidance_v1_8d7b732d7a47`.
- Metrics SHA: `e56de06182944470cd99d1a40d8d59fe14e6d287b511777e355fbdd823c6c3fd`.
- Identity SHA: `16ac726b9deaed7e520b2f184f319cec53d62ceb925f82423fa40e76c5bd0dd9`.
- Source V2 pre-acquisition push `e0c5fad`, manifest
  `83a89218c16785d961632c4a715e8f26d0fda0e0299e39ac98257f2621d75b70`.
- Единственный economic run: 2,972204s;4сценария.
- Local22new+11shared+18source+2encoding=53tests PASS, Ruff/diff PASS; server22 PASS
  до экономического run. Source V2 отдельно прошёл18server tests до acquisition.
- Audit17/17child hashes, source-state-target replay,4/4metrics/annual/count/cash
  replays PASS. Pandas сообщает future-warning о nan/None в неторгуемых nullable cells
  после Parquet round-trip; текущая pinned версия принимает их missing-equivalence.
  Frozen bytes не изменены, warning не скрыт и не превращает missing в market zero.

Raw/data/run artifacts остаются вне Git. Original historical text versions/receipt,
broker-exact BBO/fees/specs не доказаны; findings относятся к узкой lexical development
гипотезе, не опровергают любую возможную обработку новостей и не доказывают будущую прибыль.
Словарь/знак/TTL/активы/плечо после результата не перенастраивать.

V65–V72:14отсеянных гипотез,0Stage2. Следующий шаг — иной экономический механизм или
новое независимое information set, не улучшение отрицательного V72 на тех же outcomes.
Старый paper bootstrap и collectors schedules не менялись; protected2026 не читался,
реальных заявок нет. Главная цель остаётся активной, не достигнутой.
