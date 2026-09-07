# Fixed forecast publication coverage V1

2026-09-07. Integration/reporting module, no new strategy. F=null, full activation
requires own source SHA. `src/market_lab/futures/algopack_paper_coverage_v1.py`.

Для заданного weekday после F фиксированы42 E-slots10:10–17:00Moscow через10мин,
по4asset decisions на arm: denominator всегда168. До последнего entry boundary17:10
дневной отчёт не создаётся. Official evaluation calendar обязан определить набор
дней отдельно: weekday grid не доказывает, что биржа работала в праздник.

Каждый slot ищется по canonical forecast key, без отбора по успешным публикациям.
Отсутствующая публикация → missing4. Partial/corrupt/mismatched/late durable publication
→ failed4. Valid timely READY → ready4; SLEEP_MISSING_FEATURES → sleep4. Остальные
arm statuses → failed4. Два arm считаются отдельно, сумма всегда168 для каждого.
Actual journal hashes/F/chronology/model identities/source references перепроверяются.
Источник обязан быть durable до claimed input observation; это ещё не полный raw replay.

Отчёт читает original publication, а не consume_forecast поздним временем отчёта:
иначе все дневные прогнозы ошибочно стали бы late-consumption. Timely publication
НЕ доказывает timely runtime consumption/entry. Поэтому forecast_consumption_verified
всегдаfalse. Это forecast coverage, не журнал торговых отказов/risk decisions.

`build` read-only возвращает COVERAGE_NOT_PERSISTED с42slot reasons/references и actual
observation clocks. `publish` сохраняет immutable coverage_YYYYMMDD в отдельном report
root. Повторная запись запрещена; no backfill/overwrite. Не смешивать replay-time clock
отчёта с первоначальной доступностью прогноза. Exceptions не публикуют секретный текст.

Следом snapshot builder должен связать эти4counts с replayed ledger entries/closed/
open/pending/unresolved и scheduled daily MTM. Затем offline source-evidence review,
runtime consumption/failure журнал и scheduler/full publication до F. Coverage alone
не допускает metrics/promotion и не подтверждает20–50%годовых.

8 synthetic tests: fixed grid, activation refusal, all missing, independent arms,
late publication, partial failure, immature day и immutable report. Linux использует
реальный durable journal; маленькие source payloads synthetic, не actual API response.
