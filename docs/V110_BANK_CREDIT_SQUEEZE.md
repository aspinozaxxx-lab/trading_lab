# V110 — bank-credit squeeze, one conditional Stage1 screen

Pre-outcome protocol, 2026-09-17. Goal20–50% remains unverified; no live/demo orders.
One new economic mechanism: simultaneous tightening of business credit standards
and weaker loan demand may precede lower investment/activity and oil demand.
This is a public survey aggregate, not a purified supply shock or a forecast of
world oil consumption. No model, threshold grid, asset selection or lag search.

## Rule and control

Latest available complete quarter: **BR short0.9 if net tightening>0 AND net stronger
demand<0, otherwise cash**. Control: constant BR short0.9 on identical readiness
and calendar. Exact decimal signs, genuine zero means neutral but ready. Full
2018-01-01…2025-12-31 development window, initial RUB1m. One run, base and double
costs, same V72/V78/V64 integer ledger. No new execution engine.

Next factual open after EOD decision, leverage cap1.0, margin buffer2.0,
participation<=1%, collateral interest0. Base1tick+1xfees; double2ticks+2xfees.
Research proxies are not exact historical broker terms. Missing plan/price/source
stays masked or unresolved, never removed from the denominator. Terminal flat.

## Source and conditional information clock

[Source review](SLOOS_SOURCE_REVIEW_20260917.md) preserves all startup, route and
FRED timeout failures. Original PDF/HTML reconstruction is paused; no V3. FRED
numeric responses were not obtained. Successful source is one direct
[Board XML export](https://www.federalreserve.gov/releases/sloos/data/FRB_SLOOS_xml.zip)
linked by the already captured official index. Board attribution and notices retained.

Only SLOOS dataset `SUBLPDCILS_N.Q` (standards) and `SUBLPDCILD_N.Q` (demand):
all domestic banks, large/middle-market borrowers, percent, quarterly. Exact
identity/attribute tests reject large-bank subgroup or terms substitutions. FREQ162
is Quarterly in supplied structure XML. Descriptions match the publicly documented
FRED DRTSCILM/DRSDCILM definitions; no numerical cross-vendor equivalence assumed.

33 quarter-end labels2017-12-31…2025-12-31 in each series; all66 selected observation
statuses A and lexical numbers. During preflight no magnitudes, directions, targets
or new PnL inspected. Other series and out-of-window values, especially2026, are
excluded before status/value inspection. XML parsing of raw bytes is not feature
admission. Malformed selected calendar/schema/status fails closed; a dot masks the
latest complete-quarter state without older-good fallback.

Normalize the XML quarter-end period label to its quarter start. **Conditional
availability = end of second month of that labeled quarter, America/New_York**:
Jan→FebEOM, Apr→MayEOM, Jul→AugEOM, Oct→NovEOM. The record retains both period labels
and an explicitly named proxy release date. TTL120calendar days measured from that
proxy, decision-to-fill<=7days. This is a conservative screening assumption, not
original timestamp/revision evidence. One actual2017 cover was checked visually:
October survey published November6. It does not validate all releases or vintages.
Current archive revisions and possible reporting changes remain limitations.

Source root `source_evidence/sloos_board_20260917_v1/capture`, completed
04:11:43.600421UTC, invocation `028fcd1b70114233b611238480fa25af`:

- Manifest `92b003b1c7f8d88bb7bcfdf2e4536e1d60088cb427a41b9f7d24866291158903`.
- Raw ZIP `9e043b31aea376d3198fb04a94a7f8cd46e6983e1b45aea65c0bd5801f1fd0be`.
- All4 artifact hashes+manifest verified after local backup; raw stays outside Git.

## Frozen funnel gates

Source readiness>=80%; primary under **both** costs CAGR>=5%, Sharpe>=0.5,
MDD<=25%, >=20roundtrips, >=5positive years out of8, worst year>=−15%,
CAGR excess over same-calendar control>=2percentage points. All4 cases must be
execution-complete, critical0, unresolved0, terminal flat. Rolls must be disclosed
separately from signal episodes; twenty rolls do not mean twenty independent bets.
The5% component gate does not replace the user's20–50% goal. PASS can only admit
further testing, not demonstrate original-PIT feasibility or predictable income.

Existing futures history has already been seen in prior experiments: **not an
independent holdout**. Selected2017/2025 source snippets were also seen in discovery.
Do not invert/retune failed signs, asset, size, lag, TTL, control or costs after the
result. Do not promote the control after seeing it outperform. 2026market outcomes
remain protected. Main AlgoPack download proceeds independently; no expanded
AlgoPack economic scope, broker setup, purchases or Windows collectors.

Preflight:125combined synthetic tests PASS, Ruff clean; unchanged futures manifests
verified before market values. Seal code/config/tests/source-capture/source-review/
protocol and transitive V101 parent before economic run. Persist source states,
both targets, four ledgers/orders/positions, annual metrics, audit and manifest.
