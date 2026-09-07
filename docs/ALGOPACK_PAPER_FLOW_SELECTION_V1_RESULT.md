# Flow selection V1 — server result

2026-09-08. Pushed/deployed `43adb25`; gpu-mlserver, Python3.11.4, UID999.
**383/383 related synthetic tests PASS,28,07сек**, включая9selection tests.
Local8+encoding2PASS/1Linux skip; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `a87f983e53df101d26336b2ba087bc6f1c2ff365ca31beb5f9953a3b529bb2f8`
- tests `fb4a6f8b16add7d939745c0bd0e2a1ac4dddfed89f42e3bf7239632b25070519`
- protocol `a18729689d9e819d51224123dcb26eb681ff8072517c465369631d8ce47a9ff3`

Frozen training44/witnessed7 metadata checks PASS; production activation absent, F=null.
No actual source selection, archive/model/price reads, HTTP or economic run. Tests use
synthetic manifests; import-reuse test stubs predictor audit but uses actual journal.

Verified latest-completion ordering, future completion exclusion, pre-F/incomplete
skip before manifest IO, corrupt metadata/replay no fallback, explicit missing result,
existing import replay/no overwrite and partial import refusal. Actual inference
availability still uses observation/publication clocks, not vendor timestamp alone.

Next: unified runtime scheduler/CLI with durable selection evidence, offline economic
source/Fill audit and evaluation wiring, full pre-F publication. Income20–50% unverified.
