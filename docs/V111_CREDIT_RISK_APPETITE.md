# V111: EBP risk appetite, conditional Stage1 protocol

Pre-outcome,17September2026. One new information component, one stand-alone rule.
The relatively predictable20–50% goal remains unchanged and unverified.

## Economic hypothesis and frozen rule

Nonpositive excess corporate-bond premium may indicate accommodating risk appetite
and credit intermediation, supporting equities. **MIX long0.9 when latest complete
available EBP<=0, otherwise cash.** Exact Decimal sign; genuine zero means long.
Constant MIXlong0.9 control on identical readiness/calendar. Full2018–2025,
initialRUB1m, no leverage increase, idle cash interest0, no fitted thresholds/model.
This direction is not established trading knowledge: high risk premiums may predict
higher longer-horizon returns, and US-to-MOEX transmission can fail.

V25/V27 already used STLFSI stress with multileg trend/risk/cash-carry policies.
This is not a replacement indicator inside that optimized portfolio. EBP is a
default-risk-adjusted corporate-bond component; dependence on STLFSI remains
possible. No independence or alpha inferred from different source identifiers.
V110's bank-survey BRshort rule stays closed without inversion or retuning.

## Published data, provenance, and limitations

[Favara, Gilchrist, Lewis, Zakrajsek2016](https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html)
explicitly links the [research CSV](https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv).
The source is a staff research product, not a guaranteed statistical release.
Normally updated after10am on the fourth business day, subject to delays/blackouts.
Whole history may revise monthly because balance sheets and the bond sample change;
a2018 posted-file correction is documented. A delay does **not** cure historical
estimation/revision leakage. These are preliminary current-vintage calculations,
not proof of original-PIT trading or an independent track record.

Only column `ebp` selected. `gz_spread` and `est_prob` remain uninterpreted.
The latter is not a trading target or historical label. Raw CSV contains643monthly
rows1973-01…2026-07; only98date labels2017-11…2025-12 enter calendar validation,
and96eligible EBP cells enter the eventual screen. Earlier/future/unrelated cells
excluded before numeric interpretation. Source starts after the public monthly
publication announcement, but that does not establish original vintages.

Personal research on explicitly published Board research output, preserve attribution
and notices. No underlying proprietary bond-level dataset access or redistribution
rights inferred. [Board disclaimer](https://www.federalreserve.gov/disclaimer.htm)
captured previously and hash-verified by this collector.

Canonical root `source_evidence/ebp_20260917_v1/capture`:

- Two successful HTTP200 requests, no retries/redirects. CSV39697bytes received
  04:36:37.858716UTC. Source invocation `fd9220b77f964f8aafdb25e18a9526d4`.
- The initial metadata parser then failed because it expected ISO dates; actual
  dates are unambiguous US `M/D/YYYY` with day1. **Original failed capture manifest
  retained**, completed04:36:38.643636UTC. No second download or canonical overwrite.
- Manifest `87af2e4930b09a58bfe3e9bcf15d6f8c3e66b5e8f47cf28341739e583da991e1`;
  raw `cc51b2747654e3ed003e0a6ce5500de054c1a8dcd3ec00bace1c6742416ab2eb`.
- Isolated economic adapter admits only this exact saved raw/manifest and exact
  parser-failure reason, with HTTP200/returncode0/bytes verified. Its corrected
  metadata-only preflight has98monthly/96eligible/96complete cells. No magnitude,
  direction, target or new PnL read before sealing. Generic FAILED source admission
  was not relaxed; other failures or changed hashes fail closed.
- Source6files backed up locally, manifest+5artifact SHAs checked; outside Git.

## Conditional clock and execution

Availability = **end of following calendar month, America/New_York**. Retain
original token, observation-month label, actual observation month end, and proxy
release date separately. Latest eligible month2025October becomes available
2025December1 at04:59:59UTC. November/December2025 are excluded **before token
inspection** because their computed availability crosses the protected2026 boundary.
First eligible November2017 becomes available2018January1 at04:59:59UTC.

TTL93calendar days from observation month end; next decision-to-fill<=7days.
Missing newest EBP masks both arms, with no older-good fallback/interpolation/zero
fill. A real zero remains valid. Missing/duplicate monthly report, malformed value,
nonfinite number or schema/date drift fails closed. No source values after2025.

Existing V72/V78/V64 EOD-next-factual-open integer ledger, gross admission cap1,
margin buffer2, participation<=1%. Base1tick+1xfees; double2ticks+2xfees. Keep all
cash/missing/halt days and unresolved exits. These are research specs/fees/margin,
not exact broker terms or continuous intraday gross-risk guarantees.

## Gates and verification

Source ready>=80%. Primary under both costs: CAGR>=5%, Sharpe>=0.5, MDD<=25%,
>=20roundtrips, >=5positive years/8, worst year>=−15%, CAGR excess over control>=2pp.
Allfour cases execution-complete/critical0/unresolved0/terminalflat. Disclose rolls
separately from signal episodes. The5% component filter does not redefine20–50%.
PASS would only admit further examination; it cannot validate revised history.

134combined synthetic tests PASS, Ruffclean,15futures metadata checks PASS before
market values. Code/config/tests/protocol/capture and transitive V101 seal are fixed
before one economic run. Persist **96 planned source states**, two targets and
four ledgers/orders/positions, annual metrics and manifests. Actual counts govern.
Previously seen futures history is development, not holdout. Never tune sign,
asset, lag, TTL, size, control or costs after outcomes. No broker/demo/live, purchase,
new Windows tasks, credential reads or expanded AlgoPackeconomic scope.
