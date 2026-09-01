# Runbook

Все команды выполняются из корня `D:\Projects\trading_lab` в PowerShell. Канонические
run directories неизменяемы: для новых запусков используй новый output path.

## 1. Внешнее хранилище и junctions

Ожидаемая структура:

```text
D:\Projects\trading_lab_data\data
D:\Projects\trading_lab_data\runs
D:\Projects\trading_lab_data\models
```

Проверка существующих links:

```powershell
Get-Item .\data, .\runs, .\models | Select-Object FullName, LinkType, Target
```

Рекомендуемый setup (создаёт только отсутствующие targets/junctions и не заменяет
существующие каталоги):

```powershell
.\scripts\setup_external_storage.ps1
```

Для другого расположения:

```powershell
$env:MARKET_LAB_STORAGE_ROOT = 'E:\market_lab_storage'
.\scripts\setup_external_storage.ps1 -DataRoot $env:MARKET_LAB_STORAGE_ROOT
```

Не создавай junction поверх обычного непустого каталога. `data/`, `runs/` и `models/`
игнорируются Git и не должны попадать в commit.

Часть старых sealed V8 loaders сама отклоняет junction, потому что проверяет физический
resolved path строго под repo root. Не ослабляй и не reseal старый протокол задним числом:
для такого replay сначала создай новую migration-compatible loader version и новый code
identity. Основные config loaders уже допускают только repo-relative alias, чей physical
target находится внутри объявленного external storage root.

## 2. Окружение

CPU/base:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\market-lab.exe doctor
```

RTX 5090/CUDA environment использует отдельный полный lock:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.sequence.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Проект рассчитан на Python `>=3.11,<3.12`. Canonical GPU runs использовали PyTorch
2.13/CUDA 13 и bfloat16; не сравнивай byte/model identity после смены runtime.

## 3. Проверки

Быстрая проверка:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Перед дорогим run сначала запускай целевые tests, например:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_futures_v9_structural.py tests/test_futures_v9_structural_robustness.py tests/test_futures_v9_structural_execution.py
```

Проверка config seal:

```powershell
Get-FileHash .\configs\futures_v9_structural_execution.yaml -Algorithm SHA256
Get-Content .\configs\futures_v9_structural_execution.sha256
```

До загрузки Parquet/NPZ сверяй путь, SHA и temporal maximum из
[DATA_AND_INTEGRITY.md](DATA_AND_INTEGRITY.md).

## 4. Воспроизведение V9

### Structural proxy

Использовать existing verified cache без сети:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v9_structural.run --no-download
```

С загрузкой official ISS используется та же команда без `--no-download`. Не делай этого,
если цель — byte replay старого source archive.

Robustness и execution:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_futures_v9_structural_robustness.py
.\.venv\Scripts\python.exe .\scripts\run_futures_v9_structural_execution.py
```

Обе команды адресуют frozen canonical input. Не меняй их economics ради положительного
результата; исправленная execution study должна получить новый protocol/version/output.

### Sparse events

```powershell
.\.venv\Scripts\python.exe -m market_lab.event_alpha_v1.run
```

Frozen event/timing hybrid с новым output directory:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_futures_v9_event_timing_hybrid.py --output-dir runs\futures_v9_event_timing_hybrid_<new-id>
```

### Corridor

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v9_corridor.run
```

Внимание: текущий CLI использует фиксированный `runs/futures-v9-corridor-development-v1`.
Не запускай его на canonical external store. Сначала добавь versioned output interface или
используй отдельный scratch data root; это изменение не должно менять модель/экономику.

### Continuous 10m timing

Сначала строится sealed tensor:

```powershell
.\.venv\Scripts\python.exe .\scripts\build_futures_v9_intraday_timing_tensor.py
```

GPU runs:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_futures_v9_intraday_timing.py --output runs\futures_v9_intraday_timing_<new-id>
.\.venv\Scripts\python.exe .\scripts\run_futures_v9_intraday_timing_v2.py --output runs\futures_v9_intraday_timing_v2_<new-id>
```

Не создавать v3, меняющий только threshold. Нужны новый execution mechanism или новая
независимая информация.

### Market graph

```powershell
.\.venv\Scripts\python.exe .\scripts\run_market_graph_v1.py --output runs\market_graph_v1_<new-id>
.\.venv\Scripts\python.exe .\scripts\run_market_graph_v2_long_only.py --output runs\market_graph_v2_<new-id>
```

V1 требует GPU. V2 использует уже sealed V1 relative-momentum predictions и не должен
переобучать или изменять score.

### Triangular RI/MIX/SI V10/V11

Оба canonical run уже завершены с NO-GO. Для byte-new replay всегда указывай новый
external output directory:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_futures_v10_triangular_relative_value.py --output runs\v10_triangular_<new-id>
.\.venv\Scripts\python.exe .\scripts\run_futures_v11_liquidity_buffered_open.py --output runs\v11_buffered_open_<new-id>
```

V10 обязан останавливаться при capacity failure. V11 может отменить неисполненный entry,
но уже открытая корзина допускает только шесть exact same-contract exit retries. Не
ослаблять эти правила и не менять thresholds в существующих версиях. Поле ISS `end` —
время последней сделки внутри bucket; scheduled decision end равен `timestamp + 10m`.

### V12 core-four correlation trend

Canonical run уже выполнен. Для byte-new replay указывай только новый external root;
protocol SHA и economics менять нельзя:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_futures_v12_core4_correlation_trend.py `
  --output-root D:\Projects\trading_lab_data\runs
```

Команда проверяет config/data hashes и границу 2026 до загрузки price columns, затем пишет
уникальный immutable `v12_core4_trend_<timestamp>_<config8>`. Не использовать replay для
подбора horizons, costs, sleeves или universe по уже увиденному 2021–2025 результату.

### V13 trend plus curve confirmation

Canonical V13 уже выполнен и получил `NO_GO` как stability replacement. Byte-new replay
создаёт отдельный immutable каталог, но не разрешает подбирать carry threshold:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v13_trend_carry_confirmation `
  --output-root D:\Projects\trading_lab_data\runs
```

### MOEX RVI source

Canonical snapshot уже находится во внешнем хранилище. Downloader намеренно не
перезаписывает существующий каталог; новый аудит выполняй в другом versioned path:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.rvi_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\moex-rvi-<new-id>
```

Каждый URL физически ограничен `till=2025-12-31`. Processed dataset хранит
`conservative_available_from_date`, а feature join обязан требовать
`source_date < decision_date`.

### MOEX FUTOI daily-last source

Canonical target-free snapshot уже находится во внешнем хранилище. Новый аудит всегда
пиши в другой versioned каталог:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.futoi_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\moex-futoi-<new-id>
```

Downloader использует `latest=1`, поэтому это последний официальный FIZ/YUR snapshot
каждого дня, а не полный 5m архив. Для close-based решения требуется
`source_date < decision_date`; raw данные нельзя публиковать, пока права не проверены.

### V14 prior-session RVI governor

Canonical run уже завершён с `NO_GO`; replay не предназначен для перебора RVI mapping:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v14_rvi_risk_governor `
  --output-root D:\Projects\trading_lab_data\runs
```

### V15 levered V12 plus causal RUONIA collateral

Canonical V15 завершён с `NO_GO`: CAGR выше 20%, но MDD выше 25% и execution неполон.
Replay создаёт новый immutable каталог и не разрешает менять leverage/RUONIA rules:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v15_levered_ruonia_collateral `
  --output-root D:\Projects\trading_lab_data\runs
```

2x admission изолирован внутри V15: общий V12 mapper сначала строит те же даты/контракты,
после чего target удваивается; frozen ledger normalizer транзакционно масштабируется и
обязательно восстанавливается. Config SHA должен оставаться `8cbcf307...`.

### V16 FUTOI crowding governor plus capacity-aware execution

Canonical V16 имеет статус `INVALID_FUTOI_LOOKAHEAD`: 932/1 044 FUTOI states не были
доступны к decision. Текущий entry point намеренно выбрасывает `RuntimeError` до PnL;
команда ниже приведена только как имя заблокированного контура и не должна завершаться:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v16_futoi_crowding_governor `
  --output-root D:\Projects\trading_lab_data\runs
```

Config SHA должен оставаться
`d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070`. Canonical run:
`v16_futoi_governor_20260831T220539Z_d0461775`; его metrics — forensic artifact, не
performance.

Полный FUTOI 5m сохраняется только как current-vintage forward source:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.futoi_intraday_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\moex-futoi-intraday-dev-2020-2025-v2 `
  --staging-directory D:\Projects\trading_lab_data\data\processed\info_radar\.moex-futoi-intraday-dev-2020-2025-v2.staging `
  --max-workers 4
```

Официальный 1 000-row cap срезает годовой ответ, а `start` игнорируется. Collector делает
single-ticker/single-date requests и сохраняет resumable staging. Даже полный bundle не
разрешён для historical PnL: causal availability равна
`max(SYSTIME + buffer, archive_retrieved_at)`.

### EIA WPSR release-vintage source

Canonical v2 bundle уже находится во внешнем хранилище. Новый snapshot всегда получает
другой versioned output; staging можно возобновлять, но его hashes проверяются:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.eia_wpsr_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\eia-wpsr-table1-<new-id> `
  --staging-directory D:\Projects\trading_lab_data\data\processed\info_radar\.eia-wpsr-table1-<new-id>.staging `
  --max-workers 4
```

Collector берёт только issue links `2012-01-01..2025-12-30`, не использует current-vintage
API и не читает market outcomes. Выпуск 31.12.2025 исключён из-за conservative UTC
availability в 2026; stale duplicate 03.07.2019 остаётся в raw/coverage, но не processed.

### V17 EIA physical-balance direction

Canonical V17 завершён с `NO_GO`; replay создаёт новый immutable каталог, но не разрешает
инвертировать signs, менять components/normalization/lag/vol target:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v17_eia_supply_demand `
  --output-root D:\Projects\trading_lab_data\runs
```

Config SHA должен оставаться `1d8eee3f...`. Canonical run:
`v17_eia_supply_demand_20260831T234157Z_1d8eee3f`; execution complete, но primary CAGR
−7,74%, поэтому это отрицательный forensic/development result, не кандидат в live.

### CBR dated liquidity-forecast source

Canonical source-only bundle находится во внешнем хранилище. Для нового versioned
snapshot используй отдельные output и resumable staging paths:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.cbr_liquidity_forecast_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\cbr-liquidity-forecast-<new-id> `
  --staging-directory D:\Projects\trading_lab_data\data\processed\info_radar\.cbr-liquidity-forecast-<new-id>.staging `
  --max-workers 4
```

Collector проверяет дату внутри record, а не доверяет query date, пробует holiday shifts
и не читает market prices/outcomes. Raw CBR pages не распространять: пользовательское
соглашение требует ссылку при цитировании, а отдельное право на raw redistribution не
зафиксировано.

### V18 CBR forward-liquidity direction for SI

После pre-outcome commit/push один immutable run создаётся командой:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v18_cbr_liquidity_forecast `
  --output-root D:\Projects\trading_lab_data\runs
```

Config SHA должен быть `ee2d7fd7...`. Replay не разрешает инвертировать знак, менять
source row, добавлять magnitude threshold или переносить позицию за printed forecast end.

### CBR daily liquidity-factors source

Canonical current-vintage snapshot находится во внешнем хранилище. Новый versioned
snapshot всегда писать в новый directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.cbr_liquidity_factors_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\cbr-liquidity-factors-<new-id>
```

Collector читает одну официальную таблицу, сохраняет raw HTML, processed parquet и
manifest. Он выводит publication date как следующий датированный рабочий день и ставит
availability на 10:31 мск. Это current-vintage/revisable development source, не original
historical vintages; raw не распространять без проверки прав.

### V19 CBR-reported Minfin FX-flow persistence for SI

Канонический immutable run уже создан после pre-outcome commit/push командой:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v19_cbr_minfin_fx_persistence `
  --output-root D:\Projects\trading_lab_data\runs
```

Config SHA должен оставаться `1340ffac...`. Replay не разрешает sign flip, magnitude
threshold/scaling, smoothing, выбор только change days, более ранний timing или blend с
V12/V18 по увиденному V19 result. Канонический verdict — `NO_GO`: total return −0,03%,
Sharpe 0,05, MDD −30,76%; metrics SHA начинается `dff0016e...`.

### Minfin OFZ auction-result source

Canonical source-only bundle находится во внешнем хранилище. Новый immutable version
создаётся отдельным directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.minfin_ofz_auction_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\minfin-ofz-auction-results-<new-id> `
  --max-workers 6
```

Collector не читает market prices/returns/targets/PnL. Он требует reverse chronology,
stable first-page result index, классификацию каждой карточки и полные primary metrics.
Canonical V2 содержит 410 events и 364 primary results; manifest SHA начинается
`c6fcf390...`. Bundle V1 — superseded discovery и не является input эксперимента.

### V20 Minfin OFZ-PD prior-rank demand strength

Pre-outcome commit `4e52378` был pushed, после чего один immutable run создан командой:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v20_minfin_ofz_demand_strength `
  --output-root D:\Projects\trading_lab_data\runs
```

Canonical run:
`runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/`; metrics SHA
`cbfa0c88...`. Verdict `NO_GO`: primary total return −5,35%, CAGR −1,09%, Sharpe −0,63,
MDD −6,19%, 504/504 dependencies complete. Config SHA остаётся `788fadbd...`; запрещены
sign flip, threshold/extreme-only, другой rank window/expiry и добавление failed/PK/IN на
тех же 2021–2025 outcomes.

### CBR macro-survey source

Canonical source-only bundle находится во внешнем хранилище. Новый current-vintage
snapshot всегда получает новый directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.cbr_macro_survey_source `
  --output-directory D:\Projects\trading_lab_data\data\processed\info_radar\cbr-macro-survey-<new-id>
```

Collector не использует Excel/market outcomes: cached XLSX values разбираются стандартной
библиотекой, отсутствующие cells пропускаются, source cell сохраняется. Canonical V1:
11 787 records, 37 months, processed SHA `a139ead8...`, manifest SHA `faae8927...`.
Historical vintages не доказаны; availability равна концу следующего месяца, поэтому
December 2025 недоступен до protected boundary.

### V21 CBR next-year macro revision breadth

Config SHA должен оставаться
`5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc`. Pre-outcome
commit `5414251` был pushed, затем ровно один canonical run создан командой:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v21_cbr_macro_revision_breadth `
  --output-root D:\Projects\trading_lab_data\runs
```

Canonical run:
`runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/`; metrics SHA
`cfc704e7...`. Verdict `NO_GO`: mechanical total return −3,17%, Sharpe −0,08,
MDD −18,79%; coverage 200/202 и 2 critical failures делают ledger incomplete. Replay
создаёт новый immutable directory, но не разрешает sign flip, magnitude thresholds,
новые indicators, другую oil priority, cross-series bridge, risk/expiry tuning или blend
с V12 на тех же 2021–2025 outcomes.

### CBR household inflation/sentiment source и sealed V23

Canonical source-only bundle уже находится во внешнем хранилище. Новый immutable
snapshot всегда получает другой directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.cbr_inflation_expectations_source `
  --output D:\Projects\trading_lab_data\data\processed\info_radar\cbr-inflation-expectations-<new-id> `
  --max-workers 6
```

Collector сохраняет release-specific page/PDF/XLSX и две archive snapshots, разбирает
точные ряды XLSX и сверяет их с one-decimal HTML endpoints. Raw не распространять без
отдельной проверки прав. Sealed V23 имеет config SHA `2a8a35a8...`; после обязательного
pre-outcome commit/push immutable replay создаётся командой:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v23_cbr_household_confirmation_regime `
  --output-root D:\Projects\trading_lab_data\runs
```

До первого run нельзя изменять signs, two-series confirmation, cash rule, risk/expiry или
gates. Canonical run
`runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/`, metrics SHA
`33614e39...`, verdict `NO_GO`: primary return −5,35%, Sharpe −0,16, MDD −13,62%.
После outcome replay не разрешает same-history selection этих параметров.

### FRED/Cboe VIX term-structure source

Canonical V2 хранится вне Git. Новый immutable snapshot обязан иметь другой directory:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.cboe_vix_term_structure_source `
  --output D:\Projects\trading_lab_data\data\processed\info_radar\fred-cboe-vix-term-structure-<new-id>
```

Collector запрашивает только `2018-01-01..2025-12-31`, сохраняет два bounded CSV и не
forward-fill missing pairs. V1 не использовать: parquet timestamp unit не проходила
strict replay. Canonical V2 processed SHA `6ffe7daa...`, manifest SHA `0aecc29fd...`.
Raw значения copyrighted/citation-required и остаются во внешнем хранилище.

### Sealed V24 daily VIX/VIX3M governor

Protocol SHA `f81b5aaa...` разрешает ровно один adaptive development run. До запуска
убедись, что protocol commit уже pushed, а source bundle V2 не изменён:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_futures_v24_cboe_vix_term_structure_governor.py `
  tests/test_cboe_vix_term_structure_source.py tests/test_encoding.py -q
git status --short --branch
.\.venv\Scripts\python.exe -m market_lab.futures_v24_cboe_vix_term_structure_governor `
  --output-root D:\Projects\trading_lab_data\runs
```

Ожидаемый pre-outcome state seal: all `2 024` decisions = `1 785` pass, `167`
backwardation cash, `72` missing/stale cash; OOS `1270` = `1170/53/47`. Любое
несовпадение останавливает run. После первого результата нельзя менять ratio boundary,
четырёхдневную freshness, binary scale или добавлять VIX level/percentile variants на
той же истории.

Canonical run уже выполнен ровно один раз:
`runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/`, metrics SHA `1da1b995...`.
Verdict `NO_GO`: primary +38,89%, CAGR 6,79%, Sharpe 0,739, MDD −14,28%; execution
complete, но Sharpe/MDD хуже V12 и costs выше. Команду выше не повторять для подбора
вариантов на той же истории.

### FRED STLFSI4 source

Canonical V1 хранится вне Git. Для нового immutable forward snapshot используй новый id:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.stlfsi_source `
  --output D:\Projects\trading_lab_data\data\processed\info_radar\fred-stlfsi4-<new-id>
```

Canonical processed SHA `4937b686...`, manifest SHA `1a992f64...`, raw archive SHA
`d9ebef72...`. Bundle содержит 417 Friday-ending rows, 416 причинно доступны до 2026;
raw replay exact и не содержит observations 2026. Availability намеренно отложена до
конца следующего Thursday Chicago. Values copyrighted/citation-required; Version 4
current-vintage history нельзя называть независимым PIT holdout.

### Sealed V25 weekly STLFSI4 governor

Config SHA `dd8b6051...` допускает ровно один adaptive development run, но только после
commit/push implementation и pending-status:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_futures_v25_stlfsi_stress_governor.py `
  tests/test_stlfsi_source.py tests/test_encoding.py -q
git status --short --branch
.\.venv\Scripts\python.exe -m market_lab.futures_v25_stlfsi_stress_governor `
  --output-root D:\Projects\trading_lab_data\runs
```

Pre-outcome state seal: all `418 = 349/68/1`, OOS `261 = 237/24/0` для
pass/stress-cash/missing-cash. Несовпадение останавливает run. После outcome нельзя
менять official zero, 14-day age, binary scale или смешивать V24/V25 по результатам.

## 5. Новый эксперимент

1. Скопируй структуру из [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md).
2. Назначь новый protocol id/version и отдельные config/run paths.
3. Укажи exact input paths, bytes/hashes, temporal boundary и schemas.
4. Зафиксируй train/calibration/OOS и execution до outcomes.
5. Создай SHA:

```powershell
$hash = (Get-FileHash .\configs\<new-config>.yaml -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  <new-config>.yaml" | Set-Content .\configs\<new-config>.sha256 -Encoding utf8
```

6. Запусти tests/preflight, затем experiment.
7. Сохрани metrics, predictions, trades/orders, ledger, coverage, provenance и report.
8. Запиши verdict независимо от желаемого результата.
9. Обнови `docs/EXPERIMENTS.md` и `docs/STATUS.md`.

Не используй этот пример записи SHA для изменения уже sealed config: тогда необходима новая
версия протокола.

## 6. Диагностика частых проблем

- `FileNotFoundError` для `PROJECT_ROOT/data` или `runs`: проверь junctions.
- SHA mismatch: не переписывай файл автоматически; проверь BOM/EOL, bytes и правильный
  external snapshot.
- Timestamps 2026: остановить run, не фильтровать постфактум после загрузки outcomes;
  собрать физически изолированный pre-2026 bundle.
- Missing successor/contract/settle: вернуть explicit unresolved, не bridge/zero-fill.
- Нулевые trades: проверить audit/gates, но не снижать threshold по увиденному OOS.
- Отличающиеся GPU predictions: проверить exact runtime, deterministic flags и checkpoint
  identities; не смешивать с canonical run.

## 7. Handoff checklist

Перед завершением сессии укажи:

- что изменено и какие tests прошли;
- config/data/code hashes;
- новый external run path;
- headline и per-year metrics;
- coverage, unresolved и costs;
- GO/NO-GO/blocked с причиной;
- следующий конкретный шаг;
- обновлены ли `STATUS.md` и `EXPERIMENTS.md`.
