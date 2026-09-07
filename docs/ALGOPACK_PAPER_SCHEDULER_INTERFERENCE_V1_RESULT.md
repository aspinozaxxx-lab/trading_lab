# Scheduler interference reproduction result

2026-09-08. Pushed d1f3776 before exact test/doc deployment with tar --keep-old-files.
No production source or service changed.23/23 Linux synthetic tests PASS2.13s under
trading-lab UID999, including4interference cases plus runtime/startup/calendar and
quote-aging regressions. Process exited0; unique
`/tmp/algopack_interference_d1f3776_tests` and `_cache`.

Crucial interpretation: late-slot cases reproduced due servicing at+60s/+39s, beyond
the30s execution window, even with zero restart overhead. PASS confirms this remaining
unsafe scheduling behavior. It does NOT establish readiness or profitable execution.
Early cases remained schedulable with injected timing. No actual latency benchmark,
market request, forecast, fill or protected data read.

Local/server matching SHA-256:

| File | SHA-256 |
| --- | --- |
| test_algopack_paper_scheduler_interference_v1.py | 6d6bbdf306946669a37e48daaa3f1f0ca969ee365551b49e30b156f680ec141d |
| ALGOPACK_PAPER_SCHEDULER_INTERFERENCE_V1.md | fffbaae10389e44940f332f8cb5d254128e746463dc08efdbdde16bc68edf381 |

Ruff, encoding2 and git diff --check PASS. Next: separate bounded source/model
preparation from authoritative execution, or verified cooperative yielding. Do not
activate the current synchronous design on the strength of this green test result.
F remains unassigned; no income evidence produced.
