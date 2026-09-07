# Integrated asynchronous runtime V2 verification

2026-09-08. Pushed a4f49f3 before deployment. Verified prior V1 SHA79a1e87d…,
absent activation and no matching V1/V2 --serve process. Prior V1 retained at
`/tmp/algopack_paper_runtime_v1_cff39e5_retained.py`; exact four-file archive installed
with tar --keep-old-files. No actual --initialize/--serve or live worker/source run.

77/77 related Linux tests PASS12.09s UID999: V2(11), old interference, V1/startup/calendar,
async slot/due, preparation/execution workers and report store. Original late-preparation
cases (+9m/120s and +9m59s/40s) now service due at E+10 with controlled async actors,
without waiting for preparation. Old characterization still reproduces old failure.
Actual scheduler/anchor journals; timing injection is NOT actual provider latency or
full live execution. Worker suite's benign subprocess was killed/reaped by test cleanup.
Unique `/tmp/algopack_runtime_v2_a4f49f3_tests` and `_cache`; process exited0.
Local V2+startup4PASS/9Linux skips; encoding2/Ruff and diff checks PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_runtime_v1.py | 556ad5ce38eb3094cca4ef5883c298a8a73e363abfb53f1c63c9af5af79161f4 |
| algopack_paper_runtime_v2.py | 0c5490dc426ac4bd216be4317a0f9bfdf57d07be3846836cc58079aa2ea0fbab |
| test_algopack_paper_runtime_v2.py | 7169a047bf61b83afdc90cf8dd0dbd5d8a7eae39e01daffae0e53eae833831e9 |
| ALGOPACK_PAPER_RUNTIME_V2.md | 43f0053efaa18293534363376ab1d5afc928296c995ff3a8bbd52b3033d380a1 |

Training/witnessed closure verifiers succeeded under UID999; activation absent and
legacy retained. Future complete bundle must pin BOTH current V1 helper/guard and V2.
F=null, no income claim. Next: broader integration/local overhead verification, systemd
control-group cleanup and reporting cadence, full pre-F config/seal/publication. Do not
treat the controlled-clock test as a network SLA or sufficient independent income proof.
