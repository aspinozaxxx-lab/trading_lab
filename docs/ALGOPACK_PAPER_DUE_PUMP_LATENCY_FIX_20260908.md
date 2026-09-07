# Shared quote aging: due pump fix, 2026-09-08

Pre-activation timing review found avoidable stale-quote exposure: prior queue order
was exit/entry priority, due time, then position key. Keys sort by model arm first.
For4assets×2arms this processes all price_flow positions before price_only, although
both arms reuse one quote per contract/due/type. Other assets' HTTP calls age that quote.

Two deterministic regression tests (entries and exits) with artificial2seconds per
quote request reproduce failure on old implementation: second-arm BR reaches a6second
old quote, beyond the existing5second freshness condition. The first fixture iteration
was missing synthetic activation fields; after fixing the fixture both tests failed
specifically on STALE_MASK. No measured production latency or real market values used.

Fix run's stable processing order to exit/entry priority, due, asset, secid, position.
Same-contract arms now consume their shared quote contiguously. Exit-first and earlier
due priority are unchanged. No threshold, prediction, source timestamp, freshness limit,
fill window, fee, model or strategy change. Fixed asset tie order is not chosen by PnL.
Existing public due_positions enumeration remains unchanged; grouping occurs in run.

Both regressions now PASS:4requests,8synthetic outcomes, no extra inter-group quote age.
Local pump suites4PASS/6Linux skips; server verification separately. Synthetic fill
function and journal are stubbed in timing tests, actual bridge/journal separately tested.

## Remaining timing evidence

This is not an SLA measurement. Four serial HTTP requests at up to10seconds each can
still exceed the fixed30second fill window even before replay/fsync overhead. Grouping
does not solve slow responses, quote age within one group's local work, or a blocking
slot task delaying the next pump. No freshness/window relaxation or fabricated fill.
Next: bounded multi-asset/pump timing and scheduler interference validation before
activation; actual live transport latency can only be observed after authorized F.

Deployment must verify prior unactivated pump SHA, absent activation/no serving runtime,
retain old pump file, then install exact pushed bytes. Future bundle must pin new SHA.
F=null; no actual model/market/economic execution.
