# V97 — hurricane forecast supply risk; pre-outcome Stage1 protocol

New information: **published NHC tropical-cyclone forecasts**, not weather known
after the storm, existing price momentum, inventory-change normalization or a
relabelled rejected family. Search of current docs/configs/source found no earlier
weather/NHC hypothesis. Previous goal turn was PROGRESS: consensus source/rights
evidence changed the next action, but was not a new economic test. Goal20–50%
remains unverified and unchanged. No new AlgoPack economic permission assumed.

## Rationale and fixed comparison

Gulf hurricane risk can cause offshore production shut-ins; refinery shutdowns
also reduce demand, so the price sign is a hypothesis, not a certainty. The
[BSEE archived operational reports](https://www.bsee.gov/newsroom/latest-news/statements-and-releases/press-releases/bsee-hurricane-ida-activity-final-report)
confirm the physical mechanism, not a profitable trading rule. No shutdown numbers
or realized damage estimates enter this experiment.

One fixed BR long/cash rule: any latest sampled forecast point with >=64knots,
24..31N/83..98W and <=72hours after issue, still future at decision. Gross0.9, no
leverage tuning, daily18:45Moscow decision, next actual daily open. Cancel when all
qualifying points precede the planned fill-day10:00Moscow clock, source is >48h old
at fill, or the decision-to-fill gap exceeds3calendar days. Hold until next causal
decision, with existing integer resizing/roll handling. The geographic rectangle
is fixed before outcomes and is not a production-weighted installation map.

Control: same wind/clock/horizon/size, **all Atlantic** rather than the Gulf filter.
Control is not a second promotable candidate or a future sign-flip opportunity.
No model/fit or parameter grid. Both rules, controls and every year are reported.

## Source, clocks and limited sampling

[NHC archive documentation](https://www.nhc.noaa.gov/data/index.php) distinguishes
issued advisories from post-analysis best tracks. HURDAT2, final tracks, storm
damage/casualty reports and geographic selection by later landfall are excluded.
[NWS usage policy](https://www.weather.gov/disclaimer) permits use of its original
government products with attribution and no implied endorsement; no third-party
map/image products are used. Respect access failures, no immediate retries or
credentials. The public FTP-over-HTTPS archive is the documented data interface,
not an attempt to defeat website authentication. A web-renderer403 on the storm
HTML page is recorded; the separate public data archive returned200 normally.

Before design, metadata indexes2021/2024 and first2021 Ana/Ida forecasts were read
for schema. Their coordinates/winds were visible; no associated prices/returns/
targets/PnL were read. Sample root `source_evidence/nhc_messages_probe_20260916_v1`,
two-forecast report SHA `214c4c282cc3ac09e0cdc048e6fde614421e66c84d7234e32ea48c13982eefd1`.
The first probe's SSH output disconnected after printing an overlarge link list;
read-only inspection confirmed both index files and its finalreport persisted.
It was not restarted. No economic result is inferred from that transport event.

Full bounded source:2018–2025 Atlantic `fstadv` files with explicit eight-digit
MMDDHHMM version suffix. Per storm/calendar day, choose the latest version with
filename clock<=14:00UTC, before contents. Only one selected message per storm-day
is needed for this deliberately sparse daily rule. Two workers, each >=1s/request,
<=2000requests, no retries/redirects. Existing two indexes reused by SHA; remaining
indexes downloaded once. Version corrections are used only after their own clock.

Availability=max(explicit UTC issue, filename version clock)+1hour. Header storm,
advisory number/year and forecast dates checked; valid times are **predictions**,
not future realized observations. Source expires48h after availability, so sleeping
after TTL does not claim zero hurricane risk. Parser gaps retain raw and mask both
arms for48h from their version clock+lag. Any HTTP failure stops the batch; missing
HTTP files do not become zero events. Archives/version filenames are not witnessed
publication receipt or cryptographic immutability; no live/PIT guarantee.

## Inputs, execution and gates

Exact config `configs/v97_hurricane_supply_v1.json`; new code/config/test/doc closure
must be SHA-sealed and pushed before collection or new targets. Closed source
manifest SHA is separately pinned at economic invocation before market value reads.
V64 recent input declarations pin <=2025 active maps, observations and specs;
V78 reuses the already-tested daily portfolio ledger, no new engine.

2018–2025,1millionRUB,base1tick/1xfee and double2ticks/2xfee,1%participation cap,
gross ceiling1.0,margin buffer2,no cash interest. All four ledgers must complete,
terminal flat/no critical or unresolved positions. Standard5%CAGR/.5Sharpe,
MDD<=25%,worst year>=−15%,>=5positive years of8,>=80%ready coverage and primary
strictly above control at both costs. >=20round trips fixed for a single rare-event
asset across8years; not lowered after seeing counts/outcomes. This is a preliminary
component gate, **not** substitution for the original20–50%income objective.

Report all annual results/counts/costs/coverage and execution failures, including
zero-trade years. Proxy specifications and daily open are not exact historical BBO.
Already-seen development market history is not an independent holdout. No new2026
market inputs, broker/live/demo, paid services, subscriptions or Windows tasks.

Forbidden after results: sign/geography/threshold/horizon/TTL/asset/size/year/control
retuning. A positive candidate goes to robustness/execution validation, never
straight to real money. A negative/invalid candidate closes this fixed rule.

Pre-seal local verification:13new synthetic tests plus V94 mapping/V78/V64 tests,
66/66PASS in4.67s; Ruff clean. Includes no future release/forecast-horizon leakage,
month rollover, corrected-message clocks, same-clock ambiguity, protected years,
missing-parser masking, stale-fill cancellation and four-arm flat-price cost-only
ledger accounting. No historical economic result was used to choose any rule.
