# AlgoPack paper inputs V1

Новый модуль `src/market_lab/futures/algopack_paper_inputs_v1.py` для разрешённого
[future-paper эксперимента](ALGOPACK_PAPER_AUTHORIZATION_20260907.md).
Preflight не обучает модель и не читает OHLCV: проверяет exact manifest tree, bytes/SHA
raw и Parquet, затем только timestamp/end_timestamp/canonical_contract_id.
Empty segments не игнорируются. Protected UTC timestamps>=2026, null/reversed times,
duplicate/unordered bars, неверный контракт и aggregate mismatch отклоняются.
Строка2026 не допускается даже при правдоподобном имени файла и корректном SHA.

Root должен быть absolute/ordinary, без symlink ancestors; manifest paths — canonical
relative POSIX, без traversal/absolute paths/Windows alternate streams. Каждый child
проверяется по pinned parent. JSON с повторными ключами отклоняется.
`load_price_artifact` — отдельный post-seal вызов: повторяет identity и time-only gate
до ценовой projection; этот вызов ещё не разрешён до training protocol seal.

`load_active_plan` читает только семь date/identity/plan_tradable колонок, сверяет SHA,
rows и protected boundary. Использует effective_date, observed_through<=decision_date
и decision_date<effective_date. Ineligible rows сохраняет с plan_eligible=false, чтобы
будущий inference calendar не терял sleep/unresolved decisions.

## Точный source scope

- Intraday root: `/srv/trading_lab_data/data/v62-legacy-source-v1/data`.
- Top: `processed/futures_v7_10m/manifest_2018-01-01_2025-12-31.json`,1785bytes,
  SHA `f620ff77a5368c93d6415fc1b5785f9eaaba6cef873a4425fcd98e9b69f3ba01`.
- Expected source totals:4assets/219segments/1empty/1699545rows/3507pages.
- Active map root `/srv/trading_lab_data`, relative
  `data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet`,
  500949bytes/8100rows, SHA `40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823`.

Это transitive BYTE verification и metadata gating, не semantic raw-to-price replay.
Raw payloads хешируются, но не распаковываются/нормализуются до outcome seal.
Поддержка исторического2018–2019 префикса не означает включение его в обучение AlgoPack:
training rows будут только2020–2025 согласно новому training config.
Global original-version/model/live flags не меняются. Источник не скачивается заново.

## Проверки и следующая операция

### Actual server preparation и correction V2

Pre-server commit/push `506ab2d`; Linux31/31 inputs +38/38 alignment PASS.
Первый реальный preflight выявил отсутствие всей raw/ директории в V62 copy.
При восстановлении также обнаружен один отсутствующий empty Parquet, pinned SHA
`9bd1c65e8300b6dab8b3cef589e5f63d2bc74e97a99b14cf1b9941a8d00000eb`,6620bytes/0rows.
Имя содержит2027 expiry и2026 segment boundary, но parent requested_end<=2025; файл
не допускать только по имени — его реальное отсутствие/нулевой row count проверяются.

Из локальных originals отдельно перенесены219 raw archives (27626868bytes суммарно)
и exact empty Parquet. До transfer проверены manifest hashes/bytes и exact directory
membership по всем четырём assets; на сервере tar members сравнены с pinned allowlist,
symlinks/hardlinks/unexpected entries запрещены. Новый root:
`/srv/trading_lab_data/data/algopack-paper-price-inputs-v1`.
Старая V62 copy не изменяется: её manifests и218 непустых Parquet копируются в новый
root с проверкой pinned bytes; raw219 и empty Parquet добавляются из transfers.
Никаких downloads MOEX или новых outcome reads при этом нет.

Полный intraday preflight нового root прошёл; следующая проверка active map V1
остановилась на четырёх nontradable2018-01-03 rows с отсутствующими decision_date и
observed_through. Effective dates полны. Source bytes не изменялись; сборка сохранена,
assembly manifest до успешного завершения не публикуется, повторять копирование нельзя.
Новый `algopack_paper_inputs_v2.py` меняет только active-map missing-date policy:
missing prior dates сохраняются с plan_eligible=false; missing effective_date по-прежнему
ошибка. Intraday/price loaders буквально импортированы из V1 без изменения.
Local V2 synthetic7/7 PASS. V1 failure остаётся документированным; V1 не переписан.

### Первоначальный план

Local synthetic30passed/1 Windows symlink skip, Ruff PASS. Linux symlink case должен
пройти до server preflight. Тесты проверяют mutation на каждом уровне, traversal,
future timestamp до price read, подмену asset/contract, пустой сегмент и сохранение
ineligible plan rows. Все реальные числовые цены пока закрыты до training seal.

Следующая операция: readonly server preflight по этим exact source identities.
После него — training protocol/code/input seal, price/flow matrix и paired fixed Ridge.
Не выдавать metadata PASS за модель, доходность или полный execution admission.
