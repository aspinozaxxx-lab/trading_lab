# Текущее состояние исследования

Обновлено: **2026-09-01**. Период разработки ограничен данными не позже
`2025-12-31`; данные 2026 для текущих V8–V18 гипотез защищены и не используются.

## Короткий ответ

Новый главный lead — V12 core-four correlation trend. Он впервые завершил полный
integer-contract next-open ledger 2021–2025 без critical/unresolved событий и прошёл
заранее зафиксированный gate к новой независимой валидации. Текущий общий статус:
**GO TO NEW UNSEEN VALIDATION, но NO-GO for live trading**.

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

Новый независимый PIT-кандидат подготовлен: официальный EIA WPSR Table 1 bundle содержит
727 допустимых release vintages и 38 248 target-free строк `2012-01-05..2025-12-29`.
Один stale issue `2019-07-03` изолирован, 71 межвыпусковая revision сохранена. Outcome BR
ещё не читался; следующий шаг — pre-outcome seal единственного supply-demand composite.

V17 выполнил этот sealed test и получил **NO-GO**: total return **−33,1422%**,
CAGR **−7,7373%**, Sharpe **−0,1893**, MDD **−48,8033%**, только два положительных года.
Все 294 nonzero execution dependencies покрыты, 0 critical/unresolved, поэтому провал не
объясняется исполнением. Raw delayed EIA balance не является доходным сигналом; signs,
компоненты, lag и thresholds по этому результату не инвертировать и не подбирать.

Следующий независимый source family уже собран без чтения outcomes: 458 датированных
недельных прогнозов факторов банковской ликвидности ЦБ за `2017-01-10..2025-12-30`.
Это forward-looking forecast, а не реализованный поток; `available_at` консервативно
равен концу московского дня публикации. V18 уже запечатал один тест экономического знака
forecast government-account flow для SI, без threshold search и без доверия query date;
outcome ещё не прочитан, config SHA `ee2d7fd7...`.

Новая треугольная гипотеза RI/MIX/SI проверена двумя заранее зафиксированными execution
вариантами и закрыта как **NO-GO**. Оба запуска остановились fail-closed на фактической
ликвидности; все доступные до остановки метрики отрицательны.

## Сводка активных гипотез

| Направление | Главный development-результат 2021–2025 | Решение |
|---|---:|---|
| V12 core-four correlation trend | +45,11%, CAGR 7,73%, Sharpe 0,76, MDD −14,15% | GO к новой unseen validation; не live |
| V13 trend + carry confirmation | +52,46%, CAGR 8,80%, Sharpe 0,71, MDD −20,69% | Return выше, stability хуже; NO-GO как replacement |
| V14 prior-session RVI governor | +25,62%, CAGR 4,67%, Sharpe 0,73, MDD −9,40% | MDD лучше, edge слабее; NO-GO |
| V15 2x V12 + causal RUONIA | +162,87%, CAGR 21,33%, Sharpe 0,88, MDD −34,48%; 8 critical | CAGR gate пройден, stability/execution gates нет; NO-GO |
| V16 FUTOI crowding + capacity-aware 2x | Механически CAGR 22,01%, но 932/1 044 states были недоступны | **INVALID: FUTOI look-ahead**, метрики не использовать |
| V17 EIA physical balance for BR | −33,14%, CAGR −7,74%, Sharpe −0,19, MDD −48,80% | Полное исполнение, но сигнал убыточен; NO-GO |
| Structural futures breadth | RAM: CAGR 6,77%, Sharpe 0,78, MDD −15,13% | Продолжать только exact-execution проверку |
| Sparse key-rate events | 10 сделок, CAGR 0,99%, Sharpe 0,82, MDD −0,47% | Малый наблюдаемый lead, недостаточно масштаба |
| RI/MIX/SI triangular relative value | V10: 4 сделки, −2,58%; V11: 10 сделок, −0,68%; оба invalid после unresolved | Закрыт, NO-GO |
| Corridor hazard 0,8/2,8 ATR | 58 сделок, CAGR 0,46%, Sharpe 0,35 | Закрыт, NO-GO |
| Continuous 10m neural timing | 0 допущенных neural trades; breakout CAGR −53,71% | Закрыт, NO-GO |
| 30-stock market graph | IC −0,00639; CAGR −10,32%, Sharpe −1,40 | Закрыт, NO-GO |
| Long-only relative momentum | CAGR 1,29%, Sharpe 0,18, MDD −49,34% | Закрыт, NO-GO |

Полная история и точные external run paths находятся в
[реестре экспериментов](EXPERIMENTS.md).

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

### P0 — независимо подтвердить V12, не подгоняя его

1. Заморозить byte-identical V12 signal/portfolio economics; не менять 21/63/126/252,
   пять sleeves, 20% target vol, universe и execution caps по результатам 2021–2025.
2. Получить новый действительно unseen период либо независимый PIT рынок. Уже
   просмотренный legacy 2026 нельзя переименовывать в holdout.
3. До следующего PnL получить historical exchange/broker specs, fee/IM schedules и
   spread/order-book evidence хотя бы для BR/MIX/RI/SI.
4. Провести заранее запечатанный paper/shadow forward test без реального капитала;
   отдельно мониторить отрицательный 2025 и деградацию trend edge.
5. Только после независимого подтверждения проектировать отдельный live-admission
   protocol с operational risk и аварийным отключением.

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
   V18 direct SI test запечатан: знак forecast government-account flow, следующий
   factual open, prior-only volatility sizing, без порога и перебора. После pre-outcome
   push выполнить ровно один canonical run и принять его результат без подгонки.
6. RVI threshold/blend на 2021–2025 также запрещён sealed V14; совпадение с invalid V16
   drawdown остаётся только post-outcome наблюдением.

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
