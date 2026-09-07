# Async slot admission server verification

2026-09-08. Pushed4493bc9 before exact three-file deployment with tar --keep-old-files.
53/53 related Linux synthetic tests PASS14.36s UID999: async slot9, intake9, async due9,
execution worker10, mark refresh8, execution bridge8. Slot uses actual attempt journals
with fake background/intake/ledger callbacks; separate suites cover real child bindings.
No actual workers, HTTP, production models or economic trades. Test process exited0;
unique `/tmp/algopack_async_slot_4493bc9_tests` and `_cache`.
Local1PASS/8Linux skips, encoding2/Ruff and git diff --check PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_async_slot_v1.py | c821259a7601eab67377ffbe20add8d92800f56bc560b9dc88dc0b5012f95441 |
| test_algopack_paper_async_slot_v1.py | 677a8016242352bf1b8e89b752fc294889b354e7c75b096f8f29b43a402a6766 |
| ALGOPACK_PAPER_ASYNC_SLOT_V1.md | bbf5541ceb38aa0c0c625c80d135cf775497dc451bc89b9e7b2b6a2c2251d129 |

Training/witnessed closure verifiers succeeded under UID999; activation absent, F=null.
Next: integrated async runtime, background preparation plus due-first slot ticking,
calendar/daily scheduling and full late-work/restart matrix. No production latency or
income admission; legacy runtime remains synchronous and must not yet be activated.
