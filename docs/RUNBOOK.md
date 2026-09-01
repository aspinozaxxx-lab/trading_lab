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

Canonical run выполнен один раз:
`runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/`, metrics SHA `c2518d17...`.
Primary +49,07%, CAGR 8,31%, Sharpe 0,818, MDD −14,226%; execution complete. Единственный
false gate — MDD хуже V12 на 0,0736 п.п., поэтому verdict `NO_GO`. Команду не повторять
для selection на той же истории; следующий допустимый шаг — новая forward/PIT validation.

### Sealed V26/V27 capital-efficiency chain

V26 config SHA `2b085890...` фиксирует 2x V25, RUONIA и capacity admission. Canonical
run уже существует: `runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/`,
metrics SHA `b4149969...`. Его не повторять для leverage/haircut/capacity selection:
all-scenario CAGR >23%, execution complete, но MDD >33%, verdict `NO_GO`.

V27 config SHA `7a9a44cf...` добавляет только CBR key-rate `>=20%` global cash state.
Canonical run уже существует: `runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/`,
metrics SHA `5fc1f271...`. Replay/audit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_futures_v27_key_rate_extreme_governor.py `
  tests/test_futures_v26_stlfsi_levered_ruonia_capacity.py `
  tests/test_futures_portfolio_ledger.py tests/test_futures_info_radar.py `
  tests/test_encoding.py -q
```

V27 primary/stress CAGR `28,38%/27,36%`, MDD `20,71%/21,05%`; 115/115 checks,
828/828 dependencies, 0 critical/unresolved. Verdict `GO_TO_NEW_UNSEEN_VALIDATION`, not
live. Не запускай V27 повторно ради выбора threshold/age/scale на 2021–2025. Следующий
runner должен иметь новый protocol id, физически отдельный unseen/PIT input bundle и
быть sealed/pushed до первого outcome.

### Sealed V27-R1 robustness audit

V27-R1 не пересчитывает signal или execution и читает только дату/combined equity из
трёх byte-pinned V27 ledgers. Config SHA `a8d6ed42...` должен быть committed и pushed до
первого чтения daily curve. После этого audit запускается ровно один раз:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures_v27_robustness `
  --output-root D:\Projects\trading_lab_data\runs
```

Canonical audit уже выполнен и повторно запускаться не должен:
`runs/v27_robustness_20260901T054810Z_a8d6ed42/`, metrics SHA `e5c5851f...`.
Он сохранил 180 000 bootstrap paths (3 scenarios × 3 block lengths × 20 000), 3 063
rolling 252-session windows, leave-one-year-out и trial-count sensitivity; 49/49 checks
true. Verdict `INTERNAL_ROBUSTNESS_SUPPORTS_UNSEEN_VALIDATION`: minimum-20 support true,
aspirational-50 false. Результат не является forward probability или independent
holdout; запрещено выбирать block/gate или менять V27 после просмотра audit.

### Sealed MOEX 2012–2017 source collection

Source V3 config SHA `0b86cda4...`, implementation SHA `7dd25e01...`. V1/V2 metadata
preflight failures зафиксированы без daily price response. V3 был pushed commit
`38fc63a`, collection завершён; следующую команду не повторять, потому что output
immutable:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_moex_pre2018_core4_source.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/moex_pre2018_core4_source.py `
  tests/test_moex_pre2018_core4_source.py
.\.venv\Scripts\python.exe -m market_lab.futures.moex_pre2018_core4_source `
  --config .\configs\moex_pre2018_core4_source_v3.yaml
```

Default output:
`data/processed/futures_pre2018/moex-core4-daily-current-vintage-2012-2017-v1/`.
Manifest SHA `e60d0bca...`: 155 contracts, 30 059 rows, 544 requests, maximum date
`2017-12-21`. Collector не перезаписывает существующий каталог. Integrity audit уже
сверил manifest/raw hashes, exact identities и cursor rows. Не считай return/PnL до
отдельного V28 config SHA и pre-outcome push.

### Sealed MOEX 2008–2011 source collection

V1 config SHA `92c7f324...`, wrapper SHA `55965d9c...`, parent collector SHA
`7dd25e01...` был pushed commit `49467bc`. V1 collection fail-closed остановилась без
output на identity-only NULL row `RIM9_2009/2008-09-12`; V1 не повторять. Parser-only
V2 config SHA `74847dd3...`, module SHA `acc547f5...` сохраняет строку missing с false
market/execution flags и не меняет universe/dates/requests. V2 был pushed commit
`617ce72`, collection и отдельный offline audit уже выполнены; команды ниже служат для
аудита, но network collection повторять нельзя:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_moex_pre2012_core_source_v2.py `
  tests/test_moex_pre2012_core_source.py `
  tests/test_moex_pre2018_core4_source.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/moex_pre2012_core_source_v2.py `
  tests/test_moex_pre2012_core_source_v2.py
.\.venv\Scripts\python.exe -m market_lab.futures.moex_pre2012_core_source_v2
.\.venv\Scripts\python.exe -m market_lab.futures.moex_pre2012_core_source_v2 --audit-only
```

Default immutable output:
`data/processed/futures_pre2012/moex-core3-mix-daily-current-vintage-2008-2011-v2/`.
Canonical manifest SHA `e06fd978...`: 8 381 daily rows, 81 contracts, 224 requests,
две inert identities и 41/41 replay checks. Строку network collection выше не запускать;
разрешён только `--audit-only`. Manifest/coverage можно аудировать, но returns/PnL
2008–2011 запрещены до отдельного derived-source и strategy seal.

### Sealed MOEX 2008–2011 causal variable-availability derived source

D1 config SHA `8f5737bc...`, module SHA `d0c22df7...` был pushed `45e55af`, но build
остановился до daily load/output на неверной boundary equality; D1 не повторять.
Boundary-only D2 config SHA `f928e58b...`, module SHA `2e01c3fc...` был pushed
`fa61763`. Его immutable output создан, но rejected final audit (25/27): только
bool/object и tuple/list persistence round-trips, zero market-value mismatch. D2 build
не повторять и output не перезаписывать.

Persistence-only D3 config SHA `93b1d3fb...`, module SHA `438f2dd5...` pin-ит D2
diagnosis и меняет только канонические типы хранения. Он был sealed/pushed commit
`afaa278` до build. Canonical build уже завершён; команду build ниже не повторять.
Разрешены tests и deterministic `--audit-only`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_moex_pre2012_core_derived_v3.py `
  tests/test_moex_pre2012_core_derived_v2.py `
  tests/test_moex_pre2012_core_derived_v1.py `
  tests/test_futures_panel.py tests/test_futures_spec_proxy.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/moex_pre2012_core_derived_v3.py `
  tests/test_moex_pre2012_core_derived_v3.py
.\.venv\Scripts\python.exe -m market_lab.futures.moex_pre2012_core_derived_v3 --audit-only
```

Default immutable output:
`data/processed/futures_pre2012/moex-core3-late-mix-causal-derived-2008-2011-v3/`.
Canonical manifest SHA `ff9b2771...`, panel SHA `390b1c8b...`; replay 27/27 и strict
values+dtypes comparison exact. Output не перезаписывать. Strategy returns/PnL всё ещё
запрещены до отдельного strategy seal.

### Sealed MOEX 2012–2017 causal derived sources

D1 config SHA `a633883d...` был pushed до build, но его immutable output нельзя
использовать: manifest `73ffe4c3...` зафиксировал persistent unfilled SI roll/exit после
попадания в serial-month contracts. D1 не повторять и не перезаписывать.

D2 config SHA `7b60afbf...` был pushed, но build не опубликовал output: SI exact roll
count оказался 22 из-за bounded clean flat gap, а gate требовал 23. D2 не повторять.

D3 config SHA `d21dd650...`, implementation SHA `c04d8224...` наследует official-cycle
filter и фиксирует exact gap/action gates. До первого D3 build code/config/tests должны
быть committed и pushed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_moex_pre2018_core4_derived.py `
  tests/test_moex_pre2018_core4_derived_v2.py `
  tests/test_moex_pre2018_core4_derived_v3.py `
  tests/test_futures_panel.py tests/test_futures_spec_proxy.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/moex_pre2018_core4_derived_v3.py `
  tests/test_moex_pre2018_core4_derived_v3.py
.\.venv\Scripts\python.exe -m market_lab.futures.moex_pre2018_core4_derived_v3 `
  --config .\configs\moex_pre2018_core4_derived_v3.yaml
```

Default immutable D3 output:
`data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/`. Build должен
сам остановиться при любом unresolved roll/exit. После сборки сверить все artifact
SHA/rows, exact rolls и maximum session; returns/PnL запрещены до отдельного V28 seal.
Canonical D3 уже завершён: manifest SHA `3ab20092...`, 5 916 panel rows, 28 797
contract/spec rows, unresolved roll/exit = 0. Команду build повторно не запускать.

### Sealed pre-2018 macro source

S1 SHA `3daa3c40...` был pushed, но FRED request трижды timed out до response persistence;
output отсутствует, команду S1 не повторять. S2 SHA `4ad7f034...` был pushed и получил
три responses, но fail-closed parser не опубликовал output: для 1 400/1 478 RUONIA rows
publication timing отсутствует. Команду S2 не повторять. S3 config SHA `ae575962...`,
implementation SHA `5f2e4e09...` меняет только parser missing policy. До первого S3
collection code/config/tests должны быть committed и pushed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_pre2018_macro_source.py tests/test_pre2018_macro_source_v2.py `
  tests/test_pre2018_macro_source_v3.py `
  tests/test_futures_info_radar.py `
  tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/pre2018_macro_source_v3.py `
  tests/test_pre2018_macro_source_v3.py
.\.venv\Scripts\python.exe -m market_lab.futures.pre2018_macro_source_v3 `
  --config .\configs\pre2018_macro_source_v3.yaml
```

Default immutable output:
`data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/`. После collection
replay all three raw records, hashes, bounds and availability; не читать strategy
returns/PnL до отдельного V28 seal.

S3 уже выполнен после push `1f9c343`: manifest SHA `949bc7bf...`, raw archive SHA
`8109f157...`; replay и все checks прошли. Команду collection повторно не запускать.

### Sealed V28 unseen pre-2018 validation

Config SHA `4f9e6663...`, implementation SHA `b9c290f6...`. До первого запуска код,
config, sidecar, tests и docs должны быть committed и pushed. Не выполнять preflight,
который читает market price columns; разрешены только sealed tests и source metadata:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v28_pre2018_unseen_validation.py `
  tests/test_futures_v12_core4_correlation_trend.py `
  tests/test_futures_v26_stlfsi_levered_ruonia_capacity.py `
  tests/test_encoding.py
.\.venv\Scripts\python.exe -m ruff check `
  src/market_lab/futures_v28_pre2018_unseen_validation.py `
  tests/test_futures_v28_pre2018_unseen_validation.py
.\.venv\Scripts\python.exe -m market_lab.futures_v28_pre2018_unseen_validation `
  --config .\configs\futures_v28_pre2018_unseen.yaml `
  --output-root .\runs
```

Canonical run уже выполнен ровно один раз:
`runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/`, metrics SHA `73b614b8...`.
Verdict `FAIL_UNSEEN_20`, execution invalid из-за expired-contract trap после
capacity-cancelled roll. Команду не повторять. Любая risk-first roll correction — новый
V29 protocol с новым code/config/output и обязательным pre-outcome push.

### Sealed V29 post-V28 risk-first roll correction

Config SHA `d92f8cf2...`, implementation SHA `ea5aa37f...`. Это adaptive execution
correction после увиденного V28 failure, не independent holdout. До первого V29 run код,
config, sidecar, tests и docs должны быть committed и pushed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v29_risk_first_roll.py `
  tests/test_futures_v28_pre2018_unseen_validation.py `
  tests/test_futures_v26_stlfsi_levered_ruonia_capacity.py `
  tests/test_encoding.py
.\.venv\Scripts\python.exe -m ruff check `
  src/market_lab/futures_v29_risk_first_roll.py `
  tests/test_futures_v29_risk_first_roll.py
.\.venv\Scripts\python.exe -m market_lab.futures_v29_risk_first_roll `
  --config .\configs\futures_v29_risk_first_roll.yaml `
  --output-root .\runs
```

V29 выполнен после seal commit `478a246`. Canonical run:
`runs/v29_risk_first_roll_20260901T085436Z_d92f8cf2/`, metrics SHA `1c0e2dd7...`.
Artifact audit 26/26, checks 139/139; execution complete, но verdict
`FAIL_POST_V28_20`. Команду больше не запускать. Full old exit обязан уложиться в
factual 1% capacity; new entry отдельно clip-ится или заменяется cash. Если old exit
недоказуем, новый ledger обязан остаться invalid.

### V30 equal three-sleeve target with causal risk restoration

V30 выбран на уже открытом 2012–2017 development и не является holdout. V1 config SHA
`2e191a82...`, implementation SHA `b642afe2...` был sealed/pushed `271c7db`, но attempt
остановился до ledger/output на boolean polarity; V1 не повторять. D2 config SHA
`8b41f58a...`, wrapper SHA `20de599e...` меняет только positive proof. Seal `aea34e4`
был pushed до первого D2 economic read. Единственный canonical run уже выполнен:
`runs/v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a/`, metrics SHA `e5aeb7d1...`.
Команды ниже сохранены только для provenance; повторно их не выполнять:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v30_three_sleeve_risk_restoration_v2.py `
  tests/test_futures_v30_three_sleeve_risk_restoration.py `
  tests/test_futures_v29_risk_first_roll.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures_v30_three_sleeve_risk_restoration_v2.py `
  tests/test_futures_v30_three_sleeve_risk_restoration_v2.py
.\.venv\Scripts\python.exe -m market_lab.futures_v30_three_sleeve_risk_restoration_v2 `
  --config .\configs\futures_v30_three_sleeve_risk_restoration_v2.yaml `
  --output-root .\runs
```

Run сохранил source/signal/target checks, 1x baseline, selected risk-restored
primary/doubled/stress, hard-2x sensitivity, exact orders/positions/coverage и
rolling/bootstrap/leave-one-year-out; independent audit 33/33 exact. Формулу на
2012–2017 не менять; следующий economic read — только отдельный pushed V31 seal для
2008–2011.

### V31 one-shot unseen pre-2012 temporal validation

V31 config SHA `6dcb6dab...`, module SHA `ce2ee260...` pin-ит canonical V30-D2 и
pre-2012 D3. Seal `370b4d8` был pushed до market-value read. Единственный canonical run
уже выполнен: `runs/v31_pre2012_temporal_20260901T145938Z_6dcb6dab/`, metrics SHA
`d6d12842...`, verdict `UNSEEN_TEMPORAL_NO_GO_20`. Все команды ниже сохранены только
для provenance; повторно их не выполнять:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v31_pre2012_temporal_validation.py `
  tests/test_futures_v30_three_sleeve_risk_restoration_v2.py `
  tests/test_futures_v30_three_sleeve_risk_restoration.py `
  tests/test_futures_v29_risk_first_roll.py tests/test_encoding.py
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures_v31_pre2012_temporal_validation.py `
  tests/test_futures_v31_pre2012_temporal_validation.py
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v31_pre2012_temporal_validation --preflight-only
```

Команда единственного выполненного run:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v31_pre2012_temporal_validation `
  --config .\configs\futures_v31_pre2012_temporal_validation.yaml `
  --output-root .\runs
```

Canonical output не перезаписывать. После просмотра результата запрещены новый start,
asset/year filter, sign inversion, leverage/cost/gate change или повтор V31. Любая новая
информация — отдельная будущая family и новый ещё не просмотренный/forward period.

### V32 continuous curve-regime intraday

V32 config SHA `c7da1d45...`, core SHA `45bffa21...`, runner SHA `9f70fa3c...`.
Ниже сохранены выполненные tests и outcome-free metadata preflight:

```powershell
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/curve_regime_intraday.py `
  src/market_lab/futures_v32_curve_regime_intraday.py `
  tests/test_futures_v32_curve_regime_intraday.py
.\.venv\Scripts\pytest.exe -q `
  tests/test_futures_v32_curve_regime_intraday.py tests/test_encoding.py
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v32_curve_regime_intraday --preflight-only
```

Preflight должен вернуть exact 683 209 active bars, 169 644 common-four buckets,
686 curve events, 670 admitted event days, 29 810 decisions и 10/10 checks. Он не имеет
права загрузить OHLCV, return, target, equity или PnL.

Seal `936e3e0` был pushed до единственного canonical run. Команда сохранена только для
provenance и больше не выполняется:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v32_curve_regime_intraday --output-root .\runs
```

Canonical path `runs/v32_curve_regime_intraday_20260901T181223Z_c7da1d45/`, metrics SHA
`f4adf509...`; audit exact. Все ledgers incomplete из-за one-contract zero integer
capacity, поэтому V32 не повторять и не менять thresholds/sign/model/risk.

### V33 target-preserving liquidity execution repair

V33 config SHA `615d7b8e...`, module SHA `3ad113cc...`. Он читает exact V32 targets и
меняет только partial de-risk/reversal/flat-retry execution. Выполненный preflight:

```powershell
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures_v33_curve_regime_liquidity_execution.py `
  tests/test_futures_v33_curve_regime_liquidity_execution.py
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v33_curve_regime_liquidity_execution.py `
  tests/test_futures_v32_curve_regime_intraday.py tests/test_encoding.py
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v33_curve_regime_liquidity_execution --preflight-only
```

Preflight дал 10/10 checks, три exact target artifacts по 98 168 rows,
24 542 timestamps, 2 152 forced-flat rows/538 days и ровно пять parent unresolved
`insufficient_exit_capacity`. Seal `8c180e9` был pushed до единственного run; команда
ниже сохранена только для provenance:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v33_curve_regime_liquidity_execution --output-root .\runs
```

Canonical path `runs/v33_curve_regime_liquidity_20260901T183357Z_615d7b8e/`, metrics SHA
`17d9602a...`; audit 35/35 exact. Execution complete, но primary/stress CAGR
`−1,7374%/−6,7677%`, verdict `NO_GO`. V33 не повторять; threshold/sign/horizon/retry
tuning на этой history запрещён. Следующая family должна менять сам target/mechanism.

### V34 atomic RI–MIX relative-corridor barrier

V34 config SHA `eece2650...`, core SHA `f3e86c52...`, runner SHA `e8ad7882...`.
До первого economic run выполнены только outcome-free проверки:

```powershell
.\.venv\Scripts\ruff.exe check `
  src/market_lab/futures/relative_corridor_barrier.py `
  src/market_lab/futures_v34_relative_corridor_barrier.py `
  tests/test_futures_v34_relative_corridor_barrier.py
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_futures_v32_curve_regime_intraday.py `
  tests/test_futures_v33_curve_regime_liquidity_execution.py `
  tests/test_futures_v34_relative_corridor_barrier.py
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v34_relative_corridor_barrier --preflight-only
```

Seal commit `12b48dc` был pushed до outcomes. Единственный canonical запуск уже выполнен;
команда ниже сохранена только для provenance и **не должна повторяться**:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v34_relative_corridor_barrier --output-root .\runs
```

Canonical path `runs/v34_relative_corridor_20260901T213656Z_eece2650/`, metrics SHA
`1db3bc1a...`, identity SHA `687c1328...`; audit 62/62 exact. Обе MLP сделали ноль
сделок из-за insufficient nested-history gate. Fixed corridor: 118 pairs, CAGR
`−1,3634%`, Sharpe `−1,0445`, MDD `4,5066%`, zero unresolved, verdict `NO_GO`.
Параметры V34 после результата не менять и run не повторять.

### MOEX forward FUTOI/tradestats/obstats snapshots

Collector сохраняет только target-free positioning/flow/depth; absolute price, return,
target и PnL не запрашиваются. Без `MOEX_ALGOPACK_TOKEN` он получает только официальный
public FUTOI с 15-дневной задержкой. Для real-time FUTOI и subscribed futures
`tradestats/obstats` задай token в environment и exact active contracts:

```powershell
$env:MOEX_ALGOPACK_TOKEN = '<token-is-never-written-to-disk>'
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_microstructure_source `
  --source-date <YYYY-MM-DD> `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-microstructure-v1 `
  --contract SI=<SECID> --contract RI=<SECID> `
  --contract BR=<SECID> --contract MIX=<SECID>
```

Запускать one-shot каждые пять минут внешним scheduler. Каждый каталог `snapshot_*`
immutable; повтор того же retrieval timestamp запрещён. Проверка:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_microstructure_source `
  --source-date <YYYY-MM-DD> `
  --audit-directory <snapshot-path>
```

Public delayed snapshot пригоден только для проверки pipeline/архива. Neural timing
остаётся sleeping до накопления собственного real-time forward периода и отдельно
запечатанного label/evaluation protocol.

Фактический проверочный snapshot уже существует и не должен перезаписываться:
`D:\Projects\trading_lab_data\data\forward\moex-microstructure-v1\snapshot_20260901T214719330521Z`;
source date `2026-08-18`, 8 rows, audit 11/11, access mode `public_15_day_delayed`.

### V35 thirty-stock cross-sectional intraday

Pre-2026 source bundle и canonical V35 уже построены; команды ниже сохраняются только
для provenance и **не должны повторяться**:

```powershell
.\.venv\Scripts\python.exe -m market_lab.stocks.intraday_pre2026_source
.\.venv\Scripts\python.exe -m `
  market_lab.stocks_v35_cross_sectional_intraday --output-root .\runs
```

Source manifest SHA `5a7a4873...`, V35 config SHA `257422c0...`, seal commits
`95fad8a`/`fac5625`, loader-only pre-outcome fix `df207d1`. Canonical run:
`runs/v35_cross_sectional_intraday_20260901T220621Z_257422c0/`, metrics SHA
`8c9820cf...`, identity SHA `18b48fba...`, audit 16/16. Verdict `NO_GO`; обе MLP zero
trades, fixed CAGR `−12,6519%`. Порог, знак, horizon, universe, costs и leverage V35
не менять на этой history.

### V36 / V36-R1 multi-era online expert ensemble

Оба canonical run уже выполнены и **не должны повторяться**. Исходный V36 invalid из-за
разрыва execution source, но каталог сохраняется для диагноза:

```text
runs/v36_online_expert_20260901T223514Z_cb391e44/
```

R1 был sealed/pushed commit `aea629f` до corrected outcome. Он добавляет только
официальный December-2017 bridge и deterministic expiry flat, не меняя economics:

```text
runs/v36r1_online_expert_20260901T224722Z_156f573c/
```

Read-only audit разрешён:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v36r1_online_expert_boundary `
  --audit-run .\runs\v36r1_online_expert_20260901T224722Z_156f573c
```

Config SHA `156f573c...`, metrics SHA `9812a1fd...`, identity SHA `c193c7cf...`, audit
11/11. Online primary CAGR `6,4262%`, Sharpe `0,3989`, MDD `40,7292%`; static equal
лучше с CAGR `8,1551%`. Verdict `NO_GO`. Не менять expert signs/horizons, eta/decay,
cash/risk/leverage/costs или boundary bridge на этой history.

### Forward MOEX option surfaces

Один immutable public-delayed snapshot SI/RI/BR/MIX:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_source
```

Read-only audit:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_source `
  --audit-directory <snapshot-path>
```

Каждый запуск создаёт новый каталог под
`data/forward/moex-options-surface-v1/`; overwrite и historical backfill запрещены.
Собирать один EOD snapshot на торговую дату. Первый реальный snapshot —
`snapshot_20260901T230311250639Z`, 2 062 rows, audit 17/17. До 60 discovery + 20
calibration + 40 unseen evaluation snapshots экономический protocol не запускать; см.
[FORWARD_OPTION_PROTOCOL.md](FORWARD_OPTION_PROTOCOL.md).

Автоматический wrapper сначала делает source-date-only SI probe и не вызывает collector,
если эта торговая дата уже сохранена:

```powershell
.\scripts\collect_forward_option_surface.ps1
```

Регистрация/воспроизводимое обновление Windows Task Scheduler:

```powershell
.\scripts\register_forward_option_surface_task.ps1
schtasks.exe /Query /TN "TradingLabForwardOptionSurface" /V /FO LIST
```

На `2026-09-02` task `TradingLabForwardOptionSurface` active/Ready: Mon–Fri 23:55
Europe/Istanbul, interactive user, `StartWhenAvailable`, `IgnoreNew`, timeout 10 минут.
Manual verification завершилась `Last Result: 0` и сохранила snapshot count `1`, то
есть duplicate-date guard сработал.

Полный replay-аудит всех накопленных snapshot и точный gate 60/20/40:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.forward_option_readiness `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v1
```

Монитор считает только valid unique `source_date`. На `2026-09-02`: `1/60` discovery,
`0/20` calibration, `0/40` unseen evaluation, invalid `0`, поэтому создание
экономического protocol пока заблокировано. Wrapper пропускает существующую дату только
после успешного replay-аудита; повреждённый immutable snapshot не мешает записать замену.

### MOEX USD/RUB TOM source for future cash-and-carry

Canonical source уже создан и immutable. Повторный read-only replay audit:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_fx_spot_source --audit `
  --output-root D:\Projects\trading_lab_data\data\processed\fx_basis\moex-usdrub-tom-current-vintage-2018-2025-v1
```

Ожидание: 2 027 rows, 21 pages, `2018-01-03..2025-12-30`, 51/51 checks. Не запускать
collector второй раз в этот path. Source не содержит basis/return/PnL и сам по себе не
разрешает экономическую проверку: сначала нужен отдельный config/code seal с exact SI,
cost, margin и RUONIA assumptions.

Economic V1 уже immutable:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.fx_cash_carry_v1 `
  --audit-directory D:\Projects\trading_lab_data\runs\fx_cash_carry_v1_20260901T233224Z_4b3ca33e
```

Ожидание: audit 11/11, verdict `NO_GO`, evaluation trades `0`, CAGR `0%`. Run не
повторять и параметры не менять: отсутствие executable USD spot после июня 2024 —
структурная причина закрытия ветки, а не повод подобрать другой historical threshold.

CNY quarterly source replay:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_cny_cash_carry_source --audit `
  --output-root D:\Projects\trading_lab_data\data\processed\fx_basis\moex-cny-cash-carry-current-vintage-v1
.\.venv\Scripts\python.exe -m market_lab.futures.cny_cash_carry_v1 `
  --audit-directory D:\Projects\trading_lab_data\runs\cny_cash_carry_v1_20260901T234628Z_1b9406d9
```

Ожидание: source 157/157; economic audit 12/12 и `NO_GO`. Perpetual V1 output
отсутствует. Продолжать только с `moex_cny_perpetual_source_v2` SHA `9dbf7e77...` и
новым output suffix `-v2`; V1 config/code и failed attempt не переписывать.

### Forward equity TradeStats/OrderStats/OBStats

Collector требует ALGOPACK token: public fallback намеренно отсутствует, потому что
официальные equity endpoints доступны только подписчикам. Token не пишется в raw,
requests или manifest.

```powershell
$env:MOEX_ALGOPACK_TOKEN = '<token-is-never-written-to-disk>'
.\.venv\Scripts\python.exe -m `
  market_lab.stocks.moex_forward_equity_microstructure_source `
  --source-date <YYYY-MM-DD> `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-equity-microstructure-v1
```

Запускать внешним scheduler каждые пять минут. Каждый `snapshot_*` immutable. Audit:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.stocks.moex_forward_equity_microstructure_source `
  --audit-directory <snapshot-path>
```

Snapshot target-free: абсолютные цены/VWAP, returns, labels, targets и PnL исключены
из request schema. Экономический label нельзя проектировать до заранее заданного
forward accumulation window и отдельного sealed paper protocol.

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
