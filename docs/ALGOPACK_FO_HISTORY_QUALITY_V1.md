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
The completed result and limitations are recorded below; current queue is in STATUS.

## Canonical result — COMPLETE / RAW REPLAY PASS

Pre-run commit `597da59`; server188/188 tests, no skips. One network-isolated
service run completed success/exit0 in51.280s; no token or network calls.
Canonical directory:
`/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_history_quality_v1_b57b9b226d63`.

- Manifest SHA `26342273cc79f4d168486651ba6a2369bece2a12465c7dac2e7ba3eef3fe558a`.
- audit.json SHA `7c4de421746d0a3feca83ba891c1f69e93f076a391832a02c06d34ac4b9e4c18` (363bytes).
- quality.json SHA `51b296bccb9c369baf54481fe6e726cfc5431a2ebd012fa24981df4b7c055a6a` (134329bytes).

The runner separately replay-audited all294 source jobs, then completed metadata
projection. Root verified published report identities against the report manifest.
An independent report-only review also verified hashes, unchanged28-file seal,
asset/year sums and join arithmetic; it did not repeat raw replay or inspect values.
This is a technical source/report PASS, with source_date_coverage_admitted=false.

| Dataset | Rows | Pages | Expected contract-dates | Observed expected | Missing | Extra | Non-admitted jobs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TradeStats | 1 007 214 | 1 075 | 6 076 | 6 040 | 36 | 86 | 18 |
| OBStats | 1 060 735 | 1 123 | 6 076 | 6 068 | 8 | 116 | 19 |

Empty jobs0, missing asset_code0, alias mismatches0. All observed timestamp keys lie
on a five-minute grid; duplicate keys0. Grid alignment does not prove complete bars.
Shared keys1 000331, TS-only6883, OB-only60404. Counts are observations, not independent
experiments or trading decisions. Missing counterparts remain missing, not zero flow.

| Год | TradeStats | OBStats | Совпадают | Только TS | Только OB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020 | 159 932 | 171 204 | 157 371 | 2 561 | 13 833 |
| 2021 | 173 949 | 176 756 | 173 257 | 692 | 3 499 |
| 2022 | 143 109 | 173 329 | 143 109 | 0 | 30 220 |
| 2023 | 175 967 | 173 820 | 172 995 | 2 972 | 825 |
| 2024 | 171 302 | 177 724 | 170 850 | 452 | 6 874 |
| 2025 | 182 955 | 187 902 | 182 749 | 206 | 5 153 |

All selected TradeStats numeric fields are non-null in this source. OBStats depth/
level fields are non-null, but real zero depth exists. Spread masks and signed values
must remain explicit; negative spread is not proof of an executable arbitrage.
These are existing source-audited field counts, not numeric recomputation by this
metadata projection. Annual null counts are not inferred from cross-year summaries.

| Актив | OB rows | Null L1 | Null L10 | Negative L1 | Negative L10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BR | 265 674 | 593 | 684 | 32 | 9 |
| MIX | 263 978 | 1 691 | 2 565 | 35 | 0 |
| RI | 265 451 | 6 928 | 7 699 | 24 | 0 |
| SI | 265 632 | 1 931 | 2 087 | 33 | 0 |

Total null L1/L10=11143/13035; negative L1/L10=124/9. Do not clamp or fill them.

Notable calendar/key limitations: OBStats has extra2020-09-12 and lacks2020-10-06 for
all four assets. It also contains2025 weekend SI keys without corresponding SI
TradeStats. Thus OB row presence cannot establish an actual tradable session. The
calendar discussion in the parent protocol is context, not a map correction.
2022 has30220 OB-only keys; 2023 has2972 TS-only keys despite complete date coverage.
Full per-asset/year tables and exact anomaly jobs are retained in quality.json.

Historical available_at remains unknown, first-publication/revision proof absent,
and all model/live flags remainfalse. No labels, returns, portfolio metrics or profit
claim were computed. The proposed hypothetical historical screen awaits an explicit
user choice on its availability assumptions; no default answer is treated as consent.
A separately sealed contemporaneous FO collector remains the next unblocked source
step, to preserve per-response receipt/validation times and immutable revisions.
