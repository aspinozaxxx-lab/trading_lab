# V98 — scheduled FOMC event premium, pre-outcome protocol

Previous goal turn was PROGRESS: V97 completed and was rejected. The full goal
remains relatively predictable20–50% annual return, not a lower component target.
V98 is one new independent calendar-information hypothesis; V97 and earlier
calendar/month-turn/window rules are not retuned or repeated.

## Economic rule fixed before outcomes

MIX long/cash, fixed0.9gross. Nominal entry: daily open on the calendar day before
the scheduled FOMC announcement; hold through the announcement day; exit at next
actual daily open. Decisions18:45Moscow on completed days, intent for next CALENDAR
day. If a holiday eliminates the first intent, a later still-valid decision may
enter for the remaining day. At fill cancel entries outside the two-day window or
with decision-to-fill gap>3calendar days. No inference filter on future exit prices
or future exit tradability. Halts may extend exposure; missing exits remain in the
unchanged V64/V78 ledger, not deleted from the sample.

Control: identical rule seven calendar days earlier. Cancellations apply as known
at each decision, so March2020control must not be removed when the cancellation
was announced later. Control cannot be promoted after outcomes. No search, fit,
press-conference subset, return-driven dates, currency-based RI selection or leverage grid.

Motivation: [NYFed research](https://www.newyorkfed.org/research/staff_reports/sr512.html)
reports a pre-announcement equity premium, including international evidence in
its [public explanation](https://libertystreeteconomics.newyorkfed.org/2012/07/the-puzzling-pre-fomc-announcement-drift/).
V98 tests a **coarse two-day scheduled-event premium**, including announcement and
aftermath. It is NOT an exact24h pre-FOMC replication: a negative result cannot
falsify the precise intraday effect. This limitation is declared before outcomes.
MIX is the ruble-denominated equity-index instrument; this screen does not require
a forecast of the policy decision or an estimate derived from announcement outcomes.

## Sources and public cancellation

Eight original prior-year Board releases, URLs/publication days in config,
provide8meetings/year2018–2025. [Feasibility note](FOMC_CALENDAR_FEASIBILITY_20260916.md)
preserves discovery. Source collection is ten public GETs: eight schedules,
March15,2020conference page and its PDF. Serial>=1s, HTTP1.1, no retries, redirects
or credentials; keep raw, HTTP metadata and hashes. Any error closes source as failed.
Require64distinct scheduled dates; no unscheduled meetings inserted as advance signals.

The [public press-conference transcript](https://www.federalreserve.gov/mediacenter/files/FOMCpresconf20200315.pdf),
page5, explicitly says the March15meeting replaces the following Tuesday/Wednesday.
This is the public press call, NOT the private meeting transcript released years
later. Its [official landing page](https://www.federalreserve.gov/monetarypolicy/fomcpresconf20200315.htm)
also distinguishes the later April8minutes. PDF skill used to inspect the relevant
page; no PDF modifications. Extracted page identity and cancellation phrase must
match before source completion. Source documents were read before design, but no
new associated market outcomes were read.

Availability convention: end of the stated public date in New York plus1hour.
Thus cancellation becomes available2020-03-16T05:00UTC, not at a private Thursday
decision and not retroactively for the prior-week control. Schedules use the same
conservative clock. The transcript establishes the spoken announcement, not the
exact original PDF upload time. Current archive copies/dated headers are not
witnessed receipt, immutable vintages or proof of a complete revision history;
original_receipt_verified remainsfalse. This is conditional development research.

Board original material is generally public domain with attribution under its
[policy](https://www.federalreserve.gov/disclaimer.htm); no logos/third-party works
are redistributed. The2024release includes prospective2026/2027calendar metadata;
parse only the2025section. No2026prices/returns/labels/targets/PnL.

## Inputs, checks and reporting

Code/config/test/this protocol SHA closure before full collection or new targets.
Pin the closed source manifest SHA at economic invocation, then verify all files
before numeric market reads. V64 recent declarations pin<=2025active maps,
observations and specification proxies. Reuse the current daily integer ledger:
capital1mRUB, grosscap1, margin buffer2, participation1%, asset-level fills,
cancel-and-clip, no cash interest. Base1tick/1xfee, double2ticks/2xfee.

Stage1 gates: ready coverage>=80%,>=30round trips,>=5%CAGR and.5Sharpe at both
costs, MDD<=25%, worstyear>=−15%,>=5positiveyears and all8years reported, primary
strictly above control, all4ledgers complete/critical0/unresolved0/terminalflat.
Five percent is only the predeclared component filter, not income-goal success.
Already-seen development history is not an independent holdout; exact BBO/specs/
fees/margin/latency and later robustness remain required for any survivor.

Report all arms, counts, event IDs, cancellations, costs, annual returns, CAGR,
Sharpe, MDD and execution gaps. Do not hide zero-trade years or cancel a past
control because of later news. No post-outcome sign/window/year/asset/size/
press-conference/control promotion changes. No new engine/model or AlgoPack scope,
broker, demo, purchases or Windows collectors. Negative/invalid screen closes V98.

Pre-seal verification:13new and79combined synthetic tests PASS4.79s; Ruff clean.
Tests cover both schedule formats, cross-month meetings, missing/duplicate/date
errors, protected years, DST/public-day clocks, cancellation without retrospective
control deletion, expiry at delayed fill, no future-exit selection, missing plan,
flat-price cost loss for all four scenarios, and failed-source evidence preservation.
