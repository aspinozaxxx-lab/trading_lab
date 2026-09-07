# Runtime calendar verification, 2026-09-08

Code/spec pushed cff39e5 before deployment. Before replacing unactivated runtime,
verified old SHA67a34065e114f6e25faf833c55c882aad6b5a0a780b0f81dad31ad7f5417b25b,
absent activation and no matching python runtime --serve process. Old runtime retained
at `/tmp/algopack_paper_runtime_v1_09777ff_retained.py`; exact pushed new files installed
with tar --keep-old-files. No actual --initialize/--serve or calendar HTTP performed.

First Linux suite79PASS/2FAIL: fixture initialized account at11:04 then moved artificial
clock back to09:00; durable journal correctly rejected backward-time reopen. Test-only
fix6988394 sets initial fixture clock before genesis. Runtime code unchanged by fix.
Old test retained `/tmp/test_algopack_paper_runtime_calendar_v1_cff39e5_retained.py`.

Final81/81 related Linux synthetic tests PASS4.73s UID999: runtime/calendar/startup,
calendar report/policy/source/core and activation. Unique test/cache roots
`/tmp/algopack_runtime_calendar_6988394_tests` and `_cache`; process exited0.
Local prior suite4PASS/13Linux skips; encoding2 and Ruff/diff checks PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_runtime_v1.py | 79a1e87d40f872b3449e4b3d39f6ceea21d45f8f1db60452e417fdc27d098c97 |
| test_algopack_paper_runtime_calendar_v1.py | 64b9c6612e775975a96a9cabed0e4bfefb97e343d32fac4b4fe29b085b39c99a |
| ALGOPACK_PAPER_RUNTIME_CALENDAR_V1.md | 151e37c08893b08274131658a96717b461f8a7c72482225b6e863626520bd605 |

Training/witnessed closure verifiers succeeded under UID999; old runtime retained,
activation absent. Future seal must pin current runtime SHA above, not startup-fix SHA.
F=null, no economic outcome. Next: report persistence/CLI, latency and full activation.
