# V86 economic seal — forecast-revision BR screen

Frozen before selected numeric forecasts, market returns or PnL. New source information,
not V17 raw weekly balances or V74 rig counts. [Earlier design](V86_STEO_FORECAST_REVISIONS.md).

All2018–2025;97monthly vintages including December2017 predecessor, no fitted parameters.
Same **next calendar quarter** in both adjacent vintages. Difference of mean world
consumption-minus-production -> signed BR weight0.9; zero change -> flat. Constant-long
control uses identical eligibility/missing masks, never promoted by selecting its results.
Source series papr_world/patc_world, units million barrels/day, cached Decimal values,
all repeated papr_world rows must agree exactly. No other source economic cells parsed.
Post2025 physical forecast horizons in pre2026 editions are not protected actual outcomes;
all source releases and trading dates remainpre2026; no price forecast column is read.

Availability = end NewYork day max(release index date, attached notice Released date,
workbook modification UTC date), then max(current,previous vintage). A late old edition
cannot supersede a newer already available one. Missing/ambiguous clocks or values ->
explicit unavailable, not guessed timestamps or zero economic observations. Later corrections
are never backdated. These are conservative **conditional** assumptions, not originalPITproof.

Daily decision EOD Moscow -> next factual open, same existing causal roll/ledger, integer
contracts, grosscap1, target0.9, reserve margin multiplier2, participation1%,1million RUB.
Base1tick+1xcommission proxy and double2ticks+2xfees. No credited collateral interest.
Stale at fill after62calendar days or decision-to-fill>7days -> masked, unresolved
execution stays reported, final flat. No source update may use future labels for eligibility.

Two arms × two costs, all8years reported. Cheap component gates: source coverage>=90%,
ready editions>=80; both costs CAGR>=5%,Sharpe>=0.5,MDD<=25%,>=30closed episodes,
>=5positive years,worst year>=-15%,excess over control>=2pp, all executions complete/flat.
20/50% flags separate;goal/livefalse. Stage1 survivor needs independent robustness and
execution evidence. This repeatedly examined development history is not a holdout.

Source V4 completed2026-09-15T13:37:47.836166UTC,97workbooks/89737568rawbytes,18notices.
Manifest0ec267b1fb866d3bee1148d3a5792813ffe31222b262e49846eae317922a8306.
Source seal28a5dfb5f3fb75f55a73fc660148b58d309ae676d62a8c8dc2b23178c2666417.
80raw files reference-reused;three202405–07 lack original persisted transport metadata,
so original receipt timestamp staysnull, recovery observation is explicitly separate.
No forecast values were evaluated by acquisition. BothV3/V4roots must remain together.

Operational history: V1 stopped before HTTP because parent directory not writable by
service; no broad permissions changed. V2 prepared own new leaf, saved index, then
stopped because source HTML omits three row-open tags. V3 repaired syntax in RAM only,
saved77committed+3raw files, stopped on duplicate world production codes fromMay2024.
V4 preserves both duplicate identities and reuses80files,17new workbook requests.
All earlier code/seals/failed roots retained; no successful canonical rerun.

Independent check after run: raw SHA/metadata, selected physical forecasts and duplicate
equality, exact quarter revision/clock/target replay, counts/year/fee/cash reconciliation.
Rejecting this rule forbids sign, horizon, threshold, capital or year selection on its results.
