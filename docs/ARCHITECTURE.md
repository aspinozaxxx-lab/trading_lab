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

### `market_lab.futures.moex_pre2012_core_source`

Source-only fail-closed wrapper над byte-pinned pre-2018 collector для exact 81
контракта 2008–2011. Wrapper задаёт более ранние границы, exact BR/MIX/RI/SI aliases,
проверяет metadata-audit invariants и pin-ит собственный и parent module SHA. Нормализует
те же discovery/contracts/boards/segments/daily/coverage tables, но публикует их только
после exact contract/date/schema checks во внешний immutable каталог.

Каждый HTTP response архивируется с exact URL и retrieval timestamp. Встроенный replay
подменяет сеть последовательностью raw records, повторяет discovery, metadata и cursor
pagination и сравнивает все восстановленные таблицы с Parquet artifacts. Модуль не
содержит strategy/return/PnL engine. Даже после успешной collection 2008–2011 цены нельзя
использовать до отдельного derived-source и strategy seal.

V1 fail-closed parser не допускал official identity-only daily placeholders. V2 находится
в `market_lab.futures.moex_pre2012_core_source_v2`: scoped context подменяет только daily
parser на время collection/replay и гарантированно восстанавливает parent binding.
NULL-price + NULL/zero-activity строка остаётся в daily table с исходной identity,
missing values и false flags; она не становится баром или zero return. Persistence
reuse-ит V1 serialization во временном каталоге, добавляет V2 parser contract/counts,
пересчитывает manifest identity и только затем атомарно публикует отдельный V2 output.
Canonical V2 manifest SHA `e06fd978...`: 8 381 rows, 81 contracts, 224 requests и две
inert identities. Встроенный и отдельный replay дали 41/41 checks true.

### `market_lab.futures.moex_pre2012_core_derived_v1`

Outcome-free transformation source V2 в variable-availability causal panel. Сначала
official month-code filter исключает только десять serial SI contracts. Shared panel
builder вызывается в exception-safe scoped contexts: отдельно для SI/RI/BR и отдельно
для позднего MIX, после чего исходный global universe обязательно восстанавливается.

Master calendar — пересечение factual SI/RI/BR dates. До первой factual MIX session
модуль создаёт только explicit flat/mask rows: contract, curve, price, volume и OI
missing; backfill и zero return невозможны. Actual contract observations остаются
source-only, spec proxy использует строго lag-1 session, roll adjustment только forward.
Persistence атомарна, а `--audit-only` заново строит все четыре таблицы и сравнивает их.

`market_lab.futures.moex_pre2012_core_derived_v2` — узкий wrapper после D1 manifest
failure. Он раздельно интерпретирует source acquisition protection (`2026-01-01`) и
derived market ceiling (`<2012-01-01`), scoped подменяет только source verifier и output
identity, затем восстанавливает D1 globals. Panel/roll/spec/availability build остаётся
D1-identical. V2 публикуется через staging и добавляет explicit D1 failure lineage.
Его immutable output был создан после seal `fa61763`, но acceptance audit дал 25/27:
значения всех четырёх frames совпали, а два false checks вызвали только bool/object
round-trip в panel и tuple/list JSON round-trip в audit; market mismatch отсутствует.

`market_lab.futures.moex_pre2012_core_derived_v3` — persistence-only successor. Он
byte-pin-ит D2 config/module и rejected manifest, до записи переводит только два
nonmissing flag columns в bool и admitted month-code containers в JSON-native lists.
V3 не меняет market values, calendar, admission, availability, roll или spec semantics,
публикует отдельный immutable suffix и заново сравнивает каждый frame/audit с rebuild.
Seal `afaa278` предшествовал build; canonical manifest SHA `ff9b2771...`, 27/27 replay
checks true. Отдельный strict-dtype audit подтвердил values+dtypes exact всех frames.

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

### `market_lab.futures.pre2018_macro_source`

Отдельный source-only collector внешних режимов для unseen 2012–2017. Он server-bounds
FRED STLFSI4 и official CBR RUONIA/KeyRateXML, архивирует три exact raw responses,
пересчитывает conservative `available_at`, сохраняет missing и публикует immutable
Parquet/manifest bundle. Processed availability физически ограничена до 2018; schema
fail-closed запрещает price/return/target/signal/equity/PnL columns. Protocol S1 SHA
`3daa3c40...`; источник не является strategy outcome. S1 transport failed before any
persisted response. `pre2018_macro_source_v2` wraps the same collector and changes only
User-Agent to the empirically compatible `curl/8.10.1`; S2 SHA `4ad7f034...`. S2 fetched
all responses but published nothing when historical RUONIA publication timing proved
missing for 1 400/1 478 rows. `pre2018_macro_source_v3` inherits S2 byte-identical and
only preserves those dates and `available_at` as missing; it never infers timing or
credits collateral income. S3 SHA `ae575962...`; canonical manifest SHA `949bc7bf...`,
raw replay and every artifact/temporal/schema check passed.

### `market_lab.futures_v28_pre2018_unseen_validation`

Одноразовая external-period validation frozen V27 economics на D3 2012–2017. Модуль
reuse-ит V12 trend/portfolio, V26 capacity-aware 2x ledger и exact cost scenarios, но
имеет отдельные pre-2018 governors, annual metrics и collateral evaluator. Последний
credit-ит только RUONIA с explicit causal `available_at`; неизвестный timing остаётся
NaN и даёт tagged no-credit interval. Output immutable во внешнем `runs/`; verdict
разделяет поддержку CAGR 20% и 50%, но никогда не включает live admission.

### `market_lab.futures_v29_risk_first_roll`

Post-V28 execution correction поверх byte-pinned V28. Модуль не меняет signal,
governors, leverage, collateral, costs или target gates. Только при переходе с
удерживаемого old contract на новый он сначала проверяет, помещается ли полный выход из
старой позиции в factual 1% lagged-volume capacity. Если да, новый вход независимо
clip-ится к своей capacity или заменяется cash; если нет, old position сохраняется и
ledger остаётся fail-closed. Подмена admission выполняется транзакционно только на время
одного ledger run и восстанавливается даже при exception. V29 явно помечается как
post-outcome adaptive correction, а не independent validation; output immutable и live
trading запрещён.

Canonical V29 подтвердил сам механизм: все три ledgers complete, roll cancellations,
rejected legs, critical failures и unresolved равны нулю. Экономический verdict при этом
`FAIL_POST_V28_20`: исправный execution показал низкий CAGR и высокую MDD, поэтому модуль
остаётся reusable execution evidence, но не прибыльной стратегией.

### `market_lab.futures_v30_three_sleeve_risk_restoration`

Новая development target family поверх outcome-free D3 2012–2017. Модуль строит три
равно взвешенных bounded компонента: frozen V12 absolute trend, sign причинного
front/next roll yield и cross-sectional demeaned trend с clipping. Затем reuse-ит V12
weekly covariance/turnover constructor, сначала отображает 1x веса и roll events на
следующий factual open, и только потом применяет последний известный multiplier
`min(2, 0.20 / expected_vol)`. Exact V29 risk-first roll/capacity ledger остаётся
исполнителем. Canonical output включает 1x и hard-2x sensitivity, три main cost ledgers,
rolling 252, circular-block bootstrap и leave-one-year-out. V30 явно selected на уже
открытом 2012–2017 и может только породить отдельный pre-2008 strategy seal, не live.

`market_lab.futures_v30_three_sleeve_risk_restoration_v2` — узкий wrapper после V1
pre-execution failure. Он byte-pin-ит V1 config/module, наследует все source/signal/
target/risk/execution/robustness функции и меняет только отрицательно сформулированный
служебный факт на positive proof `pre2012_outcomes_not_read_by_V30=True`. V1 не создал
output и не запускал ledger; V2 публикует отдельный immutable suffix. Seal `aea34e4`
предшествует canonical run `v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a`.
Read-only replay подтвердил 33/33 artifacts, 86/86 checks и 13/13 assessment. V2 теперь
является frozen development parent: любой 2008–2011 economic read обязан идти через
новый wrapper/protocol V31, который pin-ит его bytes и не меняет economics.

### `market_lab.futures_v31_pre2012_temporal_validation`

One-shot temporal wrapper для outcome-free D3 2008–2011. Он byte-pin-ит V30-D2
config/module/canonical metrics/identity и наследует signal, risk, execution и costs без
refit. Единственная source-semantic адаптация разрешает missing `curve_available_at`
только для exact 727 строк MIX с причиной `asset_not_yet_available`; эти строки остаются
flat и не backfill-ятся. Отдельный adapter добавляет к 727 post-initial flat rows только
предыдущую factual decision date, необходимую полному four-asset mapper; contract,
tradability, price и signal остаются missing/false. Master calendar SI/RI/BR даёт
253-ю observation `2009-10-13`,
weekly decision `2009-10-16` и первый fill `2009-10-19`. Metadata-only preflight читает
только hashes, schemas, dates и masks и проходит 86/86; economic loader вызывается лишь
после отдельного commit/push seal. Output содержит те же шесть scenario views, exact
ledger/coverage и заранее зафиксированные rolling/bootstrap/leave-year-out gates.
Seal `370b4d8` предшествует единственному canonical run
`v31_pre2012_temporal_20260901T145938Z_6dcb6dab`. Read-only audit подтвердил 35/35
artifacts, 122/122 checks и exact шесть metric replays. Verdict
`UNSEEN_TEMPORAL_NO_GO_20`: execution complete, но frozen V30 economics не перенеслась.
V31 теперь immutable отрицательное evidence; повтор с другим window/sign/period запрещён.

### `market_lab.futures.moex_calendar_spread_source`

Source-only collector новой market-neutral family. Catalog строится из official MOEX
futures series: SECID обязан разлагаться на два same-root outright, а человекочитаемый
archive code выводится только из official leg names и сверяется с
`ArchiveSpreads.asmx/GetSpreadList`. Для каждого из 110 выбранных spread collector
сохраняет RFUD board/history JSON, exact ASP.NET page bytes и exact Windows-1251 CSV
export bytes.

Два источника не смешиваются: `iss_daily.parquet` хранит settlement/OI schema, а
`public_archive_daily.parquet` — Last/Bid/Ask/High/Low/Amount/Volume/Trades по официальным
archive labels. Public rows вне ISS board/series interval, last вне reported range и
crossed closing quote сохраняются с flags. Parser сначала проверяет весь CSV и аварийно
останавливается при любой market-value дате `>=2026-01-01`, затем нормализует только
`2021–2025`. Bundle публикуется атомарно и immutable; audit byte-проверяет artifacts и
полностью replay-ит series, boards, ISS pages, WebForms и CSV. Модуль не имеет кода
returns/targets/PnL и не разрешает live trading.

### `market_lab.futures.moex_calendar_spread_source_v2`

Минимальный wrapper над byte-pinned V1 после его fail-closed collection без output.
Wrapper делает shallow structural copy raw ISS payload и заменяет только пустой или
whitespace `ASSETCODE` на missing перед V1 parser. Исходный raw object и сохраняемые bytes
не мутируются; nonblank mismatch, все cursor/schema/date/archive gates и atomic output
остаются V1. На время collect/audit parent parser подменяется context manager и всегда
восстанавливается, включая exception. V2 имеет отдельный config SHA и output `-v2`,
поэтому V1 seal и возможный forensic replay не перезаписываются.

### `market_lab.futures.moex_calendar_spread_source_v3`

Collection-only wrapper после второго fail-closed запуска без output. Он копирует V1
orchestration, наследует V2 parser context и допускает ровно одну closed exception:
`BRF1BRG1` с exact official dates имеет `iss_request_till < iss_request_from`, поэтому
получает пустой ISS frame и ноль ISS requests. Catalog/board dates не переписываются,
а public archive page/CSV всё равно обязательны. Exact identity и все восемь дат/кодов
pin-ятся кодом и config; любое другое пустое окно аварийно. Manifest имеет новый V3
bundle id, output отдельный и immutable; audit остаётся полным parent raw replay.

Canonical V3 опубликован во внешнем data store и дважды прошёл 47-check replay audit:
110 catalog rows, 9 997 ISS rows, 10 157 public-archive rows и 487 raw responses. Manifest
SHA `94d5fab4...`, raw SHA `ccaba170...`. Source disagreements остаются explicit coverage
flags; outcome columns отсутствуют. Downstream обязан использовать новый immutable
derived artifact и отдельный SHA, а не добавлять strategy fields в source bundle.

### `market_lab.futures.moex_calendar_spread_derived_v1`

Source-only D1 byte-проверяет canonical V3 и lag-1 conservative spec proxy, затем строит
три отдельные таблицы: все admissible candidates, единственный active spread на
asset/date и coverage с явными source gaps. В catalog допускаются только regular
adjacent legs, у которых near expiration совпадает с официальной датой последней
торговли spread; row требует reported activity, нахождение внутри series interval,
полный uncrossed Bid/Ask и неотрицательное время до near expiry. Active выбирается как
minimum days-to-near; tie аварийно запрещён, locked quote сохраняется флагом.

Обе ноги получают собственный canonical contract id и только strictly-prior sizing
observation. Point values не усредняются и не считаются одинаковыми. Closed schema
запрещает return/target/signal/strategy/equity/PnL fields; build атомарный и immutable,
audit заново строит все таблицы и требует exact equality. Config SHA `657fd42b...`
зафиксирован push commit `35ab387` до первого build. Canonical manifest SHA
`b5e15c2e...`; initial build и отдельный replay дали 29/29 true. Экономика, execution
и стратегии должны получить другой pre-outcome seal после manifest D1.

### `market_lab.futures.calendar_spread_v1`

Первый economic runner новой family читает byte-pinned D1 только после проверки seal.
Он строит prior-only same-spread baselines 10/20/40 observations, exact-date cross-asset
features и monthly expanding MLP. У neural train каждая five-observation label обязана
закончиться строго раньше refit date; scaling и median-imputation fit-ятся только на
этом прошлом, missing indicators сохраняются.

Trade planner содержит ровно десять frozen rules и stateful take/stop/time/expiry exits.
Ledger интерпретирует official spread как `far - near`: direction +1 означает long far,
short near в строго одинаковом количестве. Decision исполняется не раньше следующего
общего factual open, PnL ног и costs считаются раздельно, capacity равна минимуму 1%
lagged volume ног, а full exit causally retry-ится. Три cost scenarios и внутренний
2024–2025 evaluation фиксированы config SHA `e74dab97...`; implementation SHA
`f8d0108e...`. Исторической multileg queue нет, поэтому это conservative synchronized-
leg proxy и development test, не live evidence.

### `market_lab.futures.calendar_spread_v2`

Минимальный wrapper после fail-closed V1 без output. Он загружает и byte-проверяет V1,
временно подменяет только `_period_metrics`: если completed trades отсутствуют, создаёт
пустые typed `status` и `net_pnl` Series вместо scalar NaN. Для непустого trade frame
вызывается исходная V1 функция без изменения. Context всегда восстанавливает parent
globals, включая exception; resolved protocol и immutable output получают отдельную V2
identity. Ни signals/MLP, ни ledger/execution/costs/gates wrapper не меняет.

Canonical V2 manifest SHA `facc159f...`; initial и повторный audits полностью true.
Run технически complete, но economic evaluation пуста: EOD width filter оставил только
13 plans 2021–2022 и ноль в 2024–2025, несмотря на 3 734 causal MLP predictions. Verdict
`NO_GO_NO_EVALUATION_EXPOSURE`; любые дальнейшие изменения помечаются post-outcome
adaptive и обязаны получить новую protocol/output identity.

### `market_lab.futures.calendar_spread_v3`

Post-V2 adaptive wrapper для исправления семантики источника, не параметров стратегии.
Feature builder передаёт parent-коду factual reported `Last` вместо closing Bid/Ask
midpoint. Plan builder сохраняет actual width в neural features, но нейтрализует только
его admission predicate, потому что fill проверяется по следующему общему outright open
и lagged capacity ног. Strict-positive quote flag остаётся обязательным.

Wrapper одновременно наследует V2 empty-metric adapter и через один exception-safe
context подменяет ровно три parent hooks плюс resolved config path. Config SHA
`c38a7356...`, module SHA `fb9b4e15...`; thresholds, MLP, ledger, costs и gates не
меняются. Результат всегда adaptive development evidence и не может подтвердить live.

Canonical V3 manifest SHA `a7de7e04...`; оба audits true. Source-semantics fix увеличил
число plans с 13 до 1 666 и дал полноценную evaluation, но primary и stress отрицательны.
Лучший exploratory cross-sectional sleeve слегка положителен только при primary costs и
отрицателен на development/stress. V3 остаётся reusable evidence, что проблема EV2 была
в admission, а не доказательством прибыльной стратегии.

### `market_lab.futures.calendar_spread_v4`

Post-selection wrapper добавляет к V3 causal cost hurdle. Он временно расширяет active
schema шестью strictly-prior leg spec fields, вычисляет ожидаемую оставшуюся амплитуду
до frozen exit и сравнивает её с полной stress round-trip стоимостью. Допуск требует
ratio `>=2`; actual ledger всё равно повторно применяет исходные capacity/margin/costs.

Promotion использует неизменные числовые gates V1, но к выбранному после V3
`cross_sectional_extremes` и никогда не маркирует результат independent. Context также
наследует V2 empty-schema и V3 Last/width corrections, подменяет resolved config/report
и полностью восстанавливает globals. Config SHA `b7ddc0ac...`, module SHA `17351808...`.

Canonical V4 manifest SHA `e9b4e301...`; replay checks полностью true. Cost hurdle
сохранил 38 evaluation trades и небольшой primary плюс, но development и stress остались
отрицательными. Verdict `NO_GO`; этот wrapper остаётся аудируемым отрицательным
экспериментом, а не основой для дальнейшей подстройки threshold или leverage.

### `market_lab.futures.moex_multileg_execution_source`

Локальный source-only ingestion для licensed/member MOEX reports. Discovery извлекает
единственную package date из имени до открытия CSV/ZIP и fail-closed запрещает undated,
outside-period и protected `2026+` objects. Parser разделяет market-wide trades/
dictionary, participant fills/actions и technical leg deals; schema не выпускает user,
clearing codes или comments. Missing IDs/fees/prices не заменяются нулём.

`event_at_moscow` предназначен только для replay решения, принятого раньше события.
Сам report считается доступным для feature engineering лишь с 00:00 мск следующего дня.
Full build требует exact two-leg dictionary, unique market trade identity, совместное
core date coverage и exact participant fill→2 legs linkage. Config SHA `464cce7a...`,
module SHA `5e64ba6a...`; synthetic build/audit прошёл, licensed canonical ещё не создан.

### `market_lab.futures.futoi_intraday_source`

Resumable current-vintage collector полного FUTOI 5m. Analytical
endpoint ограничивает ответ 1 000 строками и игнорирует обычный `start`; поэтому loader
делает один ticker/day request, архивирует каждый raw response и считает ответ ровно из
1 000 строк недоказанно полным. Финальная пара сверяется с отдельным `latest=1` proof.
Для каждой строки сохраняются official SYSTIME и actual retrieval; causal contract равен
`max(SYSTIME + buffer, retrieval_at)`. Поэтому bundle пригоден для будущего forward
collector, но не для historical PnL 2021–2025 без original-vintage archive.

### `market_lab.futures.moex_curve_coefficient_regime_source`

Строит maturity-agnostic event context из официального MOEX volatility-curve archive.
Raw coefficients S/A/B/C/D/E не трактуются как конкретный expiry без точного
`OPTION_SERIES_ID -> expiration` proof. Для каждого SI/RI/BR/MIX event сохраняются
median, IQR, median delta, series count и одновременная cross-asset dispersion. Источник
не содержит settlement/price/return/target/PnL и имеет отдельный immutable manifest.

### `market_lab.futures.curve_regime_intraday`

Outcome-agnostic V32 core. Он строит gap-tolerant признаки четырёх рынков только из
completed 10m buckets, exact six-bucket open-to-open labels, causal covariance, monthly
purged train/calibration/test, full/ablation predictions и bounded target weights.
Default-объекты immutable; все feature/model/risk числа дополнительно frozen dataclass
invariants. Модуль не открывает файлы и не публикует run самостоятельно.

### `market_lab.futures_v32_curve_regime_intraday`

Byte-sealed orchestration V32. Runner проверяет config sidecar, hashes всех transitive
10m manifests, effective-date active map, strictly-prior spec proxy и curve manifest.
`--preflight-only` читает только identity/schema/date/contract/availability columns.
Economic mode затем строит три fixed models, пять ledgers, exact artifact hashes и
atomic immutable run directory; `--audit-run` повторно проверяет bytes/rows/checks.
Неполная exit capacity остаётся explicit unresolved и economic NO-GO, но не ломает
целостность опубликованного отрицательного run.

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
