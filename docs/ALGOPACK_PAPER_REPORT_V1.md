# Combined paper report V1

2026-09-08. `src/market_lab/futures/algopack_paper_report_v1.py`.
Full activation and own SHA required; F=null. No actual report/economic run yet.

Build accepts an anchored account, market/report roots, expected day tuple and calendar
digest; validates period before economic reads. Full execution-binding audit must pass.
For each expected day discover canonical immutable daily snapshot; absent stays missing,
corrupt/partial/late record fails report instead of yielding a shortened profitable curve.

Replay ledger once more and numerically audit each unique reserved forecast. For every
snapshot bind ledger SHA to its exact MARK prefix; compare source-bound valuation,
actual daily entries/realized closes and remaining open/pending/unresolved counts.
Reject a snapshot omitting an event already durable at valuation. Recheck coverage grid,
scope, original observation chronology, per-arm categories and counts; each referenced
forecast must pass numerical source/model replay. Absent/failed publications retain
their explicit conservative masks. No caller-supplied equity or trade counts.

Only after these checks call frozen evaluator with complete expected calendar. Missing
days/unresolved risk and both cost scenarios retain parent behavior; no annualization
before252sessions+365days, no promotion. Actual audit/report clock remains current.
Historical missing-publication claims are witnessed by the saved report; not independently
provable universal absence. Positive coverage is checked against saved forecast evidence.

## Remaining admission boundary

calendar_source_verified=false: caller-provided expected days/digest are not yet verified
against official calendar provenance. This module combines economic evidence but does
not itself certify official schedule, actual fills, broker fees or independent income.
Need official expected-calendar binding, final service/latency/config/seal/publication
before F and prospective data. Full report persistence/CLI handoff still needed.
No target income claim, execution_admitted=false, target_income_verified=false.

9synthetic tests: activation, missing day/no equity fabrication, flat/no annualization,
ledger-derived roundtrip counts, positive forecast coverage and altered coverage status,
hash-valid altered equity/trade count/ledger reference rejection. Linux ledger/report
journals actual; child numerical audits stubbed here and separately tested in their suites.
