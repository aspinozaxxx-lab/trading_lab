# AlgoPack FO history V1 — source-only 2020–2025

## Назначение

Продолжение после [проверенного sample](ALGOPACK_HISTORICAL_SOURCE.md), не backtest.
Предыдущий goal turn дал progress: authenticated inventory и flow/depth sample
завершены и отдельно replay-audited. Цель относительно предсказуемых 20%–50% годовых
не подтверждена. Новая история нужна для будущего price-only vs price+flow сравнения.
Сейчас нет OHLC/VWAP, returns, labels, targets, PnL, OI/margin, обучения или live.

## Фиксированный план и inputs

Config `configs/moex_algopack_fo_history_v1.yaml` — JSON-compatible YAML.
Active map: external `data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet`,
500949 bytes / 8100 rows, SHA
`40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823`.
Читать только effective_date, decision_date, observed_through, asset_code, contract_id,
secid. Tradability/price/volume/outcomes не читать. Parent sample path/seal/manifest
pinned; его transitive raw audit обязателен перед сетью и resume.

Expected plan: 6076 asset-day rows / 1519 общих дат, 2020-01-03..2025-12-30,
147 exact SECID (BR72, MIX/RI/SI по25), 294 contract/dataset задания до pagination.
Каждая asset/date уникальна; decision_date=observed_through<effective_date.
SECID образует непрерывный участок active-map; запрос от первой до последней даты.
Наблюдения внутри диапазона, но вне expected_dates, сохраняются с флагом.
Это coverage плана, не доказанные торговые дни/наличие flow. Empty job сохраняется,
не заменяется нулевым flow. Expiry-суффикс 6 не разрешает наблюдения 2026 года.

Pre-seal metadata probe подтвердил типы: dates datetime64[ns], identities pandas string.
Из 8100 исходных rows четыре начальные строки 2018-01-03 имеют null prior dates и
contract identities (16 null fields). Они вне фиксированного окна, не входные rows
истории 2020–2025. Сначала строго проверить effective_date, затем применить уже
заданные date bounds и проверять completeness/causality выбранных 6076 rows:
у них missing metadata=0, causality failures=0. Не удалять missing внутри окна.

## API и схема

Только authenticated apim.moex.com, per-contract FO TradeStats/OBStats route,
from/till, latest=0, start, iss.meta=off, iss.only=data,data.cursor, exact data.columns.
Bearer только в header, redirects запрещены. Общие metadata5 и числовые поля как
в pinned sample: trade counts, volumes, turnover, disb; L1/L10 spreads/depth/levels.
Строгие SECID/date/schema/time/cursor, неизменный TOTAL, отсутствие duplicate keys.

Finite numeric или null, без bool/string coercion; количество сделок/контрактов
nonnegative integral (2.0 сохраняется), средняя depth/levels может быть дробной.
Disb/spreads signed; null/empty asset_code сохраняются с mask, без inference.
Historical vendor alias mismatch показывается, а не переписывается по known sample.
Дата должна быть внутри exact request и строго до 2026-01-01.

## Resume и безопасность

Новые core `market_lab.futures.algopack_fo_history_core_v1` и collector
`market_lab.futures.moex_algopack_fo_history_v1`; frozen predecessors не менять.

- Serial pacing 0,5 s; 3 retries после initial request, delays 5/15/45 s только для
  transport и HTTP429/500/502/503/504. Auth/schema failures не повторять автоматически.
  Ceiling 200 страниц на job, не expected count.
- Один OS advisory lock на source/seal. Живость определять через systemd/handle,
  не по наличию lock/PID файла. Не запускать второй writer после observation timeout.
- Raw page и безопасная provenance публикуются вместе atomic directory rename.
  Committed pages не перезаписываются/не скачиваются повторно. Resume сначала
  replay-проверяет hashes, request identity, schema/date/cursor; tamper/changed TOTAL
  означает failure, не autoheal. Незавершённые temp dirs не считаются evidence:
  сохраняются целиком в sibling `.work.orphans`, а canonical audit запрещает их
  присутствие в итоговом наборе. Ничего не удаляется и не переписывается.
- Per-job normalized JSONL/manifest, память ограничена job. Global canonical только
  после всех jobs и полного raw-to-normalized-to-diagnostics replay.
- Failure evidence без response body/headers/token/exception text. Stdout/journal
  только status/job/counts, без числовых source values. Failed raw не сохраняется.
- Только gpu-mlserver, external `/srv/trading_lab_data`; секрет только
  `/etc/trading-lab/collector.env`, root:trading-lab0640. Application-scoped pinned CA,
  полная TLS/hostname verification, без global trust changes и новых purchases.
  Existing timers и local Windows jobs не изменять; это bounded historical batch.

## Reporting и admission

Показывать source counts, expected/observed/extra/missing dates, empty jobs, field
null/zero/negative counts и alias mismatches. TS/OB не обязаны иметь одинаковые ключи;
missing trade observation не означает 0. Exact metrics только после реального run.

Current-vintage; available_at=None, original_version_verified=False,
historical_model_eligible=False, live_trading_allowed=False. Retrieval/SYSTIME не
доказывают first publication. Source PASS не означает economic signal или GO LIVE.
Права личного ML, original availability и exact execution остаются отдельными gates.
До economics нужен отдельный seal: allowed information/missing policy, baseline,
train/test, execution/costs; искусственный лаг не доказывает historical causality.

## Проверка будущего reuse, без economic run

Отдельный read-only audit старого исполнения выявил важные ограничения. Frozen V32
`build_learning_frame` отбирает строки по exact_label_path и наличию будущих targets;
такой frame нельзя использовать как inference admission нового сигнала. Сначала
causal decision frame, затем отдельно label validity и unresolved будущие пропуски.
V9 `_load_plan` использует decision_date; новый source правильно использует
effective_date с prior decision. Для нового адаптера не наследовать этот join.

Предпочтительные loader fragments — V32 runner `_verified_raw_artifacts`,
`_load_causal_active_plan`, `_load_active_bars`, `_join_specs`, но не весь runner.
`_label_structure` содержит t+1→t+7 open-to-open target для 60 минут; его можно
использовать только отдельно от eligibility. Same-contract/exact-successor rules
сохраняются; будущие пропуски не должны убирать уже сделанное решение задним числом.

`simulate_next_open_portfolio` — только возможный research ledger: sizing зависит
от NAV на execution open; capacity использует весь объём execution bar, неизвестный
на его open. Это не доказанные fills. Fees/tick cash в RUB per contract per side,
specs — lagged proxies. Labels60min не обеспечивают holding60min; flat targets
должен задавать новый adapter, exit failure/roll/gaps остаются unresolved.
Null AlgoPack available_at нельзя превращать в causal eligibility выдуманным lag.
Ревью не вычисляло и не переоценивало старый PnL; frozen code не изменён.

## Статус реализации

Pre-request config SHA
`b488c931bc86f0fffda8e742de4f57f81d4e7831e4228eae5e2c250d97ae7988`;
closure SHA `c5fb0b96b12d77f5c01b1625b0b9b7ab582ed82d09117dc6217d577de33751d1`.
Closure pin-ит 21 файл, включая все parent sample dependencies, core/collector/tests.
Local verify_seal PASS. Targeted 210 passed / 1 Windows symlink skip; core53,
collector47/1skip. Ruff clean. Этот skipped case обязательно проверить на Linux.
Два review findings (orphan admission и check-before-read) исправлены до seal;
scope correction для missing2018 metadata также до seal, config не менялся.
Pre-request commit/push `84a1661`. Server tests101/101, включая Linux symlink case.
Preflight от trading-lab подтвердил closure21files, parent11/11, actual plan294jobs,
147contracts, 2020-01-03..2025-12-30. Plan SHA
`30a6f1729f5a0213f06595cf60309fef820bd75088ecb4240ab6ded13591c01f`.
Реальный batch завершён: 294jobs, 2067949rows, 2198pages, retries0; exit0, 25min57s.
Global manifest SHA `f50fa60a6986070d45f6a69555076df1f5748d09b70407131591740e77425fb4`,
canonical `data/processed/algopack/moex_algopack_fo_history_v1_c5fb0b96b12d`.
Internal full raw replay пройден до публикации; date admission=false сохраняется.
Отдельный source replay/metadata quality и actual result — [STATUS.md](STATUS.md).

## Дальнейший contemporaneous forward source — только review

Установка ключа сама по себе не включает постоянный FO TradeStats/OBStats stream:
в ops dispatcher и deployed timer definitions нет такого job. Старый manual module
сначала вызывает FUTOI, пишет batch-start retrieval до получения response, называет
SYSTIME published_at, использует per-contract date/latest=1 без полного cursor и
не имеет новых redirect/token guards. Его нельзя включать без изменений frozen bytes.

После bounded history нужен отдельный sealed forward source/service: actual current
contract metadata discovery, correct date parameters и bounded overlap/full cursor,
response-completion/validation timestamps, immutable revisions/raw replay и CA profile.
Никаких current SECID из старой 2025 карты. Новые данные можно допускать не раньше
witnessed receipt/validation, SYSTIME оставить vendor metadata. Это будущая отдельная
реализация, сейчас ни timer, ни current-market snapshot ею не создавались.

## Partial calendar diagnosis — 2026-09-07, not a source correction

Read-only snapshot at 06:53:17 UTC: 85 completed TradeStats jobs / 378668 rows,
8 jobs with source_date_coverage_admitted=false, 18 missing and30 extra contract-dates,
2768 extra-date rows. Missing asset codes0, alias mismatches0. This is partial coverage,
not the final totals or a separate full raw replay.

The first two discrepancies were BRV0 extra2020-09-11/14 (265 rows) and BRJ2
missing2022-02-28/03-01. The pinned map and source are not changed. Official notices
confirm the FO halt on [28 February](https://www.moex.com/n43241) and
[1 March](https://cbr.ru/press/pr/?file=28022022_205401SUP_MEAS28022022_205427.htm),
supporting a calendar explanation for those missing dates. They do not establish the
reason for every later missing record. The [24 March notice](https://www.moex.com/n45532?nt=101)
describes the changed index-contract regime; do not call all FO markets fully closed
throughout that interval.

FO weekend sessions began [16 August 2025](https://www.moex.com/n92862), initially
excluding currency contracts. Officially those sessions form part of the following
trading day. Extra Saturday/Sunday BR dates after that launch are consistent with
weekend activity, but AlgoPack calendar-date versus exchange trading-day mapping is
unresolved. Never silently shift dates, fill active-map gaps or discard these records.
The extra September2020 Friday/Monday dates are not explained by weekend sessions;
bounded official-notice search did not establish their cause.

Current pages with historical publication stamps are calendar context, not proven
original PIT versions. Additional full-history metadata/TS-OB checks are specified
in [quality V1](ALGOPACK_FO_HISTORY_QUALITY_V1.md).

## Prospective economic screen — design review only

The concrete next hypothesis is incremental information from vendor buy/sell
imbalance and opposing depth, conditional on the joint state of BR/MIX/RI/SI.
Compare the same small fixed model with price-only versus price+flow/depth inputs
before expensive neural training. Construct continuous ten-minute decision rows
independently of future label availability; future missing exits remain unresolved.
Avoid assigning aggressor semantics, absolute depth/flow units or bucket boundaries
that are not confirmed by the supplier.

No economic run is authorized by this source seal. AGENTS requires actual
available_at<=decision_at; calling a return assay a "current-vintage diagnostic"
does not create an exception. A separate economic seal is necessary but not
sufficient to override missing availability evidence. Historical supervised testing
awaits admission or an explicit user-approved research-policy exception, and would
still not establish live causality. A separately sealed contemporaneous FO source
can collect witnessed receipt/validation times without weakening historical flags.
