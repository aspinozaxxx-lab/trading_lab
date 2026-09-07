# Async due execution verification

2026-09-08. Pushed a2c1b68 before exact three-file archive deployment to gpu-mlserver
using tar --keep-old-files. No existing source overwritten or actual worker/runtime run.

52/52 related Linux synthetic tests PASS10.21s UID999: async due9, execution worker10,
execution bridge8, execution audit10, portfolio anchors13, quote-aging2. Actual anchored
journals/fills use synthetic quotes and fake source pool; no real API/trade/economic run.
Unique `/tmp/algopack_async_due_a2c1b68_tests` and `_cache`; process exited0.
Local2PASS/7Linux skips, encoding2/Ruff and git diff --check PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_async_due_v1.py | 4465e78c4d8b13a0ec921c22b4261d358f7ab8a629e479fb6277d3c8f0008b49 |
| test_algopack_paper_async_due_v1.py | 8d73043ad9878d808919f547bd8e220772869a8474638689e52bbdc607dbaa24 |
| ALGOPACK_PAPER_ASYNC_DUE_V1.md | 37b68be9b4180a195cad36335c8eba24328eed05e13a5c64803e9a3e334831fa |

Training/witnessed closure verifiers succeeded under UID999; actual activation absent.
F=null. Next: async preparation-result/slot-admission state machine, runtime integration
and full interference/deadline/restart verification. Old runtime still synchronous;
component verification alone is not activation or a production latency/income claim.
