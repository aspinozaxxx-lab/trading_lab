# V80 source V2 — undated raw records are not calendar observations

2026-09-15. Narrow metadata correction to [source V1](V80_GPR_VINTAGES_SOURCE.md).
V1 code/config/root retained. Pre-source6fab970, seal
b6d521960cd39f2125802c034744d96227a8468895b4ccd7dce139995028f253;
local8/server8tests, one pilot service started09:24:51UTC then failed before any job
publication with invalid_or_protected_source_months. No GPR economic values/prices/PnL.

Read-only date diagnostic of exact202203 first-commit content found1545rows:
1467dated,78undated, valid1900-01-01…2022-03-01, unique increasing;0months after
the vintage and0months>=2026. Not a protected-date escape: V1 rejected the missing
month cells. Do NOT infer dates for those records or claim their other cells are empty.
Raw SHA fe0d0299ff70892c9e721c934690d3829ed023899389a13703f73b308882b782,
707630bytes; first commit b9ff2357dc7ca3583717c8387daeab88bc708990,
author/committer max2022-03-01T16:50:19UTC,2history entries. First commit differs from
current tree's version; earliest content must be used, not today's overwritten edition.
Both observed labels exist: GPRC_RUS (recent country index, percent of articles) and
GPRHC_RUS (historical country index). No scalar risk values inspected for this diagnosis.

V2 preserves the whole raw DTA, counts undated rows and excludes them only from dated
calendar/features. All NONMISSING months must still be unique increasing, <=edition
month and<2026. Empty dated calendar fails. Prior13 COMPLETE months must exist; current
partial edition month does not enter a future signal. No changes to indicators,
weights, horizon, returns or costs; economic protocol still separate and not run.

Same46versions202203…202512, first3pilot, then optional --full. Same immutable oldest
Git commit selection/clock caveat, anonymous allowlisted HTTPS, bounded requests,
raw/hash receipts, server-only storage, no overwrite/resume existing successful jobs.
V2 code/config/tests/doc plus complete V1 dependency closure sealed before new HTTP.
New root /srv/trading_lab_data/source_evidence/v80_gpr_vintages_2022_2025_v2.
V1 has no committed raw jobs to reuse; do not restart it or delete its failure record.
Stata remains a native statistical source, no spreadsheet artifact or new package.
All other scope/rights/protection rules of V1 apply. Source completeness is not economic
admission or original-public-push proof; no strategy outcome/20–50% achievement yet.
