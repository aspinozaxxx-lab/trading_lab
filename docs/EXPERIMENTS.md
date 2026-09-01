# Реестр экспериментов

Этот файл фиксирует научную память проекта. `Canonical` означает выбранный для аудита
неизменяемый артефакт, а не разрешение на live trading. Все внешние run paths относительны
к `D:\Projects\trading_lab_data`.

## V27: official CBR key-rate extreme governor — GO to unseen validation

- Протокол:
  [`configs/futures_v27_key_rate_extreme_governor.yaml`](../configs/futures_v27_key_rate_extreme_governor.yaml)
- Config SHA-256:
  `7a9a44cf7b09c7820a514b2706e332744a3b30ced8b7d3d4c8bdf7448a3194fe`.
- Parent V26 immutable: protocol SHA `2b085890...`, metrics SHA `b4149969...`; maximum
  2x, RUONIA haircut 50%, operational buffer 10%, `cancel_and_clip`, margin/gross/
  participation и cost scenarios не менялись.
- Один новый governor: после V25 STLFSI4 latest official CBR key rate с
  `available_at <= decision_at` и age `<=7` дней. Rate `<20%` пропускает V25; rate
  `>=20%`, missing/stale или уже cash STLFSI4 дают global cash до 2x multiplier.
- Порог 20% — заранее объявленная круглая extreme monetary boundary. Levels below 20,
  changes, percentiles, hysteresis, partial scale и asset exceptions не тестировались.
- Raw SOAP source `121958` bytes, SHA `06da1497...`, exact parse восстанавливает 2 015
  filtered key-rate rows `2018-01-09..2025-12-30`; same-day использование запрещено,
  `available_at` консервативно равно следующей календарной полуночи Moscow.
- Source-only seal: all `418 = 309 pass + 68 STLFSI cash + 40 key-rate cash + 1
  missing`; OOS `261 = 197 + 24 + 40 + 0`.
- Pre-outcome tests `43 passed`; config/code/tests committed и pushed как `aca0380` до
  первого V27 PnL.
- Promotion требовал во всех primary/doubled/stress CAGR `>=20%`, MDD `<=30%`, primary
  Sharpe/worst-year не хуже V26, 4/5 positive years, complete execution и no breaches.

- Canonical run:
  `runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/`.
- Metrics SHA-256:
  `5fc1f271acf8f9df711006bca24e6bc40425bf097c21e989eb0296baeb0e7654`.

Все 115 checks true; 27 declared artifacts плюс metrics/identity прошли bytes/SHA/row
audit. Execution complete: 828/828 nonzero dependencies, primary 616 filled order legs,
0 rejected/critical/unresolved, six causal no-open target cancellations and no gross/
margin/participation breach.

| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +248,6127% | +28,3752% | 1,2119 | −20,7138% | −1,4772% | 44 141,07 | yes |
| doubled | +238,4811% | +27,6201% | 1,1918 | −20,9410% | −2,3294% | 86 607,24 | yes |
| stress | +235,1022% | +27,3643% | 1,1839 | −21,0511% | −2,6979% | 128 784,62 | yes |

Primary годы: 2021 **+40,34%**, 2022 **+72,45%**, 2023 **+30,68%**,
2024 **+11,87%**, 2025 **−1,48%**. Collateral income primary 366 595,47 RUB.
Против V26 primary CAGR выше на **4,21 п.п.**, Sharpe на **0,2356**, MDD ниже на
**12,85 п.п.**, worst year лучше на **10,79 п.п.**, costs ниже на 11 156,59 RUB.

Verdict: `GO_TO_NEW_UNSEEN_VALIDATION`; все predeclared conditions true. Это не live
promotion: V27 выбран после V26 на том же OOS, key-rate publication time заменён
консервативным next-day proxy, STLFSI4 current-vintage и specs/fees/margin не broker-
exact. Независимое подтверждение и paper/shadow forward обязательны. Same-history
20% boundary/age/scale tuning запрещён.

## V26: 2x V25 + RUONIA + capacity admission — NO-GO by MDD

- Протокол:
  [`configs/futures_v26_stlfsi_levered_ruonia_capacity.yaml`](../configs/futures_v26_stlfsi_levered_ruonia_capacity.yaml)
- Config SHA-256:
  `2b08589013f3b3387002830cad7878ef0fffc5dc808b8165fc004e724abf4c1b`.
- Frozen V25 weekly signal/governor удваивается ровно один раз. V15 collateral formula
  byte-reused; core ledger использует asset-atomic `cancel_and_clip`, known lagged volume
  и factual open до submission.
- До PnL config/code/tests были pushed commit `3b9ce95`; pre-execution mapper остановил
  первый вызов до market ledger из-за >1 base-normalizer. Routing был исправлен до PnL
  и pushed commit `5515321`: mapping выполняется на admissible V25 weights, затем 2x.
- Promotion требовал CAGR `>=20%` и MDD `<=30%` во всех cost scenarios, Sharpe не ниже
  V25, worst year `>=−15%`, complete execution и no breaches.

- Canonical run:
  `runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/`.
- Metrics SHA-256:
  `b4149969696e23a29a06b58085510d9f8c9f2bbf584ca0d2aaa883801493567d`.

Все 99 checks true; 25 artifacts прошли audit. 1 016/1 016 dependencies complete,
primary 761 filled legs, 0 rejected/critical/unresolved. Capacity policy превратила
проблемные halt targets в шесть explicit no-open cancellations.

| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +195,1384% | +24,1698% | 0,9764 | −33,5661% | −12,2686% | 55 297,66 | yes |
| doubled | +186,2080% | +23,4090% | 0,9565 | −33,9890% | −12,9643% | 108 069,21 | yes |
| stress | +181,7881% | +23,0255% | 0,9458 | −33,9672% | −14,1060% | 160 794,39 | yes |

Verdict `NO_GO`: единственный false condition — all-scenario MDD `<=30%`. Постоянное
плечо, haircut, buffer и capacity нельзя ретюнить на этом outcome. V26 остаётся
immutable capital-efficiency/execution parent V27.

## V25: weekly STLFSI4 stress governor — NO-GO by strict MDD gate

- Протокол:
  [`configs/futures_v25_stlfsi_stress_governor.yaml`](../configs/futures_v25_stlfsi_stress_governor.yaml)
- Config SHA-256:
  `dd8b60513de7261aa051c12bd5598fffd880c90c98489a5becac820b7597416b`.
- Source collector/bundle был committed/pushed отдельно как `cdfe674`: 417 weekly rows,
  processed SHA `4937b686...`, manifest SHA `1a992f64...`; one bounded raw CSV точно
  воспроизводит processed frame и не содержит observations 2026.
- Parent неизменяем: frozen V12 signal, weekly portfolio, 20% target volatility, gross
  `<=1`, active-contract next-open execution и три cost scenarios.
- Единственный governor действует только на исходных weekly V12 decisions: последний
  complete STLFSI4 с `available_at <= decision_at` и возрастом `<=14` дней пропускает
  V12 при value `<=0`; value `>0`, missing/incomplete/stale дают global cash. Scale
  только `1` или `0`, asset exceptions отсутствуют.
- Ноль — официальное определение normal financial conditions; 14 дней — два exact
  недельных интервала source cadence. Levels, percentiles, changes, smoothing,
  hysteresis, partial scale, sign inversion и комбинация с V24 запрещены.
- Source/calendar-only seal до PnL: все `2018–2025` — 418 weekly decisions, 349 pass,
  68 stress-cash, 1 missing/stale; OOS `2021–2025` — 261 decisions, `237/24/0`.
- Pre-outcome source/config/semantic/synthetic tests: `11 passed`; implementation,
  protocol и pending-status были committed/pushed как `74c5461` до market/PnL.
- Promotion: CAGR `>=5%`, Sharpe не ниже V12 `0,7624`, MDD не хуже V12 `14,1526%`,
  не менее 4/5 positive years, positive doubled/stress, complete execution и no breaches.

- Canonical run:
  `runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/`.
- Metrics SHA-256:
  `c2518d17b4e945ef921fa8dbaa8bd330645131acddd73fc01a45c44c0aacfa86`.

Все 82 input/raw-replay/source/calendar/runtime checks true; 18 declared artifacts плюс
metrics/identity прошли bytes/SHA/row audit. Execution complete: 1 016/1 016 nonzero
dependencies, primary 438 filled legs, 0 rejected/critical/unresolved и no capacity/
gross/margin breaches. Maximum participation **0,11287%**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +49,0720% | +8,3137% | 0,8177 | −14,2262% | 4/5 | 13 835,17 | yes |
| doubled | +47,1768% | +8,0368% | 0,7932 | −14,4163% | 4/5 | 27 605,96 | yes |
| stress | +46,8571% | +7,9898% | 0,7913 | −14,1659% | 4/5 | 41 154,16 | yes |

Primary годы: 2021 **+17,53%**, 2022 **+14,01%**, 2023 **+12,08%**,
2024 **+1,54%**, 2025 **−2,26%**. Terminal positions carry; primary exit reserve
178,40 RUB оставляет post-reserve return **+49,05%**.

Против V12 V25 улучшил total return на **3,96 п.п.**, CAGR на **0,58 п.п.**, Sharpe на
**0,0553**, worst year на **0,37 п.п.** при costs всего на 447,89 RUB выше. Семь stress
episodes дали 24 cash weeks. Equity V25 ни в одной из 1 272 ledger sessions не была ниже
V12; после первого отличия 2023-03-27 она выше 707 sessions и заканчивает на 39 606 RUB
выше. Но MDD **14,2262%** хуже V12 **14,1526%** на **0,0736 п.п.**: peak/trough dates
совпадают (`2024-11-26 → 2025-03-03`), а V25 имеет более высокие и peak, и trough.

Verdict остаётся `NO_GO`: единственный обязательный MDD gate false, ослаблять его после
outcome нельзя. STLFSI4 — current-vintage Version 4, которая не существовала в точном
виде на всей истории; V25 является сильным adaptive development lead, но не независимой
PIT validation и не live-системой. Same-history threshold/age/state/scaling/combination
tuning запрещён.

## V24: daily Cboe VIX/VIX3M risk governor — NO-GO

- Протокол:
  [`configs/futures_v24_cboe_vix_term_structure_governor.yaml`](../configs/futures_v24_cboe_vix_term_structure_governor.yaml)
- Config SHA-256:
  `f81b5aaa666346fa049b550e5dfc92c24ecf6ef2790a2cb00fb83235f24c064c`.
- Parent неизменяем: frozen V12 signal, weekly portfolio, 20% target volatility, gross
  `<=1`, exact active-contract next-open execution и три cost scenarios.
- Один governor: на каждой factual MOEX decision date последняя строка с
  `available_at <= 23:59:59 Europe/Moscow` допускает frozen V12 weights только при
  complete pair и строгом contango `VIX/VIX3M < 1`. Backwardation, exact flat,
  incomplete/missing и возраст старше четырёх календарных дней переводят все assets в
  cash. Scale только `1` или `0` и никогда не увеличивает V12 risk.
- Четыре дня — заранее наблюдаемый maximum complete-pair gap source bundle, а граница
  `1` — определение term-structure inversion. VIX levels, percentiles, smoothing,
  hysteresis, partial scale и asset exceptions запрещены.
- Source-only/calendar-only seal до OOS PnL: все `2018–2025` — 2 024 decisions,
  1 785 contango pass, 167 backwardation cash, 72 missing/stale cash; OOS `2021–2025` —
  1 270 decisions, 1 170/53/47 соответственно, exact flat 0.
- Canonical V2 source: 2 087 grid rows, 2 011 complete pairs, 76 missing; processed SHA
  `6ffe7daa...`, raw SHA `d11aa637...`. Два bounded raw CSV точно воспроизводят parquet,
  не содержат observations 2026 и консервативно доступны только после Chicago day-end.
- Pre-outcome source/config/semantic/synthetic tests: `11 passed`; implementation,
  protocol и pending-status были committed/pushed как `34023c1` до первого market/PnL.
- Promotion требует CAGR `>=5%`, Sharpe не ниже V12 `0,7624`, MDD не хуже V12
  `14,1526%`, не менее 4/5 положительных лет, positive doubled/stress, complete
  execution и отсутствие breaches. Даже GO разрешит только новую unseen validation.
- Canonical run:
  `runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/`.
- Metrics SHA-256:
  `1da1b995fd432c938f62745abcc71f7e85af5a5d20735b9a98631a41d21d2f98`.

Все 83 input/raw-replay/source/calendar/runtime checks true. Все 18 declared artifacts
плюс metrics/identity существуют и повторно прошли bytes/SHA/row audit; market-derived
timestamps заканчиваются `2025-12-30`. Execution complete во всех сценариях:
3 722/3 722 nonzero next-open dependencies, primary 774 filled legs, 0 rejected,
critical/unresolved, capacity/gross/margin breaches. Maximum participation **0,13643%**,
maximum post-mark gross leverage **0,9443**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +38,8855% | +6,7910% | 0,7394 | −14,2777% | 4/5 | 26 009,44 | yes |
| doubled | +37,1342% | +6,5203% | 0,7163 | −14,4019% | 4/5 | 51 708,38 | yes |
| stress | +33,5409% | +5,9561% | 0,6643 | −15,2709% | 4/5 | 74 152,75 | yes |

Primary годы: 2021 **+16,56%**, 2022 **+8,66%**, 2023 **+7,62%**,
2024 **+10,50%**, 2025 **−7,80%**. Terminal positions carry; conservative primary exit
reserve 173,40 RUB оставляет post-reserve total return **+38,87%**.

Относительно frozen V12 primary: total return ниже на **6,23 п.п.**, CAGR на
**0,94 п.п.**, Sharpe на **0,0231**; MDD хуже на **0,125 п.п.**, worst year хуже на
**5,16 п.п.**, costs выше на **12 622,16 RUB**. Сто cash sessions образовали 67 episodes
и 133 scale transitions; filled legs выросли с 429 до 774. Governor помог 2024, но
ухудшил 2021/2022/2023/2025.

Verdict: `NO_GO`. CAGR, positive-year и cost-stress gates пройдены, но обязательные
Sharpe и MDD improvements над V12 провалены. Это один adaptive same-history stability
test, не независимое подтверждение. После outcome запрещено менять boundary/age,
инвертировать state, добавлять levels/thresholds, smoothing/hysteresis/partial scale или
выбирать asset-specific исключения на 2021–2025.

## V23: CBR household inflation/sentiment confirmation — NO-GO

- Протокол:
  [`configs/futures_v23_cbr_household_confirmation_regime.yaml`](../configs/futures_v23_cbr_household_confirmation_regime.yaml)
- Config SHA-256:
  `2a8a35a898eddae72694bce159282ced6f72230b537613ad224c0d2b6001f2ee`.
- Source был независимо собран и pushed commit `3d18a03` до протокола: 48
  release-specific страниц, PDF и XLSX за `2022-01..2025-12`; processed SHA
  `70711272...`, manifest SHA `b132a45e...`, 146/146 raw responses проходят
  byte/SHA/reparse audit.
- Единственная гипотеза: expected-inflation delta `<0` и sentiment delta `>0` даёт
  risk-on (long RI/MIX, short SI); обратная согласованная пара даёт risk-off; mixed/zero
  всегда cash, BR zero. Observed inflation, magnitudes и thresholds запрещены.
- Source-only seal: 48 releases, 1 warmup, 47 scored (`11/12/12/12`), 16 risk-on,
  17 risk-off, 14 mixed, 99 nonzero asset directions и два expiry states.
- Availability — конец более поздней publication/last-update date. Collision сентября и
  октября 2022 обязан оставить октябрь. Fill — следующий factual active-contract open;
  active legs имеют 1/3 risk budget, prior 60-session volatility и 45-day expiry.
- Promotion gates: complete execution во всех cost scenarios, 0 critical/unresolved,
  CAGR `>=5%`, Sharpe `>=0,75`, MDD `<=20%`, 3/4 positive active years и положительные
  doubled/stress results. Даже GO разрешит только новую unseen validation, не live.
- Pre-outcome source/config/semantic/synthetic tests: `6 passed`; implementation и
  pending-status были pushed commit `4ac40df` до первого market outcome.
- Canonical run:
  `runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/`.
- Metrics SHA-256:
  `33614e391a547a636ed3ef1a2df44653d05669c24495aacb43f73125cbc9b839`.

После первого outcome запрещены sign inversion, single-series selection, thresholds,
trading mixed states, risk/expiry changes и post-hoc blend на тех же 2021–2025 данных.

Все 92 input/source/temporal/runtime checks true, 19/19 run files повторно прошли
bytes/SHA/row audit. Из 47 scored releases было 33 confirmations; одинаковые September/
October 2022 states корректно оставили October. Три confirmed releases `2022-03..05`
fail-closed не получили targets из-за недоступной prior-60-session volatility во время
рыночного разрыва. Поэтому mapped confirmed states — 29/32 после collision; downstream
ledger для сформированных targets полностью исполнен: 111/111 dependencies, 109 filled
legs, 0 rejected/critical/unresolved. Maximum participation **0,03956%**, maximum gross
notional **830 572,84 RUB**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −5,3484% | −1,0935% | −0,1589 | −13,6190% | 1/5 | 2 775,79 | ledger yes |
| doubled | −5,6260% | −1,1515% | −0,1685 | −13,8318% | 1/5 | 5 551,59 | ledger yes |
| stress | −5,9180% | −1,2128% | −0,1787 | −14,0594% | 1/5 | 8 471,18 | ledger yes |

Primary годы: 2021 **0,00%**, 2022 **−3,77%**, 2023 **−2,42%**,
2024 **−1,19%**, 2025 **+2,01%**. Terminal position отсутствует.

Verdict: `NO_GO`. Return, CAGR, Sharpe, active-year и cost-robustness gates провалены;
единственный положительный active year — 2025. Household confirmation family закрыта для
same-history sign/single-series/threshold/mixed-state/risk/expiry/blend tuning.

## V22: CBR printed Business Climate Index regime — NO-GO

- Протокол:
  [`configs/futures_v22_cbr_business_climate_regime.yaml`](../configs/futures_v22_cbr_business_climate_regime.yaml)
- Config SHA-256:
  `97b2aa74416eae4ebbce28d018a460f98ade4993cfb086487d28515976c18fbe`.
- Source был независимо собран и pushed commit `7fee819` до создания протокола: 44
  release-specific страницы и PDF за `2022-05..2025-12`, processed SHA `b312f4e5...`,
  manifest SHA `99ad128b...`, 90/90 raw responses прошли byte/SHA/reparse audit.
- Pre-outcome commit: `eb0891a`; implementation, config, tests и pending-status были
  pushed до первого чтения RI/MIX/SI outcomes.
- Canonical run:
  `runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/`.
- Metrics SHA-256:
  `10d7b0bf1b84d46b7cfe6fac784ba8e279bd22bd277fa76c2c8f51238f274214`.
- Единственный signal — знак последовательного изменения one-decimal composite BCI,
  напечатанного на endpoint страницы конкретного выпуска. Chart exact decimals, текущие
  оценки и ожидания сохранены для аудита, но исключены из V22 signal.
- Улучшение BCI заранее означает long RI/MIX и short SI; ухудшение — симметрично наоборот,
  exact zero — cash. BR всегда zero. Threshold, magnitude scaling, fitting и search нет.
- Source-only seal: 44 releases, 1 warmup, 43 scored (`7/12/12/12`), 21 positive,
  18 negative и 4 zero delta, 117 nonzero asset directions и два expiry states.
- Availability — конец московского дня более поздней из publication/last-update dates.
  Две строки с одинаковым `available_at` `2022-11-24` обязаны оставить November release;
  три prior-month chart endpoints хранятся отдельно от release month.
- Три active legs имеют фиксированный risk budget 1/3, prior 60-session volatility,
  target 20%, floor 10%, gross `<=1`. State живёт до следующего release или 45 дней.
  Fill — только следующий factual active-contract open; ledger portfolio-atomic.
- Promotion требует complete execution во всех cost scenarios, 0 critical/unresolved,
  CAGR `>=5%`, Sharpe `>=0,75`, MDD `<=20%`, 3/4 positive active years и положительный
  doubled/stress result. Даже GO разрешит только новую unseen validation, не live.

Forbidden after outcome: sign inversion, BCI threshold/magnitude tuning, component
selection, exact-decimal use, risk/expiry changes и blend с V12 на этой же истории.

Все 91 input/source/temporal/runtime checks true. Из 43 scored releases получено 43
mapped states; October 2022 корректно superseded November при одинаковом availability,
terminal expiry 2026 остался `no_future_active_decision_session`. Добавлено 13 causal
roll decisions, 224 target rows и 153 nonzero dependencies; coverage **153/153**.
Все три ledger complete, 147 filled legs, 0 rejected, 0 critical/unresolved. Maximum
participation **0,12048%**, maximum gross notional **938 731,05 RUB**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +13,3661% | 2,5411% | 0,3569 | −8,8570% | 2/5 | 4 873,13 | yes |
| doubled | +12,8788% | 2,4528% | 0,3454 | −8,9610% | 2/5 | 9 746,26 | yes |
| stress | +11,9558% | 2,2846% | 0,3248 | −9,1829% | 2/5 | 15 090,51 | yes |

Primary годы: 2021 **0,00%**, 2022 **−3,78%**, 2023 **+1,52%**,
2024 **+20,84%**, 2025 **−3,96%**. Terminal carry reserve **34,65 RUB** оставляет
post-reserve total return **+13,3627%**.

Verdict: `NO_GO`. Сигнал положителен во всех cost scenarios и заметно ограничивает MDD,
но не проходит sealed CAGR, Sharpe и 3/4 positive-active-years gates; результат слишком
сильно сосредоточен в 2024. Это полезнее отрицательных V17–V21, но ещё не стабильный
доход. Direct printed-BCI delta family закрыта для same-history tuning; продолжение
требует нового forward периода или заранее иной независимой информации.

## V21: CBR next-year macro revision breadth — NO-GO

- Протокол: [`configs/futures_v21_cbr_macro_revision_breadth.yaml`](../configs/futures_v21_cbr_macro_revision_breadth.yaml)
- Config SHA-256:
  `5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc`.
- Pre-outcome commit: `5414251`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI/RI/BR/MIX outcomes.
- Canonical run:
  `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/`
- Metrics SHA-256:
  `cfc704e757393760cabcddeb6f3d1614f43df8ee8523b46db0fccd0ac8b92c0e`.
- Новый официальный current-vintage source: 11 787 non-missing записей макроопроса ЦБ,
  37 survey months, 17 indicators; до protected boundary причинно доступны 36 releases.
- Используется только медиана прогноза следующего календарного года. Revision всегда
  равна текущей медиане минус медиана предыдущего survey для строго того же indicator и
  forecast year; первый выпуск без предыдущего значения — source warmup.
- Независимые direct signs объявлены до outcomes: рост USD/RUB = long SI, рост GDP =
  long RI и MIX, рост oil = long BR; снижение даёт симметричный short, exact zero — cash.
- Нефть выбирается по неизменной очереди `oil tax > Brent > Urals`, только если у той же
  серии есть предыдущее значение того же target year. Cross-series bridge запрещён.
- Source-only seal: 36 available releases, 1 warmup, 35 scored (`4/8/8/8/7` по survey
  years), 102 ненулевых asset revisions. Magnitude scaling, threshold, fitting и
  outcome training отсутствуют.
- Каждый asset имеет отдельный абсолютный risk budget 1/4, prior 60-session volatility,
  target 20%, floor 10%. Missing component получает target zero, его бюджет не
  перераспределяется. State живёт до следующего release или 70 календарных дней.
- `available_at` намеренно поздний: 23:59:59 мск последнего дня месяца после survey
  month; fill возможен только на следующем factual active-contract open. December 2025
  исключён, потому что становится доступен в 2026.
- Current-vintage workbook не содержит original historical release vintages. Даже
  положительный результат будет adaptive development evidence и потребует нового unseen
  или forward-vintage подтверждения; live trading запрещён.

Из 35 scored releases 32 получили полную prior-60-session volatility; три выпуска
весны 2022 уснули из-за отсутствующей истории RI/MIX после остановки рынка. Получено
32 source decisions и 34 дополнительных causal roll decisions, 264 target rows.
Coverage ненулевых зависимостей — 200/202: на `2022-03-24` у RI и MIX отсутствовал
доказуемый lagged volume. Portfolio-atomic rebalance был отклонён с
`unknown_lagged_volume`; каждый scenario имеет 2 critical failures
(`unknown_liquidity_count=1` плюс `atomic_rejection_count=1`) и incomplete ledger.

| Scenario | Mechanical total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −3,1730% | −0,6429% | −0,0788 | −18,7868% | 3/5 | 4 501,83 | no |
| doubled | −3,9029% | −0,7932% | −0,1076 | −19,1190% | 3/5 | 8 868,22 | no |
| stress | −4,4273% | −0,9017% | −0,1264 | −19,5327% | 3/5 | 13 070,06 | no |

Primary годы: 2021 **+1,68%**, 2022 **−1,27%**, 2023 **+0,79%**,
2024 **+2,03%**, 2025 **−6,21%**. Mechanical метрики приведены только для forensic
полноты и недействительны для promotion из-за critical execution failures.

Verdict: `NO_GO`. Даже механический ledger отрицателен во всех cost scenarios и не
проходит CAGR/Sharpe/positive-years gates. Не инвертировать signs, не выбирать magnitude
thresholds, другие indicators/oil priority, risk/expiry или blend с V12 на этих же
outcomes. Macro-survey source сохраняется для forward vintages и иных вопросов, заранее
обоснованных новой информацией, но это семейство direct revisions закрыто.

## V20: Minfin OFZ-PD prior-rank demand strength — NO-GO

- Протокол: [`configs/futures_v20_minfin_ofz_demand_strength.yaml`](../configs/futures_v20_minfin_ofz_demand_strength.yaml)
- Config SHA-256:
  `788fadbd9c499483c560488a5a3d9d2e95f7e95496e5736ed4465eca889341ed`.
- Pre-outcome commit: `4e52378`; config, implementation, tests и pending-status docs были
  pushed до первого чтения RI/MIX/SI outcomes.
- Canonical run:
  `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/`
- Metrics SHA-256:
  `cbfa0c8803e631697400813d3fb4ba8a2ba2eda00a38cc5114dd652472d33d78`.
- Новый официальный current-vintage source: 410 Minfin events, 364 primary results и
  283 successful fixed-coupon ОФЗ-ПД rows; processed SHA
  `a8c5c02457e3fadc19e617f42ad5a0c644672689a4c9bd8759d20d4a84d5d480`.
- Все успешные ОФЗ-ПД одного дня агрегируются через total demand, total placed и
  `bid_to_cover = demand/placed`. Каждый показатель ранжируется только относительно
  предыдущих 26 successful auction days; минимум 13, ties получают half-rank.
- Единственный score: `percentile(bid_to_cover) + percentile(placed) − 1`, без threshold,
  clipping, outcome training и failed-auction imputation. Первые 13 auction days — warmup.
- Знак заранее фиксирован: strength = long RI/MIX и short SI, weakness — обратная
  корзина; BR zero. Три active legs имеют равный 1/3 risk budget, prior 60-session vol,
  target 20%, floor 10%; gross `<=1`.
- Date-only result доступен только в 23:59:59 мск publication day, fill — следующий
  factual open. Score живёт до следующего score или семь календарных дней, затем zero.
- Corrections, failed/cancelled, supplemental, announcement, ОФЗ-ПК и ОФЗ-ИН исключены
  до outcomes. Current-vintage pages не являются original publication vintages.
- Source сформировал 179 aggregated auction days: 13 warmup и 166 scored
  (`28/13/40/37/48` по годам), из них 82 positive, 76 negative и 8 zero. Добавлено
  29 causal expiry states и 10 roll decisions; 504/504 nonzero execution dependencies
  полны.
- Все 86 input/temporal/runtime checks true. Все три ledger complete, 0 critical и
  unresolved; primary содержит 128 filled legs, costs 1 409,28 RUB, maximum participation
  0,01358% и maximum gross notional 470 109,58 RUB.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −5,3468% | −1,0931% | −0,6313 | −6,1937% | 1/5 | 1 409,28 | yes |
| doubled | −5,4877% | −1,1226% | −0,6473 | −6,2418% | 1/5 | 2 818,57 | yes |
| stress | −5,4430% | −1,1132% | −0,6434 | −6,1057% | 1/5 | 4 139,14 | yes |

Primary годы: 2021 **−0,01%**, 2022 **−3,95%**, 2023 **−0,29%**,
2024 **+0,78%**, 2025 **−1,93%**.

Verdict: `NO_GO`. Prior-rank bid-to-cover плюс placed volume не дали cross-asset edge;
маленькая MDD объясняется умеренным gross, а не положительным expectation. Не
инвертировать asset signs, не выбирать extreme scores, другой rank window/expiry и не
добавлять failed/PK/IN по увиденному результату. Source остаётся полезным для иных новых
заранее обоснованных вопросов и forward vintages, но это семейство score закрыто.

## V19: CBR-reported Minfin FX-flow persistence для SI — NO-GO

- Протокол: [`configs/futures_v19_cbr_minfin_fx_persistence.yaml`](../configs/futures_v19_cbr_minfin_fx_persistence.yaml)
- Config SHA-256:
  `1340ffacae93b514fe4605262d8946a6a87cbc4619c1748b48ac45b9a9b19946`.
- Pre-outcome commit: `0558e7e`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI outcomes.
- Canonical run:
  `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/`
- Metrics SHA-256:
  `dff0016e3501136714f66b3237dfb66f37449bde69c77ab489efdc777446b08d`.
- Новый source: 1 238 current-vintage daily CBR factors `2021-01-11..2025-12-30`,
  processed SHA
  `88885d3695a88fb910d5a6ad9f3d8fd2cbd69eedaec779d4cef3048cd854c864`.
- Единственный сигнал: `sign(minfin_fx_operations_bln_rub)`; official positive FX
  purchase = long SI, negative sale = short SI, exact zero = cash.
- Observation day используется только после 10:31 мск следующего датированного рабочего
  дня ЦБ; решение — close первой factual MOEX session после availability, fill — только
  следующий factual active-contract open. Same-session collisions оставляют последний
  доступный observation.
- SI sizing: prior 60-session annual volatility, 20% target, floor 10%, absolute cap 1;
  RI/BR/MIX всегда zero. Amount scaling, threshold, smoothing, training и blend отсутствуют.
- Историческая таблица допускает revisions и не содержит original publication bytes:
  даже положительный результат будет development-only и потребует forward vintages.
- Все input/temporal checks true. Из 1 238 source rows 1 235 отображены на factual
  decision sessions; одна same-session collision причинно оставила более свежий record,
  два последних records не имели будущей active session. Получено 937 nonzero mapped
  decisions и 4 940 target rows; 937/937 execution dependencies полны.
- Все три ledger complete, 0 rejected/critical/unresolved; primary содержит 162 filled
  legs, costs 4 154,95 RUB и maximum participation 0,01155%.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −0,0316% | −0,0063% | 0,0501 | −30,7614% | 2/5 | 4 154,95 | yes |
| doubled | −0,2403% | −0,0481% | 0,0460 | −30,7447% | 2/5 | 8 249,91 | yes |
| stress | −0,5687% | −0,1140% | 0,0396 | −30,7933% | 2/5 | 9 971,81 | yes |

Primary годы: 2021 **−4,65%**, 2022 **+3,49%**, 2023 **−20,13%**,
2024 **−5,32%**, 2025 **+33,97%**.

Verdict: `NO_GO`. Лагированный прямой знак фактических операций Минфина не дал
устойчивого edge для SI: почти нулевая итоговая доходность скрывает просадку свыше 30% и
сильную зависимость от одного 2025 года. Не инвертировать знак, не выбирать magnitude/
change-day thresholds, smoothing или иной lag по увиденному результату. Следующий PnL
допустим только для новой независимой source family и заранее запечатанного protocol.

## V18: CBR forward-liquidity forecast для SI — NO-GO

- Протокол: [`configs/futures_v18_cbr_liquidity_forecast.yaml`](../configs/futures_v18_cbr_liquidity_forecast.yaml)
- Config SHA-256:
  `ee2d7fd77037eccf15237f827ed357e0b8608c96fae1f393e8a3478945b8b10a`.
- Pre-outcome commit: `0c3fc80`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI outcomes.
- Canonical run:
  `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/`
- Metrics SHA-256:
  `b67423433a03ebcd4cdebac5df33754e62be94b4719a430f1642596c357e9f28`.
- Новый source: 458 датированных CBR forecasts `2017-01-10..2025-12-30`, processed SHA
  `a8faab048579cc5449173b3f2d4ea0e2abd447095d9144ad5004a52b351a8d07`.
- Единственный сигнал: `sign(government_accounts_change_bln_rub)`; positive liquidity
  contribution = long SI, negative = short SI, exact zero = cash.
- Availability: конец напечатанного publication day Moscow; entry только следующий
  factual open. Двадцать source intervals требуют явного expiry-to-zero, потому что
  successor release появляется после напечатанного конца периода либо отсутствует.
- SI sizing: prior 60-session annual volatility, 20% target, floor 10%, absolute cap 1;
  RI/BR/MIX всегда zero. Threshold, normalization и outcome training отсутствуют.
- Все input/temporal checks true. Получено 240 OOS release decisions
  (`51/37/51/51/50` по годам), 10 expiry-to-zero и 18 roll decisions; 257/257 nonzero
  execution dependencies полны. В 2022 ещё 14 releases исключены из-за отсутствия
  prior 60-session SI volatility после остановки рынка; последний release 2025 не имел
  будущей factual decision session.
- Все три ledger complete: 183 primary filled legs, 0 critical, 0 unresolved,
  maximum participation 0,01155%; один factual halt корректно carried.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −41,9547% | −10,3092% | −0,5137 | −55,7292% | 1/5 | 8 289,95 | yes |
| doubled | −44,5908% | −11,1392% | −0,5650 | −57,5354% | 1/5 | 16 259,90 | yes |
| stress | −44,4906% | −11,1070% | −0,5616 | −57,3925% | 1/5 | 19 391,80 | yes |

Primary годы: 2021 **−1,77%**, 2022 **−46,94%**, 2023 **−9,47%**,
2024 **−1,33%**, 2025 **+24,67%**.

Verdict: `NO_GO`. Прямой экономический знак будущего изменения government accounts не
является самостоятельным edge для SI. Не инвертировать знак, не выбирать extreme weeks,
не менять lag/expiry/volatility/costs по увиденному результату. Допустима только новая
информационная гипотеза, заранее запечатанная независимо от V18 outcomes.

## V17: EIA seven-component physical balance for BR — NO-GO

- Протокол: [`configs/futures_v17_eia_supply_demand.yaml`](../configs/futures_v17_eia_supply_demand.yaml)
- Config SHA-256:
  `1d8eee3f7aa99aff5798aeaf6a946d110cfa4e4b451b57580b1d9ef6cd17b37a`
- Pre-outcome commit: `a8b8407`; config, implementation и tests были pushed до первого
  чтения BR outcomes.
- Canonical run:
  `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/`
- Metrics SHA-256:
  `fbd3b74e44ce91d484bb9e1594130ee2dd4d6589c0e50cabb34f3345b898f255`
- Новый input family: 38 248 строк из 727 release-specific EIA WPSR Table 1 vintages;
  source manifest SHA `aac389628b...`, processed SHA `5fccfa968a...`.
- Signal: семь заранее названных inventory/supply/refinery/demand changes, prior-only
  156-release z-score с минимумом 104, fixed economic signs, без trade threshold;
  BR target — знак composite с causal prior-60-session 20% vol scaling.
- Timing: conservative end-of-release-day New York, затем завершение первой factual MOEX
  decision session и только следующий factual active-contract open. Ни `Last-Modified`,
  ни same-day response не использованы.
- 623 source releases получили достаточную source history; 245 OOS release decisions и
  49 causal roll decisions; 1 176 target rows, 294 nonzero dependencies, coverage
  294/294. В 2022 13 releases уснули из-за отсутствия prior-60-session BR volatility;
  последний release 2025 не имел будущего decision session.
- Все 74 preflight/source checks true. Все три ledger полны: 0 critical, 0 unresolved,
  maximum participation 0,1383%; один factual halt был корректно carried.

| Scenario | Total return | CAGR | Sharpe | MDD | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---|
| primary | −33,1422% | −7,7373% | −0,1893 | −48,8033% | 82 842,43 | yes |
| doubled | −39,9714% | −9,7044% | −0,2734 | −49,6065% | 153 735,82 | yes |
| stress | −42,6776% | −10,5337% | −0,3237 | −51,6054% | 221 578,82 | yes |

Primary годы: 2021 **+7,80%**, 2022 **−31,73%**, 2023 **+59,58%**,
2024 **−19,83%**, 2025 **−28,99%**. Только 2/5 лет положительны.

Verdict: **NO-GO**. Это валидный отрицательный результат, а не execution failure. Не
инвертировать signs, не менять семь компонентов, 156/104 normalization, lag, vol target
или threshold на тех же outcomes. Возвращение к EIA возможно только с действительно новой
информацией, например point-in-time analyst consensus/forecast surprise, либо на новом
forward периоде по заранее запечатанному протоколу.

## V16: FUTOI crowding + capacity-aware 2x trend — INVALID, FUTOI look-ahead

- Протокол: [`configs/futures_v16_futoi_crowding_governor.yaml`](../configs/futures_v16_futoi_crowding_governor.yaml)
- Config SHA-256:
  `d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070`
- Pre-outcome Git commits: общий capacity-aware admission `1323781`; sealed V16
  protocol/code/tests `8fd2abf`. Оба отправлены в `origin` до первого PnL.
- Canonical run:
  `runs/v16_futoi_governor_20260831T220539Z_d0461775/metrics.json`
- Metrics SHA-256:
  `8246e155843dad0928c1ae283b9023622fc19fe9ed11ca956753bfbe92c6d73f`
- Invalidation audit: 932/1 044 OOS asset states имели recorded FUTOI `available_at`
  позже decision. Все 832 states 2021–2024 недоступны; первый допустимый state только
  `2025-06-27`. MOEX определяет `SYSTIME` как время публикации, а historical rows
  2020–2024 в current-vintage response имеют `SYSTIME=2025-06-21`.
- Root cause: join требовал `source_date < decision_date`, но не проверял обязательное
  `available_at <= decision_at`. Pre-outcome seal не компенсирует look-ahead; run
  недействителен и текущий entry point остановлен `RuntimeError` до PnL.
- Signal: frozen V12 weekly trend. Для каждого asset последний FUTOI строго с
  `source_date < decision_date` переводит нормальное/contrarian состояние в 2x, а
  trend-aligned crowding не менее одной robust sigma — в 1x. Median/MAD зафиксированы
  только на 168 наблюдениях каждого asset 2020 года.
- Collateral: полностью неизменные V15 RUONIA rules — 50% причинно известной ставки,
  ACT/365, двойной modeled-IM reserve, 10% buffer и отсутствие reinvestment.
- Capacity contract: неизвестный factual open или lagged volume отменяет только текущую
  попытку; известный participation excess заранее clip-ится. Нет скрытого GTC retry и
  специальных дат марта 2022.
- Artifact integrity: все 23 артефакта и 19 parquet row counts совпали с manifest.
  Предыдущий аудит проверял только отсутствие 2026 и потому не заметил, что timestamp
  2025 всё равно позже решений 2021–2024.

OOS содержит 261 weekly и 53 roll decision, 1 256 target rows и 1 040 ненулевых
targets с coverage 1 040/1 040. Из 1 044 weekly asset states: 253 crowded 1x, 577
aggressive 2x и 214 neutral/zero-signal base-risk; stale/missing не было. Primary ledger
содержит 730 filled legs, 0 rejected, 0 critical и 0 unresolved; шесть попыток были
причинно отменены из-за отсутствия factual open, позиция сохранялась до следующего
самостоятельного target.

| INVALID forensic scenario | Futures CAGR | Combined return | Combined CAGR | Sharpe | MDD | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 20,1280% | 170,3301% | 22,0082% | 0,9678 | −31,3402% | 45 074,70 |
| 2 ticks + 2x fee | 19,9683% | 168,5542% | 21,8474% | 0,9624 | −30,8848% | 89 323,92 |
| 4 ticks + 2x fee | 19,1924% | 160,3881% | 21,0971% | 0,9378 | −31,0004% | 132 148,39 |

Primary collateral income — 201 950,38 RUB. Combined годы: 2021 `+39,1146%`,
2022 `+70,4325%`, 2023 `+15,2018%`, 2024 `+9,0275%`, 2025 `−9,2234%`. Эти числа
сохранены только для forensic reproducibility: их нельзя сравнивать с V15/V12,
использовать для выбора следующей гипотезы или называть performance.

Главная просадка шла от `2024-11-26` до `2025-04-07`: RI дал около −482 тыс. RUB,
SI −270 тыс., MIX −173 тыс., BR −56 тыс. В этом окне FUTOI уже уменьшал RI/MIX/BR,
но оставлял SI в 2x во всех 19 weekly states. Это outcome-diagnostic, не разрешение
подбирать новый FUTOI/RVI threshold на том же периоде.

Verdict: `INVALID_FUTOI_LOOKAHEAD`, не `NO_GO`. Ни один promotion gate не оценивается
по недоступным признакам. Daily/intraday FUTOI current-vintage можно использовать только
после его conservative retrieval time либо с лицензированным original-vintage archive;
V16.1 и любые post-outcome FUTOI/RVI thresholds запрещены.

## V15: 2x frozen V12 + causal RUONIA — цель CAGR достигнута, stability/execution нет; NO-GO

- Протокол: [`configs/futures_v15_levered_ruonia_collateral.yaml`](../configs/futures_v15_levered_ruonia_collateral.yaml)
- Config SHA-256:
  `8cbcf30712684607e16cde27a9bca333e4740bd3bdb119646890d0b28d00a50d`
- Pre-outcome Git commits: `f68226f`; инфраструктурный 2x admission fix до PnL:
  `85b1074`.
- Canonical run:
  `runs/v15_levered_ruonia_20260831T205040Z_8cbcf307/metrics.json`
- Metrics SHA-256:
  `3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4`
- Signal: frozen V12; mapped target weights умножены на 2, gross cap 2x, modeled-IM
  reserve остаётся 2x. Первый технический запуск остановился до расчёта PnL на старом
  1x admission guard и не создал run; economics/config не менялись.
- Collateral: последняя RUONIA, консервативно доступная до начала интервала, haircut 50%,
  ACT/365; начисление только на положительный остаток после двойного IM и 10% operational
  buffer. Процент не участвует в sizing и не капитализируется в будущую базу.
- Coverage: 1 040/1 040 nonzero target dependencies; 1 271/1 271 RUONIA intervals,
  1 824 календарных дня. Все 23 run-артефакта совпадают с записанными hashes; 25
  временных полей не пересекают защищённую границу 2026.

| Scenario | Futures CAGR | Combined return | Combined CAGR | Sharpe | MDD | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 19,9802% | 162,8703% | 21,3272% | 0,8826 | −34,4823% | 51 931,22 |
| 2 ticks + 2x fee | 19,1440% | 154,0721% | 20,5038% | 0,8609 | −34,9389% | 101 335,27 |
| 4 ticks + 2x fee | 19,0763% | 153,4561% | 20,4453% | 0,8605 | −34,5370% | 151 941,78 |

Primary collateral income — 142 698,54 RUB, или 14,2699% начального капитала. Combined
годы: 2021 `+40,3432%`, 2022 `+73,0253%`, 2023 `+19,8218%`, 2024 `+6,6062%`,
2025 `−15,2535%`. Главная просадка шла от пика 2024-11-26 до минимума 2025-10-20.
Maximum post-mark gross leverage 2,1862 и maximum 2x modeled-margin/start-cash ratio
1,0831 возникали после рыночного движения; order-time gross/margin rejections равны нулю.

Execution не является полным: primary содержит 756 filled и 12 rejected legs, восемь
critical order events и ноль unresolved на конце. Все отказы сосредоточены в RI/MIX
`2022-03-09..2022-03-23`, когда требуемого factual open/mark не было; дополнительно три
случая не имели lagged volume и один превысил participation. Поэтому даже численно
высокие return/CAGR имеют `metrics_valid=false`.

Verdict: `NO_GO`. Sealed 20% CAGR gate пройден, но MDD 25% gate и complete-execution
gate провалены. V15 доказал полезность capital efficiency как направления, но не
стабильный исполнимый доход. Нельзя менять leverage, RUONIA haircut, buffer или правила
марта 2022 по этому outcome; следующий вариант обязан быть отдельной заранее
запечатанной risk/execution гипотезой и всё равно потребует независимой проверки.

## V14: previous-session RVI risk governor — просадка ниже, edge слишком ослаблен; NO-GO

- Протокол: [`configs/futures_v14_rvi_risk_governor.yaml`](../configs/futures_v14_rvi_risk_governor.yaml)
- Config SHA-256:
  `9f680ebfcfcd6aae98a1e39eb44b9c51b59aa73067edc32e7a558399a8a29a53`
- Pre-outcome Git commit: `677c713`.
- Canonical run:
  `runs/v14_rvi_governor_20260831T201919Z_9f680ebf/metrics.json`
- Metrics SHA-256:
  `1a236f0698ab906532e5381d8ecbc5c7b896c742533ad9b1e95df1096c8aa3ea`
- Signal/portfolio/execution: frozen V12. После portfolio construction все четыре target
  умножаются на `min(1, 24.135 / previous_session_RVI_close)`. Медиана `24.135`
  рассчитана только по 756 RVI строкам 2018–2020 и запечатана до OOS PnL.
- Causality: только RVI точной предыдущей factual core-four сессии; same-day запрещён,
  missing переводит все четыре target в cash с отдельным mask.
- OOS: RVI доступен для 259/261 weekly decisions, 219 решений downscaled, 2 missing;
  minimum/mean scale `0,1810/0,7308`.
- Execution: 261 weekly + 53 roll decisions, 1 256 target rows, 1 040 nonzero,
  coverage 1 040/1 040; primary 330 filled legs, 0 rejected, 0 critical, 0 unresolved.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 25,6242% | 4,6687% | 0,7342 | −9,3980% | 4/5 | 8 313,85 |
| 2 ticks + 2x fee | 25,5055% | 4,6489% | 0,7293 | −10,2238% | 4/5 | 16 390,64 |
| 4 ticks + 2x fee | 24,6763% | 4,5103% | 0,7072 | −10,4019% | 4/5 | 24 254,85 |

Primary годы: 2021 `+15,4005%`, 2022 `+3,1454%`, 2023 `+6,2241%`,
2024 `+2,1197%`, 2025 `−2,7066%`. Относительно V12 MDD лучше на 4,7545 п.п. и costs
ниже на 5 073,43 RUB, но CAGR ниже на 3,0631 п.п., Sharpe ниже на 0,0283 и worst year
немного хуже. Maximum post-mark gross leverage 0,9049, maximum 2x margin ratio 0,4545.

Verdict: `NO_GO`. RVI действительно уменьшил tail exposure, но не повысил
risk-adjusted edge и нарушил sealed minimum CAGR 5%. Не перебирать RVI thresholds,
floors или same-day joins на 2021–2025.

## V13: trend + front/next carry confirmation — больше return, хуже stability; NO-GO

- Протокол: [`configs/futures_v13_trend_carry_confirmation.yaml`](../configs/futures_v13_trend_carry_confirmation.yaml)
- Config SHA-256:
  `94841c0baa1f4c7e0f88302467dfde3bc8104b2e662382b9224bbaf9b75f07ef`
- Pre-outcome Git commit: `2c51cef`.
- Canonical run:
  `runs/v13_trend_carry_20260831T190300Z_94841c0b/metrics.json`
- Metrics SHA-256:
  `783b0a7ec9dd613df9b7f38c3070eb33ee980358a69ec4a11f4e411e079a6039`
- Parent V12 metrics были известны и byte-pinned до V13; это adaptive same-period
  challenger, а не независимая проверка.
- Signal: полный frozen V12 trend сохраняется только при строгом совпадении его знака со
  знаком annualized `(front / next - 1)` carry. Противоположный/нулевой наблюдаемый знак
  даёт cash; недоказанная кривая остаётся missing.
- Curve proof: `observed_through == decision_date`, availability `decision_close`,
  positive simultaneous settles, ordered expiries и независимый пересчёт каждого
  `roll_yield`.
- Coverage: 8 100/8 100 curve-valid source rows; OOS 5 084, из них 2 681 confirmed,
  1 363 observed-not-confirmed и 1 040 missing trend inputs.
- Execution: 261 weekly + 47 roll decisions, 1 232 target rows, 841 nonzero,
  coverage 841/841; primary 431 filled legs, 0 rejected, 0 critical, 0 unresolved.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 52,4579% | 8,8013% | 0,7081 | −20,6861% | 4/5 | 17 436,92 |
| 2 ticks + 2x fee | 51,8483% | 8,7142% | 0,7022 | −20,7601% | 4/5 | 34 753,47 |
| 4 ticks + 2x fee | 51,6187% | 8,6813% | 0,6999 | −20,8382% | 4/5 | 51 412,64 |

Primary годы: 2021 `+21,4803%`, 2022 `+20,0836%`, 2023 `+5,1862%`,
2024 `+1,2208%`, 2025 `−1,8406%`. Относительно V12 total return выше на 7,3465 п.п.,
CAGR на 1,0695 п.п. и worst year лучше на 0,7912 п.п.; одновременно Sharpe ниже на
0,0543, MDD хуже на 6,5336 п.п., costs выше на 4 049,64 RUB.

Maximum participation 0,1590%, maximum post-mark gross leverage 1,0524 и maximum 2x
modeled-margin/start-cash ratio 0,5043. Order-time gross/margin admission не отклонял
заявки; значение gross выше единицы возникло пассивно после mark/cash move между
ребалансировками. Terminal exit reserve 99,29 RUB оставляет return 52,4479%.

Sealed stability gate не пройден: и Sharpe, и MDD хуже frozen V12. Verdict: `NO_GO` как
replacement/стабилизатор. V13 можно помнить как агрессивный return-challenger, но нельзя
теперь подбирать carry threshold, blending weight или asset subset по тем же 2021–2025.

## V12: core-four correlation-aware trend — GO к unseen validation

- Протокол: [`configs/futures_v12_core4_correlation_trend.yaml`](../configs/futures_v12_core4_correlation_trend.yaml)
- Config SHA-256:
  `0b1a79d5c09cf40330886ebfba84bb9a7a8a84973301d59627200050e61b3e53`
- Canonical run:
  `runs/v12_core4_trend_20260831T182210Z_0b1a79d5/metrics.json`
- Metrics SHA-256:
  `c989377f7de65c3ef0a8dd52a1f5fcbf11c6ad8048119ea0a7b4402f47b23288`
- Input: byte-pinned V5 causal panel, active map, 66 052 contract observations и
  frozen conservative spec proxy; maximum factual date `2025-12-30`.
- Signal: одинаковый для BR/MIX/RI/SI risk-adjusted trend по 21/63/126/252 sessions;
  weekly last-session decision, covariance 60 sessions, 20% target vol, gross `<= 1`,
  five weekly turnover sleeves.
- Execution: exact next factual open, целые контракты, asset-atomic explicit rolls,
  participation `<= 1%`, current cash sizing, modeled 2x IM buffer, settlement VM.
- Counts: 261 weekly + 53 roll decisions, 1 256 target rows, 1 040 nonzero targets,
  coverage 1 040/1 040, 1 272 sessions, 429 primary filled legs, 0 rejected,
  0 critical failures и 0 unresolved halts.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 45,1114% | 7,7318% | 0,7624 | −14,1526% | 4/5 | 13 387,28 |
| 2 ticks + 2x fee | 40,8019% | 7,0841% | 0,7116 | −14,3150% | 4/5 | 26 601,80 |
| 4 ticks + 2x fee | 41,7324% | 7,2253% | 0,7207 | −14,3289% | 4/5 | 38 812,65 |

Primary yearly returns: 2021 `+17,5345%`, 2022 `+14,0141%`, 2023 `+7,7762%`,
2024 `+3,1900%`, 2025 `−2,6318%`. Stress не обязан быть монотонно хуже doubled,
потому что каждый scenario заново применяет integer sizing к собственному cash path;
fixed-primary-position cost diagnostic также остался положительным, но не участвует в gate.

Максимальная participation 0,1129%, gross leverage 0,9544, 2x modeled-margin ratio 0,4688;
нарушений cap нет. Terminal positions carried; exit reserve 173,40 RUB оставляет primary
return 45,0941%.

Verdict: `GO_TO_NEW_UNSEEN_VALIDATION`. Это adaptive same-period результат после уже
увиденных V5–V11 исследований, не независимый holdout и не разрешение на live. Запрещено
подбирать V12 параметры на 2021–2025. Следующее допустимое действие — byte-identical
проверка на новой unseen истории/рынке с broker/exchange exact specs и отдельный sealed
paper-forward protocol.

## V10/V11: triangular RI/MIX/SI relative value — закрыто, NO-GO

### V10: adverse-window execution

- Протокол: [`configs/futures_v10_triangular_relative_value.yaml`](../configs/futures_v10_triangular_relative_value.yaml)
- Config SHA-256:
  `4ff5c4cb84e5ecd608d69f5673a0e8af6e4f8103cea8f9cb348530e525e6103c`
- Canonical run:
  `runs/v10_triangular_20260831T171000Z_4ff5c4cb/metrics.json`
- Metrics SHA-256:
  `71ea94ec170544e35bb6e2896536d328bae71256537b84eec2990a98c4a0bb65`
- Signal: `log(RI) − log(MIX) + log(SI)`, prior 72 common observations, entry 2σ,
  take-profit 0,5σ, adverse stop 4σ, maximum 18 completed bars.
- Execution: exact next bucket; buy high/sell low; integer contracts; equal 30% leg
  budgets; signal and realized participation cap 1%; ordinary and doubled costs.
- Coverage: 169 071 common bars, 109 143 OOS bars, 31 953 eligible signal bars and
  3 329 raw threshold events.
- Fail-closed stop: after 4 completed trades, `2022-03-29 08:00 UTC`,
  `insufficient_entry_window_capacity`.
- Partial diagnostic only: return −2,5806%, CAGR −0,5230%, Sharpe −0,6344,
  MDD −2,5806%, 0/4 winners, costs 697,15 RUB. Full-period metrics are invalid.
- Verdict: `NO_GO_UNRESOLVED_EXECUTION`; live promotion forbidden.

### V11: liquidity-buffered next-open sensitivity

- Протокол: [`configs/futures_v11_liquidity_buffered_open.yaml`](../configs/futures_v11_liquidity_buffered_open.yaml)
- Config SHA-256:
  `584bf28977238681bfd90a39fa886eb0d1e1691a4799e041c4321d5bb02f400c`
- Canonical run:
  `runs/v11_buffered_open_20260831T171200Z_584bf289/metrics.json`
- Metrics SHA-256:
  `338fd41a35b64fe661112af389f17a1e4616c52d91cd8d41b4616aff0acb6ca1`
- Alpha and thresholds inherited unchanged from V10. Execution uses factual next-bucket
  open plus fee/one-tick cash cost, sizes from 0,25% of causal signal-bar volume, keeps a
  1% factual cap, cancels unfilled entries and retries a triggered exit for at most six
  exact same-contract buckets.
- V11 is explicitly adaptive after reading V10 on the same 2021–2025 period. It is
  hypothesis generation only and cannot make a confirmatory claim on this interval.
- Fail-closed stop: 10 completed trades, 12 exit retries, then
  `2022-06-06 11:10 UTC`, `exit_capacity_retry_limit`.
- Partial diagnostic only: return −0,6768%, CAGR −0,1361%, Sharpe −0,9736,
  MDD −0,6768%, win 20%, profit factor 0,1189, costs 1 899,99 RUB. At doubled costs:
  return −0,8668%, Sharpe −1,0571. Full-period metrics are invalid.
- Verdict: `NO_GO_UNRESOLVED_EXECUTION`. Семейство закрыто; не перебирать thresholds,
  stops, holding или capacity на уже просмотренной истории.

## V9: текущая серия challenger-экспериментов

### Structural futures breadth — условный lead

- Протокол: [`configs/futures_v9_structural.yaml`](../configs/futures_v9_structural.yaml)
- Config SHA-256:
  `c9aa50d3ea3f16e0aa8d729aef238b2d316e249c8277d39f573046880ea3ef68`
- Canonical run:
  `runs/futures_v9_structural/structural_c86d4852729d4c8a/results.json`
- Данные: official MOEX ISS, 22 candidate roots; warmup 2018–2020, OOS 2021–2025.
- Portfolio: weekly, 12% volatility target, gross `<= 1`, asset cap 15%, 5/10 bps.
- Среднее число eligible assets 17,71; минимум 15; максимум 20.

| Strategy | CAGR 5 bps | Sharpe | MDD | CAGR 10 bps | Verdict |
|---|---:|---:|---:|---:|---|
| `risk_adjusted_momentum` | 6,7745% | 0,7840 | −15,1293% | 5,3463% | Exact-execution candidate |
| `tsmom_multi` | 6,3111% | 0,7943 | −14,2108% | 4,7127% | Exact-execution candidate |
| `tsmom_6m` | 5,3410% | 0,8091 | −11,9518% | 4,1414% | Exact-execution candidate |
| `carry_momentum_confirmation` | 4,8860% | 0,5316 | −16,0089% | 3,2997% | Не продвигать |
| `tsmom_3m` | 4,7356% | 0,6598 | −13,0447% | 3,3803% | Не продвигать |
| `curve_carry` | 3,5365% | 0,5505 | −11,3214% | 2,0455% | Не продвигать |
| `tsmom_1m` | 1,4684% | 0,2344 | −16,1880% | −0,3376% | NO-GO |
| `tsmom_12m` | 1,2494% | 0,2032 | −17,4967% | 0,2733% | NO-GO |

Ограничение: это fractional daily proxy с flat-bps costs, не broker-exact PnL.

### Structural robustness — предупреждение

- Протокол: [`configs/futures_v9_structural_robustness.yaml`](../configs/futures_v9_structural_robustness.yaml)
- Config SHA-256:
  `49553bc70e36f842fb89ea387d202b4c918cda7ae327b756e101cdcfe3184daa`
- Canonical run:
  `runs/futures_v9_structural_robustness/robustness_870183b62323f8bb/audit.json`
- CSCV splits: 252; PBO-style risk 69,84%; selected OOS Sharpe `<= 0` — 22,22%.
- Median selected OOS Sharpe: 0,4038.
- RAM и `tsmom_multi` коррелируют на 0,9641; `tsmom_multi` и `tsmom_6m` — 0,8883.
- Verdict scope: promotion только к exact-execution validation, никогда прямо к live.

### Structural execution — NO-GO/blocker

- Протокол: [`configs/futures_v9_structural_execution.yaml`](../configs/futures_v9_structural_execution.yaml)
- Config SHA-256:
  `5619d5798e66360d84cc8d81e103f6d2deb5f864edc3ea01418a3a7d1f2e8f45`
- Canonical run:
  `runs/futures_v9_structural_execution/execution_8a934dfae72c769c/results.json`
- Input coverage: official daily OPEN 69,58%; realized point-value proxy 86,86%; sizing
  proxy 64,09%.
- RAM ordinary: 308/1 259 sessions; stopped `2022-03-18` на
  `GBPU:GUH2:missing_settle_or_contract`; full-period metrics invalid.
- Причина NO-GO: нет historical exchange/broker specs, fees и IM для 21 root; existing
  5/10/20 bps и 25% IM являются сценариями.

### Event Alpha V1 — маленький lead

- Протокол: [`configs/event_alpha_v1.yaml`](../configs/event_alpha_v1.yaml)
- Config SHA-256:
  `91f61abea2e4ca53179c9d5d085cbe98a8b6b863404050af547873c49cca7330`
- Canonical run:
  `runs/event_alpha_v1/development_20260818T155959Z_91f61abe/`
- Ridge `alpha=10`, purged expanding years 2021–2025, 10 bps round trip.
- Key-rate 1d: 31 events, 14 trades, CAGR 1,17%, Sharpe 0,523, MDD −0,38%, hit 71,43%.
- Corporate reporting и 30-minute horizon sleeping; synthetic documents не использовались.

### Frozen event + 10m timing hybrid — timing не помог

- Протокол: [`configs/futures_v9_event_timing_hybrid.yaml`](../configs/futures_v9_event_timing_hybrid.yaml)
- Config SHA-256:
  `92e98a7252d74bc099ef93a86d8f37eb011b11bebbe2c42b870568236b0f3465`
- Canonical run:
  `runs/futures_v9_event_timing_hybrid_development_20260818T170400Z_92e98a72/`
- Key-rate baseline: 10 trades, CAGR 0,99%, Sharpe 0,82, MDD −0,47%, hit 90%.
- Combined baseline: 36 trades, CAGR 0,42%, Sharpe 0,18, MDD −4,68%.
- Все четыре timed variants сделали 0 trades; neural gate не улучшил вход.

### Corridor competing risk — NO-GO

- Протокол: [`configs/futures_v9_corridor.yaml`](../configs/futures_v9_corridor.yaml)
- Config SHA-256:
  `aeb3b24fbb21b9400a6643815a9ad9488b91ef714358ea880cdb71c83c952053`
- Canonical run: `runs/futures-v9-corridor-development-v1/`
- Primary TP/SL: 0,8/2,8 ATR; same-bar stop-first; five-session exact time exit.
- 1×: 58 trades, CAGR 0,4574%, Sharpe 0,3480, MDD −2,4487%, win 65,52%.
- Nominal break-even win rate 77,78%; deficit −12,26 percentage points.
- 2× CAGR 0,4275%; safer 1,2/1,6 diagnostic CAGR −1,1075%, Sharpe −0,748.

### Continuous 10m timing — NO-GO

- V1 config: [`configs/futures_v9_intraday_timing.yaml`](../configs/futures_v9_intraday_timing.yaml),
  SHA `fd6ee70086bc7056ca60c73a91490362aae37c4caf053091cc73e2e0924159cf`.
- V2 config: [`configs/futures_v9_intraday_timing_v2.yaml`](../configs/futures_v9_intraday_timing_v2.yaml),
  SHA `4268723dbeca5408592399b680af36216f8f70cd7ca6439811d706e7977d3dcc`.
- Canonical V1 run: `runs/futures_v9_intraday_timing_full_20260818T163148Z/`.
- Canonical V2 run: `runs/futures_v9_intraday_timing_v2_full_20260818T164623Z/`.
- 440 094 OOS asset-decisions, 2021–2025, three fixed seeds.
- V1 attention/independent: 0 trades из-за sealed SNR; maximum SNR 0,584/0,680.
- Даже top 0,1% prediction tail имел отрицательное realized net action value.
- Breakout baseline: 6 894 trades, CAGR −53,71%, Sharpe −9,97, MDD −97,84%.
- V2: все 60 fold/variant/side/horizon gates sleeping; 0 trades.

### Market graph — NO-GO

- V1 config: [`configs/market_graph_v1.yaml`](../configs/market_graph_v1.yaml), SHA
  `4ced820c7ec5f589a5fe7f6cc4a797b65ed3013d6b4aaa3a169d0ca225819344`.
- Canonical V1 run: `runs/market_graph_v1_20260818T164732Z/`.
- Full graph IC −0,00639 против no-attention −0,00436; paired difference −0,00203,
  normal 95% interval `[−0,01180; 0,00775]`.
- Full graph: CAGR −10,32%, Sharpe −1,398, MDD 43,86%; promotion false.
- Relative momentum имел IC 0,04890, но sealed long/short CAGR −4,83% после costs/borrow.
- V2 config: [`configs/market_graph_v2_long_only.yaml`](../configs/market_graph_v2_long_only.yaml),
  SHA `50ff5688535b852a16b40e34aaf630935c9425259bdf45b3677d496aee554a01`.
- Canonical V2 run: `runs/market_graph_v2_long_only_20260819T074638Z/`.
- Top5/keep10: CAGR 1,2877%, Sharpe 0,1803, MDD 49,34%, worst year −38,09%,
  passive beta 0,901; at 2× costs CAGR 0,2672%. Исследовательское решение — NO-GO.

## V8: сохранённый, но незавершённый контур

- Base run: `runs/v8_20260818T111317Z_83135473/`.
- 15/15 моделей, 5 076 OOS predictions, SHA
  `ca7dae8d856e512a6b3e476662b73d7d7f4f87521f0c103606b147f117acd437`.
- Regime V2: `runs/v8_20260818T111317Z_83135473_enrichment_regime_v2/`.
- Raw-10m context V2:
  `runs/v8_20260818T111317Z_83135473_context_raw10m_v2/`.
- Authoritative PnL не рассчитан: admission trust anchor остаётся placeholder, admission
  certificate отсутствует. Не трактовать training completion как trading result.

## Legacy-результаты

| Контур | Результат | Решение |
|---|---|---|
| SBER MVP | 2026 уже участвовал в iterative selection | Только legacy/exploratory |
| Alpha50 XGBoost ranker | validation CAGR 34,42%; просмотренный 2026 holdout −15,84% | NO-GO |
| Daily residual TCN | CAGR −2,23%, Sharpe −0,148, MDD 28,99%, IC 0,0258 | NO-GO |
| Fixed 15-rule probe | best +7,01%, но selected на тех же folds и positive 2/4 | NO-GO |
| Futures V6 | CAGR 2,396%, Sharpe 0,300; worst fold отрицателен | NO-GO |
| Futures V7 | CAGR 0,670%, Sharpe 0,117; 2× costs CAGR −0,023% | NO-GO |

## Superseded и недействительные run

| Path относительно external root | Статус |
|---|---|
| `runs/futures_v9_structural/structural_bb356559262f8fb7/` | INVALIDATED: accounting bug |
| `runs/futures_v9_structural/structural_a3ffe0286b44b38c/` | Superseded implementation revision |
| `runs/futures_v9_structural/structural_d1f5eac9c2cf9ddb/` | Superseded implementation revision |
| `runs/futures_v9_structural_robustness/robustness_f87dc82859c38fb6/` | Superseded audit |
| `runs/futures_v9_structural_robustness/robustness_e0e18f1cd8284e62/` | Superseded audit |
| `runs/futures_v9_structural_execution/execution_4585b145edf0d4e8/` | Superseded incomplete execution |
| `runs/futures-v9-corridor-development-v1.invalid-carry-fx-causality/` | INVALID: carry/FX causality |
| `runs/futures_v9_event_timing_hybrid_development_20260818T170000Z_92e98a72/` | Byte-identical duplicate; use 170400Z |
| `runs/market_graph_v2_long_only_20260819T074419Z/` | Superseded; final cap diagnostics are in 074638Z |

Остальные timestamp-run считаются legacy/scratch, пока явно не внесены в этот реестр.
