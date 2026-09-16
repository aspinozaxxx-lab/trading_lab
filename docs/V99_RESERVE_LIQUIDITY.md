# V99 — published US bank-reserve liquidity, pre-outcome protocol

One new information mechanism: quarterly growth of dollar bank reserves may support
subsequent risk demand and transmit to Russian equities. This is a hypothesis, not
causal evidence. Search of existing code/config/docs found no prior WALCL/WTREGEN/
RRPONTSYD/reserve-balances screen. V71 tested Russian budget-liquidity forecast errors,
V72 CBR qualitative guidance; early FRED features were STLFSI4/VIX, not this quantity.
Do not retune those parents or the rejected V98 scheduled-event rule.

## Fixed economics

MIX long/cash, target0.9gross, 2018–2025. Use the first officially listed H.4.1
release of every calendar month. Compare its Wednesday reserve-balances level with
the first release exactly3calendar months earlier. Positive change => long; zero
or negative => cash. No model fit, sign/window/asset/size grid. A monthly review and
quarterly change are declared for a slow liquidity-regime hypothesis, not selected
from source-to-return correlations. September–December2017 are warmup only.

Control: constant0.9MIX long on the identical valid-source calendar. Missing source
or baseline masks BOTH arms; control is not an unconditional full-period benchmark.
Do not promote the control after seeing the result. Decision18:45Moscow, latest
available released state; fill next actual daily open. Maximum source age40calendar
days, decision-to-fill gap3days. At fill cancel stale entry; never filter an entry
on a future exit price/tradability. Unknown exits/halts remain in the existing ledger.

## Source and availability

[Official H.4.1 index](https://www.federalreserve.gov/releases/h41/) points through
its JavaScript to [releaseDates.json](https://www.federalreserve.gov/releases/h41/releaseDates.json).
The pinned date-only index selects100months2017-09..2025-12. No current DDP/FRED
value bundle, no2026dated value requests. Current index includes2026calendar metadata,
ignored before selecting source URLs. All raw data stay outside Git on gpu-mlserver.

Read table1 **Reserve balances with Federal Reserve Banks**, last column:
Wednesday point level, millions of USD. Do not substitute weekly averages or the
nonidentical assets−TGA−RRP formula. Each baseline comes from its own dated release,
never overwritten with revisions in a later release. Format-only samples2018/2020/
2025were inspected before design, with no associated new market outcome calculation.

[Official announcements](https://www.federalreserve.gov/feeds/h41.html) document a
January2,2025release delay without an actual recovery clock on the inspected feed.
That selected monthly release is unusable both as current state and later baseline;
no substitute second release, no forward-fill of the previous valid regime. Other
inspected delayed dates2020Mar19/Apr16/Jul30and2025Apr17are not selected first-month
releases. DDP delays need not imply an HTML delay. ASCII discontinuedMarch2021;
the collector uses HTML/preformatted HTML rather than attempting unavailable ASCII.

For other releases availability is end of original release date in New York plus1h,
not Wednesday observation time. This is an explicit conditional archive assumption,
not witnessed receipt or proof of immutable originals/revision completeness. The
publication feed demonstrates that historical releases can be corrected. A lag does
not repair unknown vintages. Original receipt/economic/live admission remainfalse.
Original Board material is used privately with attribution under its
[policy](https://www.federalreserve.gov/disclaimer.htm), no third-party redistribution.

The discovery index, announcements, landing page and HTTP metadata are SHA/size pinned
in config. Reuse these bytes, then100serial public GETs >=1s, HTTP1.1, no retries,
redirects or credentials. Preserve raw/HTTP metadata. Missing date, row, malformed
units, mismatched release/Wednesday identity or transport failure closes the source
as failed before economics. Source manifest SHA supplied at economic invocation.

## Checks and decision

Code/config/tests/this protocol frozen before full source/state/targets/outcomes.
Use existing V64/V78 integer daily ledger and SHA-pinned2018–2025active map/quotes/
spec proxies: capital1mRUB, grosscap1, marginbuffer2, participation1%, no cash yield,
base1tick/1xfee, double2ticks/2xfee, unchanged cancel-and-clip/roll accounting.

Stage1 gates: readycoverage>=80%,>=20round trips, CAGR>=5% and Sharpe>=.5 at BOTH
costs, MDD<=25%, worstyear>=−15%,>=5positiveyears/all8reported, CAGRexcess over
matched-calendar control>=2percentage points. All4ledgers complete/critical0/
unresolved0/terminalflat. Round trips include rolls, not independent macro events;
also report source-month and actual exposure counts. Five percent is a component
filter, not the user's relatively predictable20–50% annual objective.

Report every arm/cost/year and invalid or missing outcomes. Development period is
already seen, not independent holdout. Exact original BBO/specs/fees/margin and
later robustness remain unproved. No post-outcome formula/sign/window/asset/size/
calendar/control tuning, no new engine or broad AlgoPack admission, broker/demo,
purchase or Windows collector. A negative result closes this precise family rule.

Pre-seal verification:14new/76combined synthetic tests PASS7.13s, Ruff clean.
Three preserved2018/2020/2025HTML format samples parsed successfully before seal;
2018/2025local copies match source hashes. No new market outcomes loaded.
