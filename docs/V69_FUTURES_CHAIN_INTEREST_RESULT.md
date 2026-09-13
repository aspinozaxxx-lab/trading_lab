# V69 — завершён, REJECT_STAGE1

2026-09-13. Новый фиксированный monthly target по знаку 63-session изменения суммы
reported futures-chain OI. BR/MIX/RI/SI совместно, 2018–2025. [Протокол](V69_FUTURES_CHAIN_INTEREST.md)
зафиксирован до единственного run и не менялся после outcomes.

## Экономический результат

| Вариант | CAGR | За весь период | Sharpe | MDD | Закрытых эпизодов | Прибыльных лет |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Основной, обычные затраты | -5,5559% | -36,6619% | -0,5639 | 44,0979% | 200 | 3/8 |
| Основной, удвоенные затраты | -5,9359% | -38,6691% | -0,6115 | 45,2677% | 198 | 2/8 |
| Constant-long контроль, обычные | 2,7772% | 24,4647% | 0,2987 | 20,3097% | 174 | 4/8 |
| Constant-long контроль, удвоенные | 2,2152% | 19,1301% | 0,2500 | 22,3968% | 173 | 4/8 |

| Год | Основной, обычные | Основной, удвоенные | Контроль, обычные | Контроль, удвоенные |
| --- | ---: | ---: | ---: | ---: |
| 2018 | 2,6780% | 2,4944% | -5,8853% | -5,2932% |
| 2019 | 5,6563% | 5,4464% | 3,6807% | 3,1733% |
| 2020 | -27,5093% | -28,3455% | 15,4905% | 14,9772% |
| 2021 | -4,6952% | -4,9689% | 17,1422% | 17,0184% |
| 2022 | -3,9710% | -1,9512% | -3,1124% | -3,7287% |
| 2023 | -8,3062% | -9,1676% | 11,2473% | 11,4969% |
| 2024 | 1,9584% | -0,0793% | -3,8101% | -5,2925% |
| 2025 | -5,8696% | -6,3518% | -9,0622% | -10,8620% |

Основной сигнал проиграл контролю при обоих costs. Провалены заранее заданные CAGR,
Sharpe, MDD, число прибыльных лет, худший год и превосходство над контролем. Доступность,
число эпизодов, наличие всех восьми лет и полнота исполнения проходят. Verdict:
**REJECT_STAGE1; кандидатов Stage2 — 0**. Контроль не продвигается как новая стратегия.

На начальный миллион рублей primary base: gross VM −348 781,66 руб., costs 17 837,04 руб.,
net −366 618,70 руб. Double: gross VM −351 844,62 руб., costs 34 846,66 руб.,
net −386 691,27 руб. Убыток есть до затрат; это не эффект исключительно дорогого исполнения.
Integer sizes зависят от капитала, поэтому doubling costs меняет последующие размеры
и gross PnL. Итоговый капитал 633 381,30 / 613 308,73 руб.; это результаты всей истории,
не годовые суммы.

CAGR — среднегодовой сложный темп роста, MDD — наибольшее падение капитала от его пика.
Sharpe здесь annualized по sqrt(252), без вычитания безрисковой ставки. Cash interest
не добавлялся. Закрытый эпизод определяется по активу/знаку/контракту, не равен order:
primary filled legs 523/498, control 616/571.

## Доступность и исполнение

- Source: 66 052 rows, 8 100 asset dates. 1 081 missing OI cells сохранены; 7 125 дат
  имеют полные OI среди присутствующих контрактов, 6 564 daily states готовы к growth.
  Это не доказательство полного market-wide inventory или оригинальных vintages.
- 384 monthly asset decisions; готовы 309 (80,4688%), включая initial warmup в denominator.
  Минимальный screen gate 60% объявлен до outcomes и не снижался после результата.
- Каждый arm: 8 096 daily asset decisions, 6 479 ненулевых targets; feature unavailable
  1 581, map unavailable 32, stale 80. Эти flags пересекаются и не образуют разбиение.
- Все четыре сценария: 2 025 sessions, execution complete, critical 0, unresolved 0,
  terminal flat. Exposed asset-sessions: primary 4 240/4 224, control 6 123/6 116.
  Ненулевой target не гарантирует хотя бы один integer contract при доступном капитале.
- Factual halt marks/carries: primary 17/17, control 32/32; соответствующие no-open
  target cancellations сохранены. No-liquidity cancellations 3 во всех сценариях.
  Нет выдуманных fills или удалённых незакрытых рисков.
- Maximum modeled participation: primary 0,4292%, control 0,6024%; ниже cap 1%.
  Participation/gross/margin/atomic rejections и participation clips равны нулю.
  У control double post-mark gross leverage достигал 1,011689: order-time cap 1x
  не гарантирует 1x после движения рынка. Primary максимум 0,911867/0,913857.
- Старый 2026 не читался. История 2018–2025 уже открыта, это development screen,
  не independent holdout и не verified доходность. Historical fees/margin/open — proxies.

## Воспроизводимость

- Pre-outcome commit `0c8b0eb719188d60affff100e711c6de0b1f20a0`, pushed до запуска.
- Config SHA `a1be61f1422e427cfbd36f26862145db4beaf98ec75cc1639cc7fa5b24bf3b8a`.
- Seal SHA `ba001c39c1fa02e790d7837380b60c0327e99e1d051d8402b9b7c96554e860f1`.
- Implementation SHA `3310afcfa1f40f5478a816a0794290af11e989f8708f146ba4eb17df47b2c3fc`.
- Canonical `/srv/trading_lab_data/runs/v69_futures_chain_interest_v1_ba001c39c1fa`.
- Metrics SHA `e40a5a53a5437b0e701fbb58bc3713f470fa045ccae2c9d9eac5de51e4879a44`.
- Identity SHA `6fa1da1e389d4da7a590e778684ce7e012b07ff43c5dd202db227df8c92f8788`.
- 18 новых synthetic tests +11 shared-helper regression +2 encoding tests: local
  31 PASS. Server до economics: 18 PASS / 0,66s. Ruff/diff PASS.
- Единственный economic run exit 0, вычислительное время 5.4935s.
  До цен проверены 15 futures identity/schema/date checks, OI schema и hash/linkage
  исходного V5 audit. Старый raw replay повторно не запускался.
- Read-only audit: 17/17 artifact hashes, 4/4 NAV metric/count replays и causal clocks,
  месячная фиксация requested weights и exact verdict — PASS.
- Во внешнем root остаются inputs, chain states с masks, оба targets,
  четыре набора ledger/orders/positions, metrics и identity; не в Git.

## Следующий допустимый шаг

Закрыт именно этот fixed quarterly-growth / monthly-direction сигнал. Не инвертировать
его знак, не менять горизонт, месяц, активы, missing policy или плечо по увиденному
убытку. Это не опровержение всей информации открытого интереса и не разрешение
переименовать прежнюю гипотезу. Следующий screen требует иного экономического механизма
или действительно иной информации после сверки реестра.

V65/V66/V67/V68/V69: 11 отсеянных гипотез, 0 кандидатов Stage2. Цель относительно
предсказуемых 20–50% годовых остаётся недостигнутой. Paper bootstrap, модели и новые
collectors не запускались; schedules существующих collectors не менялись.
