# Startup lock correction — server result

2026-09-08. Pushed/deployed `09777ff`; gpu-mlserver, Python3.11.4, UID999.
**409/409 related synthetic tests PASS,38,35сек**, including2new startup regressions.
Before fix2/2new regressions failed on actual old source ordering. After fix local
2regression+1runtime+2encoding PASS/6Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- corrected runtime `67a34065e114f6e25faf833c55c882aad6b5a0a780b0f81dad31ad7f5417b25b`
- regression tests `50af083bbb5343a872e06d595273ada34ed1ac0b8917a066da682c26f745237c`
- fix note `a1940af2a4cd455738bd55d3c9b636feddc1fc0c2674e1fcb84028d0ed71ee01`

Before replacement, old deployed runtime matched102229e3...; activation absent and
no runtime --serve process found. Old file retained at
`/tmp/algopack_paper_runtime_v1_a1b4cd7_retained.py`, existence reverified afterward.
No data/models/canonical runs removed or changed. Frozen training44/witnessed7 metadata
checks PASS; F=null, no production activation or economic run.

Future full bundle must pin corrected runtime bytes, not the original runtime result
SHA. This fixes startup freshness ordering, not trading economics or source evidence.
Next combined economic audit/evaluation report, calendar/latency and full activation.
