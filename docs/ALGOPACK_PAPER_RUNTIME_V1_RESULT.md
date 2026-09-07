# Unified runtime V1 — server result

2026-09-08. Pushed/deployed `a1b4cd7`; gpu-mlserver, Python3.11.4, UID999.
**390/390 related synthetic tests PASS,29,65сек**, включая7runtime tests.
Local1+encoding2PASS/6Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `102229e37766cb5b4d99f66baf58cb5d21e7b99adaa0812342ab5c23f95f01ac`
- tests `effdc7e0bbae7741efede5cde519551ca0a01853f2e35af99ae9200ab4fab288`
- protocol `54d8ebd8722f418194d820b865ab2f4dad55fd3ad5fb631d0ff23b8658766888`

Metadata-only frozen training44/witnessed7 checks PASS. Production activation absent,
F=null. Actual deployed CLI --check with dummy SHA refused with exit1 and sanitized
RUNTIME_STOPPED_REQUIRES_REVIEW. No token read or HTTP needed for this negative check.
Neither --serve nor --initialize was run against production state; no service enabled.

Verified pump-first order, persisted missing-flow selection, one slot across restart,
daily once, idle tick, pump uncertainty/invalidation, failed selection/no rerun and
existing-root initialization refusal. Tests stub child actions, use real Linux journals;
this is not a full actual source→prediction→trade→annual-return experiment.

Next: offline raw/forecast/Fill/economic evidence replay, evaluation/report wiring,
official expected-calendar and latency checks, full config/seal/publication before F,
server service setup and explicit genesis. Target20–50% income remains unverified.
