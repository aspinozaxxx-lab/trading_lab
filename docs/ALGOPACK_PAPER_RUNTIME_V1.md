# Unified prospective paper runtime V1

2026-09-08. `src/market_lab/futures/algopack_paper_runtime_v1.py`.
Unified scheduler/CLI implemented, NOT activated. F=null; production config/seal/
activation still absent. This module's existence is not economic admission.

## Order and state

Every tick verifies complete activation and code closure; pump due exits/entries first,
then read actual clock again. In weekday E+3..E+10 window reserve scheduler work once,
select/import fixed as-of flow, durably record selection, run frozen slot orchestrator.
In18:20..18:20:30 reserve daily job once, collect marks for open contracts (shared across
arms), produce ledger-derived snapshot. Outside windows no retrospective work/backfill.
Pump still handles outstanding risk outside forecast windows, subject to parent rules.

Scheduler root transaction lock serializes ticks; separate attempt lock serializes
child runners. --serve holds an additional activation-root lifetime lock, so two
serving processes cannot operate the same activation. Separate private roots:
market/control/ledger/attempts/scheduler/reports under
`/srv/trading_lab_data/data/forward/algopack-paper-v1/<full-activation-SHA256>`.

STARTED reserves work before selection/source calls. Any existing or partial work
reservation blocks automatic replay; missing outcomes are not successful decisions.
Recorded source/slot failure or uncertain pump invalidates runtime and stops serving;
restart constructs a new anchored account by full replay, never arbitrary cash cache.
No background service is installed/enabled by writing this code.

## CLI and secret boundary

All modes require `--activation-sha256` and load exact activation/code/time gates first.

- `--check`: validate only, no token/network/directory creation.
- `--initialize`: explicit once-only genesis AFTER F. Existing/partial root refuses;
  ordinary restart never calls initialization.
- `--serve`: read server MOEX_ALGOPACK_TOKEN only after activation, create a requests
  session with trust_env=false, run ticks with1sec idle pause. Frozen child transports
  still pin CA/URL/bounds. No broker API; paper simulation only.

Stdout carries sanitized status, not key/header/payload/exception text. CLI failures
exit1 with RUNTIME_STOPPED_REQUIRES_REVIEW. Token storage stays only server env.
Do not run --serve/--initialize now: activation absent, F unassigned.

## Required before activation

Offline raw-source/forecast/Fill/economic replay and report/evaluation wiring;
official expected-day calendar evidence and fixed robustness/forecast evaluation;
production latency/readiness checks, complete config/bundle publication before F;
server service configuration, explicit genesis at F, then monitoring. Do not silently
relax freshness/windows or treat365days of infrastructure tests as investment evidence.
Serial HTTP/replay may miss execution/snapshot windows; current behavior masks/fails,
not guaranteed production availability. System-level restart policy not configured yet.

7synthetic tests: CLI activation refusal before token access, pump/selection/slot order
and restart deduplication, daily once, idle scheduling, pump uncertainty, failed flow
selection/no retry, initialization/no reset. Child calls stubbed, Linux journals actual.
The first local CLI test incorrectly intercepted LANGUAGE lookup from argparse; guard
was narrowed to API token lookup. Production code was not changed to bypass the gate.
