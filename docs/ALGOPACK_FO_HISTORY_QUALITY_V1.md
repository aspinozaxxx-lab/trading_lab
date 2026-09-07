# AlgoPack FO history quality V1 — metadata-only follow-up

## Scope and admission

Additional diagnostic of the completed [history V1](ALGOPACK_FO_HISTORY_V1.md),
not a new API download, feature calculation, label pass or backtest. The source
collector and its canonical output remain frozen. The full source replay must
finish successfully before this follow-up; hash checks in a report do not replace it.

Only normalized metadata columns `dataset`, `requested_asset_code`, `secid`,
`tradedate`, `tradetime` are projected for timestamp matching. The existing per-job
manifests supply date coverage and field null/zero/negative counts. No OHLC, returns,
targets, PnL or numeric flow/depth values are used by the metadata projection.
All observations remain strictly before 2026-01-01. Current-vintage flags remain:
historical_model_eligible=false, original_version_verified=false and live=false.

The new module and synthetic tests are separate files, not edits to frozen history
code. Before reading the completed source, pin the actual parent global manifest,
source seal, new code/test hashes and exact diagnostic settings in a new config/seal.
Execution and generated reports stay outside Git on gpu-mlserver.

## Fixed reporting questions

1. Did all 294 source jobs / 147 contract pairs finish? Bind the global manifest,
   each job manifest and each normalized file by exact hashes and bytes. Check
   parent totals and preserve empty/non-admitted jobs and their date differences.
2. What is coverage for each dataset, asset and year? Use exact `(asset,SECID,date)`
   keys, not inferred trading sessions. Show expected, observed-expected, missing
   and extra keys, rows, first/last dates and contracts touching each year. Cross-year
   job/contract counts are not additive. Do not allocate pages arbitrarily to years.
3. How many numeric fields were null, zero or negative? Aggregate the already stored
   counts by dataset/asset with row denominators. Annual field counts cannot be
   recovered from cross-year job summaries; do not manufacture annual estimates.
4. What is the exact intraday TS/OB overlap? Project the five metadata columns and
   compare `(asset,SECID,date,time)` keys per pair. Report shared, TS-only and OB-only
   keys, duplicates and off-five-minute-grid observations by asset/year and total.
   Unequal sets are diagnostic findings, not permission to replace missing flow by 0.

## Limits

The source auditor returns a verdict and totals, not a numbered list of 294 checks.
Report "294 jobs completed and replay-audited", not "294 checks passed".
source_date_coverage_admitted only checks nonempty data, exact expected date sets,
and present/matching asset aliases. It does not require all numeric fields populated,
complete five-minute intervals, matched TS/OB timestamps or a verified exchange
calendar. A full cursor does not prove an atomic vendor snapshot or first publication.

This diagnostic neither assigns historical available_at nor removes extra/missing
dates from the immutable source. Calendar notices may explain context but cannot
silently remap vendor tradedate or repair the old active map.

## Status

Implementation/review complete before this report run. Local targeted187 passed /
3 Windows symlink skips; Ruff clean. Parent collector has completed all294jobs,
2067949rows and2198pages, with internal raw replay and date admission=false.
Actual parent manifest `f50fa60a6986070d45f6a69555076df1f5748d09b70407131591740e77425fb4`.

Config SHA `8a6a356e4aac9c2b4643b7c7a1110a6047b6257d8d01b2918aeb560450d7c59e`;
28-file closure `b57b9b226d63842dd0a3c09bafcd98746bcd48f383324f53e0b1bb4558f260ba`.
Module SHA `55519cb8c6c11dda0d34e192a0707d02913a05d7d92ad8d29617fe364e101d6e`;
runner SHA `0c93b4fa8f3934a54cec2f16d883ca94e9aac3b9384631ea8e6887b72781603b`.
Both modules and tests reviewed before seal. Linux skipped cases must pass before
source/report execution. Runner does full history.audit first, then metadata projection,
verifies identities again and atomically publishes three external report files.
Canonical report stem: `data/processed/algopack_quality/algopack_fo_history_quality_v1_b57b9b226d63`.
No quality result is claimed yet; actual runtime/result is in [STATUS.md](STATUS.md).
