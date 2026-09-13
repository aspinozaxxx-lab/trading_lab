# V70 - относительная дешевизна ОФЗ, REJECT_STAGE1

2026-09-13. [Исходный протокол](V70_OFZ_RELATIVE_CURVE.md) проверяет top-3 positive
leave-one-out yield-curve residuals против close-to-curve контроля. SU262, 2-7 лет,
первое месячное решение, prior features, следующий factual dirty OPEN, fully-funded
long only. Source 2021-2025, fixed 10/20 bps на сторону, купоны и terminal reserve.
Первоначальная incomplete accounting классификация устранена отдельной
[R1 сверкой](V70_ACCOUNTING_RECONCILIATION_R1.md), не повтором торговой стратегии.

## Экономический результат

| Вариант | CAGR | За весь период | Sharpe | MDD | Закрытых эпизодов | Прибыльных лет |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Основной, 10 bps | 4,4929% | 24,4974% | 0,5811 | 19,2397% | 103 | 3/5 |
| Основной, 20 bps | 3,0249% | 16,0181% | 0,4055 | 19,8828% | 103 | 2/5 |
| Контроль, 10 bps | 3,6400% | 19,5124% | 0,4932 | 21,0618% | 110 | 2/5 |
| Контроль, 20 bps | 2,0872% | 10,8477% | 0,3002 | 22,3134% | 110 | 2/5 |

| Год | Основной, 10 bps | Основной, 20 bps | Контроль, 10 bps | Контроль, 20 bps |
| --- | ---: | ---: | ---: | ---: |
| 2021 | -2,8675% | -4,1219% | -3,6763% | -5,0454% |
| 2022 | 4,6819% | 3,4366% | 5,1481% | 3,8967% |
| 2023 | -0,3267% | -1,6463% | -0,7304% | -2,4291% |
| 2024 | 0,1802% | -1,5376% | -1,7550% | -3,4454% |
| 2025 | 22,6206% | 20,8011% | 20,9906% | 19,2657% |

Итог: **REJECT_STAGE1, не передавать на Stage2**. При обоих costs не выполнены
CAGR>=5%, превосходство над контролем >=2 процентных пунктов и минимум 4 положительных
года. При double costs также не выполнен Sharpe>=0,5. Coverage, rebalances, MDD<=25%,
worst year>=-15% и наличие всех пяти лет проходят. Пороги не менялись.

Дополнительный CAGR primary относительно контроля всего +0,8530 / +0,9378 процентного
пункта. Большая часть итогового роста пришлась на 2025 год. Его +22,6206%/+20,8011%
не означают устойчивые 20% в год: до этого при double costs три из четырёх лет убыточны.
Это не доказательство бесполезности всей относительной оценки облигаций; закрыто
именно заранее зафиксированное правило, без подбора степени кривой, сроков и costs.

На стартовый миллион основной вариант дал net +244 973,87 / +160 180,51 руб.
за весь период после затрат и terminal reserve. Начисленные известные cashflows
432 997,54 / 415 824,10 руб.; trading costs 70 779,36 / 136 675,76 руб.;
reserve 1 221,58 / 2 279,00 руб. Изменение dirty-price стоимости до trading costs
и без cashflow credits отрицательно: -116 022,73 / -116 688,83 руб.
Это ledger attribution, не отдельная новая стратегия и не чистая ценовая доходность
без НКД. Купоны дали положительный вклад, переоценка его частично съела.

CAGR - среднегодовой сложный рост; MDD - наибольшее падение капитала от пика.
Sharpe annualized по sqrt(252), без вычитания безрисковой ставки. Остаточный cash не
приносит процентов. Начальный капитал 1 млн; fractional lots и комиссии - research proxy,
налоги/исторический BBO/settlement/ёмкость не доказаны. История уже открыта, не holdout.

## Counts и закрытие accounting gap

- 70 896 history rows; 584 issue/month curve scores. 60 месяцев: 56 selected (93,3333%),
  3 insufficient curve issues, 1 snapshot unavailable. Missing месяцы не вырезаны.
- Каждый arm/cost: 56 завершённых rebalances, все 1271/1271 daily marks;
  нет unresolved rebalances. Основной: 271 trade legs, 106 entries /103 closed episodes;
  контроль: 278 legs, 113 entries /110 closed. На конце у каждого 3 открытых позиции.
  Terminal mark минус cost reserve НЕ объявляется исполненной ликвидацией.
- Исходный V1 имел 11 missing principal record dates в каждом scenario и правильно
  не публиковал CAGR/Sharpe/MDD/NAV/PnL. Это sourcewide счётчик, включая неприобретённые
  выпуски, а не установленная потеря денежных выплат.
- R1 доказал 44/44 zero entitlements: 5 never-held/traded +6 exact redemption dates
  на каждую из 4 комбинаций. Принятые dates <=2025, известные положительные суммы;
  для ever-held нет trades/positions от года перед погашением до конца истории.
- Все ранее credited cashflows независимо воспроизведены по исходному schedule и
  полному position book. Remaining unresolved cashflows 0 у всех четырёх scenarios.
  Missing source dates остались missing: сырые данные не перезаписывались.
- Новый код не вызывает simulate или signal builder. Все исходные decisions, trades,
  positions, raw NAV и coupon credits byte-identical; изменено только разрешение
  метрик после доказательства нулевого права на спорные выплаты.
- PDF skill помог проверить исходные уведомления визуально: FinProInvest REDM120744
  и НРД row178. Отменённое положение ЦБ2011 исключено; чужие delayed foreign-account
  payment clocks не использованы. Exact six documentary sources/SHA - в R1 config/note.
- Protected 2026 prices/returns/labels/PnL не использованы. Внешние current-vintage
  документы используются только для конкретных прошлых record dates, не predictors.
  Paper bootstrap, модели, live orders и schedules collectors не менялись.

## Воспроизводимость

V1, сохранённый исходный incomplete run:

- Pre-outcome push `de7a2f872994194f9448ede2b5fc75a6954aeb4e`.
- Config SHA `13495875f1ed0e3f428ff09e4f0a6b0c0b3550483f737e444122e26043ff0130`.
- Seal SHA `7295e716381f64929e8fed7119963616523a2435d0f4a24dd6006afe8ec33c4a`.
- Canonical `/srv/trading_lab_data/runs/v70_ofz_relative_curve_v1_7295e716381f`.
- Metrics SHA `f6c012ff0fa4bcdcdf9cc0fc38ed55caa0f3503fdd8aa1e214c7b44025a9db11`.
- Identity SHA `a3f780817c47acff84c844bea58d00aa92c137c3afc1084f56af29cb26ee9520`.
- Единственный economic simulation run: 2,824659s. Local15+5regression+2encoding PASS;
  server15 PASS до запуска. Старый V1 audit20 hashes/0 complete metric replays:
  ноль означал отсутствие полного результата, а не проверенную доходность.

R1, отдельный окончательный accounting/report run:

- Pre-performance-reveal push `068df83c791a8144ef8870b5846c76ecc14a4eb8`.
- Config SHA `876cce9a04bf5f8365a29df6041d265aef31e881d7d404dcda9cc5250aaf7d4c`.
- Seal SHA `60b09b6b212163b31c934c7b6b814ee400603a3c0456d1e94e2a7b6e959280ac`.
- Implementation SHA `e207c848f38e16ee121dfb631c91823f3065c160d32b849676b9cb4601fa8180`.
- Canonical `/srv/trading_lab_data/runs/v70_ofz_relative_curve_r1_60b09b6b2121`.
- Metrics SHA `b18acbc2cc427f23fc720c7908ff1a06bb772829f55744ca663bb8f57ece64f0`.
- Identity SHA `5175f69e941242f891cc60be3f19f399973e87ae65ee0fa3c27e64df38fa0e1b`.
- 13 new +15 V70 regression +2 encoding: local30 PASS/6,73s. Ruff/diff PASS.
  Server13 PASS/0,09s, затем одна accounting evaluation: 0,252720s, exit0.
- Audit: 20 parent artifact hashes +6 documentary hashes, 6 new artifact hashes,
  44 proof rows, 4/4 full metric/valuation/coupon replays PASS. Trading simulations rerun0.
- R1 root: proof, четыре valuation, metrics/identity. Исходный root сохраняет decisions,
  scores, trades, positions и raw ledger. Все данные и PDF/HTML остаются вне Git.

## Следующий допустимый шаг

V65-V70: **12 отсеянных гипотез, 0 Stage2 candidates**. R1 не считается новой гипотезой.
Цель относительно предсказуемых 20-50% годовых не достигнута.

Следующий быстрый screen должен иметь иной экономический механизм или новую
содержательную информацию на допустимой истории. Не повышать плечо, не менять
степень кривой/сроки/число выпусков/месячное правило/costs по V70 outcomes; не продвигать
контроль и не возвращаться к закрытым V52/V53/V67. Общий engine задним числом не
исправлять и старые canonical runs не пересчитывать ради улучшения.
