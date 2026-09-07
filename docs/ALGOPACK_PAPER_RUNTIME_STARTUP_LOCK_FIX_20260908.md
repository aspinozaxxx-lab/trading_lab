# Runtime startup lock ordering correction

2026-09-08. Pre-activation correctness fix to runtime V1; no strategy/model changes.

Inspection found --serve constructed Runtime (full anchored account replay) before
acquiring activation-root lifetime lock. A competing process could advance ledger
between that replay and lock acquisition/release. The new instance might then start
with an old RAM state, including missing a newly pending position until a later write
detected stale tail. Per-tick locks did not establish startup snapshot freshness.

Regression test first ran on previous code: **2FAIL**, showing construct before lock
both when lock was free and busy. Fix acquires DATA_ROOT/full-activation-SHA lock
before Runtime construction and holds it through serving. Busy lock means no account
construction or tick. Existing initialization remains explicit and unchanged.

Local after fix:2regressions+1runtime PASS/6Linux skips, Ruff PASS; Linux verification
pending. No production activation or serving process was running; F=null. The deployed
old unactivated runtime file will be retained during replacement, not deleted.
Previous runtime result hashes document the previous bytes, not the new corrected file.
Training44/witnessed7 sealed parents are not modified. Future bundle must pin new bytes.

This is a discovered scheduling bug, not financial evidence. Combined economic audit/
evaluation report, official calendar, latency and full service activation remain next.
