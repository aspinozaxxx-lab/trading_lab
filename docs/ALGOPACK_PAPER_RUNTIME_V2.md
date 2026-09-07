# Integrated asynchronous paper runtime V2

2026-09-08. New entrypoint `algopack_paper_runtime_v2`; actual activation absent, F=null.
Config must explicitly select runtime_protocol=algopack_paper_runtime_v2 and complete
closure must include new bytes. Legacy V1 CLI now refuses a different selected protocol
before credentials/session access. Its reusable helpers remain usable by sealed workers.

Initialize/check/serve CLI mirrors original lifecycle, same private components and
activation-root lifetime lock BEFORE account recovery. Runtime creates one anchored
execution owner, dedicated async due pool, preparation supervisor and at most one slot.
Tick ordering: due executor → preparation poll → existing slot step → optional dispatch
or maintenance. Slot dispatch immutable before child/slot creation; restart never replays
an existing dispatch. Failed preparation alone does not block due servicing while child
is being terminated/reaped. Uncertain due/slot writes invalidate the runtime for reopen.

No synchronous forecast/model/network execution in the trading-slot path. Preparation
has its own process/session; slot sources and due sources have independent bounded pools.
Terminal slot retained until children reaped. End+10 stops admission, never extends fills.
Calendar09:00–09:05 and daily18:20–18:20:30 use existing fixed procedures only when no
slot/preparation/due worker is active and no actionable position remains (flat or solely
UNRESOLVED risk). Skip, do not delay a due trade to perform maintenance. Missing scheduled
calendar/snapshot remains an explicit evaluation failure under existing report rules.

Serve idle sleep0.1second is polling cadence, NOT an achieved deadline bound. Runtime
checks/replay/fsync/spawn overhead and actual transport latency still need measurement.
On Python shutdown kill all owned children first, then bounded2second wait per child for
reaping, outside trading loop. Service MUST use control-group cleanup too: SIGTERM or
crash can bypass Python finally. No automatic service stop by reporting command.

11new tests: missing activation, legacy CLI refusal for async config, original4injected
interference cases, no duplicate dispatch after restart, due failure before other work,
guarded morning maintenance, daily ordering and kill-all-before-reap. Actual Linux
runtime/anchor/scheduler journals; async actors controlled doubles. This proves ordering
under the reproduced artificial durations, NOT actual provider SLA or full live fills.
Child component suites separately exercise source/forecast/ledger bindings.

Local V2+startup4PASS/9Linux skips; server result separately. No --initialize/--serve,
actual workers/market/model/economic run. Before deployment retain original unactivated
V1 file; future closure must pin changed legacy guard bytes and V2.

Next: broader integration/performance verification, service configuration with child
cleanup/report cadence, complete pre-F config/seal and actual future boundary publication.
No new strategy, threshold, fee assumption, training or income claim.
