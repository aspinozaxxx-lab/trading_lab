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
