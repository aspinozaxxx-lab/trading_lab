# Offline execution-binding replay V1

2026-09-08. `src/market_lab/futures/algopack_paper_execution_audit_v1.py`.
Requires full activation and own SHA. F=null. No actual data audit/economic run yet.

Given an already verified AnchoredPortfolio, replay each ledger event from initial
state. Before parent transition, verify economic evidence scope, clocks and raw source
bindings, reproduce fixed intent/fill/mark, compare full canonical serialized value.
Finally compare replayed state and full current ledger tail with anchored snapshot.
Concurrent tail advancement fails, not silently accepted.

Source reference is observed now from immutable journal and complete execution-source
raw replay. Original observation time must lie between source durable publication and
decision time. A separate in-memory reconstruction uses that recorded original time
to rebuild historical Quote/Terms/Session; no record, actual audit clock or live source
is backdated. This trusts the sealed runtime's durable clock evidence, not an independent
exchange execution certificate. Actual audit timestamp is recorded separately.

RESERVE recomputes fixed make_intent from original consumed forecast/quote/calendar and
then-current portfolio risk. ENTRY/EXIT recompute simulate_fill from stored intent,
its durable timestamp and original quote evidence. MARK covers every open position;
positive values must match source projection, missing masks explicit. CANCEL/UNRESOLVED
must match fixed missed-window reason/timing and correct pending/open state.
Unknown operation/evidence, altered price/mid/quantity or foreign source root fails.

## Scope limits

Status EXECUTION_BINDINGS_REPLAYED is NOT full economic admission. Forecast payload
identity/model hash checked, but numerical forecast not yet independently recomputed:
forecast_recomputed=false. Need forecast/source-feature replay and report/evaluation
wiring, official calendar and runtime service/seal before F. Failure/missing masks do
not prove that a missing observation could never have been available elsewhere.
No alteration of historical2026 restrictions, execution thresholds or target income.
No broker execution or20–50% income claim; target_income_verified=false.

10synthetic tests: activation, durable chronology, roundtrip binding replay, altered
price/mid/quantity rejection, positive/missing MARK, missed entry cancellation and
foreign root rejection before IO. Linux ledger actual; reconstructed source fixtures
stubbed, while parent execution-source suite covers its own raw parsers/replay.
