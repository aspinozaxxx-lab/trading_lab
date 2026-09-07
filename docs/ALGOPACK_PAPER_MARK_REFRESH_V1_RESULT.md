# Mark refresh V1 — server result

2026-09-07. Pushed/deployed `c9093ab`, gpu-mlserver, Python3.11.4, runtime UID999.
**344/344 related synthetic tests PASS,22,95сек**, включая8mark-refresh tests.
Local1+encoding2PASS/7Linux skips; Ruff PASS, diff check PASS.

Local/server SHA256 match:

- core `997cacd2e74c6d7d834b07d5c4edc99c8c642c6c650366412622937d12d06e3a`
- tests `b2ca3a9ce65d20b2a6acf729427e80ff2a43ead61e8bd8ae5ff585be234069a2`
- protocol `0f45a3200de69c4b93b43619da98eafda8551be36ec95ba5e3ae0f2ed1801943`

Frozen training44/witnessed7 metadata closure checks PASS. Production activation
отсутствует; F=null, actual source HTTP/forecasts/trades/economic results0.
Source observations synthetic/stubbed, persistence actual Linux journal.

Проверены cost-adjusted liquidation MTM, restart parity, removal of prior marks on
missing/unavailable/corrupt source, actual publication-delay expiry, independent
unaffected arm, pending capital reservation и сохранение unresolved missed exit.
Эти проверки не являются подтверждением прибыли и не дополняют daily evaluation
отсутствующим decision/calendar denominator. Следом durable decision coverage,
ledger-derived snapshots, offline evidence replay и scheduler/full pre-F seal.
