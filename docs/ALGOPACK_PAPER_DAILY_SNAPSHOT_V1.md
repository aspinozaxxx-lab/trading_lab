# Daily ledger-derived snapshot V1

2026-09-07. Integration-only; `src/market_lab/futures/algopack_paper_daily_snapshot_v1.py`.
Requires complete activation and own module SHA; F=null, no actual economic run.

Fixed window18:20:00–18:20:30Moscow. Outside it publish refuses before ledger mutation.
Within it: fixed-slot coverage replay → reopen/verify anchor commands and ledger →
replay daily ENTRY/realized EXIT counts → source-bound MARK → actual post-commit
valuation → immutable daily_YYYYMMDD report in a dedicated root. Stale account or
unexpected intervening ledger sequence fails. No caller-supplied equity/counts.

Daily entries count by Fill observation Moscow date; closed count only when reducer
actually realizes the exit, not each EXIT attempt. Pending/open/unresolved count from
current ledger; unknown equity remains None. Both arms and both cost scenarios use
the same actual state. Publication counts remain distinct from consumed decisions.

Snapshot observed_at is when the builder has observed/replayed the ledger result;
valuation_at is actual post-MARK clock. Report payload retains both. `observe` later
checks original identity and valuation≤observation≤durable publication≤18:20:30;
it does not backdate a new valuation or replace original clocks with report-read time.
If publication crosses the deadline, immutable record stays but status is
RECORDED_LATE_NOT_EVALUABLE and observe rejects it. Missing day stays missing.
If preparation times out after MARK, ledger MARK stays, no daily snapshot is admitted.

## Remaining gates

This is not autonomous scheduler or final economic report. Official expected-calendar
evidence, runtime forecast consumption/failure recording, offline source/Fill replay,
evaluation/report wiring and full publication before F still required. Later observe
validates saved builder/publication provenance, not a fresh full raw-source economic audit.
Current builder fully replays history inside30sec: correct fail-closed behavior, but
long-run latency is not proven. A verified pre-window replay/cache may be needed;
never relax the deadline or import arbitrary serialized cash to meet it.

No model fit, historical PnL, market HTTP or live orders. No target income verification.
7 synthetic tests: activation refusal, flat/full-missing day, realized roundtrip
counts/equity and next-day read clocks, unknown open position, early/late invocation,
late publication rejection. Real Linux journal, synthetic source stubs only.
