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

### Authoritative server collectors

Forward snapshots собирает только `gpu-mlserver` через native systemd services/timers.
Код находится в `/opt/trading_lab`, данные — в `/srv/trading_lab_data`, процесс работает
от пользователя `trading-lab`. Все 16 локальных Windows definitions `TradingLab*`
отключены и служат только recoverable fallback; не включать их, пока server timers
активны.

```powershell
ssh gpu-mlserver 'systemctl list-timers --all --no-pager "trading-lab-*"'
ssh gpu-mlserver 'systemctl --failed --no-pager "trading-lab-*"'
```

Расписания, журнал, deployment и аварийный откат описаны в
[SERVER_COLLECTORS.md](SERVER_COLLECTORS.md). PowerShell registration scripts больше не
являются production scheduler и не должны запускаться на локальном компьютере.

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

### Forward cross-market BBO каждые 10 минут

Ручной запуск только внутри sealed slot `10:09..18:39` МСК:

```powershell
.\scripts\run_forward_cross_market_bbo_v2.ps1
```

Readiness и exact replay отдельного снимка:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_delayed_bbo_v2_readiness

.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_cross_market_bbo_source_v2 `
  --audit-directory <snapshot-directory>

.\scripts\register_forward_delayed_bbo_v2_tasks.ps1
```

Server timer `trading-lab-cross-market.timer` запускает V3 по будням каждые 10 минут
с 10:09 до 18:39. Все local V1/V2/V3 tasks отключены. Не запускать historical backfill и не удалять invalid snapshot:
он является частью operational evidence. До 20 полных discovery sessions outcomes и
PnL запрещены. Полный контракт:
[FORWARD_CROSS_MARKET_BBO_PROTOCOL.md](FORWARD_CROSS_MARKET_BBO_PROTOCOL.md).

### Forward broad 30-stock futures carry

```powershell
.\scripts\run_forward_broad_stock_futures_carry_v2.ps1

.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_delayed_bbo_v2_readiness

.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_broad_stock_futures_carry_source_v2 `
  --audit-directory <snapshot-directory>
```

Server timer `trading-lab-broad-carry.timer`: Mon–Fri, каждые 10 минут
`10:09..18:39`. До 20 полных discovery sessions не считать basis/rank/PnL. Missing pair или
fractional `LOTVOLUME/LOTSIZE` остаётся invalid и не заменяется нулём. V2 хранит
delayed BBO, а depth/size/queue/fill оставляет unresolved. Полный контракт:
[FORWARD_BROAD_STOCK_FUTURES_CARRY_PROTOCOL.md](FORWARD_BROAD_STOCK_FUTURES_CARRY_PROTOCOL.md).

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

### Historical MOEX RMS V4 and sealed V38

Canonical source уже собран; не перезаписывать:

```powershell
$env:PYTHONPATH = 'src'
python -m market_lab.futures.moex_rms_historical_pit_source --audit-only `
  --output-root 'D:\Projects\trading_lab_data\data\processed\info_radar\moex-rms-historical-pit-2018-2025-v4'
```

Ожидается 11/11 true. V1–V3 output не существует. V38 config SHA `3f9288e3...` и
canonical run `v38_moex_margin_risk_governor_20260902T020147Z_3f9288e3` имеют verdict
`NO_GO`; run повторно не запускать. Не менять MR1 threshold/age/persistence, не
переключаться post-hoc на MR2/MR3 и не инвертировать правило. Forward RMS task остаётся
source-only до завершения заранее объявленных discovery/calibration/evaluation окон.

### Dividend-stock calendar spreads V1 — canonical NO-GO

Source and economic outputs already exist and must not be overwritten. Offline replay:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_dividend_calendar_spread_source `
  --audit-only
.\.venv\Scripts\python.exe -m market_lab.futures.dividend_calendar_spread_v1 `
  --audit-directory D:\Projects\trading_lab_data\runs\dividend_calendar_spread_v1_20260902T032624Z_52a8ce06
```

Source manifest `a8c1b0b0...` covers 53 spreads and replays 222 raw responses.
Economic config `52a8ce06...` produced 31 cashflow-change events and zero executable
following-quote entries, verdict `NO_GO`. Do not rerun collection, change sign/lag,
select events, relax bid/ask entry or use same-day RMS. A successor requires an earlier
original-timestamp issuer/board disclosure source and a new pushed protocol.

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

Один immutable timestamped V2 public-delayed snapshot SI/RI/BR/MIX:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_source_v2
```

Read-only audit:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_source_v2 `
  --audit-directory <snapshot-path>
```

Каждый запуск создаёт новый каталог под
`data/forward/moex-options-surface-v2-timestamps-margin/`; overwrite, V1 copy и
historical backfill запрещены. Source config/implementation SHA
`f9a06462.../74d015a6...`, earliest eligible retrieval `2026-09-02T21:25:00Z`.
Первый V2 snapshot — `snapshot_20260902T212518751694Z`, audit `22/22`.

Локальный legacy wrapper ниже сохраняет V1 source-date-only EOD semantics, но Windows
task отключена. Он нужен только для ручного диагностического V1 capture:

```powershell
.\scripts\collect_forward_option_surface.ps1
```

Authoritative server intraday timer `trading-lab-option-surface.timer` вызывает V2
Mon–Fri каждые 10 минут с 10:09 до 22:59 МСК и в 23:09/19/29/39/55. Отдельный
`trading-lab-option-surface-eod.timer` в 23:57 создаёт V1 snapshot для frozen V39/V49,
которые сохраняют прежний input contract. Локальные Windows tasks отключены. Проверка
таймеров приведена в [SERVER_COLLECTORS.md](SERVER_COLLECTORS.md).

Read-only readiness intraday V2 admission (config SHA `fb598938...`, eligibility
boundary `2026-09-02T21:25:00Z`):

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.forward_option_intraday_readiness_v2 `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v2-timestamps-margin
```

V1 и pre-boundary snapshots не считаются. Полная торговая сессия требует не менее 30
valid snapshots, span не менее 300 минут и maximum gap не более 25 минут. Экономические
features, labels и PnL запрещены до 20 полных discovery-сессий; затем заранее
зафиксированы 20 calibration и 60 unseen sessions. Будущие сравнения:
full-surface neural timing, price-only ablation, fixed skew/term rule и always-abstain;
только defined-risk позиции с наблюдаемыми OFFER на входе и BID на выходе.

Первый V2 readiness: eligible/preboundary/invalid `1/0/0`, complete discovery sessions
`0/20`. Поле `market_update_time`, `last_trade_time`, `exchange_sequence_number` и
`initial_margin_exchange_time` обязательно в каждом V2 snapshot. Public depth/queue
не заявляется: эти ISS fields оказались полностью пустыми.

Sealed counts-only clock/BBO/margin quality report для одного V2 snapshot:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_quality_v1 `
  --snapshot <v2-snapshot-path> `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v2-quality-v1
```

Replay-аудит:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_option_surface_quality_v1 `
  --audit-directory <quality-report-path>
```

Server dispatcher выполняет этот diagnostic автоматически после каждого intraday V2
capture. Ошибка parent replay или negative exchange-clock lag делает service failed;
report не сохраняет BID/OFFER/strike values, features, returns или PnL.

V1 продолжает собственные неизменные readiness-контракты. Для V39/V49 использовать
только прежний root `data/forward/moex-options-surface-v1` и соответствующие команды
ниже; V2 нельзя подставлять в frozen protocol без новой версии и нового seal.

Historical public MOEX option EOD pilot V2 уже canonical; повторять collection в тот же
path нельзя. Допустим только read-only raw replay:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_options_surface_history_v2 `
  --audit-only `
  --output-root D:\Projects\trading_lab_data\data\processed\options\moex-core4-options-pilot-2021-01-v2
```

Ожидание: 9/9 true, 105 318 rows, 1 133 pages. Source не разрешает historical option
PnL: нет bid/ask, `THEOR_PRICE` пуст, а SETTLEPRICE запрещено трактовать как fill.

Weekly option-state V3 также immutable; collection не повторять. Read-only replay:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_options_weekly_state_source_v3 `
  --audit-only `
  --output-root D:\Projects\trading_lab_data\data\processed\options\moex-core4-options-weekly-2021-2025-v3
```

Ожидание: 11/11 true, 1 327 744 rows, 13 802 pages, 261 dates.

Historical Type B artifacts существуют только на `gpu-mlserver` и не пересобираются.
Допустимы read-only audits:

```bash
cd /opt/trading_lab
PYTHONPATH=src .venv/bin/python -m \
  market_lab.futures.moex_type_b_derivatives_sample_source_v3 \
  --audit-directory /srv/trading_lab_data/data/processed/options/moex-type-b-derivatives-sample-2024-10-01-v3
PYTHONPATH=src .venv/bin/python -m \
  market_lab.futures.moex_type_b_core4_bbo_derived_v2 \
  --audit-directory /srv/trading_lab_data/data/processed/options/moex-type-b-core4-bbo-2024-10-01-v2
PYTHONPATH=src .venv/bin/python -m \
  market_lab.futures.moex_type_b_defined_risk_vertical_admission_v1 \
  --audit-directory /srv/trading_lab_data/data/processed/options/moex-type-b-defined-risk-vertical-admission-2024-10-01-v1
PYTHONPATH=src .venv/bin/python -m \
  market_lab.futures.moex_type_b_vertical_execution_diagnostics_v1 \
  --audit-directory /srv/trading_lab_data/data/processed/options/moex-type-b-vertical-execution-diagnostics-2024-10-01-v1
```

Ожидание: source `10/10`, BBO `12/12`, vertical admission `12/12`, execution diagnostic
`11/11`, все `all_true`. Не запускать commands без `--audit-directory`: output immutable.
Один sample day не поддерживает PnL/CAGR; полный Type B archive требует отдельного
разрешения на покупку. Детали: [MOEX_TYPE_B_OPTION_SOURCE.md](MOEX_TYPE_B_OPTION_SOURCE.md).

V39 canonical run повторять нельзя:
`runs/v39_option_oi_tail_governor_20260902T025023Z_3b5d3074/`. Ожидание: metrics SHA
`52993f827af146af03ca240ee08af678487c59c95e02253844176183042d0113`, identity SHA
`fe60f262ed752935be7eb52618bdb3759de709b0f4a1507e86f7f131d2af0c71`, 17/17 artifact
hashes, verdict `GO_TO_NEW_FORWARD_CONFIRMATION`. Same-history V39 tuning запрещён;
следующий PnL только в заранее замороженном forward challenger.

Совместный V39 forward readiness (никаких signal/PnL):

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.v39_forward_validation_readiness `
  --option-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v1 `
  --futures-root D:\Projects\trading_lab_data\data\forward\v27-validation-v2
```

На `2026-09-02` после publication retry: option warmup начат, futures CLOSE `1/253`,
invalid `0`; `paper_economics_may_start=false`. Tasks зарегистрированы отдельно: V1
option EOD 23:57, V27 decision 00:45/01:15/06:00 Tue–Sat и execution 10:05 мск. Новый
collector/task для V39 не нужен.

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

Ожидание: source 157/157; economic audit 12/12 и `NO_GO`.

CNY perpetual source и исправленный economic run:

```powershell
.\.venv\Scripts\python.exe -m market_lab.futures.moex_cny_perpetual_source_v2 `
  --audit `
  --output-root D:\Projects\trading_lab_data\data\processed\fx_basis\moex-cny-perpetual-current-vintage-v2
.\.venv\Scripts\python.exe -m market_lab.futures.cny_perpetual_quarterly_spread_v2 `
  --audit-directory D:\Projects\trading_lab_data\runs\cny_perpetual_quarterly_spread_v2_20260902T000944Z_6a0a7cbe
```

Ожидание: source 33/33, economic audit 15/15, verdict `NO_GO`, 0/4 evaluation
trades. V1 economic run с suffix `5b2d6be7` не удалять, но его numeric GO invalid из-за
point-value error. V1/V2 повторно не запускать и historical thresholds не менять.

V27 independent forward validation:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_component_readiness_v2 `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v3-components
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_paper_preflight `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v2
```

Legacy Windows registration script не запускать, пока authoritative timers работают на
`gpu-mlserver`.

Server timers `trading-lab-v27-execution.timer` (10:05) и
`trading-lab-v27-decision.timer` (00:45/01:15/06:00 Tue–Sat) работают на сервере.
Schedule correction SHA `48f16f2c...`: прежний 23:45 запуск не имел полного official
history coverage, а первый неизменный 00:45 retry создал 25-row decision component и
прошёл полный replay. Dispatcher сохраняет
required MOEX market component первым, затем
независимо пытается CBR и FRED. Каждый component raw-replayable; EOD market дополнительно требует
official history `CLOSE/VOLUME/OPENPOSITION` каждого контракта. Не запускать market backfill до
`2026-09-02`; первые 253 common CLOSE дают 252 return sessions и являются только
warmup, следующие 504 — immutable evaluation. До завершения warmup PnL/CAGR запрещены.
Macro разрешён только после собственного actual retrieval и не ремонтирует прошлые dates.
Если `/etc/trading-lab/collector.env` содержит валидный официальный `FRED_API_KEY`,
dispatcher использует authenticated API component; иначе остаётся anonymous route.
Ключ нельзя передавать аргументом или сохранять в repo/log/raw/manifest. После
authenticated failure fallback запрещён. Readiness показывает раздельные route counts,
но никогда значение ключа.
Для exact hard fallback нужен `MOEX_ALGOPACK_TOKEN`; generic weekdays запрещены.
Подробности:
[FORWARD_V27_PROTOCOL.md](FORWARD_V27_PROTOCOL.md).

Forward MOEX RMS risk/cashflow source:

```powershell
.\scripts\register_forward_moex_rms_task.ps1
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_rms_readiness `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-rms-risk-cashflow-v2
```

Server timer `trading-lab-moex-rms.timer` запускается Mon–Fri 23:35 мск. Dispatcher пропускает уже
audited `risk_source_date`, отклоняет дату раньше `2026-09-02`; collector сохраняет
полные paginated raw pages и replayable Parquet трёх таблиц. Не добавлять `from/till`,
не считать PnL до 60 discovery dates; далее нужны 20 calibration и 60 unseen evaluation.

V37 canonical audit only; experiment не повторять:

```powershell
.\.venv\Scripts\python.exe -m market_lab.stocks_v37_cross_market_breakout `
  --audit-directory `
  D:\Projects\trading_lab_data\runs\v37_cross_market_breakout_20260902T011012Z_15c6d67c
```

Ожидание: все artifact/runtime checks true, verdict `NO_GO`. Config, threshold, sign,
exit corridor, stop, leverage, universe и years после результата не менять.

Forward CNY quotes/funding collector:

```powershell
.\scripts\register_forward_cny_relative_value_task.ps1
.\scripts\collect_forward_cny_relative_value.ps1
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_cny_relative_value_readiness `
  --output-root D:\Projects\trading_lab_data\data\forward\moex-cny-relative-value-v1
```

Server timer `trading-lab-cny-relative-value.timer` запускается Mon–Fri 18:30 мск. Dispatcher до
записи отклоняет/пропускает уже сохранённую quote date, collector запрещает любую дату
до `2026-09-02`, архивирует raw current responses и только post-seal history
`CNYRUBF`. Первый economic seal запрещён до 40 audited unique dates; затем нужны 20
calibration и 60 unseen evaluation. Collateral yield нельзя добавлять без отдельного
byte-pinned broker rule/haircut protocol.

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

### V41 idle-RUONIA stability candidate

Canonical runners (do not rerun to tune parameters):

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.stock_futures_cash_carry_idle_ruonia_v2
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v41_v39_cash_carry_ruonia_stability
```

Canonical outputs:

- `runs/stock_futures_cash_carry_idle_ruonia_v2_20260902T041838Z_a4c03aaa/`;
- `runs/v41_v39_cash_carry_ruonia_stability_v1_20260902T042117Z_45418128/`.

Проверять manifest/audit hashes из `docs/STATUS.md`. Нельзя менять 80/20, 50% RUONIA,
cash-carry trades или V39 по этим metrics. Для forward нужно отдельно доказать
исполняемые quotes и фактический cash instrument.

Forward stock-futures cash-carry BID/OFFER:

```powershell
.\scripts\register_forward_stock_futures_cash_carry_tasks.ps1
.\scripts\collect_forward_stock_futures_cash_carry.ps1 -Stage decision
.\scripts\collect_forward_stock_futures_cash_carry.ps1 -Stage fill
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_stock_futures_cash_carry_readiness `
  --output-root `
  D:\Projects\trading_lab_data\data\forward\moex-stock-futures-cash-carry-v1
```

Tasks работают Mon–Fri в 15:49/15:59 МСК. Сбор до времени stage, source date до
`2026-09-02` и повтор той же date/stage отклоняются. Existing immutable snapshot
wrapper только replay-аудирует и пропускает; повреждённый не перезаписывается.
До 60 valid ordered pairs запрещены paper signal/PnL, затем нужны 20 calibration и
60 unseen evaluation. Полный контракт:
[FORWARD_STOCK_FUTURES_CASH_CARRY_PROTOCOL.md](FORWARD_STOCK_FUTURES_CASH_CARRY_PROTOCOL.md).

Forward LQDT idle-cash execution evidence:

```powershell
.\scripts\register_forward_lqdt_idle_cash_tasks.ps1
.\scripts\collect_forward_lqdt_idle_cash.ps1 -Stage decision
.\scripts\collect_forward_lqdt_idle_cash.ps1 -Stage fill
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_lqdt_idle_cash_readiness `
  --output-root `
  D:\Projects\trading_lab_data\data\forward\moex-lqdt-idle-cash-v1
```

Tasks используют те же exact 15:49:00/15:59:00 МСК. Не запускать до stage time и не
перезаписывать snapshot. LQDT нельзя учитывать одновременно как пай и как свободный
cash/collateral; будущая продажа оценивается только по BID. iNAV LQDTM не собирать до
разрешения вопроса о договоре на индексные данные. Полный контракт:
[FORWARD_LQDT_IDLE_CASH_PROTOCOL.md](FORWARD_LQDT_IDLE_CASH_PROTOCOL.md).

Canonical joint depth/readiness gate for V41:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v41_forward_execution_admission `
  --stock-root `
  D:\Projects\trading_lab_data\data\forward\moex-stock-futures-cash-carry-v1 `
  --lqdt-root `
  D:\Projects\trading_lab_data\data\forward\moex-lqdt-idle-cash-v1
```

Именно `joint_date_count`, а не отдельные readiness counts, является discovery
progress V41. Raw должен доказать best-level depth для 100 shares/1 future на каждой
паре и positive LQDT depth; максимальный same-stage retrieval skew — 30 секунд.
Config/threshold после первого snapshot не менять.

Forward fixed money-market fund pool:

```powershell
.\scripts\register_forward_money_market_fund_pool_tasks.ps1
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_money_market_fund_pool_readiness `
  --output-root `
  D:\Projects\trading_lab_data\data\forward\moex-money-market-fund-pool-v1
```

Server timers `trading-lab-fund-pool-decision/fill.timer` используют exact
15:49:00/15:59:00 МСК.
Universe LQDT/SBMM/AKMM/TMON фиксирован seal `ac299a7`; не добавлять фонд после чтения
котировок. До 60 ordered pairs запрещены ranking, yield и PnL. Полный контракт:
[FORWARD_MONEY_MARKET_FUND_POOL_PROTOCOL.md](FORWARD_MONEY_MARKET_FUND_POOL_PROTOCOL.md).

Canonical V42R2 idle-fund cost stress:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v42r2_v41_idle_fund_cost_stress
```

Использовать только config SHA `02a61505...`. V42R1 run `...T052021Z...` invalid:
он не применил initial purchase cost к NAV. R2 обязан списывать её на первом следующем
интервале и требует 9/9 комбинаций. Результат диагностический и не разрешает выбирать
LQDT/TMON до 60 forward пар.

### V49 exact double-risk canonical audit

Source-only readiness отдельного post-seal paper arm:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m market_lab.futures.v49_double_risk_paper_readiness \
  --option-root /srv/trading_lab_data/data/forward/moex-options-surface-v1 \
  --component-root /srv/trading_lab_data/data/forward/v27-validation-v3-components
```

Parent config SHA `520bd3d4...`; отдельный paper-arm config SHA `56822e1e...`.
Окончательная eligible retrieval boundary — `2026-09-02T19:16:00Z`; не сдвигать её и
не запускать ещё один seal. Команда не вычисляет signal/target/return/PnL.

V49 уже выполнен ровно один раз на `gpu-mlserver`; повторный economic run запрещён.
Проверять immutable result можно только read-only audit-командой на сервере:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m market_lab.futures_v49_v39_double_risk_exact_execution \
  --audit-directory \
  /srv/trading_lab_data/runs/v49_v39_double_risk_exact_execution_v1_20260902T122406Z_37b4fcb0
```

Ожидается `all_true: true`. Canonical implementation commit `540741a`, config SHA
`37b4fcb0...`, manifest SHA `b806e811...`. Не запускать модуль без
`--audit-directory`, не менять scale/cap/buffer/gates и не переносить расчёт на
локальную Windows-машину.

### V60/V61 shadow-equity governor and robustness audit

V60 и V61 уже выполнены ровно один раз; повторный economic/bootstrap run запрещён.
Разрешены только read-only audits на `gpu-mlserver`:

```bash
cd /opt/trading_lab
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 ARROW_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m market_lab.futures_v60_v49_equity_trend_governor \
  --audit-directory \
  /srv/trading_lab_data/runs/v60_v49_equity_trend_governor_v1_20260902T193821Z_40145868

env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 ARROW_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m market_lab.futures_v61_v60_robustness \
  --audit-directory \
  /srv/trading_lab_data/runs/v61_v60_robustness_20260902T194742Z_321fff16
```

V60 development gates прошли, но V61 не подтвердил internal minimum 20: stress q05
CAGR `8.9513%`, joint CAGR `>=20%` + MDD `<=25%` frequency `52.188%`, все пять
обязательных robustness conditions false. Не менять 126-session rule или 1x/2x по
этому outcome.

### Official MOEX OFZ source R2 audit

Canonical collection уже завершена; повторный download запрещён. Network-independent
raw replay выполняется только на `gpu-mlserver`:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m market_lab.futures.moex_ofz_total_return_source_r2 --audit
```

Ожидается `all_true: true`. Config SHA `227b1641...`, implementation commit
`7ae803b`, manifest/audit SHA `102b4add.../809eef13...`. Не запускать без `--audit`,
не переносить bundle в Git и не читать price/yield values до V52 economic seal.

### V51 read-only all-nine V42R2 robustness artifact audit

Canonical V51 выполнен один раз на `gpu-mlserver`. Повторять bootstrap run нельзя;
разрешён только replay существующих артефактов:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m market_lab.futures_v51_v42r2_robustness \
  --audit-directory \
  /srv/trading_lab_data/runs/v51_v42r2_robustness_20260902T161549Z_2a1e467b
```

Ожидается `all_true: true`. Config SHA `2a1e467b...`, implementation commit
`5a00d74`, metrics/manifest SHA `2c3eabb4.../8385fd60...`. Запуск без
`--audit-directory` запрещён; на локальной Windows-машине расчёт не выполнять.

### V50R1 read-only robustness artifact audit

V50 parent остановился до resampling и не создал output из-за несовпадения metric
calendar basis. Единственный canonical R1 уже выполнен на `gpu-mlserver`; повторять
его без необходимости нельзя. Проверка существующего результата:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m market_lab.futures_v50r1_v49_robustness \
  --audit-directory \
  /srv/trading_lab_data/runs/v50_v49_robustness_20260902T155610Z_5a5b36ca
```

Ожидается `all_true: true`. R1 config SHA `5a5b36ca...`, implementation commit
`0714967`, metrics/manifest SHA `3b60978b.../a5002f6d...`. Команда без
`--audit-directory` создаёт новый bootstrap run и поэтому запрещена; локально этот
расчёт не запускать.

### V40R1 fixed V39 + cash-carry stability blend

Run command:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures_v40_v39_cash_carry_stability
```

Canonical V40R1 is
`runs/v40r1_v39_cash_carry_stability_v1_20260902T041248Z_05ce1266/`. The earlier
`...T041223Z...` directory is noncanonical because the process failed only while
printing a Unicode report to CP1251 after writing artifacts. Do not use either run to
change the sealed 80/20 weight; verify canonical hashes from `docs/STATUS.md`.

### Covered stock–futures cash-and-carry V1

Canonical source audits:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_stock_futures_cash_carry_source --audit-only
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_stock_futures_cash_carry_intraday_source --audit-only
```

Economic runner создаёт новый immutable run:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.stock_futures_cash_carry_intraday_v1
```

Canonical уже находится в
`runs/stock_futures_cash_carry_intraday_v1_20260902T040404Z_aa35b0d8/`; повторный run
для подбора time/DTE/hurdle/haircut/costs запрещён. Проверять canonical по его
`manifest.json`, `audit.json` и SHA, не перезаписывать output.

Broad historical source расширяет только coverage с 61 до 339 contracts:

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_broad_stock_futures_cash_carry_intraday_source
.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_broad_stock_futures_cash_carry_intraday_source --audit-only
```

Перед запуском убедиться, что output V1 отсутствует и на диске достаточно места.
Collector делает тысячи official requests и может работать долго; не запускать его
параллельно с первыми critical forward snapshots. Config SHA `6bc8f4a2...` требует
ровно 339 contracts, 29 covered stocks и физически ограничивает candles датой
`<2026-01-01`. После завершения сначала audit/docs/commit, затем отдельный economic seal;
не запускать прежний V1 runner напрямую на новом bundle.

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
