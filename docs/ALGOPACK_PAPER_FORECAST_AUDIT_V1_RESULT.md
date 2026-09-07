# Numerical forecast audit V1 — server result

2026-09-08. Pushed/deployed `7c0da8f`; gpu-mlserver, Python3.11.4, UID999.
**407/407 related synthetic tests PASS,38,10сек**, включая7forecast-audit tests.
Local1+encoding2PASS/6Linux skips; Ruff/diff checks PASS.

Local/server SHA256 match:

- core `d02ca3b6dee0183e6c4176cc2de9c231a9ef3823b21d8798e89c8038cdc81cbc`
- tests `b203bc5b667f2326a49e947cead5679fd5c4ccabefc67eb78e421b0c11743a5f`
- protocol `a04df42d7a49289e8401743b0f1cd4ce0e6d3be6a86f8acb1fe772b4c1d5c545`

Frozen training44/witnessed7 metadata checks PASS. Production activation absent,
F=null. No actual protected price/label/model reads, source HTTP or economic run.
Synthetic HTTP/raw archives and fake fixed model bytes, actual source parsers/projections,
numeric inference and Linux durable journal were used in these integration tests.

Verified later-day exact reconstruction for price-only/paired flow forecasts, hash-valid
but altered numerical prediction/contract rejection, preserved late-completion masks,
and corrupt raw flow rejection with an otherwise intact forecast journal.
FORECAST_RECOMPUTED verifies recorded forecast derivation, not forecast accuracy,
execution admission or profitable strategy. Target income remains unverified.

Next: combine forecast and execution audits with daily evaluation/report provenance,
official calendar and latency checks, complete pre-F config/seal and service setup.
