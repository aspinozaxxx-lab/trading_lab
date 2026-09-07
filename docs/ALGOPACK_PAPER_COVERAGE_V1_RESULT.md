# Coverage V1 — server result

2026-09-07. Pushed/deployed `0d5bc62`, gpu-mlserver, Python3.11.4, UID999.
**352/352 related synthetic tests PASS,22,99сек**, включая8coverage tests.
Local2+encoding2PASS/6Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `79e4ee1f62baafbd1616fe0015b61831778c67bb098c303024fe6dd3b1f8622e`
- tests `4835d784cdcf0dc60e8ab1b3719b2eea149e06bd9a30cc21e0354c3b9d287e08`
- protocol `b3723df542e749d040be06276d75ca9ed94f77f600a6411b84b73459510f766c`

Metadata-only frozen training44/witnessed7 verification PASS; production activation
отсутствует, F=null. No actual source HTTP, price/label reads, forecasts или PnL.
Tests используют synthetic publications и настоящий Linux journal.

Проверены168missing при пустом дне, независимые ready/sleep arms, failed вместо missing
для partial и late durable forecast, maturity gate и immutable publication. При
позднем чтении отчёт не заменяет original publication на late-consumption результат.
Timely consumption, economic source replay и исполнение этим не доказаны.

Следом scheduled ledger-derived snapshots:4publication counters соединить с
entries/closed/open/pending/unresolved из verified ledger и с daily mark. Затем
runtime consumption/failure evidence, offline audit и scheduler/full pre-F seal.
Целевая доходность20–50% не подтверждена, actual economic run ещё не начат.
