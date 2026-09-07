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

Local synthetic30passed/1 Windows symlink skip, Ruff PASS. Linux symlink case должен
пройти до server preflight. Тесты проверяют mutation на каждом уровне, traversal,
future timestamp до price read, подмену asset/contract, пустой сегмент и сохранение
ineligible plan rows. Все реальные числовые цены пока закрыты до training seal.

Следующая операция: readonly server preflight по этим exact source identities.
После него — training protocol/code/input seal, price/flow matrix и paired fixed Ridge.
Не выдавать metadata PASS за модель, доходность или полный execution admission.
