# Текущее состояние исследования

Обновлено: **2026-09-01**. Период разработки ограничен данными не позже
`2025-12-31`; данные 2026 для текущих V8–V29 гипотез защищены и не используются.

## Короткий ответ

Новый главный research lead — **V27**, но только для новой независимой валидации.
Он объединяет frozen V12/V25 trend, неизменный максимум 2x, консервативный доход RUONIA,
capacity-aware исполнение и новый binary cash governor: latest causally available
официальная ключевая ставка ЦБ `>=20%`. Все правила были committed/pushed до PnL.
Primary combined CAGR **28,3752%**, Sharpe **1,2119**, MDD **−20,7138%**; stress CAGR
**27,3643%**, MDD **−21,0511%**. Все sealed gates пройдены. Текущий общий статус:
**GO TO NEW UNSEEN VALIDATION, но NO-GO for live trading**.

Отдельный post-selection audit **V27-R1** был запечатан и pushed до чтения дневной
equity curve, затем выполнен ровно один раз.
Config SHA `a8d6ed420593aeb26e0bf537b402a6edba6b40ab7dd64d48947dc2a936ec8b10`
фиксирует circular block bootstrap по 5/21/63 сессии, 20 000 повторов на каждый из трёх
cost scenarios, rolling 252-session windows, leave-one-year-out и deflated-Sharpe
sensitivity. Все 49 checks true. В stress minimum bootstrap-frequency совместного
`CAGR >=20%` и `MDD <=30%` равна **65,70%**, а для `CAGR >=50%` — только **4,33%**;
5-й процентиль CAGR падает до **8,13%**. В rolling 252-session stress-окнах **87,95%**
положительны, но лишь **57,00%** достигают 20%, minimum CAGR **−17,32%**. Поэтому audit
поддерживает переход к unseen validation, но прямо отвергает трактовку V27 как уже
доказанного «предсказуемого 20% ежегодно» и не поддерживает цель 50%.

V26 был необходимым промежуточным прорывом: 2x V25 + RUONIA + `cancel_and_clip` дал
primary CAGR **24,1698%**, Sharpe **0,9764**, MDD **−33,5661%**, а stress CAGR
**23,0255%**. Он устранил 8 critical events V15, но strict MDD `<=30%` не прошёл;
verdict **NO-GO**. V27 не менял плечо или costs, а добавил один новый официальный
причинный режим риска и снизил MDD на **12,8523 п.п.**.

Decisive проверка **V28** выполнена один раз после push seal `4310bc3`. Canonical run
`runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/`, metrics SHA `73b614b8...`.
Результат плохой: primary combined CAGR **−2,4271%**, Sharpe **−0,2682**, MDD
**−17,6953%**; stress CAGR **−2,5950%**. Но execution одновременно invalid: пять
capacity-cancelled atomic rolls оставили expired old contracts; с `2014-05-19` BRK4
не имеет factual rows, что породило 5 129 critical failures и 1 251 rejected legs.
Поэтому V28 не поддерживает ни 20%, ни 50%, а его метрики нельзя считать валидным
полным тестом signal economics. Следующий отдельный V29 должен проверить risk-first
roll: full executable old-leg exit, independently capacity-clipped new entry/cash.

V29 был sealed/pushed commit `478a246`, затем выполнен ровно один раз. Исправление
полностью устранило execution trap: 639/639 coverage, 527 filled legs, 15 clips и ноль
roll cancellations/rejected/critical/unresolved. Но стабильной прибыли нет: primary
total `+24,8749%` за пять лет, CAGR лишь `4,6133%`, Sharpe `0,3191`, MDD `−47,3846%`;
stress CAGR `3,7117%`, MDD `−48,6822%`. Положителен только 2014 (`+90,9463%`), четыре
остальных года отрицательны. Verdict `FAIL_POST_V28_20`: V29 не поддерживает 20% или 50%,
не является independent confirmation и запрещён для live.

Следующее принципиально иное направление — exchange-listed календарные спреды, а не
ещё один threshold directional trend. Source-only protocol запечатан до bulk collection:
config SHA `7268753933efb4c9633f3e314ebc1d67cf4a7d63e4290e0f3a0142bacce8048e`,
implementation SHA `db217488...`. Metadata preflight причинно связал все 110 RFUD
спредов SI/RI/BR/MIX с официальными кодами публичного архива без ручных aliases.
Обычный ISS probe дал шесть settlement rows и ноль reported trade rows, тогда как
официальный CSV того же спреда содержит 71 уникальную дату и фактические поля
Last/Bid/Ask/High/Low/Amount/Volume/Trades. Collector сохраняет ISS и public archive
раздельно, архивирует exact HTML/CSV bytes, сохраняет и помечает расхождения интервалов,
аварийно запрещает любую market-value дату `>=2026-01-01` и не считает returns/PnL.
Bulk bundle ещё не собран; первым следующим действием должен быть push seal, затем один
immutable collection/replay audit.

Новый source-only protocol V3 для официального MOEX EOD 2012–2017 подготовлен до
первого daily price response: config SHA
`0b86cda4d3bddf72831075a771c3e7f6568a0a4ba2f78c64b0254c980c902b08`,
implementation SHA `7dd25e01...`. V1 metadata preflight выявил lowercase-sensitive
finder; V2 после исправления обнаружил все 155 aliases, но остановился до daily history
на отсутствующем у старых descriptions `LSTTRADE`. Полный metadata-only audit показал:
FRSTTRADE/LSTDELDATE и один RFUD segment есть у 155/155, LSTTRADE есть у 91 и missing
у 64. V3 сохраняет missing, а обязательный LSTDELDATE использует как request end. Exact
set 155 contracts (BR/MIX/RI/SI = 71/24/24/36), dates, daily schema/cursor и raw archive
не менялись. V3 был pushed commit `38fc63a` до первого daily response и успешно собрал
immutable bundle: 30 059 rows `2012-01-03..2017-12-21`, 544 raw requests, manifest SHA
`e60d0bcacff17af0229d150552a70ac235e821c2d271970ea2567c212a5f3da6`. Exact replay
подтвердил 18 finder + 155 description/boards + 371 daily pages и все 30 059 raw rows.
Стратегия, returns и PnL ещё не рассчитывались; следующий этап — derived source panel/
spec proxy и отдельный V28 seal.

Derived-source D1 был pushed commit `ce22460` до единственного build. Byte/hash/temporal
аудит прошёл, но operational verdict — **непригоден**: в source есть старые serial-month
Si contracts, и nearest-expiry planner после трёх успешных roll получил 9
`carry_unfilled_roll`, затем 1 276 `carry_unfilled_exit`. Returns, signal и PnL не
считались. D1 сохранён immutable с manifest SHA `73ffe4c3...` как честный failed source
derivation. D2 с official-cycle filter был sealed/pushed commit `b858d54`, но его build
правильно остановился без output: SI дал 22, а не ошибочно ожидавшиеся 23 roll. Source-
only diagnosis показал единственный bounded gap: после factual exit `2016-12-09` нет
admitted 2017 SI observation до `2017-01-03`; planner остаётся flat пять сессий и
re-enters `2017-01-04`, не создавая return bridge. D3 подготовлен до build: config SHA
`d21dd650...`, implementation SHA `c04d8224...`. Он наследует D2 byte-identical, требует
exact action counts, 22/23/70/23 roll для SI/RI/BR/MIX, exact flat-gap dates и ноль
unfilled roll/exit. D3 был pushed commit `8877b75` до build и успешно опубликован:
manifest SHA `3ab20092dbe4fd8a58211d11db1b6dcd6a8335f98051146da76a0f3c0c82fa71`,
1 479 common sessions `2012-01-03..2017-12-01`, 5 916 panel rows, 28 797 contract/spec
rows, все exact action gates true, unresolved roll/exit = 0. Ни returns, ни PnL пока не
считались. Следующий этап — bounded STLFSI4/RUONIA/key-rate source и отдельный V28 seal.

Macro source S1 был pushed commit `9a5ff96`, но первый request трижды получил FRED read
timeout с research User-Agent; ни один response не сохранён и output не создан. S2
transport-only correction был pushed commit `5bec23f` и получил все три responses, но
fail-closed parser остановился до publication на старом RUONIA marker: из 1 478 rows
только 78 имеют explicit publication date, для 1 400 timing неизвестен. Market outcomes
не читались, S2 output отсутствует. S3 parser-only correction запечатан до collection:
config SHA `ae575962...`, implementation SHA `5f2e4e09...`; unknown publication и
`available_at` сохраняются missing, inference/zero-fill/collateral credit запрещены.
Seal был pushed commit `1f9c343`, затем S3 успешно опубликован и полностью replayed:
manifest SHA `949bc7bf...`, raw SHA `8109f157...`; 312 STLFSI4, 1 478 RUONIA и 1 065
key-rate rows, все SHA/schema/availability checks true. Следующий разрешённый шаг —
отдельный pre-outcome V28 seal.

V12 primary: total return **45,1114%**, CAGR **7,7318%**, Sharpe **0,7624**,
MDD **−14,1526%**; четыре из пяти лет положительны. При doubled costs total return
**40,8019%**, при stress — **41,7324%**. Это conservative research proxy, а не
broker-exact обещание прибыли.

V13 добавил строгий front/next carry confirmation и поднял historical total return до
**52,4579%** и CAGR до **8,8013%**, но Sharpe упал до **0,7081**, а MDD вырос до
**−20,6861%**. Поэтому V13 — агрессивный return-challenger с verdict **NO-GO** как
стабилизатор; V12 остаётся главным более устойчивым lead.

V14 проверил предыдущую сессию RVI как forward-volatility governor. MDD снизился до
**−9,3980%**, но CAGR упал до **4,6687%**, Sharpe — до **0,7342**. Verdict снова
**NO-GO**: риск стал меньше, но цель доходности отдалилась.

V15 впервые пробил целевую доходность: frozen V12 с 2x targets и консервативным доходом
на свободное обеспечение дал combined CAGR **21,3272%** (stress **20,4453%**). Но MDD
вырос до **−34,4823%**, 2025 дал **−15,2535%**, а остановка RI/MIX в марте 2022 создала
8 critical execution events. Поэтому V15 — важный capital-efficiency lead, но его
verdict **NO-GO**, метрики недействительны для promotion и live trading запрещён.

V16 после дополнительного source-аудита **INVALIDATED**. У 932 из 1 044 FUTOI states
официальный `systime`/`available_at` позже decision; все 2021–2024 states и часть 2025
были недоступны. Механические CAGR **22,0082%** и Sharpe **0,9678** нельзя считать
причинным результатом: join проверял только `source_date`, а не обязательное
`available_at <= decision_at`. Replay теперь аварийно запрещён кодом. V12 остаётся
единственным lead с GO только к новой unseen validation.

Официальный MOEX FUTOI daily-last — current-vintage archive, а не доказанный PIT history.
MOEX описывает `SYSTIME` как время публикации; для 10 456 из 11 744 строк оно отстаёт от
observation более чем на сутки, а для всей истории 2020–2024 равно 21.06.2025. Полный
5m downloader сохраняет actual retrieval и использует
`conservative_available_at = max(SYSTIME + buffer, retrieval_at)`, поэтому архив не
может участвовать в backtest 2021–2025. Bundle уже завершён: 2 015 624 строки,
1 007 812 paired points, manifest SHA `cc432d59...`; minimum conservative availability
`2026-08-31T22:43:34Z`. Подробности — в
[карте источников](INFORMATION_SOURCES.md).

Официальный EIA WPSR Table 1 bundle содержит 727 допустимых release vintages и 38 248
target-free строк `2012-01-05..2025-12-29`. Один stale issue `2019-07-03` изолирован,
71 межвыпусковая revision сохранена; его единственный sealed-тест уже завершён как V17.

V17 выполнил этот sealed test и получил **NO-GO**: total return **−33,1422%**,
CAGR **−7,7373%**, Sharpe **−0,1893**, MDD **−48,8033%**, только два положительных года.
Все 294 nonzero execution dependencies покрыты, 0 critical/unresolved, поэтому провал не
объясняется исполнением. Raw delayed EIA balance не является доходным сигналом; signs,
компоненты, lag и thresholds по этому результату не инвертировать и не подбирать.

V18 проверил новый release-keyed source family: 458 датированных недельных прогнозов
факторов банковской ликвидности ЦБ за `2017-01-10..2025-12-30`. Прямой знак будущего
government-account flow для SI дал **−41,9547%**, CAGR **−10,3092%**, Sharpe
**−0,5137**, MDD **−55,7292%** и только один положительный год. Все 257 nonzero
execution dependencies покрыты, 0 critical/unresolved. Verdict **NO-GO**; знак,
thresholds, lag и expiry по этому outcome не подбирать.

V19 проверил следующий независимый current-vintage source: 1 238 фактических дневных
факторов ЦБ `2021-01-11..2025-12-30`, включая 939 ненулевых операций Минфина с валютой.
Прямой persistence-знак для SI дал total return **−0,0316%**, CAGR **−0,0063%**,
Sharpe **0,0501**, MDD **−30,7614%** и два положительных года. Все 937 nonzero
execution dependencies покрыты, 0 critical/unresolved. Verdict **NO_GO**: сильный
**+33,97%** в 2025 не компенсирует убытки трёх лет и не разрешает post-outcome отбор
amount/change days, smoothing, lag или sign flip.

V20 проверил новый Minfin OFZ source family после pre-outcome seal. 283 successful
ОФЗ-ПД rows дали 166 prior-only scored auction days; demand-strength basket long RI/MIX и
short SI получил total return **−5,3468%**, CAGR **−1,0931%**, Sharpe **−0,6313%** и
MDD **−6,1937%**. Все 504 nonzero dependencies покрыты, 0 critical/unresolved. Verdict
**NO_GO**: низкая просадка при maximum gross 47% не превращает отрицательный expectation
в стабильный edge. Signs, extreme-score threshold, rank window, expiry и event kinds по
этому outcome не подбирать.

Новый target-free CBR macro-survey source собран без чтения market outcomes: 11 787
records, 37 survey months и 17 indicators. Processed SHA `a139ead8...`, manifest SHA
`faae8927...`; original historical vintages отсутствуют. Консервативный month+1-end
contract допускает до границы 2026 только 36 releases. Источник готов для одного
predeclared development test revisions ожиданий, но не для независимого подтверждения.

V21 был запечатан и pushed до outcome, затем выполнен ровно один раз. Direct next-year
median revisions дали механический total return **−3,1730%**, CAGR **−0,6429%**,
Sharpe **−0,0788**, MDD **−18,7868%** и 3/5 положительных лет. Coverage 200/202:
у RI/MIX на `2022-03-24` не было lagged volume, portfolio-atomic rebalance отклонён,
поэтому все ledger incomplete с двумя critical failures. Verdict **NO_GO**; знаки,
indicators, oil priority, thresholds, risk/expiry и blend по этому outcome не подбирать.

V22 проверил новый release-specific Business Climate Index после pre-outcome commit
`eb0891a`. Результат впервые после серии V17–V21 положителен во всех cost scenarios:
primary total **+13,3661%**, CAGR **2,5411%**, Sharpe **0,3569**, MDD **−8,8570%**.
Но положительны только 2023/2024, а 2024 дал почти всю прибыль; sealed CAGR/Sharpe/3-of-4
year gates не пройдены. Execution полностью доказан: 153/153 dependencies, 0 rejected,
critical и unresolved. Verdict **NO_GO**; BCI thresholds, components, exact decimals,
signs, risk/expiry и blend по этому outcome не подбирать.

Следующий независимый источник подготовлен без чтения рыночного outcome: 48
release-specific выпусков ЦБ по инфляционным ожиданиям и потребительским настроениям,
включая HTML/PDF/XLSX и 146 сохранённых официальных ответов. Processed SHA
`70711272...`, manifest SHA `b132a45e...`; все 48 HTML endpoints подтверждают XLSX после
округления. V23 запечатан SHA `2a8a35a8...`: единственный confirmation regime, cash rule,
risk, expiry и promotion gates были неизменяемы до outcome. Canonical run дал primary
**−5,3484%**, CAGR **−1,0935%**, Sharpe **−0,1589**, MDD **−13,6190%**; doubled/stress
тоже отрицательны. Verdict **NO_GO**, same-history tuning этой family закрыт.

Новая треугольная гипотеза RI/MIX/SI проверена двумя заранее зафиксированными execution
вариантами и закрыта как **NO-GO**. Оба запуска остановились fail-closed на фактической
ликвидности; все доступные до остановки метрики отрицательны.

## Сводка активных гипотез

| Направление | Главный development-результат 2021–2025 | Решение |
|---|---:|---|
| V29 risk-first roll, post-V28 2013–2017 | +24,87%, CAGR 4,61%, Sharpe 0,32, MDD −47,38%; execution complete | Execution fixed, economics unstable; **FAIL/NO-GO** |
| V27 V26 + CBR key-rate `>=20%` cash governor | +248,61%, CAGR 28,38%, Sharpe 1,21, MDD −20,71%; stress CAGR 27,36% | Все sealed gates пройдены; **GO к новой unseen validation, не live** |
| V26 2x V25 + causal RUONIA + capacity admission | +195,14%, CAGR 24,17%, Sharpe 0,98, MDD −33,57%; complete | Return/execution gates пройдены, MDD `>30%`; NO-GO |
| V12 core-four correlation trend | +45,11%, CAGR 7,73%, Sharpe 0,76, MDD −14,15% | GO к новой unseen validation; не live |
| V13 trend + carry confirmation | +52,46%, CAGR 8,80%, Sharpe 0,71, MDD −20,69% | Return выше, stability хуже; NO-GO как replacement |
| V14 prior-session RVI governor | +25,62%, CAGR 4,67%, Sharpe 0,73, MDD −9,40% | MDD лучше, edge слабее; NO-GO |
| V15 2x V12 + causal RUONIA | +162,87%, CAGR 21,33%, Sharpe 0,88, MDD −34,48%; 8 critical | CAGR gate пройден, stability/execution gates нет; NO-GO |
| V16 FUTOI crowding + capacity-aware 2x | Механически CAGR 22,01%, но 932/1 044 states были недоступны | **INVALID: FUTOI look-ahead**, метрики не использовать |
| V17 EIA physical balance for BR | −33,14%, CAGR −7,74%, Sharpe −0,19, MDD −48,80% | Полное исполнение, но сигнал убыточен; NO-GO |
| V18 CBR forward-liquidity direction for SI | −41,95%, CAGR −10,31%, Sharpe −0,51, MDD −55,73% | Полное исполнение, прямой знак убыточен; NO-GO |
| V19 CBR reported Minfin FX persistence | −0,03%, CAGR −0,006%, Sharpe 0,05, MDD −30,76% | Полное исполнение, но edge отсутствует; NO-GO |
| V20 Minfin OFZ-PD demand strength | −5,35%, CAGR −1,09%, Sharpe −0,63, MDD −6,19% | Полное исполнение, но сигнал убыточен; NO-GO |
| V21 CBR next-year macro revisions | −3,17%, CAGR −0,64%, Sharpe −0,08, MDD −18,79%; 2 critical | Signal отрицателен и execution incomplete; NO-GO |
| V22 CBR printed BCI regime | +13,37%, CAGR 2,54%, Sharpe 0,36, MDD −8,86%; complete | Положительный, но нестабильный и ниже gates; NO-GO |
| V23 CBR household confirmation | −5,35%, CAGR −1,09%, Sharpe −0,16, MDD −13,62%; ledger complete | Отрицателен во всех cost scenarios; NO-GO |
| V24 daily VIX/VIX3M governor | +38,89%, CAGR 6,79%, Sharpe 0,74, MDD −14,28%; complete | Прибыльный, но stability и costs хуже V12; NO-GO |
| V25 weekly STLFSI4 governor | +49,07%, CAGR 8,31%, Sharpe 0,82, MDD −14,23%; complete | Return/Sharpe лучше V12, MDD хуже на 0,074 п.п.; strict NO-GO |
| Structural futures breadth | RAM: CAGR 6,77%, Sharpe 0,78, MDD −15,13% | Продолжать только exact-execution проверку |
| Sparse key-rate events | 10 сделок, CAGR 0,99%, Sharpe 0,82, MDD −0,47% | Малый наблюдаемый lead, недостаточно масштаба |
| RI/MIX/SI triangular relative value | V10: 4 сделки, −2,58%; V11: 10 сделок, −0,68%; оба invalid после unresolved | Закрыт, NO-GO |
| Corridor hazard 0,8/2,8 ATR | 58 сделок, CAGR 0,46%, Sharpe 0,35 | Закрыт, NO-GO |
| Continuous 10m neural timing | 0 допущенных neural trades; breakout CAGR −53,71% | Закрыт, NO-GO |
| 30-stock market graph | IC −0,00639; CAGR −10,32%, Sharpe −1,40 | Закрыт, NO-GO |
| Long-only relative momentum | CAGR 1,29%, Sharpe 0,18, MDD −49,34% | Закрыт, NO-GO |

Полная история и точные external run paths находятся в
[реестре экспериментов](EXPERIMENTS.md).

## V27 extreme key-rate governor — все sealed gates пройдены

Protocol/config commit `aca0380` был pushed до первого PnL. Config SHA
`7a9a44cf7b09c7820a514b2706e332744a3b30ced8b7d3d4c8bdf7448a3194fe`
фиксирует ровно один круглый monetary boundary: latest key rate `>=20%` переводит
уже STLFSI4-governed portfolio в cash; `<20%` пропускает его. Missing/stale старше семи
дней также cash. Максимум 2x, RUONIA haircut 50%, buffer 10%, capacity и costs V26 не
изменены. Source-only states до PnL: all `418 = 309 pass / 68 STLFSI cash / 40 key-rate
cash / 1 missing`; OOS `261 = 197/24/40/0`.

Canonical run:
`runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/`; metrics SHA
`5fc1f271acf8f9df711006bca24e6bc40425bf097c21e989eb0296baeb0e7654`.

- 115/115 checks true; 27/27 declared artifacts прошли bytes/SHA/row audit;
- raw CBR SOAP 121 958 bytes, SHA `06da1497...`, exact replay всех 2 015 key-rate rows;
- 828/828 nonzero next-open dependencies; все orders filled, 0 critical/unresolved;
- primary combined return **+248,6127%**, CAGR **28,3752%**, Sharpe **1,2119**,
  MDD **−20,7138%**, costs **44 141,07 RUB**, collateral **366 595,47 RUB**;
- doubled: CAGR **27,6201%**, Sharpe **1,1918**, MDD **−20,9410%**;
- stress: CAGR **27,3643%**, Sharpe **1,1839**, MDD **−21,0511%**;
- primary годы: **+40,34%/+72,45%/+30,68%/+11,87%/−1,48%**;
- против V26: CAGR `+4,21 п.п.`, Sharpe `+0,2356`, MDD лучше на `12,85 п.п.`,
  worst year лучше на `10,79 п.п.`, costs ниже на 11 156,59 RUB;
- market artifacts заканчиваются `2025-12-30`; timestamps/targets/PnL 2026 отсутствуют.

Verdict **GO_TO_NEW_UNSEEN_VALIDATION** означает только переход к заранее запечатанному
forward/PIT или ранее не просмотренному рынку. V27 создан после просмотра V26 на тех же
2021–2025, поэтому не является независимым доказательством и live trading запрещён.
Нельзя менять 20% boundary, age, cash/partial scale или V26 economics по этому outcome.

## V26 capital efficiency — цель доходности пробита, MDD gate не пройден

Config SHA `2b08589013f3b3387002830cad7878ef0fffc5dc808b8165fc004e724abf4c1b`
и commit `3b9ce95` были pushed до market outcome; pre-PnL routing fix `5515321` лишь
перенёс 2x после допустимого base mapper, не читая PnL. Canonical run:
`runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/`; metrics SHA
`b4149969696e23a29a06b58085510d9f8c9f2bbf584ca0d2aaa883801493567d`.

- 99/99 checks true; 25/25 declared artifacts прошли audit;
- 1 016/1 016 dependencies, all filled orders, 0 critical/unresolved; шесть причинных
  no-open cancellations на фактических остановках заменили 8 critical events V15;
- primary/doubled/stress combined CAGR **24,17%/23,41%/23,03%**;
- Sharpe **0,976/0,956/0,946**, но MDD **33,57%/33,99%/33,97%**;
- единственный false promotion condition — all-scenario MDD `<=30%`.

Verdict остаётся `NO_GO`; снижать постоянное плечо после этого outcome нельзя. V26
сохраняется как exact parent V27 и как доказательство работоспособности capacity policy.

## V25 STLFSI4 weekly governor — сильнейший challenger, strict NO-GO

Source commit `cdfe674` и protocol commit `74c5461` были pushed до первого outcome.
Config SHA `dd8b60513de7261aa051c12bd5598fffd880c90c98489a5becac820b7597416b`
фиксирует official zero, following-Thursday availability, 14-day age, binary global
scale и OOS states `237 pass / 24 stress-cash / 0 missing`. Canonical run:
`runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/`; metrics SHA
`c2518d17b4e945ef921fa8dbaa8bd330645131acddd73fc01a45c44c0aacfa86`.

- 82/82 checks true; raw CSV exact replay; 20/20 run files прошли SHA/row audit;
- 1 016/1 016 dependencies, 438 primary filled legs, 0 rejected/critical/unresolved;
- primary/doubled/stress return **+49,07%/+47,18%/+46,86%**;
- primary CAGR **8,31%**, Sharpe **0,818**, MDD **−14,226%**, costs 13 835,17 RUB;
- годы: **+17,53%/+14,01%/+12,08%/+1,54%/−2,26%**;
- maximum participation **0,11287%**, no order-time gross/margin breach;
- market artifacts заканчиваются `2025-12-30`.

V25 улучшил V12 total return на 3,96 п.п., CAGR на 0,58 п.п., Sharpe на 0,0553 и worst
year на 0,37 п.п.; equity ни в одной ledger session не ниже V12. MDD gate, однако,
false: `14,2262% > 14,1526%`. Обе кривые имеют тот же peak/trough interval
`2024-11-26 → 2025-03-03`; V25 имеет более высокий trough в RUB, но также более высокий
peak, поэтому относительная просадка хуже на 0,0736 п.п. Verdict `NO_GO` менять нельзя.
Практический статус — приоритетный кандидат для новой forward/PIT validation, не live.

## V24 Cboe VIX/VIX3M daily governor — прибыльный, но хуже V12

V24 не меняет frozen V12 signal/risk/execution. Config SHA
`f81b5aaa666346fa049b550e5dfc92c24ecf6ef2790a2cb00fb83235f24c064c`
заранее зафиксировал daily binary global scale: causally available complete contango
`VIX/VIX3M < 1` пропускает V12, backwardation/flat/missing/stale переводит всё в cash.
Source/calendar-only counts `1785/167/72` all и `1170/53/47` OOS были sealed до PnL.
Pre-outcome commit `34023c1` pushed до canonical run
`runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/`; metrics SHA
`1da1b995fd432c938f62745abcc71f7e85af5a5d20735b9a98631a41d21d2f98`.

- 83/83 checks true; strict replay двух raw CSV точно восстановил processed source;
- 3 722/3 722 dependencies, primary 774 filled legs, 0 rejected/critical/unresolved;
- primary/doubled/stress return **+38,89%/+37,13%/+33,54%**;
- primary CAGR **6,79%**, Sharpe **0,739**, MDD **−14,28%**, costs **26 009,44 RUB**;
- годы: **+16,56%/+8,66%/+7,62%/+10,50%/−7,80%**;
- maximum participation **0,13643%**, maximum post-mark gross leverage **0,9443**;
- все 20 run files прошли bytes/SHA/row audit, market timestamps `<=2025-12-30`.

V24 прошёл CAGR, 4/5 years и положительные doubled/stress gates, но проиграл V12 по
Sharpe на `0,0231` и по MDD на `0,125 п.п.`. Сто cash sessions создали 67 episodes и
133 scale transitions; filled legs выросли с 429 до 774, costs — на 12 622,16 RUB.
Verdict `NO_GO`: не ретюнить ratio boundary, freshness, levels, smoothing, hysteresis,
partial scale или asset exceptions на 2021–2025.

## V23 CBR household confirmation — валидный отрицательный NO-GO

V23 использует новую household source family и не изменяет увиденные BCI outcomes V22.
Config SHA
`2a8a35a898eddae72694bce159282ced6f72230b537613ad224c0d2b6001f2ee` фиксирует:

- exact XLSX expected-inflation и consumer-sentiment sequential deltas;
- risk-on только при inflation down + sentiment up, risk-off только при обратной паре;
- mixed/zero = cash, long/short signs RI/MIX/SI неизменны, BR = zero;
- 48 releases, 1 warmup, 47 scored, 16/17/14 regimes и 99 nonzero directions;
- risk budget 1/3, prior 60d vol, target 20%, floor 10%, gross `<=1`, expiry 45 days;
- next factual open, portfolio-atomic execution и costs 1×/2×/stress;
- CAGR/Sharpe/MDD/year gates и запрет данных/метрик `>=2026-01-01`.

Source commit `3d18a03` уже pushed до protocol. Pre-outcome тесты прошли (`6 passed`),
включая полный replay 146 raw responses и synthetic expiry/collision. Реализация была
pushed commit `4ac40df` до outcome. Canonical run:
`runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/`, metrics SHA
`33614e391a547a636ed3ef1a2df44653d05669c24495aacb43f73125cbc9b839`.

- 92/92 checks true; 19/19 artifacts сверены по bytes/SHA/rows;
- 33 confirmations до collision; September/October 2022 оставили October;
- три confirmed states `2022-03..05` fail-closed остались cash из-за отсутствия causal
  prior-60-session volatility: mapped 29/32 distinct confirmed states после collision;
- сформированный ledger complete: 111/111 nonzero dependencies, 109 filled legs,
  0 rejected/critical/unresolved, maximum participation **0,03956%**;
- primary/doubled/stress return **−5,35%/−5,63%/−5,92%**;
- primary CAGR **−1,09%**, Sharpe **−0,159**, MDD **−13,62%**, costs **2 775,79 RUB**;
- годы: 2021 **0,00%**, 2022 **−3,77%**, 2023 **−2,42%**,
  2024 **−1,19%**, 2025 **+2,01%**; terminal position отсутствует.

Verdict `NO_GO`: return, CAGR, Sharpe, active-year и cost gates провалены. Нельзя
инвертировать signs, выбирать один household ряд, вводить thresholds, торговать mixed
states или подбирать risk/expiry/blend на том же outcome.

Новый независимый FRED/Cboe VIX/VIX3M source V2 собран без MOEX outcome: 2 087 grid rows,
2 011 complete pairs, 76 missing сохранены, 174 backwardation и 1 837 contango. Processed
SHA `6ffe7daa...`, manifest SHA `0aecc29fd...`; оба bounded raw CSV не содержат 2026 и
точно воспроизводят processed frame. V24 был запечатан config SHA `f81b5aaa...` и pushed
commit `34023c1` до единственного outcome. Daily contango governor сохранил прибыль:
total **+38,8855%**, CAGR **6,7910%**, Sharpe **0,7394**, MDD **−14,2777%**, все cost
scenarios положительны и execution complete. Но он оказался хуже frozen V12 и по Sharpe,
и по MDD, а costs выросли на 12,62 тыс. RUB. Verdict **NO_GO**; boundary, freshness,
binary scale и state mapping на этой истории больше не менять.

V25 с независимым weekly STLFSI4 оказался наиболее сильным challenger: total
**+49,0720%**, CAGR **8,3137%**, Sharpe **0,8177**, четыре положительных года и все cost
scenarios profitable при полном исполнении. Он улучшил V12 return/Sharpe/worst year и
ни в одной ledger session не имел equity ниже V12. Но MDD **−14,2262%** оказался на
**0,0736 п.п.** хуже строгой границы V12. Поэтому официальный verdict — **NO_GO** по
единственному MDD gate; результат перспективен только для новой forward/PIT validation,
а current-vintage STLFSI4 Version 4 не разрешает live claim.

## V22 CBR Business Climate Index — положительный, но слабый NO-GO

V22 использует новую official release-specific информацию и не меняет провалившиеся
V20/V21 families. Config SHA
`97b2aa74416eae4ebbce28d018a460f98ade4993cfb086487d28515976c18fbe` фиксирует:

- только знак sequential delta printed one-decimal composite BCI;
- improvement = long RI/MIX и short SI, decline = обратный знак, BR = zero;
- 44 releases, 1 warmup, 43 scored, 117 nonzero asset directions;
- risk budget 1/3 для SI/RI/MIX, prior 60d vol, target 20%, floor 10%, gross `<=1`;
- 45-day expiry, next factual open, portfolio-atomic execution и costs 1×/2×/stress;
- exact chart decimals, component selection, thresholds, training и blend запрещены.

Pre-outcome commit `eb0891a`; canonical run
`runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/`, metrics SHA
`10d7b0bf1b84d46b7cfe6fac784ba8e279bd22bd277fa76c2c8f51238f274214`.

- 43 mapped signal/expiry states, одна корректная October/November collision и 13 rolls;
- 224 target rows, 153/153 nonzero dependencies complete;
- primary/doubled/stress return **+13,37%/+12,88%/+11,96%**;
- primary CAGR **2,54%**, Sharpe **0,357**, MDD **−8,86%**, costs **4 873,13 RUB**;
- годы: 2021 **0,00%**, 2022 **−3,78%**, 2023 **+1,52%**,
  2024 **+20,84%**, 2025 **−3,96%**;
- все 91 checks true, все 17 declared artifacts повторно сверены, market outputs
  заканчиваются `2025-12-30`.

Verdict `NO_GO`: execution и costs выдержаны, но CAGR/Sharpe/positive-active-years нет.
После просмотра результата параметры менять нельзя; новый тест требует нового источника
или forward history.

## V21 CBR macro revisions — отрицательный и execution-incomplete результат

V21 был запечатан и pushed commit `5414251` до первого чтения market outcomes.

- config SHA:
  `5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc`;
- metrics SHA:
  `cfc704e757393760cabcddeb6f3d1614f43df8ee8523b46db0fccd0ac8b92c0e`;
- canonical run:
  `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/`;
- 11 787 source records дали 36 causal releases, 1 warmup и 35 scored releases;
  component counts: SI 34, RI 28, MIX 28 и BR 12 ненулевых revisions;
- 32 mapped source decisions, три skipped signals весны 2022 без полной prior volatility,
  34 roll decisions и 264 target rows;
- coverage **200/202**: RI и MIX на `2022-03-24` не имели lagged volume;
- каждый cost scenario имеет один `unknown_lagged_volume` atomic rejection,
  `critical_failure_count=2`, 0 unresolved и `execution_complete=false`;
- primary/doubled/stress mechanical return **−3,17%/−3,90%/−4,43%**;
- primary CAGR **−0,64%**, Sharpe **−0,079**, MDD **−18,79%**, costs
  **4 501,83 RUB**, maximum participation **0,06402%**;
- годы: 2021 **+1,68%**, 2022 **−1,27%**, 2023 **+0,79%**,
  2024 **+2,03%**, 2025 **−6,21%**;
- все 87 input/source/temporal/runtime checks true; все 17 declared run artifacts
  повторно сверены по bytes/SHA, цены/returns/targets/PnL 2026 не читались.

Verdict `NO_GO`: signal не проходит return gates даже механически, а incomplete
execution дополнительно запрещает promotion. Same-history sign/indicator/threshold/oil-
priority/risk/expiry tuning и blend с V12 закрыты.

Новый target-free CBR Business Climate Index source собран без market outcomes: 44
release-specific страницы и 44 PDF за `2022-05..2025-12`, processed SHA `b312f4e5...`,
manifest SHA `99ad128b...`. Сохранены сводный BCI, текущие оценки и ожидания; 90/90 raw
responses повторно прошли byte/SHA audit. Availability использует конец более поздней из
publication/last-update dates, а same-time collision оставляет более новый release month.
Sealed V22 direct-delta уже завершён положительным, но слабым `NO_GO`; источник остаётся
development-only и требует forward snapshots для независимого подтверждения.

## V20 Minfin OFZ demand strength — валидный отрицательный результат

V20 был запечатан и pushed commit `4e52378` до первого чтения RI/MIX/SI outcomes.

- config SHA:
  `788fadbd9c499483c560488a5a3d9d2e95f7e95496e5736ed4465eca889341ed`;
- metrics SHA:
  `cbfa0c8803e631697400813d3fb4ba8a2ba2eda00a38cc5114dd652472d33d78`;
- canonical run:
  `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/`;
- 283 successful ОФЗ-ПД rows агрегированы в 179 auction days: 13 causal warmup и
  166 scored; 82 positive, 76 negative и 8 zero scores;
- 29 expiry-to-zero states и 10 roll decisions; 504/504 nonzero execution dependencies
  complete;
- primary/doubled/stress total return **−5,35%/−5,49%/−5,44%**;
- primary CAGR **−1,09%**, Sharpe **−0,631**, MDD **−6,19%**, costs
  **1 409,28 RUB**, maximum participation **0,01358%**;
- годы: 2021 **−0,01%**, 2022 **−3,95%**, 2023 **−0,29%**,
  2024 **+0,78%**, 2025 **−1,93%**;
- все 86 input/temporal/runtime checks true; все три ledger complete,
  0 rejected/critical/unresolved.

Последняя source publication — `2025-12-24`; последняя mapped market session —
`2025-12-30`. Ни price/return/target/PnL 2026 не читались. Прямой prior-rank score
bid-to-cover плюс placed volume закрыт. Signs, extreme-score threshold, rank window,
expiry и event kinds нельзя выбирать по увиденному результату.

## V19 CBR Minfin FX persistence — валидный отрицательный результат

V19 был запечатан и pushed commit `0558e7e` до первого чтения SI outcomes.

- config SHA:
  `1340ffacae93b514fe4605262d8946a6a87cbc4619c1748b48ac45b9a9b19946`;
- metrics SHA:
  `dff0016e3501136714f66b3237dfb66f37449bde69c77ab489efdc777446b08d`;
- canonical run:
  `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/`;
- 1 235 mapped source decisions, одна same-session collision и два records без будущей
  active session; 937/937 nonzero execution dependencies complete;
- primary/doubled/stress total return **−0,03%/−0,24%/−0,57%**;
- primary CAGR **−0,006%**, Sharpe **0,050**, MDD **−30,76%**, costs
  **4 154,95 RUB**, maximum participation **0,01155%**;
- годы: 2021 **−4,65%**, 2022 **+3,49%**, 2023 **−20,13%**,
  2024 **−5,32%**, 2025 **+33,97%**;
- все три ledger complete, 0 rejected/critical/unresolved.

Последние source publications доходят до `2025-12-31`, но decisions, targets, positions
и PnL заканчиваются `2025-12-30`; outcomes 2026 не читались. Прямой persistence-знак
закрыт. Magnitude/change-day selection, smoothing, иной lag или инверсия после просмотра
результата запрещены как data mining.

## V18 CBR liquidity forecast — валидный отрицательный результат

V18 был запечатан и pushed commit `0c3fc80` до первого чтения SI outcomes.

- config SHA:
  `ee2d7fd77037eccf15237f827ed357e0b8608c96fae1f393e8a3478945b8b10a`;
- metrics SHA:
  `b67423433a03ebcd4cdebac5df33754e62be94b4719a430f1642596c357e9f28`;
- canonical run:
  `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/`;
- 240 OOS release decisions, 10 expiry-to-zero и 18 roll decisions; 257/257 nonzero
  execution dependencies complete;
- primary/doubled/stress total return **−41,95%/−44,59%/−44,49%**;
- primary costs **8 289,95 RUB**, maximum participation **0,01155%**;
- годы: 2021 **−1,77%**, 2022 **−46,94%**, 2023 **−9,47%**,
  2024 **−1,33%**, 2025 **+24,67%**;
- все три ledger complete, 0 rejected/critical/unresolved; один factual halt carried.

Последний forecast interval заканчивается в январе 2026, но market decisions, targets,
positions и PnL заканчиваются `2025-12-30`; защищённые outcomes 2026 не читались. Прямой
знак government-account forecast закрыт. Простая инверсия или отбор extreme weeks после
просмотра результата запрещены как data mining.

## V17 EIA physical balance — валидный отрицательный результат

V17 был запечатан и pushed commit `a8b8407` до первого чтения BR outcomes.

- config SHA:
  `1d8eee3f7aa99aff5798aeaf6a946d110cfa4e4b451b57580b1d9ef6cd17b37a`;
- metrics SHA:
  `fbd3b74e44ce91d484bb9e1594130ee2dd4d6589c0e50cabb34f3345b898f255`;
- canonical run: `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/`;
- 245 OOS release decisions и 49 roll decisions; 1 176 target rows, 294/294 nonzero
  execution dependencies complete;
- primary/doubled/stress total return **−33,14%/−39,97%/−42,68%**;
- primary costs **82 842,43 RUB**, maximum participation **0,1383%**;
- годы: 2021 **+7,80%**, 2022 **−31,73%**, 2023 **+59,58%**,
  2024 **−19,83%**, 2025 **−28,99%**;
- все три ledger complete, 0 rejected/critical/unresolved; один factual halt carried.

Source полезен как чистый PIT dataset, но именно raw-change delayed weekly direction
закрыт. Допустимое возвращение к EIA требует новой информации — прежде всего исторического
point-in-time analyst consensus для настоящего surprise — либо нового forward периода.

## V16 FUTOI governor — INVALID из-за недоказанной доступности

V16 был честно запечатан до PnL, но последующий более глубокий source-аудит обнаружил
нарушение общего PIT-контракта. Это делает run недействительным независимо от красивых
метрик или pre-outcome seal.

- config SHA:
  `d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070`;
- metrics SHA:
  `8246e155843dad0928c1ae283b9023622fc19fe9ed11ca956753bfbe92c6d73f`;
- canonical run:
  `runs/v16_futoi_governor_20260831T220539Z_d0461775/`;
- 1 044 weekly asset states: только 112 имели recorded `available_at` не позже decision;
  932 были недоступны, включая все 832 states 2021–2024;
- первый допустимый state появляется только `2025-06-27`, последний недопустимый —
  `2025-06-20`; исторические строки 2020–2024 были republished 21.06.2025;
- 1 040/1 040 nonzero target dependencies, 730 filled legs, 0 rejected/critical/
  unresolved, шесть текущих attempts причинно отменены из-за отсутствия factual open;
- primary futures-only CAGR **20,1280%**; collateral **201 950,38 RUB**; combined CAGR
  **22,0082%**, Sharpe **0,9678**, MDD **−31,3402%**;
- doubled/stress combined CAGR **21,8474%/21,0971%**, оба complete и положительны;
- годы: 2021 **+39,1146%**, 2022 **+70,4325%**, 2023 **+15,2018%**,
  2024 **+9,0275%**, 2025 **−9,2234%**;
- все 23 artifact hashes и 19 parquet row counts совпали; 40 временных полей имеют
  максимум `2025-12-30`.

Числа выше сохранены только как forensic record. Их нельзя сравнивать с V12/V15 как
causal performance и нельзя использовать для выбора новой стратегии. Причина ошибки:
`build_futoi_governor` требовал `source_date < decision_date`, но не требовал
`available_at <= decision_at`; warmup 2020 также не был доказанно доступен к началу OOS.
Canonical directory и metrics SHA не изменяются, а текущий entry point V16 теперь
выбрасывает `RuntimeError` с причиной invalidation до чтения PnL.

## V15 capital efficiency — доходность найдена, устойчивость ещё нет

V15 был запечатан commit `f68226f`; отдельный fix `85b1074` только разрешил уже
объявленный 2x target в mapper/ledger и был отправлен до первого расчёта PnL.

- config SHA:
  `8cbcf30712684607e16cde27a9bca333e4740bd3bdb119646890d0b28d00a50d`;
- metrics SHA:
  `3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4`;
- primary futures-only CAGR **19,9802%**; collateral **142 698,54 RUB**; combined CAGR
  **21,3272%**, Sharpe **0,8826**, MDD **−34,4823%**;
- doubled/stress combined CAGR **20,5038%/20,4453%**, оба total return положительны;
- четыре из пяти лет положительны, но 2025 **−15,2535%**;
- 1 040/1 040 targets и 1 271/1 271 RUONIA intervals покрыты;
- 12 rejected legs и 8 critical events относятся к factual halt RI/MIX в марте 2022;
  unresolved на конце нет, но `execution_complete=false`.

Это первый прямой результат выше 20% CAGR, однако не решение задачи стабильного дохода:
25% MDD gate превышен почти на 9,5 п.п., а неполное исполнение запрещает считать метрики
promotion-valid. Не создавать V15.1 с подстройкой leverage/haircut/buffer по уже
увиденному результату.

## V14 RVI governor — risk control работает, доходность нет

V14 был запечатан commit `677c713` до PnL и выполнил один вариант без threshold search:

- config SHA:
  `9f680ebfcfcd6aae98a1e39eb44b9c51b59aa73067edc32e7a558399a8a29a53`;
- metrics SHA:
  `1a236f0698ab906532e5381d8ecbc5c7b896c742533ad9b1e95df1096c8aa3ea`;
- 259/261 OOS weekly decisions имели точный previous-session RVI, 219 downscaled;
- primary return **+25,62%** за пять лет, CAGR **4,67%**, Sharpe **0,734**,
  MDD **−9,40%**;
- doubled/stress return **+25,51%/+24,68%**;
- 1 040/1 040 nonzero targets покрыты, 0 rejected/critical/unresolved.

RVI снизил MDD V12 на 4,75 п.п., но не улучшил Sharpe и опустил CAGR ниже sealed 5%.
Не создавать V14.1 с новым порогом по уже увиденной истории.

## V13 carry confirmation — доход выше, устойчивость хуже

V13 был запечатан commit `2c51cef` до просмотра outcome. Он оставил V12 portfolio и
execution byte-identical, но допускал trend только при совпадении знака с одновременной
front/next кривой, доказанно известной на close решения.

- config SHA:
  `94841c0baa1f4c7e0f88302467dfde3bc8104b2e662382b9224bbaf9b75f07ef`;
- metrics SHA:
  `783b0a7ec9dd613df9b7f38c3070eb33ee980358a69ec4a11f4e411e079a6039`;
- 2 681 OOS confirmed и 1 363 observed-not-confirmed asset rows;
- 841/841 nonzero target dependencies полны; 431 primary filled legs, 0 rejected,
  0 critical и 0 unresolved;
- годы: 2021 **+21,48%**, 2022 **+20,08%**, 2023 **+5,19%**,
  2024 **+1,22%**, 2025 **−1,84%**;
- doubled/stress total return **+51,85%/+51,62%**.

По сравнению с V12 CAGR выше на 1,07 п.п. и worst year лучше на 0,79 п.п., но MDD хуже
на 6,53 п.п., Sharpe ниже на 0,054 и costs выше на 4 049,64 RUB. Это не улучшение
стабильности. Не создавать V13.1 с carry threshold/blend на уже просмотренной истории.

## V12 core-four correlation trend — новый исполнимый lead

V12 использует только BR/MIX/RI/SI, для которых уже существовал единый frozen
conservative spec proxy. После закрытия каждой недели он строит общий multi-horizon
trend score 21/63/126/252 сессий, затем учитывает 60-session covariance всех четырёх
рынков, target volatility 20%, gross `<= 1` и пять недельных turnover sleeves. Сигнал
исполняется только на следующем factual open; roll получает отдельное причинное решение.

- sealed protocol SHA:
  `0b1a79d5c09cf40330886ebfba84bb9a7a8a84973301d59627200050e61b3e53`;
- 261 weekly decisions, 53 дополнительных roll decisions, 1 256 полных target rows;
- 1 040 ненулевых targets, coverage **1 040/1 040**;
- 1 272 ledger sessions, 429 filled legs, 0 rejected legs, 0 critical failures,
  0 unresolved halts;
- primary costs **13 387,28 RUB**, maximum participation **0,1129%** при cap 1%,
  maximum gross leverage **0,9544**, maximum 2x modeled-margin ratio **0,4688**;
- primary годы: 2021 **+17,53%**, 2022 **+14,01%**, 2023 **+7,78%**,
  2024 **+3,19%**, 2025 **−2,63%**;
- terminal positions carried; отдельный one-way exit reserve **173,40 RUB** оставляет
  total return **45,0941%**.

Sealed gate полностью пройден, но результат adaptive: V5–V11 и широкий structural lead
уже были известны до V12. На этой же истории запрещено менять horizons, sleeves, universe,
vol target или costs. Historical exchange specs, broker fees, spread/queue и intraday
margin остаются приблизительными, поэтому live promotion запрещён.

## V10/V11 triangular relative value — почему закрыт

V10 фиксировал residual `log(RI) − log(MIX) + log(SI)`, prior-72 z-score, вход при
`|z| >= 2`, take-profit внутри `0,5σ`, дальний stop `4σ`, максимум 18 баров и три
integer-contract legs. Заполнение было намеренно неблагоприятным: buy по high, sell по
low следующего точного 10m bucket; gross `<= 0,9`, участие `<= 1%`.

- 169 071 общих баров, из них 109 143 OOS и 31 953 допустимых signal bars;
- 4 завершённые корзины, все убыточны; partial ordinary return **−2,5806%**,
  Sharpe **−0,6344**, costs **697,15 RUB**;
- первая unresolved заявка: `2022-03-29 08:00 UTC`, недостаточный entry-window volume;
- full-period CAGR/Sharpe недействительны: ledger остановлен, а не продолжен с
  игнорированием неудобной заявки.

V11 не менял alpha/пороги и проверил open следующего bucket с one-tick cost, sizing по
0,25% известного signal volume и фактическим cap 1%. Это adaptive same-period diagnostic,
не независимое подтверждение.

- 10 завершённых корзин: partial return **−0,6768%**, Sharpe **−0,9736**, profit factor
  **0,1189**, win rate **20%**, costs **1 899,99 RUB**;
- 12 exit-capacity retries; `2022-06-06 11:10 UTC` выход не вместился в шесть следующих
  bucket и стал unresolved;
- verdict снова `NO_GO_UNRESOLVED_EXECUTION`.

Не создавать V12, который меняет только z-threshold, holding period, stop или liquidity
cap на той же истории. Возвращаться к relative value имеет смысл лишь с новой информацией:
PIT spot/index basket, funding/dividends, calendar-spread legs или order-book execution.

## Structural: почему ещё нет GO

Канонический proxy использовал 22 candidate roots, в среднем 17,71 допустимых активов и
1 259 development-сессий. Три лидера:

| Strategy | CAGR 5 bps | Sharpe | MDD | CAGR 10 bps |
|---|---:|---:|---:|---:|
| `risk_adjusted_momentum` | 6,7745% | 0,7840 | −15,1293% | 5,3463% |
| `tsmom_multi` | 6,3111% | 0,7943 | −14,2108% | 4,7127% |
| `tsmom_6m` | 5,3410% | 0,8091 | −11,9518% | 4,1414% |

Robustness-аудит не даёт независимого подтверждения:

- PBO-style probability выбранного кандидата оказаться ниже медианы: **69,84%**;
- вероятность selected OOS Sharpe `<= 0`: **22,22%**;
- корреляция `tsmom_multi`/RAM: **0,9641**;
- семь silent-missing proxy sessions: `2024-06-17…2024-06-21` и
  `2025-11-27…2025-11-28`;
- сигнал использует official close, а proxy получает следующий close-to-close return,
  поэтому same-close предположение само по себе неисполнимо.

Sealed execution study имеет verdict `NO_GO`. Для RAM ordinary расчёт остановился после
308 из 1 259 сессий: первая unresolved дата `2022-03-18`, причина
`GBPU:GUH2:missing_settle_or_contract`. Historical specs/fees/IM отсутствуют для 21
эффективного root; полная registry есть только для BR/MIX/RTS/Si. Дневной `OPEN` не
доказывает spread, очередь, partial fills или intraday tradability.

## Очередь работ

### P0 — новый market-neutral source family

1. Push source-only calendar-spread seal SHA `72687539...` до bulk history.
2. Один раз собрать immutable official MOEX bundle за `2021-01-01..2025-12-31`:
   отдельно ISS settlement/OI и public-archive trade/bid/ask, затем выполнить exact raw
   replay, hashes, schema, coverage и protected-date audit.
3. Только после успешного source manifest отдельно запечатать economic target. Первый
   кандидат — carry/convergence listed spread с market-neutral sizing, factual archive
   liquidity, next-session execution и 1x/2x/stress costs. Никаких returns, thresholds
   или PnL до этого seal; development 2021–2025 не называть независимым holdout.
4. Historical bid/ask архива остаётся EOD field, а не order-time quote. Для live evidence
   всё равно нужны licensed order book/trade log, historical fees, IM и broker rules.

### P0 — независимо подтвердить V27, не подгоняя его

1. Заморозить byte-identical V27 целиком: V12 signal, V25 STLFSI4 zero/age, key-rate
   boundary `>=20%`/7-day age, максимум 2x, RUONIA haircut/buffer, universe, capacity и
   execution costs. Не выбирать partial scale или новый threshold по 2021–2025.
2. Новый unseen market period получен: official MOEX 2012–2017 source V3 содержит
   30 059 daily rows по 155 contracts; D3 причинно построил common calendar/roll/spec
   без synthetic gap return. Raw replay, hashes и границы проверены.
3. D1 выявил serial-contract failure; D2 остановился без output на неверном ожидании
   непрерывного SI roll; D3 с exact flat/sleep semantics успешно собран и проверен.
   S1 transport failed без output; S2 failed parse без output; S3 успешно собран и
   replayed. V28 завершён с отрицательным и execution-invalid outcome; не повторять.
   V29 risk-first correction выполнен один раз после pre-outcome push. Execution стал
   полным, но CAGR `3,71–4,61%`, MDD `47,38–48,68%` и только 1/5 positive years дают
   `FAIL_POST_V28_20`. V29 не повторять и не tune-ить на 2013–2017. Следующий PnL —
   только новая независимая информация/target family либо forward collection; historical
   specs/fees/IM всё ещё proxy, licensed MOEX/broker archive обязателен для live evidence.
4. Провести заранее запечатанный paper/shadow forward test без реального капитала;
   отдельно мониторить key-rate/STLFSI availability, отрицательные недели, drawdown,
   capacity cancels и деградацию trend edge.
5. Только после независимого подтверждения проектировать отдельный live-admission
   protocol с operational risk и аварийным отключением.
6. V27-R1 уже выполнен ровно один раз: 180 000 bootstrap paths, 3 063 rolling windows,
   49/49 checks. Его resampling frequency не называть вероятностью будущей прибыли и не
   менять V27 по результатам.

### P1 — новая информация для intraday timing и устойчивости

1. Считать V16 `INVALID`: 932/1 044 FUTOI states нарушают `available_at <= decision_at`.
   Не использовать его return, diagnostics или thresholds для дальнейшего отбора.
2. Полный официальный FUTOI 5m уже сохранён как current-vintage/forward source:
   2 015 624 строки, 5 896 raw records, все hashes совпали. Для каждой строки есть
   official `SYSTIME`, actual retrieval и `conservative_available_at`; история 2021–2025
   при таком contract не backtest-admissible.
3. Для исторического continuous timing нужен лицензированный archival feed с original
   publication vintages либо собственный forward collector. Без него FUTOI-гипотеза
   sleeping, даже если анонимный endpoint технически возвращает данные.
4. EIA v2 source audit завершён, но sealed V17 raw-change composite убыточен и закрыт.
   Не инвертировать его signs и не сокращать lag; искать point-in-time consensus surprise
   либо принципиально другой независимый source family.
5. Новый CBR release-keyed liquidity-forecast bundle готов: 458 releases, 537 requests,
   12 недель без record, maximum release gap 16 дней, processed SHA `a8faab04...`.
   V18 direct SI test выполнен после pre-outcome push и дал `NO_GO`: CAGR −10,31%,
   Sharpe −0,51, MDD −55,73%. Не инвертировать знак и не перебирать строки/пороги;
   следующий тест должен использовать новую заранее обоснованную информацию.
6. RVI threshold/blend на 2021–2025 также запрещён sealed V14; совпадение с invalid V16
   drawdown остаётся только post-outcome наблюдением.
7. CBR daily-factors source собран: 1 238 admitted rows, processed SHA `88885d36...`,
   manifest SHA `f1701ec3...`. V19 выполнен после pre-outcome push и дал `NO_GO`:
   total return −0,03%, Sharpe 0,05, MDD −30,76%. Не выбирать magnitude/change days,
   smoothing, lag, blend или sign flip по увиденному результату.
8. Официальный Minfin OFZ source готов: 410 events, 364 primary results, 283 ОФЗ-ПД,
   processed SHA `a8c5c024...`, manifest SHA `c6fcf390...`; все карточки классифицированы
   и primary fields полны. Availability консервативно равна концу publication day.
9. V20 prior-only demand-strength test завершён `NO_GO`: total return −5,35%,
   Sharpe −0,63, MDD −6,19%, 504/504 dependencies complete. Не менять rank window,
   basket signs, expiry, threshold или включённые event kinds по этому outcome.
10. CBR macro-survey bundle готов: 11 787 records, 37 months, 17 indicators, processed
    SHA `a139ead8...`, manifest SHA `faae8927...`. V21 завершён `NO_GO`: mechanical
    total return −3,17%, Sharpe −0,08, MDD −18,79%, 200/202 coverage и 2 critical.
    Direct revisions family закрыт; не менять signs/indicators/oil priority/thresholds,
    risk/expiry или blend по этому outcome. December 2025 остаётся исключён.
11. CBR Business Climate Index bundle готов: 44 releases, 90 raw responses, processed
    SHA `b312f4e5...`, manifest SHA `99ad128b...`; 21 positive, 18 negative и 4 zero
    sequential changes. V22 direct regime завершён `NO_GO`: +13,37%, Sharpe 0,36,
    MDD −8,86%, complete execution. Не подбирать threshold/components/sign/risk/expiry;
    следующий PnL допускается только с новой независимой информацией или forward period.
12. CBR household inflation/sentiment bundle готов: 48 releases, 146 raw responses,
    processed SHA `70711272...`, manifest SHA `b132a45e...`; 16 risk-on, 17 risk-off и
    14 mixed source confirmations после warmup до collision handling. V23 завершён
    `NO_GO`: −5,35%, Sharpe −0,16, MDD −13,62%, downstream ledger complete, но 3
    confirmed states fail-closed не mapped. Same-history household tuning закрыт.
13. FRED/Cboe VIX/VIX3M V2 готов: 2 087 grid rows, 2 011 complete pairs, processed SHA
    `6ffe7daa...`, manifest SHA `0aecc29fd...`; 2 010 pairs causal до границы 2026,
    включая 174 backwardation. V24 был запечатан/pushed до outcome и завершён `NO_GO`:
    +38,89%, Sharpe 0,739, MDD −14,28%, complete execution, но оба stability gates хуже
    V12 и costs выше. Same-history VIX boundary/freshness/scaling tuning закрыт.
14. Source-only screen отверг NFCI/ANFCI: 0 above-zero OOS weeks означают тождественный
    V12. STLFSI4 bundle готов: 417 weekly rows, 416 causal до 2026, processed SHA
    `4937b686...`, manifest SHA `1a992f64...`, strict raw replay exact. V25 был sealed и
    pushed до outcome; +49,07%, Sharpe 0,818 и worst year лучше V12, execution complete,
    но MDD хуже на 0,0736 п.п., поэтому strict `NO_GO`. Следующий шаг — только новая
    forward/PIT validation; same-history STLFSI tuning закрыт.
15. V26 доказал capital efficiency: all-scenario CAGR `23,03–24,17%`, 0 critical, но
    MDD `33,57–33,99%`, strict `NO_GO`. V27 добавил raw-replayed official key-rate
    `>=20%` cash state и прошёл все gates: primary/stress CAGR `28,38%/27,36%`, MDD
    `20,71%/21,05%`, Sharpe `1,212/1,184`. Это adaptive same-history lead; следующий
    PnL допустим только в отдельной unseen/PIT validation, не через tuning V27.

### P2 — разблокировать широкий structural exact execution

1. Получить лицензированный point-in-time архив historical contract specifications,
   multipliers/ticks, exchange и broker fees, initial margin и settlement rules для 21
   фактически торгуемого root.
2. Разобрать `GBPU:GUH2` на `2022-03-18` и все rejected/partial roll cases без
   zero-imputation или ручного подглядывания в будущие данные.
3. Устранить либо честно исключить семь silent-missing sessions, сохранив причинность.
4. Без изменения сигналов повторно проверить только `tsmom_6m`, `tsmom_multi` и
   `risk_adjusted_momentum`.
5. Требовать 1 259/1 259 разрешённых сессий и положительный результат при 5/10/20 bps,
   delayed execution, integer contracts, capacity и gross cap.

### P3 — наблюдать sparse event lead

Не оптимизировать key-rate sleeve на десяти сделках. Его можно расширять только новой
историей или независимыми заранее объявленными event families. Сохранять отдельный
baseline: neural timing не улучшил входы и полностью abstained.

### P4 — корпоративная отчётность

Контур sleeping до появления корпуса с подтверждёнными правами, точным publication time,
revision chain и page evidence. Локальная LLM извлекает факты, но не видит рыночные labels.

## Что не продолжать без новой независимой идеи

- threshold-only `intraday_timing_v3`;
- повторный 30-stock attention/graph на том же target;
- новые варианты corridor на тех же OOS после просмотра результатов;
- новые пороги/стопы/ослабление capacity для RI/MIX/SI triangle на тех же OOS;
- long-only momentum overlays на той же таблице без независимого holdout;
- V27 key-rate threshold/age/partial-scale variants на 2021–2025;
- V8 PnL до authoritative admission certificate и полного источникового аудита.

## Канонические внешние артефакты

Пути ниже относительны к `D:\Projects\trading_lab_data`:

- `runs/futures_v9_structural/structural_c86d4852729d4c8a/results.json`
- `runs/futures_v9_structural_robustness/robustness_870183b62323f8bb/audit.json`
- `runs/futures_v9_structural_execution/execution_8a934dfae72c769c/results.json`
- `runs/event_alpha_v1/development_20260818T155959Z_91f61abe/report.md`
- `runs/futures-v9-corridor-development-v1/metrics.json`
- `runs/futures_v9_intraday_timing_v2_full_20260818T164623Z/report.md`
- `runs/futures_v9_event_timing_hybrid_development_20260818T170400Z_92e98a72/report.md`
- `runs/market_graph_v1_20260818T164732Z/metrics.json`
- `runs/market_graph_v2_long_only_20260819T074638Z/metrics.json`
- `runs/v10_triangular_20260831T171000Z_4ff5c4cb/metrics.json`
- `runs/v11_buffered_open_20260831T171200Z_584bf289/metrics.json`
- `runs/v12_core4_trend_20260831T182210Z_0b1a79d5/metrics.json`
- `runs/v13_trend_carry_20260831T190300Z_94841c0b/metrics.json`
- `runs/v14_rvi_governor_20260831T201919Z_9f680ebf/metrics.json`
- `runs/v15_levered_ruonia_20260831T205040Z_8cbcf307/metrics.json`
- `runs/v16_futoi_governor_20260831T220539Z_d0461775/metrics.json`
- `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/metrics.json`
- `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/metrics.json`
- `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/metrics.json`
- `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/metrics.json`
- `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/metrics.json`
- `runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/metrics.json`
- `runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/metrics.json`
- `runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/metrics.json`
- `runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/metrics.json`
- `runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/metrics.json`
- `runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/metrics.json`
- `runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/metrics.json`
- `runs/v29_risk_first_roll_20260901T085436Z_d92f8cf2/metrics.json`

При переносе или восстановлении данных сначала сверяй hashes из
[DATA_AND_INTEGRITY.md](DATA_AND_INTEGRITY.md), затем открывай артефакт.

## Состояние миграции репозитория

Канонические код и документация находятся в `D:\Projects\trading_lab`; canonical `data`,
`runs` и модели остаются вне Git в `D:\Projects\trading_lab_data`. Любая сохранившаяся
копия под `D:\Projects\Trading` является только recovery source, а не рабочим репозиторием.
Проверка 2026-08-31:

- в старом source/config/test дереве не было old-only файлов: 274 файла совпали
  побайтово, 10 имеют ожидаемые migration-изменения в актуальной копии, 8 добавлены уже
  после переноса;
- все 1 403 файла `data` и 1 598 файлов `runs` совпали с external storage по
  относительному пути, размеру и SHA-256; отдельными оставались только `.venv` и кеши;
- восстановлены ошибочно исключённые общим `.gitignore` Python-пакеты
  `market_lab.data` и `market_lab.models`; root external paths теперь anchored как
  `/data`, `/runs`, `/models`, `/checkpoints`;
- полный CPU suite: **642 passed, 7 skipped, 2 failed**;
- два failure относятся только к sealed V8 `context_run`: его старый anti-symlink guard
  намеренно не принимает external NTFS junction. Старый byte-sealed код нельзя менять
  задним числом; нужен новый migration-compatible loader/code identity;
- migration/config/offline-CLI slice: **5 passed**; тестовый CLI теперь пишет только в
  pytest temp, а не в canonical external `runs`;
- Ruff для изменённых config/migration файлов: clean; полный legacy tree имеет 58
  существующих замечаний (27 `E501`, 27 `F401`, 2 `I001`, 2 `UP035`), которые нельзя
  массово auto-fix без проверки code seals;
- encoding tests проходят. Для неизменяемых identity-pinned V9–V11 файлов без BOM задан
  точный allowlist; новые незапечатанные text/code files обязаны иметь UTF-8 BOM.

Git-инвентарь содержит только код/config/tests/docs и маленькие fixtures: ни `data/`, ни
`runs/`, ни `models/`, ни checkpoints/Parquet/NPZ/PT в commit не входят.
