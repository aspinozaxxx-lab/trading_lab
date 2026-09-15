# V87 — GOLD positioning as a risk-demand proxy

Stage1, declared2026-09-15T14:05:36Z before new GOLD features/MOEX outcomes. One
hypothesis, not a retune of WTI→BR V58/V59, V86 oil forecasts or a new engine.
Existing source V1 mentioned later BR research; this separate protocol explicitly
extends its economic use to previously unused GOLD→MIX/SI. Source bytes/admission and
all previous runs stay unchanged. No WTI numeric values or additional downloads.

Hypothesis: sustained accumulation of GOLD futures by managed-money traders may
proxy demand for defensive assets and precede weaker RUB/Russian equities. This is
an inference to test, not observed fund transfers, trader intent or proven causality.
Gold may instead reflect dollar weakness, inflation, rates or prior gold momentum.
[CFTC definitions](https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm)
classify traders, not each trade's motivation; categories can change.

## Fixed information and timing

Source:418GOLD reports2018–2025 in the existing836-row energy/metals bundle.
Manifest e0151b2b86b45ffc62043d3d24856e68221bc75b47fdbc004abb4e2cf3fcfb68;
all exact file bytes/identities in `configs/v87_gold_positioning_risk_v1.json`.
Server metadata/hash-only preflight checked this identity before numeric feature use.
Three selected fields: managed_money_long, managed_money_short, open_interest;
net share=(long−short)/OI. Sign of change over13reports;14complete reports required,
maximum adjacent gap10calendar days and window100days. Invalid/missing values mask,
not skip or zero. Direction computed by exact integer cross-products.

The old source's uniform report+7days lag is NOT sufficient during publication
interruptions. New adapter uses EOD NewYork of max(report+7days, existing pinned
official special-release override, known gold correction date). The full14report
window uses maximum availability; late older windows cannot overwrite newer reports.
The March26,2019GOLD report correction is delayed through April3EOD, as stated in
[CFTC special announcements](https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm).
2018/19shutdown dates use the existing override table and
[resumption schedule](https://www.cftc.gov/PressRoom/PressReleases/7864-19);
2023ION and2025shutdown delays use the same official announcements, including the
December9accelerated schedule. Even a released report is ineligible if older than
21calendar days at fill. No assumption of a complete original revision chain.

## One economic comparison

- 2018warmup, full2019–2025evaluation; all years previously examined in other families,
  not unseen holdout. No fitting, seeds, calibration or hyperparameter search.
- Positive GOLD impulse: SI+0.45/MIX−0.45; negative: SI−0.45/MIX+0.45; exactzero:cash.
- Control: constant SI+0.45/MIX−0.45 with identical source/execution masks.
- Daily EODMoscow decisions, factual next open, same active contract, normal rolls,
  max decision→fill7days. Terminal flat. No same-bar fills or future-label eligibility.
- Reuse V78/V72/V68/V64 daily integer portfolio ledger; initial cash1millionRUB,
  max signalgross0.9/order grosscap1.0, marginbuffer2, participation1%, no cash interest.
  This is not guaranteed continuous leverage control or synchronized paired BBO fills.
- Base1tick+1xfees; double2ticks+2xfees, both arms. Missing exits remain unresolved.

Before market values: ≥300ready source dates in evaluation and≥90%ready asset-dates.
Promotion requires bothcosts CAGR≥5%,Sharpe≥0.5,MDD≤25%,≥30closed episodes,
≥5positive years of7,worstyear≥−15%,excess CAGRovercontrol≥2percentagepoints;
allarms/costsexecutioncomplete,zero critical/unresolved,terminalflat. Stage2only,
not target20–50%or live. A failure closes this exact family; do not change signs,
lookback, assets, risk, costs, years or missing-source rules after results.

## Execution and saved evidence

`src/market_lab/futures_v87_gold_positioning_risk.py`, synthetic tests, config,
this protocol, official-override module and reused runtime modules are byte-sealed
before the run. ParentV64seal pins market inputs and inherited ledger dependencies.
Server only, separate immutable `runs/v87_gold_positioning_risk_v1_<seal-prefix>`.
Persist GOLD inputs, report clocks/features, per-asset states, targets, integer orders,
positions, ledger, counts, all annual returns/costs/risk metrics, limitations/verdict.
Verify source→state→target and saved ledger arithmetic once after run; no retest or
new detailed infrastructure for a rejected idea. AlgoPack downloads remain independent.

Annual archive may include later revisions; known delays/correction floors do not
prove original PIT. Historical broker fees/spec/margin/BBO remain research proxies.
No2026prices/returns/labels/PnL, real trades, collector restart or subscription change.

During this inspection the old V58 source clock was found insufficient for documented
delays. Its old audit checked replay against its rule, not full historical publication
truth. V58 was already rejected; do not rerun it or promote any old clock as causal proof.
