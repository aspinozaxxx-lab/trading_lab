# Immutable economic report store and CLI V1

2026-09-08. `algopack_paper_report_store_v1.py`. Full activation and current runtime/
calendar-report dependencies plus own SHA required. No HTTP, credentials or broker API.
F=null, actual activation absent. No actual economic report generated.

Publish reserves canonical evaluation_YYYYMMDD_started before invoking the calendar-bound
economic report. Output journal must be separate and non-nested relative to input roots.
Record activation/bundle identity, all source root paths, requested end date and anchored
ledger sequence/hash. Compare account state before/after build. COMPLETE contains original
result and actual start/completion clocks; FAILED contains scope and a sanitized state.
Partial, failed and completed attempts are immutable and block automatic rerun for that
end date. A later report through another date is a new period artifact, not overwrite.
Unresolved calendar is saved explicitly with evaluation=null, not reported as a profit.

Observe checks journal integrity, activation/bundle, canonical end/key and original
completion-to-durability chronology; returns original payload and actual reread time.
economic_recomputed=false: this operation verifies saved publication, not a fresh rerun
of all source/model evidence. No live/income admission flags become true.

## Offline server command, only after complete activation and F

`python -m market_lab.futures.algopack_paper_report_store_v1 --activation-sha256 SHA --through YYYY-MM-DD`

Run with the server venv under trading-lab, while --serve is stopped. The command never
stops the service itself. It acquires the runtime's nonblocking lifetime lock BEFORE
account construction/recovery. Missing activation or busy lock refuses; no competing
writer. Verify existing runtime components; create only private economic_reports child
under the existing activation root. Anchored account construction may finish a previously
durable command's verified anchor recovery; it never re-executes a trade. No init/reset.
stdout on success is only durable report reference; failure is sanitized review status.

8 tests: missing activation, busy lifetime lock before account construction, immutable
full report/later observation, no duplicate rebuild, retained sanitized failure, unresolved
calendar report, corrupt saved bytes and output/input isolation. Real Linux journals and
report wrapper; child calendar/numerical fixtures synthetic. Local2PASS/6Linux skips.
Server verification separately. Next: latency validation and final activation/service
configuration including a safe reporting cadence; no reporting inside trading windows.
