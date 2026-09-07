# Combined report V1 — server result

2026-09-08. Pushed/deployed `2b61650`; gpu-mlserver, Python3.11.4, UID999.
**418/418 related synthetic tests PASS,40,93сек**, including9combined-report tests.
Local1+encoding2PASS/8Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `dfab42a08c2eae5a82fbf6940e7ed4c5747bcd0d996836d6520a854b312c114d`
- tests `86033cef1b2a7a94ceb79600a13266d46d8d07e201b7acf781d9670f8bb1aae4`
- protocol `fc3e577c1281a8f1c28142ebb6b9ff179beb5968df3468992c8aa0ea99e8976c`

Frozen training44/witnessed7 metadata checks PASS; production activation absent, F=null.
No actual prices/labels/models read, market HTTP or economic run. Report integration
tests use real Linux journals and fixed evaluator; child forecast/execution audits are
stubbed here and exercised separately in their dedicated synthetic suites.

Verified missing day remains missing with metricsNone; flat day retains zero forecast
coverage and no premature annualization; actual ledger roundtrip counts; positive
coverage agrees with original forecast status; hash-valid forged equity, trade counts,
ledger reference or coverage classification rejected before evaluation.

No independent calendar source verification yet (calendar_source_verified=false).
Next official expected-day provenance, report persistence/CLI, production latency checks,
complete pre-F config/seal and service setup. Target20–50% income remains unverified.
