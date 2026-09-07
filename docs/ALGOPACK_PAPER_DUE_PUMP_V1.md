# Due-position pump V1

2026-09-08. `src/market_lab/futures/algopack_paper_due_pump_v1.py`.
Full activation/own SHA required; F=null. No economic tuning or live orders.

One pass locks dedicated attempts root, snapshots anchored positions, skips UNRESOLVED,
selects due≤actual now and orders exits first, then earliest due and stable position key.
Nothing due means no source HTTP and no attempt event. Otherwise UUID attempt and each
position STARTED are durable before processing. Outcomes are immutable; no old Fill is
reused as an execution command.

Within original30sec fill window collect post-boundary quote. Same asset/secid/due/side
of lifecycle shares a source reference between arms within this pass; each bridge
observation still verifies raw data and actual freshness. No stale-quote exception.
After deadline skip HTTP and delegate to bridge: entry CANCEL, exit UNRESOLVED.
If HTTP itself crosses deadline, same rules apply on actual post-request clock.
Source failure is explicit source_failed; pending remains eligible for a fresh attempt
on the next pass only while its original window permits it. This is operational
first-valid-quote retry, not price/outcome-based trade selection.

Fill/ledger error terminates pass as FAILED_REOPEN_REQUIRED; caller must reopen anchored
account before continuing. Any uncertain outcome is resolved by ledger replay, not
repeating saved command. If attempt publication fails, exception propagates; partial
events remain. Completed entry/exit and unresolved state are naturally not retried by
subsequent passes. Unresolved exposure is not erased.

## Remaining runtime work

No CLI/timer/unified scheduler yet. Scheduler must prioritize pump before forecast jobs,
avoid overlap under shared attempt lock, reopen after uncertainty, and use fixed as-of
witnessed-flow selection. Serial request latency can exhaust30sec; this module fails
closed rather than inventing fills, but production latency/entitlement is not established.
No actual market HTTP or models were run in tests. Offline economic evidence review,
evaluation wiring and full pre-F publication still required. Income20–50% unverified.

8synthetic tests: activation, exit priority, no early HTTP, entry/exit/no duplicates,
shared quote for two arms, expired entry/no HTTP, failed source crossing exit deadline,
uncertain fill/reopen. Child quote collection stubbed; anchored ledger/Linux IO actual.
