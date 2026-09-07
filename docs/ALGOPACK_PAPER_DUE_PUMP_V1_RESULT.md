# Due pump V1 — server result

2026-09-08. Pushed/deployed `01e964b`; gpu-mlserver, Python3.11.4, UID999.
**374/374 related synthetic tests PASS,27,48сек**, включая8due-pump tests.
Local2+encoding2PASS/6Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `93b296317da677707da931b0ba5b981cab2e4b064a8504aef07c193172333a61`
- tests `fd997181fbe811d8b0dd681693a74d0caf583479092d7beeec1d51f0a0b3c669`
- protocol `34d43a1d25254b99a73097909cee2e59d65d752971a3b2e5b8cda06d0e0fb50c`

Frozen training44/witnessed7 metadata checks PASS. Production activation absent;
F=null. Synthetic quote collection, actual Linux anchored ledger; no actual market
HTTP, model execution, real price/label reads or economic run in this work.

Verified exit priority, no early HTTP, two-arm same-contract shared quote, entry/exit
without duplicates, expired entry cancellation without HTTP, source failure across
exit deadline retaining exposure, uncertain fill followed by anchored recovery.
Tests do not prove production request latency, account entitlement or profitability.

Next: fixed as-of witnessed-flow selection, unified scheduler/CLI, offline economic
evidence review/evaluation wiring and complete pre-F publication. Target annual
income20–50% remains unverified; current technical PASS is not income evidence.
