# Preparation completion intake V1

2026-09-08. New bridge from isolated preparation supervisor to future async slot
admission. Own/worker/runtime closure required; actual activation absent, F=null.

Exact fixed slot after F, E+3 minimum. Derive canonical scheduler/market roots and
prepare_E key internally. Before deadline and without supervisor-finished publication,
return WAITING_PREPARATION without reserving an intake attempt. Once ready reserve an
immutable intake_E_started under scheduler transaction lock. Existing/partial attempt
returns EXISTING_INTAKE_ATTEMPT, never re-executes consumption after uncertain failure.

At or after E+10 record MISSED_INTAKE_DEADLINE without forecast reads. Otherwise check
supervisor start, child start/complete and supervisor WORKER_EXITED protocol/activation/
states, strict integer exit0, exact information_end and original durable chronology.
Forecast must reference this exact slot and have become durable inside child lifetime.
Consume via existing journal at actual read time, retaining its deadline masks; save
forecast reference, actual observation clock and arm states in immutable intake result.

This verifies publication/supervision binding, not a second numerical model run. Existing
forecast audit independently replays raw sources and pinned model output for economic
reporting. Intake never changes a position, price, timestamp or model; result remains
FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED. Later execution must recheck actual time and
source freshness, rather than treating this intake as an irrevocable trading permission.
Late completion of the intake's own journal write does not extend the entry deadline.

9 tests: activation, waiting then completion, once-only consumed chain, deadline before
forecast IO, foreign slot, publication outside worker lifetime, failed child, bool exit
code and nonzero exit. Linux journal/forecast validation actual; synthetic completion
and forecast payloads, no HTTP/model. Local1PASS/8Linux skips; server result separately.

Next: async slot calendar/marks/intent stages, integrated runtime with due service first,
full original interference/deadline/restart matrix and activation. This helper alone does
not replace the old synchronous scheduler or prove production latency/income.
