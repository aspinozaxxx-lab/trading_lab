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
