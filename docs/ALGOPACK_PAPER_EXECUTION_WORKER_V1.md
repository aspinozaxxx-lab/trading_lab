# Bounded execution-source worker pool V1

2026-09-08. Infrastructure for asynchronous execution-source requests, not yet integrated
into the runtime. No actual workers/HTTP/fills launched. F=null, activation absent.

Job is an immutable key/kind/not-before/deadline/asset/secid descriptor. Closed quote or
intraday-calendar routes only; same Moscow calendar date, after F, at most10minute job
span. The eventual executor must pass the actual phase deadline (e.g. due+30seconds for
fills); maximum job span is not an extension of execution rules. Canonical async_UUID
key, activation and own closure checked before spawn or child credential access.

Pool owns at most4children and has no waiting queue. Full pool returns POOL_FULL before
reserving another job. STARTED is durable before fixed module spawn; restart cannot
repeat the same key. Separate processes create their own requests.Session; no shared
session or credentials in command line/stdout/stderr. Existing execution-source collector
retains TLS, raw response and per-page journal behavior. No portfolio/account methods.

Poll checks every child without wait/join/communicate. Deadline requests termination;
5second monotonic grace then kill. ProcessLookupError from a concurrent exit is reaped
on the next tick. Slot freed only on observed exit; durable terminal record retains
expired/failed/success exit state, never source admission just because exit0.

Observe within the original job deadline fully replays source receipts, checks earliest
page request against not-before, exact quote asset/contract and deadline after replay.
Returns only an observed reference/candidate, not a fill. Existing execution bridge must
still enforce5second quote freshness, source timing, margin/fees and30second fill rule.

10 tests: missing activation, capacity4/no queue, independent child expiry, exit0 not
admission/retry, raw source roundtrip/contract mismatch, late observation, early/long/
malformed/unknown-route rejection. Children mocked; actual Linux journals and existing
fake HTTP source replay. Local1PASS/9Linux skips; server verification separately.

## Remaining integration boundary

Executor must reserve/prioritize capacity for exits and avoid letting preparation jobs
occupy every execution worker at a due boundary; no performance-dependent arm selection.
Main process remains sole ledger owner. Source observation/fsync/activation validation
still require measured local latency; poll is non-waiting, not a hard real-time guarantee.
Service control-group cleanup must prevent orphan workers after restart. Runtime still
uses synchronous execution source calls today: this module alone does not fix the
reproduced interference or establish a production network SLA. Next: async executor
integration, response consumption and deadline/failure/restart matrix verification.
