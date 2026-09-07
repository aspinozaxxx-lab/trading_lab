# Execution-source worker pool verification

2026-09-08. Pushed034e7d4 before exact three-file archive deployment with
tar --keep-old-files on gpu-mlserver. No existing production source overwritten.

56/56 Linux tests PASS3.46s under trading-lab UID999: execution worker10, preparation
worker9, execution source27, execution bridge8 and quote-aging2. Source jobs use mocked
children/fake HTTP but actual raw replay/private journals. Preparation suite includes
its benign real sleeping child, killed/reaped by test cleanup. No actual market/model
worker, HTTP or fill. Unique `/tmp/algopack_execution_worker_034e7d4_tests` and `_cache`;
process exited0. Local1PASS/9Linux skips, encoding2/Ruff and git diff --check PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_execution_worker_v1.py | c587e98e823512164cfbb6a32ecaa1d9b90a8771c55cd3d767fbb68c82be4fb4 |
| test_algopack_paper_execution_worker_v1.py | dbc1763186849bbb941a2e9625a2aa1da5629d657c2ab84c112a6ab8be73bd1d |
| ALGOPACK_PAPER_EXECUTION_WORKER_V1.md | b825c8e5fc713b839824621b62d872d9b342da3d199dafc2d0c9a61a842dba87 |

Training/witnessed closure verifiers succeeded under UID999; actual activation absent.
F=null. No runtime integration or production latency readiness yet. Next: execution
owner state machine with exit-priority capacity, deadline/restart behavior and eventual
actual-time source consumption. Do not activate original synchronous scheduler.
