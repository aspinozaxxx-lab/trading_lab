# Asynchronous due execution owner V1

2026-09-08. New Executor bridges dedicated execution-source pool to existing anchored
ExecutionBridge. Own activation closure and exact worker/execution market-root identity
required. Caller must hold runtime lifetime lock. No standalone service or activation.

Each tick polls owned children without waiting, groups current due positions by exit/
entry, due time, asset and contract. Exits first, earlier dues first, both model arms
share one request and consume contiguously. Pool dedicated to due operations (not slot
preparation/calendar); starts up to4jobs, leaves excess groups for another tick.
Before due there is no job; not-before=due and deadline=due+30seconds. No main-thread HTTP.

On observed successful child exit, fully observe current source then call existing
fill_due serially against current authoritative state. It still enforces fresh actual
quote and original execution/fee/risk rules. Missing/corrupt/late source produces explicit
source-completion failure, not invented fill; retry only on a later tick with fresh UUID
while original window remains. Invalid/stale source exceptions are sanitized.

At actual now>deadline invoke existing bridge without quote: cancel unfilled entry or
retain open position as UNRESOLVED. Child remains owned until reaped; completed mapping
is removed even when its position has expired/disappeared. No lost economic risk.
FILL_STARTED/FINISHED and source outcomes durable in dedicated attempt journal.
Any uncertain fill/write invalidates executor and requires anchored reopen; no replayed
fill. Normal restart must occur only after service control-group child cleanup.

9tests: activation, grouped exit priority, no early job, shared two-arm async quote/no
fill while running, fresh later retry, expired entry/exit, invalid source and lost fill
acknowledgment. Linux tests use real anchored bridge/ledger with fake pool/source fixture;
pool lifecycle/raw transport have separate suites. Local2PASS/7Linux skips.

This replaces a blocking due pass as a component, NOT yet the running scheduler. Runtime
still requires preparation completion/slot admission state machine and integration.
Source replay, fsync and spawning have local latency; no hard real-time/network guarantee.
Do not activate legacy runtime because this component passed tests. F=null, no actual
workers, HTTP, trades, retraining or income result. Next async slot/runtime integration
and full interference/deadline/restart tests before activation.
