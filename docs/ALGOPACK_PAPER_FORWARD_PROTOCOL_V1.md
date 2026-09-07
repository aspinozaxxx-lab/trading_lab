# AlgoPack prospective paired paper protocol V1

2026-09-08. User authorization2026-09-07; this is the single previously authorized
archive-training/future-only paired experiment, not another model search. Hypothesis:
joint witnessed flow/depth adds useful future execution-adjusted information to the
same-assets price-only model. Both already-trained Ridge models are retained unchanged.
Training2020–2025 has completed once; no historical AlgoPack PnL or retraining permitted.

Production config `configs/algopack_paper_forward_v1.json` selects runtime V2 and the
existing execution/evaluation implementations. Its implementation_snapshot documents
code constants and is checked by tests; it is NOT a live parameter override mechanism.
Complete byte seal must pin config+sidecar and executable closure together. No config
file alone grants data access. Actual F belongs only in a separate activation document,
must be genuinely future Moscow midnight after publication and every deployment time.
Until that document and complete seal exist, F=null and old2026 protection remains.

## Fixed execution and comparison

Two independent virtual1m RUB accounts, price_only and price_flow; BR/MIX/RI/SI joint
features and fixed42ten-minute information boundaries10:10–17:00Moscow weekdays.
Preparation E+3..E+10, planned entry E+10, exit E+70. Model selects signed exposure only
when existing edge/cost and risk rules admit it; no extra arms or post-outcome tuning.
Same-asset overlap sleeps under portfolio rules;42slots do not mean42trades.

Actual original observation clocks and raw-source replay govern eligibility. Only
dated post-boundary quotes within30s fill window,5s freshness, observed session/specs,
depth and risk limits. Both cost scenarios1x/2x retained. Broker3RUB/contract/side is
explicitly unverified, not the user's known tariff. Missing entry cancels reservation;
missing exit remains unresolved risk, never an invented closing price.

Independent arm coverage must be reported; do not choose one arm by paper results and
describe its selected performance as independent. Economic report includes all eligible
calendar days, source/missing/sleep/failed counts, entries/closed/open/pending/unresolved,
daily equity/drawdown and yearly results when admitted. Whole-period missing/unknown
gates remain. Annualized CAGR/Sharpe require252sessions AND365elapsed days; early reports
may show actual cumulative results without extrapolation. Paper success alone cannot
prove the user's20–50% annual-income objective or authorize real trades.

## Operations and remaining admission

Use the prepared server-only service and offline report handoff documented in
ALGOPACK_PAPER_SERVICE.md. All market/model/calculation work on gpu-mlserver; real data
and model files remain outside Git. Static/unit/integration/sandbox evidence is recorded
in STATUS; it is not entitlement/schema or actual runtime evidence.

Before F: assemble all transitive source/training/runtime/execution/report/calendar and
service code identities, verify parent seals and config constants, publish immutable
bundle and activation before the selected boundary. Do not read protected prices to
test subscription access. After F: initialize once, start exact instance, verify actual
source/schema/timing failures without silently changing sealed protocol. Any required
implementation correction must preserve failed evidence and receive a new prospective
version/boundary, never rewrite the old cohort. No broker orders or new purchases.
