# Source-to-execution integration measurement

2026-09-08. Test code511d348 pushed before exact one-file deployment to gpu-mlserver.
New integration test connects real execution-source collect/raw replay, real bounded
worker Pool state machine and observation, async due executor, intent/fill bridge,
anchored ledger and restart recovery. Both fixed arms share one BR synthetic contract
quote for each due boundary. Running child does not admit a fill; completed observed
source produces exactly two entries/two exits. Subsequent ticks do not duplicate fills.
Six ledger events (two reserves, two entries, two exits); reopened state exactly matches.

Explicit substitutes: synthetic consumed signal, fake HTTP response bodies, fake Popen
child handles, authority/readiness gates except source identity checks. No prediction
model or production activation is loaded. Market/source/ledger clocks advance with real
perf_counter duration within each synthetic boundary; boundaries are advanced explicitly
to avoid waiting for market intervals. No production prices, network or credentials.

Server UID999 one measured run:1PASS2.21s, process exit0:

| Segment | Seconds |
| --- | ---: |
| Initial raw quote/calendar + two reservations | 0.516251844 |
| Due launch/poll, raw quote, observed two entries, idempotent next tick | 0.641903654 |
| Due launch/poll, raw quote, observed two exits, idempotent next tick | 0.612915142 |
| Full anchored reopen and state equality | 0.006690007 |

Separate related server suite65PASS7.40s: async due, execution worker/source/bridge,
runtime V2. Ruff PASS. These are integration measurements, NOT provider latency or an
end-to-end production SLA: no actual child startup, model/capture preparation, all-asset
contention, growing ledger, full readiness overhead or production sandbox in this test.
Do not sum separate benchmark samples and call the sum a guaranteed latency bound.

Synthetic roots `/tmp/algopack_execution_path_v1_tests` and
`/tmp/algopack_execution_path_related_tests`, separate caches. No existing runtime code,
economic thresholds or parent seal changed. F=null and service not started. Next:
actual benign-child service sandbox/cleanup check and full pre-F activation preparation.
