# V84 — funding plus endpoint basis versus cash

Declared2026-09-15T12:29:24Z, before new candle/rate/spot values. This is a short
post-selection accounting follow-up of BOTH V81/V82 pairs, not an unseen alpha screen
or a full paired portfolio. V81 funding and V82 capital results are already known.
Question: does the observed entry-to-exit basis contribution remove the funding
shortfall, and does the measurable component exceed a same-period cash-rate proxy?

## Fixed design

SBER100shares/short1SBERF and GAZP100shares/short1GAZPF. Fixed first/last parent
sessions2024-10-01/2025-12-30; no ticker, direction, date or hour selection.
Reuse the prior stock-pair execution convention: completed15:40bar, next15:50open
Europe/Moscow. Inspect exactly these bars in both legs; missing/no-volume execution
is unresolved, never a shift to a better bar. Four public ISS candle-day requests,
500-row hard cap, bounded date-only source admission before price projection.
Candles are research execution proxies, NOT BID/OFFER or actual fills.

Prices are RUB/share, Lot=100 per archived stock-perpetual specifications pinned by
V82. Entry/exit costs use actual observed leg notionals, stock10/future5bps per side,
then double together. Capital=1.30*initial stock nominal, no leverage/tuning and no
interest credited on margin. The inherited reserve is not proof of liquidity.

The measured component is:

    basis = 100*((stock_exit-stock_entry)+(future_entry-future_exit))
    funding = 100*sum(SWAPRATE for entry_date <= date < exit_date)
    component = basis + funding - entry_and_exit_costs

Unlike V81's after-first-close/before-last-close window, these intraday entries
receive first-day funding but not exit-day funding. Keep the source's unrounded
funding arithmetic explicitly as a proxy, not exact rounded VM receipts. Do not
silently carry V81's cashflow total into the new holding window.

Actual pair PnL additionally requires net dividends minus gross dividend adjustment,
conversion/replacement trades, margin/cash/liquidation and execution costs. All these
remain UNKNOWN, not assumed zero. We publish the sum of measured components and the
unmeasured residual required to meet the hurdle; this is not an upper bound on full
PnL, proof of a continuous feasible hold, or rejection of every possible pair variant.
No idealized sum may be relabeled portfolio CAGR/Sharpe/MDD.

## Benchmark and decision

Existing CBR manifest/data SHA pinned in config; only pre2026 admitted rows. For each
of455calendar days from entry until exit, take the last RUONIA with available_at at
or before15:50Moscow. Compound rate/100/365.25 daily, also report simple accrual and
maximum publication age. No post-outcome lag/TTL changes. It is a lagged research
cash-rate comparator, not the official RUONIA index, an investable deposit/fund,
or an income credit on encumbered cash. Missing rate makes comparison unresolved.

For BOTH candidates, report base/double component RUB, simple APR on full initial
capital, and RUB/percentage-point shortfalls versus20%APR and the compounded cash
proxy. COMPONENT_HURDLES_MET only if double costs meet BOTH; otherwise
COMPONENT_HURDLES_NOT_MET. Neither can admit Stage2 or verify the20–50% goal while
five liability/execution groups remain unresolved. No aggregate counts are added to
the23completed V65–V80 independent screens. No training, retuning or unseen claim.

## Inputs / outputs / audit

V81 eight raw pages are reused by pinned parent receipts, not downloaded/audited again.
The unchanged30-stock pre2026 manifest accompanies only its two required files in an
explicitly named partial-subset leaf; parent2026-containing files are NOT transferred.
CBR available_at was date-only checked through2025-12-31. Four new raw candle replies
and receipts are immutable; their manifest records actual retrieval/hash/date coverage
before arithmetic. Original-vintage/publication of historical candles is not proven.

Config/code/tests/protocol and imported V81 closure are sealed before outcomes.
Economic calculation only gpu-mlserver service UID999, new external run root, no rerun.
Synthetic tests cover units/signs/window, costs, exact bars, rate availability, nulls
and protected dates. Independent final arithmetic audit uses saved endpoint/funding/
benchmark records without HTTP or writing canonical outputs.

Counts:2scheduled pair endpoints per candidate,4leg proxy fills if all present,
actual decisions/trades/fills0. Full pair PnL/CAGR/Sharpe/MDD and yearly returns=null.
Yearly/monthly funding cashflows may be shown but are NOT yearly/monthly pair returns.
Detailed unresolved reasons survive even a positive measured component.

During source-only news search before this design, an unopened secondary RBC search
snippet incidentally exposed undated quote-header changes (IMOEX/SBERP/GAZP/SBER).
They were not used in design/calculation. No intentional2026market outcome access.
Known forced-conversion rule from official dated news: https://www.moex.com/n75703.

Next action: preserve both outcomes and opportunity-cost conclusion. If measured
headroom is absent, do not build a large execution engine to rescue this hold rule.
Any genuinely new basis-timing/conversion mechanism needs independent rationale and
a new seal; broker answers alone do not authorize lowering capital/cost assumptions.
