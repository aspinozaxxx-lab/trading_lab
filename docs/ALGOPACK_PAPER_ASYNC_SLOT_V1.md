# Stepwise asynchronous slot admission V1

2026-09-08. New Slot component; not yet an activated integrated runtime. F=null.
Caller holds runtime lifetime lock and ticks due executor before each slot step.
No main-thread HTTP, subprocess wait/join or model fitting. Full own/dependency closure.

Canonical async_slot_E STARTED reserves one attempt. Stages: preparation intake,
background intraday session calendar, background quote set, all-open MARK, then one
asset's two model-arm intent decisions per tick in fixed asset order. Dedicated pool
has4children, separate from due pool. Quotes cover union of current open contracts and
forecast target contracts; same contract reuses one reference for MARK and reservation,
avoiding another HTTP round between valuation and decision. More than4unique contracts
are queued explicitly by repeated ticks, not an unbounded worker queue.

Before mark write reread current positions: removed positions are excluded; newly opened
positions without a collected reference get unknown mark via existing refresh, never an
old value. Existing bridge reobserves all decision inputs and enforces freshness/fees/
budget/model statuses. Shared quotes do not relax the5second freshness rule. Local
replay/fsync can still age a source and must be measured; no hard real-time claim.

Missing session stops admission. Failed quote masks corresponding intents, with explicit
per-arm outcomes. Actual E+10 expiry stops new decisions and marks slot EXPIRED; keep
ticking terminal slot to reap/terminate owned children. Partial reserved positions remain
owned by the independent due executor. Uncertain mark/reserve/write invalidates slot and
requires anchored reopen, not re-execution. Existing/partial slot cannot be reconstructed
by replaying its intent decisions. Restart requires service child cleanup first.

9tests: activation, full phased8decision path/once-only journal, waiting intake without
jobs, expiry/reaping, failed calendar, missing quote masks, mark/entry reference reuse,
position removed during source work, uncertain reserve. Actual Linux attempt journal;
pool/intake/mark/reserve callbacks synthetic. Separate suites cover those child bindings.
Local1PASS/8Linux skips; server verification separately.

Next: combine preparation supervisor, this slot, async due owner and calendar/daily
snapshot scheduling in new runtime; repeat original late-preparation interference tests.
Old runtime remains synchronous and unadmitted. No real request/trade/profit result.
