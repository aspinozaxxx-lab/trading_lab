# Calendar-bound economic report V1

2026-09-08. `algopack_paper_calendar_report_v1.py` wraps fixed calendar policy and
the existing combined economic report. Full activation plus own/source/policy/report
closure required. Actual activation absent, F=null, no economic run.

Caller supplies through date, never expected_days or a calendar digest. Calendar policy
first reconstructs complete F-to-through source evidence. If unresolved, return no
evaluation before economic ledger/model reads. Missing calendar cannot shorten a curve.

For resolved calendar replay the full anchored portfolio prefix. At every excluded
calendar date require no carried position, pending reservation or unresolved exposure;
permit only flat MARK events. Any RESERVE/ENTRY/EXIT/CANCEL/UNRESOLVED on an excluded
date fails, even if a roundtrip leaves the final state flat. Check economic events whose
durable publication crosses an excluded midnight. Days without events still receive
the carried-risk check. Replay remaining suffix, compare account cache and full recovery.

Only then invoke the existing source/model/execution/snapshot/coverage report with the
calendar-derived expected tuple and evidence digest. Confirm the same ledger prefix.
Preserve the child's calendar_source_verified=false (that module did not verify it);
the wrapper's true flag certifies the added calendar binding only. Missing snapshots
remain missing, an empty expected calendar yields NO_DATA, no premature annualization.
execution_admitted=false and target_income_verified=false always.

9 tests: activation, open-calendar report, missing snapshot, unresolved calendar before
economic reads, flat closed day/no profit, excluded reservation for closure/weekend,
carried risk on a day without events, completed roundtrip cannot be dropped.
Real Linux journals and parent report; calendar policy and numerical child audits
stubbed here, with separate source/policy/audit suites. Local1PASS/8Linux skips.

Next: runtime canonical calendar scheduling, immutable report persistence/CLI,
latency and complete pre-F config/seal/publication/service. Models unchanged.
