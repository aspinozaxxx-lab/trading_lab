# V85 — EQOrderStats / HI2: source feasibility, no economic run

2026-09-15. Previous goal turn was PROGRESS: V84 completed, changing the next action
from a funding/basis follow-up to a different information set. Starting worktree
49b7e61 was clean. Goal20–50% remains active and unverified.

## What was actually inspected

Read-only metadata of already committed archive day manifests, then only
tradedate/tradetime/secid/metric/SYSTIME keys of one fixed2025-12-30 day. No numeric
OrderStats/HI2/price features, returns, labels, predictions, fit, orders or PnL were
used. No new market-data HTTP, collector, transfer, model or execution engine.

Root /srv/trading_lab_data/data/algopack-archive/algopack_archive_v1_5b7c66fa0e04.
Producer seal5b7c66fa0e0446eb3b395d3776c4496907e2c4cc760c5a87bc38e57da32f97e0.
Every inspected manifest has date<2026, current_vintage=true,
original_version_verified=false and economic_admission=false. Flags unchanged.

Actual snapshot2026-09-15T12:50:15.741715UTC:

| Dataset | Committed calendar days | Nonempty days | Rows | Nonempty2024 /2025 days |
| --- | ---: | ---: | ---: | ---: |
| EQOrderStats | 116 | 105 | 4269594 | 1 /104 |
| EQHI2 | 115 | 104 | 135333 | 1 /103 |
| EQTradeStats | 116 | 105 | 2587250 | 1 /104 |

There is no committed2020–2023 history for these three datasets at this snapshot.
The sole2024day is the fixed2024-10-15 archive pilot. Counts of daily rows do NOT
mean a multiyear strategy sample or independent observations. By12:52:43UTC the
download reached nonempty2025-09-06 forOrderStats and2025-09-07 forHI2; the continuing
change is archival progress, not a change in economic design based on outcomes.
The inventory print label latest_nonempty_manifest accidentally pointed to the last
calendar item2025-12-31 with0rows; use the explicitly computed maximum nonempty date
2025-12-30, not that misnamed field. Source files/manifests were not changed.

## Fixed-day field/clock evidence

2025-12-30 OrderStats:49pages/48208rows,253tickers,204distinct time labels,
06:55:00…23:50:00. HI2:2pages/1694rows,154tickers,11metric names per instrument in
this sample, one time label18:40:00. Duplicate projected keys0 in both. All SYSTIME
dates equal2025-12-30, no missing clock. Numerical values were never projected.

All51selected page-metadata/raw-gzip/decompressed SHA, date and row-count checks PASS.
This is a new EQ clock/schema sample, not a repeated audit of the old FO history.
Day manifests:

- eq_orderstats/2025/2025-12-30/manifest.json:
  c7b23aedd5f49239489c01189f038a8be8dd88b87782826e4022dc49e9dcf10a.
- eq_hi2/2025/2025-12-30/manifest.json:
  895a63de58645c2847f458e8ac186255339e5a8f59892678668f4f71b4be3cbd.

Same-day SYSTIME is NOT proof of first-version availability, timezone, bucket
completion or lack of later revisions. The vendor reply leaves those unresolved.
The [official HI2 method](https://moexalgo.github.io/docs/method/hi2/) states daily
calculation and end-of-day delivery. A daily HI2 cannot inform that morning's trade;
its next-session use still needs a frozen availability assumption/admission. The
last2025HI2 observation cannot be turned into a2026evaluation through this protocol.

## Independent mechanisms worth a fixed cheap contest

These are candidate rationales, NOT selected signs/thresholds, a sealed economic
protocol, tested hypotheses or a profitability claim:

1. **Asymmetric cancellation:** withdrawal of sell-side liquidity versus withdrawal
   of buy-side liquidity, rather than executed-volume imbalance already tested in V79.
2. **Persistent replenishment:** new limit-order volume net of cancellations staying
   on one side across completed buckets. A quantity put into the book is not a fill;
   orders away from best quotes can make this aggregate uninformative.
3. **Prior-day concentration plus flow:** HI2 distinguishes concentrated activity
   from broad participation. Its influence on the next session is a hypothesis,
   not evidence that concentrated participants are informed or profitable.

[MOEX OrderStats methodology](https://moexalgo.github.io/docs/method/supercandles/)
provides separate put/cancel quantities/counts/values by side. They add information
not present in the three rejected V79 FO rules. Whole-book5min aggregates do NOT
reconstruct best-quote event order or queue position.
[Cont/Kukanov/Stoikov](https://arxiv.org/abs/1011.6402) examine limit/market/cancellation
events and short-interval price changes for US stocks. Their price-impact result
does not establish forward predictability after5min aggregation, costs, or a MOEX edge.

## Scope and next action

The existing exception permits ONE conditional historical contest of three FO
mechanisms; V79 used it. The archive authorization explicitly does not economically
admit each newly downloaded dataset. The user's latest instruction to continue
research is not silently converted into removal of that final-vintage restriction.

An optional scope question was sent once during this turn: allow all new preliminary
contests on saved AlgoPack<=2025, with explicit current-vintage uncertainty, protected
2026, no real trades and no relaxation of Stage2/live admission. No answer yet at
this note. Do not build a new backtest engine/fit/PnL until that extension is confirmed.
Do not ask again on every automatic continuation; read actual subsequent user input.
Old freezes, failed rules, source flags and paper pause remain unchanged.

On approval: choose an explicit snapshot/period, controls, causally delayed features,
entry/exit and1x/2xcost rules, then seal BEFORE numeric features/outcomes. Available
late2025 alone cannot prove multiyear20–50% stability. Positive quick tests require
the later robustness/execution/demo stages; do not extrapolate a short-period CAGR.

At12:50:15UTC both download units were actually active/running withPID1663880 and
2522946; no restart, timer polling loop or subscription change. Download continues
independently of the scope question. No new economic screens/Stage2 candidates;
decisions/trades/fills0, PnL/CAGR/Sharpe/MDD/annual returns=null.
