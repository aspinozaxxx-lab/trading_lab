# Calendar-bound report V1 server verification

2026-09-08. Code/test/spec pushed99762b7 before exact three-file archive deployment
on gpu-mlserver using tar --keep-old-files. No existing source overwritten.

111/111 related Linux synthetic tests PASS16.46s under trading-lab UID999:
calendar report9, calendar policy/source/core, combined report, evaluator, portfolio,
execution audit and forecast audit. Real journals with synthetic source/model fixtures;
not actual calendar entitlement or economic verification. Test process exited0.
Unique `/tmp/algopack_calendar_report_99762b7_tests` and
`/tmp/algopack_calendar_report_99762b7_cache`. Local1PASS/8Linux skips, encoding2/Ruff
check and git diff --check PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_calendar_report_v1.py | d32fb8b4da7d6dd8157701819a3d1b1c4592bc70ae55ca403efb46ef0a540d57 |
| test_algopack_paper_calendar_report_v1.py | 9c091edd3198247dcbcc2d071c0564c2cfe69652d61572a95cfb5b966dcb9b9b |
| ALGOPACK_PAPER_CALENDAR_REPORT_V1.md | 02fd564aa299ea6c4d63046d87781020774d354c5afad8b9c5cd2adf7bbd6934 |

Training/witnessed closure verification succeeded under UID999; actual activation
absent, F=null. No source HTTP, actual forecast, economic run or new model fit.
Next: runtime calendar scheduling, report persistence/CLI, latency, complete pre-F
config/seal/publication/service. No verified income claim.
