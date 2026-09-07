# Preparation worker V1 verification

2026-09-08. Pushed c8d3851 before exact three-file archive deployment to gpu-mlserver
using tar --keep-old-files. No existing production source overwritten or runtime activated.

47/47 related Linux tests PASS15.22s UID999: worker9, scheduler-interference4, predictor,
flow selection, capture and startup-lock tests. Includes a real benign sleeping Python
child proving responsive supervisor polling/termination; test cleanup killed/reaped it.
No actual preparation CLI, market HTTP or production model executed. Remaining child/
source/model tests synthetic. Interference suite still reproduces OLD synchronous defect.
Unique `/tmp/algopack_preparation_c8d3851_tests` and `_cache`; process exited0.
Local credential guard PASS, encoding2/Ruff and git diff --check PASS.

Local/server SHA-256 match:

| File | SHA-256 |
| --- | --- |
| algopack_paper_preparation_worker_v1.py | 6a299a33394092e6bb13d3c5fd5d3f51f332af75e2fa285c6c3a8f745ca72c63 |
| test_algopack_paper_preparation_worker_v1.py | fd22dc35dda1413ad09e07eddd1e997bda6deb20af00f9e411933cdc78110f77 |
| ALGOPACK_PAPER_PREPARATION_WORKER_V1.md | ed0710faf74e952865ccf210ea884fe7a92d28774c782530084596de3a578e31 |

Training/witnessed closure verifiers succeeded under UID999, actual activation absent.
F=null. No full scheduler latency readiness or income claim. Next: integrate async
executor with actual-time publication consumption, address remaining blocking quote/
calendar/mark work and retest exit deadlines; enforce service child lifecycle cleanup.
