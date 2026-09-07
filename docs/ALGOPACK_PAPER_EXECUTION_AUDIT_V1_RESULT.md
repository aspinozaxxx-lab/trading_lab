# Execution-binding audit V1 — server result

2026-09-08. Pushed/deployed `e01a84b`; gpu-mlserver, Python3.11.4, UID999.
**400/400 related synthetic tests PASS,32,18сек**, включая10execution-audit tests.
Local2+encoding2PASS/8Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `9643282aa699679da68cfe07974fb5320578dc1c76dbe581d428f8223fb24242`
- tests `9b684d53ef21adcda377a48d6fa75aead188561c46646e7d84d30a2c41363801`
- protocol `c18ef4c5b12f3f720d39978510d18cbf330af1fbf054994e7b53845394890c64`

Frozen training44/witnessed7 metadata checks PASS. Production activation absent,
F=null. No actual archive/price/model reads or HTTP/economic run. Test ledger actual
Linux; reconstructed quote/calendar/forecast fixtures stubbed. Parent source parsers
and transport replay remain covered by their separate synthetic tests.

Verified intent/fill roundtrip binding, altered price/mid/quantity rejection,
positive/missing MARK replay, missed-entry cancellation, original observation
chronology, foreign root rejection before IO and full ledger parity.
Status does not independently reproduce forecasts: forecast_recomputed=false and
target_income_verified=false. Do not promote execution binding PASS to economic PASS.

Next: numerical forecast/source-feature replay from fixed model bytes, evaluation/
report wiring, calendar/latency checks and final activation/service setup. No income
20–50% evidence has been obtained by these technical tests.
