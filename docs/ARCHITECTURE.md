# Архитектура Market Lab

## Главный поток

```text
official/source archives
  → byte hashes + source manifests
  → point-in-time causal panel
  → train/calibration/OOS folds with purge
  → target-free predictions
  → next-bar/next-open execution contract
  → positions, orders and ledger
  → net metrics, robustness and explicit verdict
```

Каждый переход должен быть проверяемым. Manifest связывает источник, схему, временную
границу и SHA-256; protocol связывает information set, folds, execution, costs и promotion
rule; run хранит provenance и результаты, но не меняет уже запечатанный protocol.

## Структура репозитория

```text
configs/                  frozen experiment protocols and SHA files
scripts/                  thin reproducible entry points
src/market_lab/           Python package
tests/                    synthetic/unit/integration tests
docs/                     project memory and runbook
data -> external junction ignored by Git
runs -> external junction ignored by Git
```

Реальные `data` и `runs` находятся в `D:\Projects\trading_lab_data`. Код и docs не должны
зависеть от наличия бинарных артефактов для обычного импорта или synthetic test suite.

## Базовые компоненты

- `market_lab.data` — MOEX download/storage foundation.
- `market_lab.validation` — chronological и expanding splits.
- `market_lab.backtest` — базовый event/backtest engine и metrics.
- `market_lab.strategies`, `features`, `models` — ранний single-asset MVP.
- `market_lab.reporting`, `optimization` — run artifacts и Optuna foundation.
- `market_lab.alpha` — cross-sectional equity ranker experiments.
- `market_lab.sequence` — 10m/daily causal TCN experiments.

## Futures foundation

Модули в `market_lab.futures` обеспечивают:

- official ISS download и cached source archives;
- contract catalog и point-in-time roll state;
- daily/10m panels;
- session timing;
- contract/spec proxies;
- portfolio construction, ledger и information radar;
- CBR/CFTC features и specialist routers.

`market_lab.futures.eia_wpsr_source` собирает release-specific WPSR Table 1 во внешнее
хранилище, архивирует каждый исходный CSV, отделяет `release_date` от `available_at`,
сохраняет revisions и fail-closed исключает stale/non-increasing issue files.

`market_lab.futures.cbr_liquidity_forecast_source` перебирает датированные недельные
прогнозы факторов банковской ликвидности ЦБ. Историческая страница на несуществующую
дату молча возвращает последний выпуск, поэтому collector сверяет дату внутри строки
аукциона с запрошенной датой, проверяет будущий период прогноза и только затем допускает
record. Availability консервативно ставится на конец московского дня публикации; raw
страницы, coverage и hashes остаются во внешнем хранилище.

`market_lab.futures.cbr_liquidity_factors_source` сохраняет отдельную current-vintage
таблицу фактических дневных факторов. Для observation day publication day выводится как
следующий датированный рабочий день таблицы, а `available_at` ставится на 10:31 мск по
официальному правилу «предыдущий рабочий день — до 10:30». Source помечает допустимость
revisions и отсутствие original publication bytes; raw HTML, processed parquet и hashes
хранятся вне Git.

`market_lab.futures.minfin_ofz_auction_source` проходит официальный paginated result
archive Минфина до нижней границы интервала, повторно проверяет result-index первой
страницы, классифицирует каждую карточку и сохраняет listing/detail raw bytes с hashes.
Успешный primary result обязан содержать issue/type/date, demand, placement, proceeds и
cutoff/weighted price; yield обязателен кроме floating-rate ОФЗ-ПК. Date-only публикация
доступна только в `23:59:59 Europe/Moscow`; current-vintage history не считается
independent/original-vintage evidence.

`market_lab.futures.cbr_macro_survey_source` скачивает официальный aggregated XLSX
макроопроса аналитиков и без `openpyxl` читает только cached values 17 именованных sheets.
Каждая ненулевая ячейка становится tidy record с survey month, forecast period,
statistic, indicator и source cell; отсутствующие ячейки не превращаются в zero.
Исторические workbook vintages недоступны, поэтому current snapshot допускается только
как development source. Чтобы не угадывать старое время публикации, `available_at`
консервативно равен концу следующего московского месяца.

`market_lab.futures.cbr_business_climate_source` обнаруживает 44 versioned страницы
«Мониторинга предприятий», архивирует каждую страницу и PDF и извлекает только
подписанные endpoints сводного BCI, текущих оценок и ожиданий. Release month и
observation month хранятся отдельно. Availability равна концу более поздней из
publication/last-update dates; same-time collision downstream разрешается в пользу
последнего release month. Exact chart decimals остаются audit-only, сигнал может видеть
только напечатанную one-decimal label.

`market_lab.futures_v7` и `market_lab.futures_v8` — предыдущие neural generations.
V8 разделяет training, target-free enrichment/context, admission и evaluation. Его base
predictions сохранены, но authoritative PnL намеренно fail-closed.

## V9 challenger-модули

### `market_lab.futures_v9_structural`

- `run.py` загружает/проверяет official daily history, строит causal asset panel и восемь
  заранее объявленных structural strategies.
- `structural.py` содержит signals, inverse-vol weighting и flat-bps proxy.
- `robustness.py` воспроизводит canonical ledgers, attribution, leave-one-out, bootstrap и
  CSCV warnings.
- `execution.py` переводит три лидера в next-open integer-contract proxy и fail-closed
  останавливается на unresolved PnL.

Это текущая главная ветка исследований.

### `market_lab.event_alpha_v1`

Строит sparse point-in-time CBR/CFTC events, train-only standardized Ridge prediction,
purged expanding OOS и редкий event ledger. Corporate text extraction пока не участвует.

### `market_lab.futures_v9_corridor`

Общий causal loader → competing-risk labels → expanding calibrated classifier → exact
adverse-fill corridor backtest. Primary и единственный predeclared diagnostic фиксированы.

### `market_lab.futures_v9_intraday_timing`

Синхронизирует BR/MIX/RI/SI на регулярной 10m clock, хранит asset masks и запрещает
cross-contract horizons. Shared GRU сравнивает masked cross-asset attention с таким же
independent encoder. V2 применяет только train-slice gates.

### `market_lab.market_graph_v1` и `market_graph_v2`

V1 получает одновременно 30 equities, causal market context, asset masks и rolling
correlation bias. Factor head отделён от demeaned residual head. V2 не переобучает score,
а проверяет sealed relative momentum только в long-only execution.

### `market_lab.futures_v10_triangular_relative_value` и V11

V10 собирает exact common active-contract 10m buckets RI/MIX/SI, проверяет полный
manifest/SHA chain и lag-1 causal spec proxy, затем считает экономический residual
`log(RI) − log(MIX) + log(SI)`. `core.py` отделяет prior-only signal от adverse
next-window execution; `data.py` сохраняет factual last-trade timestamp отдельно от
scheduled bucket end; `run.py` пишет hashed signal/trade/leg/unresolved audit.

`market_lab.futures_v11_liquidity_buffered_open` наследует тот же сигнал без изменения и
изолированно проверяет buffered next-open execution. Оба контура fail-closed и имеют
NO-GO; V11 дополнительно помечен adaptive same-period и не является независимым OOS.

### `market_lab.futures_v12_core4_correlation_trend`

Загружает только byte-pinned pre-2026 V5 artifacts для BR/MIX/RI/SI, строит единый
21/63/126/252-session trend score и передаёт его существующему covariance-aware portfolio
constructor. Weekly weights дополняются причинными roll decisions, затем exact next-open
mapping проходит через общий integer-contract portfolio ledger с conservative tick/fee,
capacity, gross и modeled-margin проверками. Run сохраняет scores, targets, coverage,
orders, positions и ledger для трёх cost scenarios. Текущий результат прошёл только gate
к новой unseen validation; live остаётся запрещён.

### `market_lab.futures_v13_trend_carry_confirmation`

Импортирует frozen V12 portfolio/execution, независимо пересчитывает simultaneous
front/next roll yield и пропускает trend только при строгом совпадении знака. Config
pinning, curve proof, comparison с frozen V12 и три exact-ledger scenario входят в один
immutable run. V13 повысил development return, но ухудшил Sharpe/MDD и имеет NO-GO как
stability replacement.

### `market_lab.futures.rvi_source`

Target-free downloader официального индекса MOEX RVI. Каждый ISS URL ограничен
2018–2025, cursor проверяется на полноту и дубликаты, OHLC проходит fail-closed validation,
а raw pages, Parquet и manifest получают SHA-256 во внешнем immutable каталоге. Для
features действует отдельный contract: `source_date < decision_date`.

### `market_lab.futures.futoi_source`

Target-free downloader официального MOEX FUTOI. Он делает 24 bounded ticker-year запроса
для Si/RI/BR/MX с `latest=1`, сохраняет закрытую схему, exact `systime`, минутный delivery
buffer, raw JSONL gzip и hashed daily-last Parquet. Пары ФИЗ/ЮР валидируются, но
официальный ненулевой reporting imbalance сохраняется явно. Полный 5m архив этим
контуром не заявляется. Source current-vintage: `source_date` не доказывает availability;
consumer обязан проверять official `SYSTIME`/`available_at` против каждого decision.

### `market_lab.futures_v14_rvi_risk_governor`

Строит byte-identical V12 weekly weights, сопоставляет им только RVI точной предыдущей
core-four сессии и применяет общий downward-only scale. В run отдельно сохраняется
`rvi_governor.csv`, а metrics содержат delta против frozen V12. Контур уменьшил MDD, но
получил NO-GO из-за падения CAGR/Sharpe.

### `market_lab.futures_v15_levered_ruonia_collateral`

Повторно использует frozen V12 mapping/ledger, удваивает уже причинно сопоставленные
targets в изолированном 2x admission-контуре и начисляет haircutted RUONIA только на
свободное обеспечение после двойного modeled IM и operational buffer. Interest хранится
отдельно и не влияет на sizing. V15 пробил 20% combined CAGR, но получил NO-GO из-за
MDD выше 25% и critical halt orders; это механизм для дальнейшего risk research, а не
live-кандидат.

### `market_lab.futures_v16_futoi_crowding_governor`

Накладывает на frozen V12/V15 asset-level risk state из последнего строго предыдущего
MOEX FUTOI daily-last. Warmup median/MAD фиксированы только по 2020, crowded state
оставляет 1x, обычное/contrarian состояние допускает 2x, missing/stale закрывается в 1x.
Общий ledger policy `cancel_and_clip` отменяет текущую попытку при недоказанном factual
open/lagged volume и не создаёт скрытый retry. Однако V16 **INVALIDATED**: join проверял
только предыдущий `source_date`, и 932/1 044 FUTOI states имели `available_at` позже
decision. Entry point теперь останавливается до PnL; старые metrics хранятся только для
forensic audit.

### `market_lab.futures_v17_eia_supply_demand`

Проверяет семь fixed EIA physical-balance changes без outcome training: каждый компонент
получает prior-only rolling z-score, fixed economic sign и общий BR direction. Source
`available_at` переводится в первую завершённую MOEX decision session, затем frozen V12
active-contract mapper/ledger исполняет следующий factual open и отдельные roll events.
V17 технически завершён, но получил `NO_GO`: полный ledger доказал, что отрицательный
результат относится к сигналу, а не к missing execution.

### `market_lab.futures_v18_cbr_liquidity_forecast`

Проверяет один заранее зафиксированный forward-flow signal для SI: знак официального
прогноза изменения government accounts, где положительное влияние на рублёвую
ликвидность означает long SI, отрицательное — short SI. Release доступен только в конце
московского дня, fill — следующий factual open. Если successor release отсутствует,
отдельное нулевое решение завершает позицию по напечатанной дате конца forecast period.
Остальные три asset target всегда равны нулю; sizing использует только prior 60-session
SI volatility и frozen V12 execution mapper/ledger.

### `market_lab.futures_v19_cbr_minfin_fx_persistence`

Проверяет один direct-flow signal: официальный знак фактической операции Минфина с
валютой, опубликованный только на следующий рабочий день. Source допускается после 10:31
мск, решение принимается после закрытия factual session, fill выполняется на следующем
open. Несколько публикаций, попавших в одну session после разрыва торгов, разрешаются
только latest-known observation. Amount не масштабирует target; остальные assets zero,
execution и risk sizing унаследованы от frozen V12.

### `market_lab.futures_v20_minfin_ofz_demand_strength`

Агрегирует successful fixed-coupon ОФЗ-ПД results по publication day и строит два
empirical percentile только по предыдущим 26 auction days: bid-to-cover и total placed.
Их сумма минус один даёт непрерывный score без threshold. Strength задаёт long RI/MIX и
short SI, weakness — симметрично наоборот, BR zero; три legs имеют равный risk budget и
prior 60-session volatility sizing. Date-only source допускается в конце московского дня,
fill выполняется на следующем factual open, state истекает через семь календарных дней.
Failed/corrected/supplemental events и ОФЗ-ПК/ИН не получают synthetic zero.
Sealed V20 run завершён `NO_GO`; этот модуль сохраняется для воспроизводимости, а не как
основание перебирать знак, thresholds, rank window или expiry на той же истории.

### `market_lab.futures_v21_cbr_macro_revision_breadth`

Проверяет независимые ревизии next-year median из официального макроопроса ЦБ. История
предыдущего значения группируется одновременно по indicator и forecast year, поэтому
смена target year не создаёт ложную revision. USD/RUB управляет SI, GDP — RI/MIX, oil —
BR; разные oil sheets не склеиваются, а missing-компонент оставляет свой 1/4 budget
неиспользованным. Консервативный `available_at` отображается на первую factual decision
session, исполнение наследует next-open active-contract mapper и portfolio-atomic ledger
V12. Протокол SHA `5d97fd51...` был запечатан до outcome. Canonical run завершён
`NO_GO`: mechanical return отрицателен, а RI/MIX roll `2022-03-24` не имел доказуемого
lagged volume, поэтому portfolio-atomic ledger честно остался incomplete.

### `market_lab.futures_v22_cbr_business_climate_regime`

Проверяет один заранее объявленный regime: знак изменения printed composite BCI между
последовательными release months. Improvement задаёт long RI/MIX и short SI; decline —
обратные направления, BR zero. В signal запрещены exact chart decimals и отдельный выбор
current-assessment/expectations. Даты publication/revision схлопываются только через
консервативный `available_at`; same-time collision оставляет последний release month.
Три active legs имеют по 1/3 risk budget, prior 60-session volatility и 45-day expiry;
next-open mapper и portfolio-atomic ledger унаследованы от frozen V12 infrastructure.
Config SHA `97b2aa74...` был запечатан до outcome. Canonical V22 полностью исполним и
положителен после costs, но CAGR 2,54%, Sharpe 0,36 и только 2/4 positive active years
дали `NO_GO`; модуль сохраняется для воспроизводимости, а не для threshold tuning.

### `market_lab.futures.cbr_inflation_expectations_source`

Собирает отдельную датированную страницу, PDF и XLSX каждого официального выпуска
«Инфляционных ожиданий и потребительских настроений» ЦБ за `2022-01..2025-12`.
Стратегические значения извлекаются из release-specific XLSX по смысловым названиям
листов и рядов: медиана ожидаемой на 12 месяцев инфляции и индекс потребительских
настроений. Округлённые до одного знака endpoints HTML-графика служат независимой
проверкой XLSX, но не заменяют точные значения. Availability равна концу московского дня
более поздней из publication и last-updated dates; при одинаковом `available_at`
downstream оставляет максимальный `release_month`. Bundle включает 48 страниц, 48 PDF,
48 XLSX и две archive snapshots. Это current-retrieved release-specific history:
development backtest допустим, но независимое подтверждение требует forward vintages.

### `market_lab.futures_v23_cbr_household_confirmation_regime`

Проверяет один заранее объявленный двухрядный confirmation regime из точных значений
release-specific XLSX. Expected inflation down вместе с consumer sentiment up означает
risk-on: long RI/MIX и short SI. Обратная согласованная пара означает risk-off; любой
mixed/zero release переводит все legs в cash, BR всегда zero. Модуль использует frozen
causal state/volatility mapper V22, но полностью заменяет BCI signal и provenance.
Параметры исполнения остаются заранее фиксированными: по 1/3 risk budget, prior 60-day
volatility, 45-day expiry, next factual open и portfolio-atomic ledger. Config SHA
`2a8a35a8...` был запечатан до outcome. Canonical run дал отрицательный результат во
всех cost scenarios и `NO_GO`; 3 confirmed releases fail-closed остались cash из-за
недоступной prior-60-session volatility. Модуль сохраняется только для воспроизводимости.

### `market_lab.futures.cboe_vix_term_structure_source`

Собирает два официальных Cboe daily-close ряда, распространяемых FRED: 30-day `VIXCLS`
и 3-month `VXVCLS`. URL серверно ограничены `2018-01-01..2025-12-31`, поэтому raw bytes
физически не содержат наблюдений 2026. Missing значения сохраняются, общий ряд создаётся
только на точной общей date grid, а structural state равен backwardation строго при
`VIX/VIX3M > 1`. Conservative availability — `23:59:59 America/Chicago` observation day;
при московском join это запрещает использовать ещё не закрывшуюся американскую сессию.
Canonical V2 содержит 2 087 grid rows и 2 011 complete pairs. V1 superseded только из-за
нерепродуцируемой parquet timestamp unit; V2 raw replay совпадает точно.

### `market_lab.futures_v24_cboe_vix_term_structure_governor`

Сохраняет frozen V12 без изменения и разворачивает последний weekly target на каждую
factual active-contract decision date. На `23:59:59 Europe/Moscow` модуль делает
`merge_asof` только назад по `available_at`; complete свежий Cboe pair в contango
пропускает V12 с scale 1, а backwardation, flat, missing/incomplete или возраст более
четырёх календарных дней дают global scale 0. Следующий factual active-contract open,
integer sizing, asset-atomic ledger, gross/capacity/margin и costs импортированы из V12.
Перед чтением market outcomes runner проверяет SHA всех source artifacts, sidecar и
manifest payload, декодирует два raw CSV, повторяет parse/combine и требует exact
DataFrame equality. Config SHA `f81b5aaa...` фиксирует один вариант и state counts до
первого PnL; current-vintage источник не является независимым holdout. Pre-outcome
commit `34023c1` был pushed до canonical run. V24 дал +38,89%, но Sharpe 0,739 и MDD
−14,28% оба хуже frozen V12, поэтому verdict `NO_GO`; модуль сохраняется для exact replay.

### `market_lab.futures.stlfsi_source`

Скачивает один server-bounded FRED CSV `STLFSI4` за `2018-01-01..2025-12-31`, сохраняет
raw response в gzip/base64 с SHA и строит weekly processed frame без заполнения missing.
Официальная structural boundary равна нулю: positive означает above-average financial
stress, zero/negative — normal-or-below. Friday-ending observation получает
консервативный `available_at` только в конец следующего Thursday Chicago, на день позже
обычного Wednesday update. Canonical V1 содержит 417 rows, 416 доступны до protected
boundary; raw replay exact. Источник current-vintage и использует нынешнюю Version 4 на
всей истории, поэтому не является independent PIT confirmation.

### `market_lab.futures_v25_stlfsi_stress_governor`

Импортирует byte-identical V12 и применяет global binary scale только к его исходным
weekly weights. Latest STLFSI4 выбирается backward `merge_asof` по
`available_at <= decision_at`; fresh complete value `<=0` даёт scale 1, positive,
missing или старше 14 дней — scale 0. V12 next-open mapper сам добавляет необходимые roll
decisions. Перед market outcomes runner проверяет все source SHA, manifest/sidecar,
декодирует raw CSV и требует exact replay processed/coverage. Config SHA `dd8b6051...`
фиксирует один вариант и weekly counts до PnL. Pre-outcome commit `74c5461` был pushed.
Canonical result улучшил V12 return и Sharpe, но MDD хуже на 0,0736 п.п.; strict verdict
`NO_GO`. Модуль сохраняется для exact replay и будущей forward/PIT validation.

### `market_lab.futures_v26_stlfsi_levered_ruonia_capacity`

Компонует immutable V25 governor и V15 collateral без нового сигнала. Governed weekly
weights отображаются на factual active contract в admissible base units, после mapping
умножаются ровно на 2. Ledger запускается через тот же 2x normalization contour, но с
`unexecutable_target_policy=cancel_and_clip`: factual no-open target отменяется, а
известная lagged-volume capacity ограничивает заявку до submission. RUONIA начисляется
только на незанятое обеспечение и не влияет на будущий sizing. V26 дал CAGR >23% во всех
cost scenarios и 0 critical, но MDD >33%, поэтому immutable verdict `NO_GO`.

### `market_lab.futures_v27_key_rate_extreme_governor`

Наследует все exact inputs/economics V26 и добавляет raw-replayed официальный CBR
key-rate state до 2x multiplier. `verify_key_rate_bundle` проверяет manifest request,
request-body SHA, raw bytes/SHA, повторяет SOAP XML parse и требует exact equality с
filtered `cbr_daily.parquet`. На weekly decision выбирается только latest
`available_at <= decision_at`; age >7 дней fail-closed. V25 pass допускается при rate
`<20%`, rate `>=20%` переводит все targets в cash. Counts sealed до market outcome.
Canonical V27 прошёл все gates и сохраняется как главный research lead только для новой
unseen/PIT validation; модуль не разрешает live trading.

### `market_lab.futures_v27_robustness`

Читает только byte-pinned `session_date` и `combined_ending_equity` трёх canonical V27
ledgers и отдельно воспроизводит исходные metrics. Неизменяемый post-selection audit
считает rolling 252-session paths, leave-one-calendar-year-out, deflated-Sharpe
sensitivity и circular moving-block bootstrap для 5/21/63-session blocks. Все bootstrap
samples и summaries сохраняются во внешнем immutable run. Его частоты описывают только
повторную выборку уже увиденной истории и не являются independent validation или
калиброванным прогнозом. Canonical V27-R1 завершён: 180 000 bootstrap paths, 3 063
rolling windows и verdict `INTERNAL_ROBUSTNESS_SUPPORTS_UNSEEN_VALIDATION`; 20% получил
только внутреннюю поддержку, 50% — нет.

### `market_lab.futures.moex_pre2018_core4_source`

Отдельный source-only collector для ранее не просмотренного периода 2012–2017. Он
исчерпывает официальный expired-security finder, но допускает только exact shortname set
из config (155 BR/MIX/RI/SI contracts), затем проверяет description dates и RFUD board
history. Daily EOD запрашивается закрытой схемой и только с exact `history.cursor`;
каждый segment обязан быть non-empty. Raw responses, discovery/contracts/boards/segments,
daily observations и coverage атомарно сохраняются во внешнем immutable bundle. Модуль
не вычисляет returns, targets, labels или PnL; V28 потребует отдельного protocol seal.

### `market_lab.futures.moex_pre2018_core4_derived`

Source-only преобразование byte-pinned MOEX bundle 2012–2017 в common factual-session
panel, causal active-contract map, contract observations и lag-1 conservative spec proxy.
Оно использует существующие frozen roll defaults, не переписывает прошлое при roll,
сохраняет отсутствующий participant OI как missing и проверяет, что ни одна выходная
таблица не содержит return/target/label/signal/strategy/equity/PnL columns. Protocol D1
SHA `a633883d...`; output immutable и находится во внешнем хранилище. Это всё ещё source,
а не strategy validation.

D1 source audit обнаружил persistent SI `carry_unfilled_exit`, потому что старые
serial-month contracts попали в nearest-expiry chain. D1 остаётся immutable failed
artifact. `market_lab.futures.moex_pre2018_core4_derived_v2` добавляет только structural
cycle admission: H/M/U/Z для SI/RI/MIX, все месяцы для BR. Код требует exact contract/
daily/roll counts и ноль unresolved roll/exit до atomic publication. Protocol D2 SHA
`7b60afbf...`; никакие strategy outcomes для correction не использовались. D2 не
опубликовал output, потому что source имеет clean SI flat gap между декабрём 2016 и
первой строкой 2017, а gate ожидал непрерывный roll. V3 SHA `d21dd650...` наследует D2,
но pin-ит exact exit/flat/re-entry dates и action counts; gap всегда cash и никогда не
превращается в synthetic return. Canonical D3 manifest SHA `3ab20092...`; все exact
gates прошли, unresolved roll/exit отсутствуют.

### `market_lab.futures.futoi_intraday_source`

Resumable current-vintage collector полного FUTOI 5m. Analytical
endpoint ограничивает ответ 1 000 строками и игнорирует обычный `start`; поэтому loader
делает один ticker/day request, архивирует каждый raw response и считает ответ ровно из
1 000 строк недоказанно полным. Финальная пара сверяется с отдельным `latest=1` proof.
Для каждой строки сохраняются official SYSTIME и actual retrieval; causal contract равен
`max(SYSTIME + buffer, retrieval_at)`. Поэтому bundle пригоден для будущего forward
collector, но не для historical PnL 2021–2025 без original-vintage archive.

### `market_lab.filings`

Содержит schema, revision logic, extraction и source research для корпоративной
отчётности. Production sleeve sleeping, пока нет прав и полного PIT document corpus.

## Временной и execution contract

Нормальный decision flow:

```text
completed information at t
  → decision stamped at t
  → order cannot fill before factual t+1
  → exit requires an observable factual bar/open
```

Для фьючерсов contract id фиксируется в момент решения. Если требуемый successor bar,
open, exit, spec или settlement не доказан, результат unresolved. Нельзя заменять его
синтетическим continuous price.

## Run artifact contract

Полноценный новый run должен содержать:

- exact resolved config и protocol SHA;
- code/data identities;
- train/calibration audit;
- OOS predictions;
- orders/trades и ledger;
- coverage/unresolved reasons;
- metrics при базовых и stress costs;
- human-readable report и verdict.

Большие run artifacts остаются во внешнем хранилище. Их canonical path и главные hashes
фиксируются в [EXPERIMENTS.md](EXPERIMENTS.md).

## Технический долг путей

Часть новых модулей вычисляет `PROJECT_ROOT / "data"` и `PROJECT_ROOT / "runs"` напрямую.
Пока это поддерживается локальными junctions. Если появится необходимость Linux/CI или
нескольких data roots, следующий рефакторинг должен ввести один validated settings object,
но не менять economics или identities уже канонических run.
