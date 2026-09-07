# Immutable report store V1 server verification

2026-09-08. Pushed a199992 before exact three-file archive deployment to gpu-mlserver
using tar --keep-old-files. No existing source overwritten, actual report/HTTP or
service stop performed. Production activation remains absent, F=null.

100/100 related Linux synthetic tests PASS9.86s under trading-lab UID999: report store8,
calendar report, combined report, calendar policy, runtime/calendar/startup, portfolio
anchors and journal. Actual durable storage/locks; synthetic calendar/model fixtures.
Unique `/tmp/algopack_report_store_a199992_tests` and `_cache`; process exited0.
Local2PASS/6Linux skips, encoding2/Ruff and git diff --check PASS.

Local/server SHA-256 matches:

| File | SHA-256 |
| --- | --- |
| algopack_paper_report_store_v1.py | bfb23e51fcc1fcfc00988dc5752ad36d79d178bb8c301770118ced9ec168656d |
| test_algopack_paper_report_store_v1.py | 6e85afa644249eae52643ea340965141af9fef7441e709d6acc1660adf617e28 |
| ALGOPACK_PAPER_REPORT_STORE_V1.md | e351fc0df2321edbec610e2620386b5e4e1b1297bc5ffc43af3011220f4c37ca |

Training/witnessed parent closure verifiers succeeded under UID999. No income claim.
Next: latency verification, full activation/service configuration and safe report cadence.
Offline CLI does not stop --serve automatically; reporting must not interrupt fills.
