# Calendar core V1 verification, 2026-09-08

Code/test/spec pushed as297d088 before deployment. Exact three files exported from
that commit, transferred outside Git and installed using tar --keep-old-files in
`/opt/trading_lab`. No existing file overwritten, service activated or data fetched.

Linux gpu-mlserver, Python3.11 environment, runtime UID999, PYTHONDONTWRITEBYTECODE=1:
74/74 PASS in3.03s across calendar core21, evaluation17, combined report9 and
execution-source27. Synthetic only; actual calendar entitlement/schema not tested.
Unique pytest roots `/tmp/algopack_calendar_297d088_tests` and
`/tmp/algopack_calendar_297d088_cache`. No live process remains from this test run.

Local core+evaluation38 PASS; encoding2 PASS; Ruff check and git diff --check PASS.
An initial local failure exposed string/date mismatch in the reused date validator;
explicit conversion fixed it before commit/deployment. No frozen parent changed.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_calendar_core_v1.py | 2b010a3f7c2d6cb92c0353516dc366cebca89799fec68ff09378cf74dfbb2758 |
| test_algopack_paper_calendar_core_v1.py | f76b1ee3c579d93aea050c66001b007fa74cece5bbb64b057b5fbd905e098f15 |
| ALGOPACK_PAPER_CALENDAR_CORE_V1.md | 0bea0aba08167fd75193f27f0d509cf740b503c8eba065618ac46bddd9048ea5 |

Server training and witnessed closure verifiers returned successfully under UID999.
Actual forward activation file remains absent; F=null. No profit evidence produced.
Remaining: durable authenticated calendar capture, sealed version-selection/amendment
rule, calendar-to-report binding, report persistence, latency and complete activation.
