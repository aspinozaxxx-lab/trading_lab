# Реестр экспериментов

Этот файл фиксирует научную память проекта. `Canonical` означает выбранный для аудита
неизменяемый артефакт, а не разрешение на live trading. Все внешние run paths относительны
к `D:\Projects\trading_lab_data`.

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
