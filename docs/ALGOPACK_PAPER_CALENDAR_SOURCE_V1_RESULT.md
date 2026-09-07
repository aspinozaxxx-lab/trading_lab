# Calendar source V1 server verification

2026-09-08. Pushed c864a38 before deployment. Three exact new files exported from
that commit and installed on gpu-mlserver via tar --keep-old-files. No existing file
overwritten, service activated or actual HTTP request performed.

113/113 Linux synthetic tests PASS4.43s under trading-lab UID999:
calendar source, calendar core, journal, execution source, activation and combined report.
Includes all14new source tests and real durable journal behavior with fake HTTP.
Unique roots `/tmp/algopack_calendar_source_c864a38_tests` and
`/tmp/algopack_calendar_source_c864a38_cache`; test process exited0.
Local10PASS/4Linux skips, encoding2PASS, Ruff check and git diff --check PASS.

Exact local/server SHA-256 matches:

| File | SHA-256 |
| --- | --- |
| algopack_paper_calendar_source_v1.py | 15a6b31be32e8968133a4855624594e9dfc4ca94e0ad0d66eddc675baa6fb4d7 |
| test_algopack_paper_calendar_source_v1.py | 00fd5280b12a00642102bb6239605c2925c13655c63e5f599dc1b61d818f7e0f |
| ALGOPACK_PAPER_CALENDAR_SOURCE_V1.md | d524a675b39d3af484d6d4ec07a8e239ed638e7bf01536a7d0985c8711996314 |

Training and witnessed parent closure verifiers succeeded under UID999. Production
activation file absent, F=null. No new actual calendar or market data inspected.
No economic result, income verification, automatic calendar job or paper runtime activation.

Next: sealed calendar version-selection/cutoff/amendment policy, report expected-day
binding, immutable report persistence/CLI, latency and complete pre-F activation/service.
