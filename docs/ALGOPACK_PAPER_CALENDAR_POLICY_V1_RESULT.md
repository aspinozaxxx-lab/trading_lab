# Calendar policy V1 server verification

2026-09-08. Pushed f908f0c before exact three-file archive deployment to gpu-mlserver
using tar --keep-old-files. No existing source overwritten, actual HTTP or service run.

124/124 related Linux synthetic tests PASS5.28s under trading-lab UID999:
policy11, calendar source/core, journal, execution source, activation and combined report.
Real durable journals, fake HTTP and synthetic activation/clock; not live entitlement
or economic verification. Unique `/tmp/algopack_calendar_policy_f908f0c_tests` and
`/tmp/algopack_calendar_policy_f908f0c_cache`; process exited0.
Local3PASS/8Linux skips, encoding2PASS, Ruff check and git diff --check PASS.

Local/server SHA-256 matches:

| File | SHA-256 |
| --- | --- |
| algopack_paper_calendar_policy_v1.py | 461528deaf1dd42aa66308da925f416c6d13074b7079e7ff4802516693a4ef0f |
| test_algopack_paper_calendar_policy_v1.py | 7dd48d4c39fd95bc1234751cc761ccc3dc8f09998809a2740aa0c46e5b88a55d |
| ALGOPACK_PAPER_CALENDAR_POLICY_V1.md | 14f5a2ede2810a7077005e69870006b54da94ad10562eb73a5f82088b0581a30 |

Training and witnessed closure verification succeeded under UID999. Actual forward
activation absent, F=null. This is not a completed calendar-to-economic-report binding.
Next: report wrapper with full excluded-day/exposure ledger checks, runtime canonical
calendar scheduling, persistence/CLI, latency and full pre-F activation/service.
