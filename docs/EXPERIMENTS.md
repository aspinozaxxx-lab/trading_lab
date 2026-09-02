# Реестр экспериментов

## Forward money-market fund pool V1 — SEALED, 0/60 discovery pairs

- Fixed pre-value universe: LQDT, SBMM, AKMM and TMON on TQBR with exact official
  ISIN/registration identities. Config SHA `37a3baeb...`, seal `ac299a7`, boundary
  `2026-09-02`; additions, substitutions and historical backfill are forbidden.
- Decision/fill snapshots at 15:49/15:59 preserve executable BID/OFFER, best and total
  depth, lot/minstep, settlement, exchange/retrieval clocks and exact raw ISS responses.
  All four valid rows are required; no ranking, yield, return, signal, trade or PnL.
- Discovery is 60 complete ordered pairs. Only then may a presealed selection rule use
  20 calibration pairs, followed by 60 unseen pairs. The future rule must account for
  offer-to-buy, bid-to-sell, broker fee, tax and liquidation before active cash-carry.
- This is an idle-only instrument comparison, not evidence that any fund is eligible
  broker collateral and not authorization for live trading.

## V41 joint forward execution admission V1 — SEALED, 0/60

- Config SHA `8183eb50...`, seal `293165b` precedes first parent quote/depth values.
  It consumes exact raw archives of stock-futures source `b25fe86c...` and idle-LQDT
  source `15fb471a...`; neither parent is rewritten.
- Each decision/fill stage requires both-sided best depth for one covered unit:
  100 shares converted through current TQBR LOTSIZE and one RFUD contract for every
  asset. LQDT BID/OFFER depth must be positive; its allocation capacity is deferred.
- Same-stage retrieval skew is capped at 30 seconds and both fill retrieval times must
  follow decisions. Only 60 jointly admitted dates unlock a separate economic seal;
  20 calibration + 60 unseen then follow. No outcome or annualization is produced now.

## Forward LQDT idle-cash source V1 — SEALED, 0/60 discovery pairs

- LQDT fixed before quotes: ISIN `RU000A1014L8`, fund rules №3915, TQBR. Official
  manager material describes CCP-repo money-market objective; official MOEX/NCC notice
  effective 2026-07-15 does not admit it to the expanded collateral list.
- Therefore the frozen hypothesis is idle-only: LQDT units must be zero while the
  corresponding stock-futures cash-carry sleeve is active. No collateral double count.
- Config SHA `15fb471a...`, seal `8ae3dc3`, boundary `2026-09-02`. Decision/fill source
  stores only BID/OFFER, lot/minstep, settlement, exchange/retrieval clocks and exact raw.
  iNAV is excluded pending index-data rights; yield/return/signal/trade/PnL are forbidden.
- Implementation `d03a8b7`; exact 15:49:00/15:59:00 Windows tasks are registered and
  `Ready` before the first quote snapshot.
- Readiness 60 complete pairs + 20 calibration + 60 unseen evaluation. A later economic
  seal must buy at OFFER, sell at BID and pin broker fees, taxes and settlement netting.

## Forward stock-futures cash-carry source V1 — SEALED, 0/60 discovery pairs

- Config SHA `b25fe86c...`, seal `a193e0d`, boundary `2026-09-02`; historical backfill
  forbidden. Universe and stock mapping are frozen to GAZR/SBRF/ROSN/TATN/NOTK.
- Two immutable source-only snapshots per Moscow session: decision 15:49 and fill
  observation 15:59. Futures selection uses only official metadata, exact LSTTRADE
  30–90 days and LOTSIZE 100 before quotes are read.
- Every valid snapshot requires five positive non-locked TQBR/RFUD BID/OFFER pairs and
  an exchange clock. Raw canonical JSON is replayed; basis/signal/trade/return/PnL are
  forbidden outputs. No eligible contract is an explicit sleep, not a zero.
- Implementation `a8f0139`, scheduler correction `766c6f8`; both Windows tasks are
  registered and `Ready` at exact 15:49:00/15:59:00 Moscow time.
- Readiness requires 60 complete ordered decision/fill pairs, then 20 calibration and
  60 unseen evaluation. Paper economics is forbidden before discovery; annualization
  is forbidden before unseen evaluation. Live remains false.

## V41 fixed V39 + cash-carry idle-RUONIA blend — GO to forward confirmation

- Cash-carry V2 SHA `a4c03aaa...`, seal `3265bd8` preserves exact 15 parent trades and
  credits 50% causal RUONIA only to inactive equal asset sleeves. Canonical
  `runs/stock_futures_cash_carry_idle_ruonia_v2_20260902T041838Z_a4c03aaa/`;
  metrics/manifest/audit/ledger
  `2ddc7ba4.../018044c6.../22a17cd.../69310021...`. Mean eligible fraction 87.10%,
  no missing rates. Primary/doubled/zero CAGR `8.3450%/8.2022%/6.5768%`, MDD near
  0.56%; no parent signal/trade/cost/cashflow changed.
- V41 SHA `45418128...`, seal `67a1eef` inherits exact V40R1 80/20 initial allocation
  and no-rebalance rule; it replaces only the zero-yield cash parent with frozen V2.
  No weight search followed V40R1.
- Canonical `runs/v41_v39_cash_carry_ruonia_stability_v1_20260902T042117Z_45418128/`;
  metrics/manifest/audit/ledger
  `000ae99b.../586e1b2d.../7dfc4696.../38bdd2ce...`.
- Primary/doubled/stress CAGR `25.5683%/25.1454%/24.6187%`, Sharpe
  `1.2689/1.2478/1.2273`, MDD `17.3235%/17.4244%/16.7796%`, worst year
  `+0.9087%/+0.4820%/-0.4482%`. All five presealed gates pass versus V39; primary
  has 5/5 positive years. Verdict `GO_TO_FORWARD_PORTFOLIO_CONFIRMATION`, live false.
- Freeze allocation, RUONIA fraction and all child rules. Required confirmation is a
  new forward period with synchronous executable cash-carry quotes and a byte-pinned
  broker/cash instrument rule; overlapping history is not independent evidence.

## V40R1 fixed 80/20 V39 + cash-carry stability blend — strict NO-GO

- V40 SHA `125c4740...` failed before combined metrics on a declared parent row-count
  typo. R1 SHA `05ce1266...`, seal `eddd16f` corrected only `781 -> 793`; allocation,
  scenarios, dates and gates are byte-identical in economics. ASCII report correction
  `b445f33` followed a post-write CP1251 print failure and did not change metrics.
- Fixed initial capital: 80% frozen V39, 20% frozen cash-carry, no rebalancing. Stress
  maps to V39 stress plus cash-carry zero-dividend/doubled-cost. No weight search.
- Canonical `runs/v40r1_v39_cash_carry_stability_v1_20260902T041248Z_05ce1266/`;
  metrics/manifest/audit/ledger
  `8812dffb.../9460e514.../572221d6.../9bd3ebdc...`.
- Primary/doubled/stress CAGR `25.0336%/24.6070%/24.1113%`, Sharpe
  `1.2392/1.2188/1.1993`, MDD `17.4210%/17.5226%/16.8766%`. Every CAGR remains
  above 20%; MDD improves by 2.56–2.64 pp and worst year improves in every scenario.
  Primary has 5/5 positive years, with 2025 `+0.2264%` versus V39 `−0.5162%`.
- Strict verdict `NO_GO`: Sharpe is lower by `0.0122/0.0129/0.0196`, violating the
  presealed all-scenario non-degradation gate. Freeze 80/20; do not search weights on
  this history. It is a risk-reduced alternative for forward comparison, not live GO.

## Covered stock–futures intraday cash-and-carry V1 — stable but standalone NO-GO

- Source V2 SHA `ffef4524...` replaced a denied subscription-only CCI dividend route
  without changing the preselected 61 contracts. It contains 16 589 daily rows and
  4 625 pinned MOEX RMS PIT cashflow observations; exact replay true.
- Intraday source V3 SHA `d6e751e7...` was pushed before selected 10m values. Canonical
  `data/processed/info_radar/moex-stock-futures-cash-carry-intraday-2023-2025-v3/`:
  485 141 candles, 61 official descriptions with `LOTSIZE=100`, 1 058 raw responses;
  manifest/candles/raw `c9ca6aa8.../0f16e6e9.../dbe9b156...`, exact raw replay.
- Economic SHA `aa35b0d8...`, seal `0416fb4`: fixed 15:40 decision/15:50 next-open,
  exact stock/futures timestamp, nearest 30–90 DTE, 5-DTE exit, 50% PIT cashflow
  haircut, `max(20%, RUONIA+4%)`, fully funded capital plus 30% futures reserve, and
  10/5 bps per-side ordinary versus 20/10 doubled costs.
- Canonical `runs/stock_futures_cash_carry_intraday_v1_20260902T040404Z_aa35b0d8/`;
  metrics/manifest/audit `e9eee0c3.../9025f572.../e2216343...`. 2 262 decisions,
  15 trades, 120 unresolved. All 15 primary and 14/15 zero-cashflow doubled-cost trades
  profitable. Primary/doubled/zero CAGR `5.1921%/4.9605%/2.3388%`, Sharpe
  `2.944/2.906/3.601`, MDD `0.640%/0.642%/0.655%`; 2024/2025 primary
  `+5.5773%/+10.2042%`.
- Verdict `NO_GO` standalone because `15 < 20` trades and CAGR is below 20%. Freeze
  time/DTE/hurdle/haircut/costs. It may enter only a separately sealed portfolio test
  as a stabilizing sleeve; RMS proxy is not a verified dividend and live remains false.

## Dividend-adjusted single-stock calendar spreads — V1 NO-GO

- Source-only SHA `ad9a3008...`, seal `3e8dd71` precedes all selected spread prices.
  Universe GAZR/SBRF/ROSN/TATN/NOTK selected only by positive PIT cashflow coverage and
  official exchange spread metadata, never returns.
- Cashflow coverage: 4 994 rows, 170 dates. Metadata: 53 spreads = `10/10/10/12/11`;
  every derived archive code exists in the official public list.
- Canonical source: `data/processed/info_radar/moex-dividend-calendar-spreads-2023-2025-v1/`;
  manifest `a8c1b0b0...`, raw `439a514a...`; 3 513 ISS rows, 3 556 public-archive
  rows, 222 exact responses and full raw replay true. Archive has 3 248 reported-trade
  rows versus zero in ISS.
- Economic config SHA `52a8ce06...`, seal `adf36d5`, implementation `7fba805` and
  empty-ledger audit correction `f62fdbd` precede the successful canonical output.
  One fixed rule used strictly prior RMS cashflow, opposite fair-value sign, following
  quote entry, bid/ask fills, 2/4/8 additional points and no parameter search.
- Canonical `runs/dividend_calendar_spread_v1_20260902T032624Z_52a8ce06/`; metrics
  `18646592...`, manifest `37759b73...`, independent audit exact. There were 31
  cashflow-change events and **0 executable entries**: the following quote never left
  positive edge to the fixed fair target. Verdict `NO_GO`; do not change sign, lag,
  threshold, event subset or use same-day RMS on this history.

## V39 weekly option-OI tail governor — canonical GO to forward confirmation

- Weekly source V3 config `a1ec093e...`, implementation `c709d35a...`; canonical
  manifest `0453f05c...`, audit `e09534ff...`, Parquet `fdd67cd9...`, raw ZIP
  `c1308810...`; 1 327 744 rows, 261 dates, 1 044 complete asset-week OI groups,
  independent replay 11/11.
- Economic config SHA `3b5d3074...`, seal `700ff9a` precedes any option-state/PnL join.
  Fixed rule: lag one weekly source state; trailing 52 prior put-share changes; cash a
  long above q90 or a short below q10. Options are not traded.
- Canonical `runs/v39_option_oi_tail_governor_20260902T025023Z_3b5d3074/`; metrics
  `52993f82...`, identity `fe60f262...`; 17/17 artifacts and independent metric/rule
  replay true. Counts: 97 put shocks, 101 call shocks, 44 reduced nonzero targets.
- Primary/doubled/stress CAGR `28,6849%/28,2235%/27,8287%`; Sharpe
  `1,2515/1,2317/1,2189`; MDD `20,0322%/20,1593%/19,4348%`. Every predeclared gate
  passed and each scenario improved MDD versus V27.
- Verdict `GO_TO_NEW_FORWARD_CONFIRMATION`, never live. Do not change window, quantiles,
  direction, warmup, age, assets or add volume/strike filters after this result.

## Public MOEX option EOD history pilot V2 — source-only, complete

- Config SHA `685fb7e9...`, seal `cecda6f`; implementation `affed25` были pushed до
  чтения январских значений. Источник не вычисляет return/target/prediction/PnL.
- Canonical `data/processed/options/moex-core4-options-pilot-2021-01-v2/`: 105 318
  rows, 6 956 SECID, 124 jobs, 1 133 pages; SI/RI/BR/MIX
  `58 742/18 956/17 010/10 610`; calls/puts по 52 659. Manifest `0211e452...`,
  Parquet `9a37fb55...`, raw ZIP `76474c32...`; independent replay 9/9 true.
- Execution coverage недостаточен: `CLOSE` 7 868, positive volume/trades 7 887,
  positive open interest 17 215, `THEOR_PRICE` 0 nonmissing; historical bid/ask нет.
- Verdict `SOURCE_COMPLETE / ECONOMICS_BLOCKED`. Не использовать SETTLEPRICE как fill
  и не строить historical premium PnL до exact expiry/spec reference и licensed
  quote/order history. Экономическая ветка остаётся forward-only, defined-risk.

## V38 official MOEX MR1 asset-specific governor — canonical NO-GO

- Historical source V4 config SHA `83bcabed...` was sealed before MR1/CF values.
  Canonical `moex-rms-historical-pit-2018-2025-v4`: 4 647 raw pages; limits/static/
  cashflow rows `189 682/88 639/10 817`; manifest `e88360d3...`, audit `013c6e23...`,
  raw ZIP `d2b8d5e4...`; independent raw replay 11/11 true. V1–V3 failed closed without
  output while temporal semantics and the real intraday keys were established.
- Economic config SHA `3f9288e3...`/seal `dd5d118`, implementation `832f12c` were pushed
  before historical MR1/PnL. The only rule was an exact positive week-over-week MR1
  change: cash the affected frozen-V27 asset for one weekly interval; unchanged/lower
  MR1 passes, missing/stale cashes. No fitted magnitude, percentile, smoothing or
  leverage change.
- Canonical `runs/v38_moex_margin_risk_governor_20260902T020147Z_3f9288e3/`; metrics
  `32b457ab...`, identity `f5c76687...`; 26/26 artifact identities and 15/15 independent
  metric replay checks true. OOS: 1 044 asset-week states, 23 MR1 increases, 18 affected
  nonzero parent targets, 800/800 execution dependencies complete.
- Primary/doubled/stress CAGR `24,5261%/23,9458%/23,5132%`. Primary Sharpe `1,0868`,
  MDD `20,2538%`, worst year `−0,5832%`. Compared with V27, primary MDD improved by
  `0,4600 п.п.` and worst year by `0,8940 п.п.`, but CAGR/Sharpe fell by
  `3,8491 п.п./0,1251`; doubled/stress MDD worsened by `0,1088/0,7363 п.п.`.
- Verdict `NO_GO`: the strict stability gates failed. Do not tune MR1 threshold, age,
  persistence, global/asset scope, MR2/MR3, direction or leverage on these outcomes.
  Historical MR1 is development evidence only; forward RMS remains source-only.

## V37 cross-market intraday breakout — canonical NO-GO

- Frozen 30-stock source manifest `5a7a4873...`; config SHA `15c6d67c...`, seal
  `f8dd07f`. One-sided top-three Donchian continuation, all-stock breadth/value/correlation
  state, fixed MLP threshold `0,60`, next-open execution, trailing `0,6%/0,4%`, stop
  `1,8%`, 24-bar maximum and `1x/2x/3,5x` costs were fixed before targets/PnL.
- Implementation `b12876f` pushed before outcomes. Initial run failed before target/PnL
  and without output because Parquet restored timestamp as index; parser-only correction
  `6cd2c0a` was pushed before resume.
- Canonical `runs/v37_cross_market_breakout_20260902T011012Z_15c6d67c/`; metrics
  `4023a7ea...`, identity `ead762ab...`, audit `1279ea48...`, manifest `a000b2a3...`;
  independent artifact replay all true. Counts: 6 392 candidates, 6 355 observed,
  5 045 ungated OOS signals, 10 090 predictions, 1 030 evaluation sessions.
- Full MLP: one signal, zero trades, one capacity unresolved (`1,994% > 1%`);
  aggregate MLP: zero signals. Ungated primary: 751 trades, CAGR `−9,0797%`, Sharpe
  `−1,2835`, MDD `35,5776%`, one positive year; doubled CAGR `−23,2151%`, stress
  `−83,7847%`. Long-only primary CAGR `−6,6135%`, all years nonpositive.
- Verdict `NO_GO`. Gross continuation is too weak after costs and the largest factual
  participation need is `42,716%`; probability threshold, sign, corridor, stop,
  leverage, universe and years may not be tuned on these outcomes. Next action requires
  new information or a genuinely forward period.

## V27 independent forward validation — ACTIVE, 0/253 price warmup

- Parent development V27: SHA `7a9a44cf...`, canonical metrics `5fc1f271...`; primary
  CAGR `28,3752%`, Sharpe `1,2119`, MDD `20,7138%`, но same-period adaptive и не live.
- Forward V1 SHA `c1acf97b...`, seal `a79fd4c`; до первого snapshot он superseded,
  потому что current `LAST` не является official daily `CLOSE`. Source-only V2 SHA
  `f4a7d016...`, seal `941e0b9`, implementation `f38a41f0...`/commit `09e73c4`
  исправляет только это соответствие, параметры не меняет. Historical 2026 market
  backfill запрещён.
- V2 сохраняет полные SI/RI/BR/MIX chains, отдельный official history row каждого
  EOD-контракта и raw STLFSI4/RUONIA/key-rate vintages. Tasks 10:05/23:45 мск
  переназначены на V2 и `Ready`.
- Paper SHA `d68f0595...`/seal `51acd4c`, preflight `05a1f74`: для 252 return
  observations нужны 253 common price sessions; partial week запрещено считать
  завершённой. Official calendar authorization пока отсутствует, generic weekdays
  запрещены.
- Требуется 253 common price sessions warmup без reported PnL, затем минимум 504 unseen
  evaluation sessions / 104 weekly decisions / два года. На момент записи 0/253 и
  0/504. Gates: all-cost CAGR `>=20%`, Sharpe `>=1`, MDD `<=30%`, положительные годы,
  zero critical/unresolved и observed-quote paper profit.
- Даже numeric GO не разрешает live: требуется второй unseen period и broker-exact
  collateral/margin/fees/order audit.

## MOEX RMS risk/cashflow forward source — ACTIVE, 0/60 discovery

- Public official source содержит `staticparams`, `limits` и anticipated `cashflow`;
  absolute price/return/target/PnL не запрашиваются. Future use ограничен dividend fair
  value, exchange-margin stress, cross-asset ranking и option-risk regime.
- V1 SHA `fd0145eb...` sealed до values и fail-closed без output: cashflow имеет свой
  revision clock. V2 SHA `48044ecf...`, seal `cc1bcd2`, меняет только temporal schema;
  values до V2 seal не читались.
- Collector `dcd9795`, scheduler/readiness `ff4d0d0`, tests `4/4`. Task
  `TradingLabForwardMoexRms` Ready, Mon–Fri 23:35. Source date раньше `2026-09-02`
  reject; 60 discovery + 20 calibration + 60 unseen evaluation, PnL пока запрещён.

## FX cash-and-carry V1 — NO-GO

- Protocol SHA `4b3ca33e...`, seal `7ddc677`; runner commits `a6d945b`/`4b4b5a2`
  были pushed до canonical basis/PnL.
- Canonical: `runs/fx_cash_carry_v1_20260901T233224Z_4b3ca33e/`; metrics SHA
  `3f638a7b...`, identity `432b25fb...`, audit `65a9ee95...`; replay 11/11 и все
  execution/source checks true.
- Механика: fixed quarterly long `USD000UTSTOM`/short SI, entry около 60 DTE,
  same-session opens, 5 bps half-spread + 1 bp commission per leg/side, full spot
  principal + 30% margin + 10% buffer, USD yield zero, admission только `>=2%`
  annualized excess over causal RUONIA. Stress использует 10 bps.
- Development 2018–2022: 1/20 trade; primary total `+1,7449%`, CAGR `0,3471%`,
  Sharpe `0,3470`, MDD `1,0063%`; RUONIA CAGR `7,2699%`. Stress total `+1,6150%`.
- Evaluation 2023–2025: 0/12 trades, CAGR `0%`, RUONIA CAGR `16,5405%`; 6 entries
  below hurdle и 6 без complete fixed schedule. После `2024-06-12` source содержит
  398 zero-price/zero-trade rows из-за прекращения on-exchange USD/RUB spot trading.
- Verdict `NO_GO`: 6/8 promotion gates false. Не ослаблять hurdle/capital/costs и не
  подбирать alternate dates на этой истории. Reverse carry остаётся запрещён без
  доказанного USD borrow.

## CNY cash-and-carry V1 — NO-GO

- Source-only bundle: 2 027 spot + 3 636 quarterly futures rows, 12 contracts, 157/157
  replay checks; manifest `7b8c4a8d...`. Все четыре 2025 CR и CNY spot исполнимы.
- Economic SHA `1b9406d9...`; config/runner commits `0fef4c6`/`f17e1f6` были pushed
  до outcomes. Canonical `runs/cny_cash_carry_v1_20260901T234628Z_1b9406d9/`;
  metrics `f1da93e6...`, identity `252fee8b...`, audit `da712d33...`, replay 12/12.
- Fixed 60-DTE long spot/short CR, full spot principal + 30% margin + 10% buffer,
  CNY yield zero, 5/10 bps spread scenarios и `>=RUONIA+2%` admission.
- Development 2023–2024: 0/8 trades, CAGR `0%` vs RUONIA `14,3844%`. Evaluation
  2025: 0/4, CAGR `0%` vs RUONIA `20,9377%`. Все 12 причины — hurdle not met.
- Family conclusion: fully funded currency cash-and-carry не конкурентен дорогому RUB
  cash. Не ослаблять capital/hurdle. Следующий допустимый mechanism — margin-only
  perpetual/quarterly spread с observed prior-day SWAPRATE.

## CNY perpetual/quarterly spread V1 — INVALID; V2 — NO-GO

- Perpetual source V2: 937 active `CNYRUBF` rows `2022-04-26..2025-12-30`, 784
  nonmissing exchange `SWAPRATE`, manifest `1664a012...`, Parquet `3b1ee181...`,
  audit 33/33. Quarterly parent remains the exact 12-contract CR bundle.
- V1 config SHA `5b2d6be7...` was sealed before rates/basis/PnL. Immutable run
  `runs/cny_perpetual_quarterly_spread_v1_20260902T000440Z_5b2d6be7/` is invalid:
  it applied `SWAPRATE × 1000`, but used point value 1 for price PnL, notional,
  spreads and commissions. Its huge numeric GO is a unit artifact and is rejected.
- V2 correction SHA `6a0a7cbe...`, seal `df9a7bb`, runner `48afc99` changed only
  contract cash units to point value 1 000; schedule, direction, causal 20-session
  funding estimate, costs, capital fractions, RUONIA+2% hurdle and gates are inherited.
- Canonical corrected run:
  `runs/cny_perpetual_quarterly_spread_v2_20260902T000944Z_6a0a7cbe/`; metrics
  `d1a23519...`, identity `44211bd7...`, audit `c6d8cdd2...`, artifact manifest
  `f79bb792...`; independent audit 15/15.
- Development 2023–2024: 0/8 admissions, CAGR `0%` vs RUONIA `14,3844%`.
  Evaluation 2025: 0/4, CAGR `0%` vs RUONIA `20,9377%`. Best sealed CRH5 expected
  pair yield was `13,8903%` with RUONIA `20,85%`; all entries failed the hurdle.
- Verdict `NO_GO`. Do not tune threshold/date/direction on 2023–2025. A collateralized
  version requires independently proven yield/haircut rules and forward confirmation.
- Forward source SHA `1305af9d...` и code `13371f2` были pushed до первого post-seal
  quote. Он детерминированно сохраняет exact `CNYRUBF` и два ближайших CR, public
  bid/offer, current IM/spec/fees, actual retrieval и funding history только начиная с
  `2026-09-02`; return/target/PnL отсутствуют. Readiness `7abf796` требует последовательные
  40 discovery + 20 calibration + 60 unseen evaluation дат. На момент записи 0/120.

Этот файл фиксирует научную память проекта. `Canonical` означает выбранный для аудита
неизменяемый артефакт, а не разрешение на live trading. Все внешние run paths относительны
к `D:\Projects\trading_lab_data`.

## V36-R1: multi-era online expert ensemble — canonical NO-GO

- Fixed 10-expert family на `2008-10-08..2025-12-30`: trend 21/63/126/252,
  multi-trend, carry, confirmation, relative, consensus и cash. Online weights —
  prior-week-only discounted exponential wealth (`decay=0,98`, `eta=8`), без epoch или
  future-label selection. Evaluation `2013..2025`; comparisons заранее фиксированы как
  static equal active experts и frozen three-sleeve.
- V36 config SHA `cb391e44...` был sealed/pushed до outcomes. Первый immutable run
  `runs/v36_online_expert_20260901T223514Z_cb391e44/` имеет metrics SHA `3fa9e454...`,
  но invalid: pre-2018 derived execution оборвался `2017-12-01` с тремя открытыми Z7,
  дал 6 161 missing contract rows, 555 atomic rejects и нулевой 2018–2025 PnL. Этот
  результат не является economic test и не перезаписывается.
- R1 — только source-boundary repair. Из уже sealed official parent daily SHA
  `00a9a872...` выбраны независимо от позиций/PnL все quarterly Z7 SI/RI/MIX: 45 rows
  с lag seed, из них 42 factual execution rows / 14 sessions `2017-12-04..2017-12-21`.
  На известном expiry open `2017-12-21` добавлен exact flat всех assets; re-entry только
  из original causal targets. Signal, expert weights, risk, 2x cap и `1/1, 2/2, 4/2`
  costs не менялись.
- R1 config SHA `156f573cd52b0f648f7c1c33c203a0ff021c1d99dd55b4d186b01bb16df2a801`,
  runner SHA `7a1c18b9...`, core SHA `51633026...`; seal `aea629f` pushed до corrected
  outcome. Tests `14/14`, preflight base+bridge fully true.
- Canonical `runs/v36r1_online_expert_20260901T224722Z_156f573c/`: metrics SHA
  `9812a1fdce5db12908d92f35a863742fb1a7a957743e562626cb2d2ac11096fc`, identity SHA
  `c193c7cf0a839094ecf34c97692dc5184f66074758834da0a6c92f40abbbbbbd`, audit SHA
  `d97aaa829cda7294a7882ec0dd6417d53acef18312e227ecccc23022fab65805`; 11/11 true.
- Online primary: total `+124,78%`, CAGR `6,4262%`, Sharpe `0,3989`, MDD `40,7292%`,
  7/13 positive years, worst `2020 −25,937%`, costs `154 148,20 RUB`, 2 255 filled
  legs. Doubled/stress CAGR `5,1407%/4,8394%`; all execution complete, zero critical/
  unresolved. Static equal primary лучше: `8,1551%/0,4566/39,3230%`; frozen three
  primary `6,6055%/0,3949/48,7712%`.
- Verdict `NO_GO`, 20%/50% claims false. Online allocation не улучшила static ensemble;
  V36/R1 parameters и bridge не tune-ить. Следующий test — только новый independent
  return mechanism/source либо настоящий forward/PIT period.

## V35: thirty-stock cross-sectional intraday — canonical NO-GO

- Source-only protocol `stock-intraday-pre2026-source-v1`, config SHA `ba1934d6...`,
  code SHA `0d2d55e2...`, seal `95fad8a`. Immutable external bundle
  `data/processed/stocks_10m_pre2026_v1/`: 30 tickers, 4 527 436 source OHLCV rows,
  maximum `2025-12-30`, manifest SHA `5a7a4873...`, 12/12 audit. Никакие return/label/
  target/PnL в source build не вычислялись.
- V35 config `configs/stocks_v35_cross_sectional_intraday.yaml`, SHA
  `257422c0ce2824e3a12252f1759e01fdee29c321f11190bd3b09d9a2b4984388`; core SHA
  `f31e0b80...`, runner SHA `b7dce2d8...`. Seal `fac5625` pushed до outcomes.
  Loader-only pandas-index fix `df207d1` также pushed до первого economic calculation;
  failed attempt не вычислила outcomes и не создала output.
- Mechanism: exact common 30-stock panel; completed-bar residuals to equal-weight market,
  causal rolling beta/scale; long bottom-3 and short top-3 residual z. Decision every
  20 minutes, next exact open entry, exact 60-minute exit, maximum one concurrent basket.
  Primary/doubled/stress one-way costs are 10/20/35 bp plus 20%/20%/30% annual short
  borrow. Gross target 1,5, known signal-value participation 0,25%, factual cap 1%.
- Full `[48,24]` MLP sees 30-stock residual-z, one-bar residual, beta and value-rank
  vectors plus 20 aggregates. `[24,12]` ablation sees only aggregates. Two fixed seeds;
  annual expanding 2022–2025, prior-year nested calibration and one-session purge.
- Canonical run `runs/v35_cross_sectional_intraday_20260901T220621Z_257422c0/`.
  Metrics SHA `8c9820cf4da133cc915f0e2fd9529015eb7f301e73f6aff724d2f8e5e53e67bc`,
  identity SHA `18b48fbaf42e1ce5bf91bad18a6ac57da76def955210dad9b005e43b4181d70f`,
  audit SHA `dbfb13057280eac93565c5bb460ae8b6e0e9ee6c1cd4d1fa15937b2e6d1737a9`;
  independent audit 16/16 exact.
- Counts: 96 005 exact common timestamps, 11 297 candidates, 9 024 evaluation candidates,
  420 doubled-cost-positive labels, 18 048 OOS predictions. Все 8 fold/variant records
  `sleep_insufficient_calibration`; обе MLP имеют 0 signals/trades. Gate не ослаблять.
- Fixed primary: 2 965 trades, 867 unresolved capacity, costs 447 585,40 RUB including
  borrow. Gross profit only 29 706,79 RUB, net `−417 878,61`; total `−41,7879%`, CAGR
  `−12,6519%`, Sharpe `−8,9863`, MDD `41,7928%`, positive years 0/4. Calendar returns:
  2022 `−2,7500%`, 2023 `−9,7048%`, 2024 `−15,2270%`, 2025 `−21,8009%`.
  Doubled CAGR `−38,1944%`; stress total nearly `−100%`.
- Verdict `NO_GO`, 20%/50% claims false, live forbidden. Экономическая причина — mean
  executed gross edge `0,858 bp` против 20 bp primary round trip. Capacity, current-
  universe survivorship, absent short-locate/lot records are additional blockers. Не
  менять V35 threshold/sign/horizon/universe/cost/leverage на этой history.
- После source extension целевые tests `23/23`, scoped Ruff clean. Full regression:
  `997 passed, 7 skipped`, плюс те же два заранее документированные V8 anti-junction
  failures; новых V35/equity-source regressions нет.

## V34: RI–MIX relative-corridor barrier — canonical NO-GO

- Новая family после V33 economic NO-GO: barrier meta-label вместо absolute-return
  regression. Relative residual `RI - beta*MIX`, rolling beta `132/min66`, residual
  history `18`, admission `|z| >= 1,5`, TP `1x`, distant stop `3x`, maximum hold `12`
  exact 10-minute bars.
- Config `configs/futures_v34_relative_corridor_barrier.yaml`, SHA
  `eece2650f3f049d29ae6e9ba3fe65f98393f368c6ab40c36740da0ab7c6c7c09`; core SHA
  `f3e86c52...`, runner SHA `e8ad7882...`. `sealed_before_outcomes=true`, protected
  boundary `2026-01-01`, live trading forbidden.
- Full neural meta-label uses the simultaneous SI/RI/BR/MIX state plus same-day robust
  MOEX option-curve context. Frozen ablations: identical market-only MLP and fixed
  corridor rule. Architecture `[24,12]`, seeds `3401/3402/3403`; calibration may choose
  only `0,55/0,65/0,75`, with 30 trades and two positive prior months required.
- Execution is atomic across both legs, maximum two nonoverlapping pairs/day, stop-risk
  budget `0,75%`, pair gross `<=1,2`, each asset `<=0,6`, factual cap `1%`, six bounded
  exit retries. Scenarios `1tick/1fee`, `2/2`, `4/2` are all mandatory.
- Promotion requires every cost CAGR `>=20%`, primary Sharpe `>=1`, MDD `<=25%`, all
  three calendar segments positive, at least 200 filled legs and incremental edge over
  the best market-only/fixed baseline. Even a pass is only a lead for new forward paper
  validation.
- Metadata-only preflight 8/8, targeted V32–V34 tests `25/25`, scoped Ruff clean. Full
  suite: `976 passed, 7 skipped`; only the two pre-existing V8 anti-junction failures
  remain because external data intentionally resolves outside Git root.
- Seal commit `12b48dc` был pushed до первого outcome. Единственный canonical run:
  `runs/v34_relative_corridor_20260901T213656Z_eece2650/`; metrics SHA `1db3bc1a...`,
  identity SHA `687c1328...`, independent audit 62/62 exact.
- Candidate coverage: 389 rows / 156 source-event days; evaluation 323, positive barrier
  targets 133. Все 26 monthly folds у обеих MLP спали: maximum calibration event days
  33 `<` sealed 40, поэтому curve/market MLP trades = 0. Это coverage failure, не
  разрешение ослабить gate post-outcome.
- Fixed corridor: 118 completed pairs / 472 filled legs, zero unresolved, six exit-retry
  trades, costs 27 624,64 RUB. Total `−2,9293%`, CAGR `−1,3634%`, Sharpe `−1,0445`,
  MDD `4,5066%`; years `2022 +0,7919%`, `2023 −4,0636%`, `2024 +0,3874%`.
  Exit split: 52 TP, 11 distant stop, 55 time exit. Verdict `NO_GO`; family закрыта.

## V33: V32 target-preserving liquidity execution repair — canonical NO-GO

- Это post-outcome adaptive correction после V32 execution halt, не новая model search
  и не independent confirmation. Exact V32 run/metrics/identity и три targets byte-pin-ятся.
  Каждый target artifact содержит 98 168 rows, 24 542 timestamps и 538 flat days.
- Feature, label, MLP/Ridge, seeds, folds, selected monthly threshold, signal sign,
  covariance target weights, gross/asset caps, costs и promotion gates не пересчитываются
  и не меняются. Config явно фиксирует `signals_models_and_target_weights_changed: false`.
- Единственная correction: capacity applies одинаково к increase и de-risk; неполный
  de-risk исполняется до integer 1% capacity и остаток переносится с factual marks.
  Reversal разбит на close-first/open-second с общей bucket capacity. Daily 18:30 flat
  получает шесть exact 10m retries и затем fail-closed `flat_retry_exhausted`.
- Synthetic tests доказали: volume `<100` не создаёт fill, следующий bucket закрывает
  один контракт; reversal не пересекает zero до close; exhausted retries дают explicit
  unresolved. V32+V33+encoding tests `21/21`, scoped Ruff clean.
- Config SHA `615d7b8e...`, module SHA `3ad113cc...`. Preflight `10/10` и parent audit
  exact: пять V32 unresolved records имеют только `insufficient_exit_capacity`; три
  parent target hashes/rows/timestamps/flat days совпали. Seal `8c180e9` был pushed до
  outcomes. Canonical run `runs/v33_curve_regime_liquidity_20260901T183357Z_615d7b8e/`,
  metrics SHA `17d9602a...`, identity SHA `d0b5b436...`; audit 35/35 exact.
- Full-MLP primary/doubled/stress execution complete, unresolved 0; repair действительно
  прошёл весь горизонт. Primary total `−3,6783%`, CAGR `−1,7374%`, Sharpe `−0,2471`,
  MDD `17,0343%`; doubled CAGR `−4,0113%`; stress total `−13,9154%`, CAGR `−6,7677%`,
  Sharpe `−1,1212`, MDD `22,5476%`. Market-only CAGR `−2,8398%`. Ridge baseline отдельно
  invalid на missing exact mark successor, но complete market-only уже достаточен для
  отрицательного comparison.
- Full MLP имел signals только в двух первых test months: 5 932 active rows в 2022 и
  zero в 2023/2024; 24/26 monthly folds уснули на calibration gate. Active signed gross
  `0,198 bp` против `8,981 bp` stress cost; 2022/2023/2024 returns `−3,6783%/0%/0%`.
  Это economic `NO_GO`, не execution failure. V32/V33 threshold/sign/horizon/weight/
  retry больше не менять; следующая family обязана иметь новый target/mechanism.

## V32: continuous curve-regime cross-asset intraday — execution-incomplete NO-GO

- Новая family после закрытия V30/V31. Она не меняет знак/плечо старой стратегии, а
  обучает отдельный прогноз следующих 60 минут после каждого completed 10m bucket на
  совместном состоянии SI/RI/BR/MIX и official MOEX coefficient-event context.
- Source — immutable
  `data/processed/options/moex-curve-coefficient-regime-2021-2024-v1/`: 686 events
  `2021-09-01..2024-05-21`, wide SHA `8cb63799...`, manifest SHA `f76a8ce1...`.
  Используются только robust median/IQR/delta коэффициентов S/A/B/C/D/E и их
  cross-asset dispersion; цена/settlement, maturity и недоказанный T не используются.
- Критическая correction выполнена до outcomes: 10m bars соединяются с contract plan
  по `effective_date`, причём `decision_date < effective_date` и
  `observed_through <= decision_date`. Старый intraday loader по `decision_date` для этой
  family запрещён, потому что мог выбрать контракт по информации после close того же дня.
- Exact information contract: source `available_at <= decision_at`; четыре factual bar
  ends `<= decision_at`; feature не создаёт return через gap/overnight; label требует семь
  exact successors одного contract; entry равен следующему common open, exit-label —
  open через шесть buckets, forced flat — 18:30 мск.
- Models frozen до outcome: full MLP ensemble `[32,16]`, seeds `1729/2718/3141`;
  market-only twin; full Ridge alpha 10. Monthly expanding core, prior-three-month
  calibration и one-day purge. Calibration выбирает только cost multiple
  `1,5/2,5/4,0`, требует 200 actions и два positive months; иначе весь test month cash.
- Risk/execution frozen: 30% annual target, gross `<=1,6`, per-asset `<=0,6`, causal
  132-bucket covariance with 50% diagonal shrinkage, integer next-open size, 0,25%
  signal-volume cap, 1% factual capacity, 2x margin buffer, full fail-closed exits and
  primary/doubled/stress costs `1/1`, `2/2`, `4/2` ticks/fee multiplier.
- Promotion requires every cost CAGR `>=20%`, primary Sharpe `>=1`, MDD `<=25%`, all
  three calendar segments positive, at least 200 filled legs and full model advantage
  over both ablations of `+2 п.п.` CAGR and `+0,1` Sharpe. Aspirational 50% is reported
  separately. Any pass is development-only and requires sealed forward/paper evidence.
- Config SHA `c7da1d45...`; core SHA `45bffa21...`; runner SHA `9f70fa3c...`.
  Outcome-free unit/encoding tests `13/13`; metadata-only preflight `10/10`: 218 raw
  artifacts, 683 209 active bars, 169 644 common-four buckets, 686 source events,
  670 event days and 29 810 structural decisions. Seal commit `936e3e0` был pushed до
  outcomes. Canonical run `runs/v32_curve_regime_intraday_20260901T181223Z_c7da1d45/`,
  metrics SHA `f4adf509...`; independent artifact audit полностью true.
- Economic horizon не завершён. Full MLP primary/doubled/stress и Ridge остановились
  `2022-04-26 11:00 UTC` на одном BR contract при bucket volume 79; market-only —
  `2022-05-13 11:00 UTC` на одном MIX contract при volume 97. Integer 1% capacity в
  обоих случаях равна zero, а V32 policy сразу делала весь run unresolved. Все пять
  ledgers incomplete, поэтому partial-2022 CAGR/Sharpe статистически и экономически
  невалидны. Verdict `NO_GO`; V32 не повторять и не переписывать.

## V31: one-shot unseen 2008–2011 temporal validation — canonical NO-GO

- V31 byte-pin-ит canonical V30-D2 config/module/metrics/identity и не меняет signal,
  equal component weights, 20% final-risk restoration, cap 2x, V29 risk-first ledger или
  primary/doubled/stress costs. Config SHA
  `6dcb6dab554137525015c4408393141388f883ccf580f6d0425e255b0e445fd9`, module SHA
  `ce2ee2605b5dc62cba2bc34d54716025afa924fc781427decdfc446c3abbab95`.
- До seal прочитаны только exact hashes/bytes/schemas, dates, asset masks и причинные
  non-price timestamps. Preflight 86/86 true; values `close/open/settle/roll_yield`,
  returns, targets, equity и PnL 2008–2011 не читались.
- 253-я master-сессия механически приходится на `2009-10-13`; первая последующая
  weekly decision — `2009-10-16`, первый допустимый next-open fill — `2009-10-19`.
  Evaluation заканчивается `2011-12-15`: 525 sessions, плюс predecessor = 526.
- MIX отсутствует 727 master-сессий и допускается только как exact
  `asset_not_yet_available` flat mask. Единственный контракт появляется слишком поздно
  для 252-session trend, поэтому backfill и синтетический сигнал запрещены. Для 727
  post-initial zero rows causal adapter присваивает только предыдущую factual decision
  date, чтобы полный four-asset mapper перенёс flat; contract/price/signal не создаются.
- Seal commit `370b4d8` был pushed до первого economic read. Единственный immutable run:
  `runs/v31_pre2012_temporal_20260901T145938Z_6dcb6dab/`; metrics SHA
  `d6d1284279e111001b7d90ea59b3fad01a9036191cd62d5191de3125bdfb6d93`, identity SHA
  `9e98428eb96629c3b57234822500b70ff46c2d081bb72cc2b0eeb0eb974a1052`.
- Read-only audit: 35/35 artifact bytes/hashes/Parquet rows exact, directory set exact,
  source/signal/target/execution checks 122/122 true, parent copies exact и все шесть
  ledger CAGR/Sharpe/MDD/annual-return replays exact.
- Baseline 1x primary: total `−10,7243%`, CAGR `−5,1096%`, Sharpe `−0,6464`, MDD
  `15,9385%`. Selected primary: total `−14,0346%`, CAGR `−6,7528%`, Sharpe `−0,4630`,
  MDD `26,9631%`; doubled CAGR `−7,0119%`; stress CAGR `−7,1594%`, Sharpe `−0,4958`,
  MDD `27,3717%`. Все ledgers complete, coverage 193/193, critical/unresolved 0.
- Primary segments: 2009 `−3,7877%`, 2010 `0,0000%`, 2011 `−10,6502%`; 0/3 positive.
  Stress rolling positive fraction `57,09%`, ни одно 252-window не достигло 20% CAGR;
  bootstrap joint 20%-CAGR/30%-MDD minimum `0,10%`, LOYO minimum CAGR `−13,5540%`.
- 2010 cash объясняется не имитацией нулевой доходности: strict 252-session signal не
  имел ни одной finite строки после сохранённых missing observations. Формулу нельзя
  повторять с shorter window/gap fill на этом уже открытом периоде.
- Verdict `UNSEEN_TEMPORAL_NO_GO_20`; supports 20%/50% false. V30/V31 family закрыта,
  V31 не повторять и не tune-ить; live trading запрещён.

## V30-D2: canonical development run complete

- V30 V1 был sealed/pushed commit `271c7db` до canonical attempt. Попытка остановилась
  до первого ledger и без output: 85/86 aggregated checks true, единственный false —
  корректный служебный факт `pre2012_outcomes_read_by_V30=False`, который ошибочно был
  включён в `all(checks)` как assertion. Strategy outcomes не вычислялись; pre-2012
  prices/returns/PnL не читались. V1 code/config не менять и не повторять.
- D2 config SHA
  `8b41f58a17d757b56f4e88a26515416e4e519d98cad915277e1fee18a20cc2ae`, wrapper SHA
  `20de599e5bdcace2fae4f8ea37f58cb53e5310609ec5720f2a1b42323ce6ed66`.
  Он pin-ит V1 bytes/failure и заменяет только non-assertion на positive proof
  `pre2012_outcomes_not_read_by_V30=True`. Signal, targets, risk, execution, costs,
  bootstrap seeds и gates наследуются byte-identical.
- D2 был sealed/pushed commit `aea34e4` до economic read. Canonical immutable output:
  `runs/v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a/`; metrics SHA
  `e5aeb7d1af12c861af3c81003d31bcc10cafed17665547b3f302255aed4ad054`, identity SHA
  `acc03e16e71d9209028589f92ceaf9a8954570549fde6e73cddcf51e78923448`.
- Independent read-only audit: artifact hashes/bytes/Parquet row counts 33/33 exact,
  checks 86/86 true, assessment 13/13 true, metrics identity exact. Primary CAGR
  `22,9090%`, Sharpe `1,121648`, MDD `27,78698%`; doubled `22,26594%/1,09846/27,88775%`;
  stress `21,41126%/1,063413/28,47069%`. Все ledgers complete, critical/unresolved 0.
- Четыре из пяти лет положительны, но 2014 дал `+75,4006%`, а stress rolling q05 CAGR
  `−15,930%`. Stress circular-block bootstrap q05 CAGR равен `2,922%/1,962%/0,249%`
  для блоков 5/21/63 дней. Verdict
  `DEVELOPMENT_CANDIDATE_READY_FOR_SEPARATE_PRE2012_SEAL`: development gate 20% пройден,
  50% нет; устойчивые 20% этим результатом не доказаны. V30-D2 не повторять и не
  подбирать по нему параметры. Последующий sealed V31/2008–2011 уже дал independent
  `UNSEEN_TEMPORAL_NO_GO_20`; V30 family закрыта.

## V30-V1: equal trend/carry/relative sleeves — sealed, failed before ledger/output

- Это development selection после полного просмотра V29/2012–2017, не independent
  validation. На момент V30 seal outcomes 2008–2011 не читались; позже их один раз
  открыл sealed V31 и получил NO-GO. Config SHA
  `2e191a82f1a6145667f640d565541de49e69e5bee6081b06764074344c43ce8a`, module SHA
  `b642afe2cd7b112a2f69c6854fcf47e28bd566c065dd39b7412a0ba04df3c9e7`.
- Target экономически отличен от V27/V29: arithmetic equal thirds из frozen V12
  time-series trend, same-close front/next carry sign и clipped cross-asset demeaned
  trend. Missing carry усыпляет только carry sleeve; missing trend оставляет asset flat.
  Macro cash governors и collateral credit не используются.
- После causal 1x covariance/turnover construction последний известный expected-vol
  восстанавливается к тем же 20% формулой `min(2, 0.20 / expected_vol)`. Mapping на
  factual next open выполняется до multiplier; roll получает последний известный scale.
- Open development diagnostics до protocol freeze сравнили ограниченный набор trend,
  carry, relative, breakout, consensus и volatile-corridor targets. Corridor ухудшил
  CAGR/Sharpe и закрыт. Выбранный bounded composite предварительно дал all-cost CAGR
  примерно `21,4–22,9%`, Sharpe `1,06–1,12`, MDD `27,8–28,5%`, но это не canonical.
- Preflight: 62 source, 14 signal и 6 target checks true; 4 550 finite component rows,
  254 weekly + 50 roll decisions, 1 216 mapped rows, mean multiplier 1,496x. Следующий
  V1 attempt был fail-closed на aggregation polarity; canonical economics переносится
  только в D2, V1 не повторять.

## MOEX-PRE2012-DERIVED-D3: canonical outcome-free source complete

- D2 был sealed/pushed commit `fa61763` до загрузки market rows. Его отдельный immutable
  output создан, но rejected: exact audit дал 25/27 true. `active_contract_map`,
  `contract_observations` и `spec_proxy` совпали полностью; у `panel` значения совпали,
  но два boolean столбца прочитались из Parquet как bool вместо исходного object.
  `audit.json` сохранил те же month codes как JSON lists вместо Python tuples.
- Diagnosis зафиксировал zero market-value mismatches, 3 124 panel/active rows, 6 627
  contract/spec rows, successful source-only rolls SI/RI/BR/MIX = 11/11/36/0 и zero
  unresolved roll/exit. D2 manifest SHA
  `da7c922ddd429fcd6b5c3d1070329574c742207a56617a7592020169dde88405`; D2 не
  перезаписывать и не принимать как canonical.
- D3 config SHA
  `93b1d3fbe5c9f909dd204f140c0e902d63647173bdf12f22fb2638d3a926cfe7`, module SHA
  `438f2dd5a5c99d5738e2b43822bb2539275e0bd348f30f681d912ed56c821c39`.
  Он pin-ит failed D2 bytes/diagnosis, приводит только два nonmissing flags к bool и
  month-code containers к JSON-native lists. Значения, prices, calendar, contract
  admission, availability, roll и spec rules не меняются.
- Seal commit `afaa278` был pushed до первого D3 build. Canonical separate immutable
  output:
  `data/processed/futures_pre2012/moex-core3-late-mix-causal-derived-2008-2011-v3/`.
  Manifest SHA `ff9b277166c4c50f8f95bc9a6b41b1c4678911bf4038425063dfc7bcd9c3923d`,
  payload SHA `ac087463...`, panel SHA `390b1c8b...`; active/contract/spec SHAs остались
  D2-identical. Build и отдельный replay дали 27/27 true. Дополнительное строгое
  сравнение подтвердило values+dtypes exact для всех четырёх frames; оба normalized
  flags сохранены и rebuilt как bool.
- Canonical counts: 781 master sessions, 3 124 panel/active rows, 6 627 contract/spec
  rows, successful rolls SI/RI/BR/MIX = 11/11/36/0, zero unresolved roll/exit.
  Returns/targets/PnL не вычислялись и остаются запрещены до отдельного strategy seal.

## MOEX-PRE2012-DERIVED-D2: boundary correction built, audit rejected

- D1 был sealed/pushed commit `45e55af`, но остановился до `daily.parquet` load и без
  output: source acquisition manifest правильно хранит `protected_from=2026-01-01`,
  тогда как D1 ошибочно сравнивал его с derived market ceiling `2012-01-01`. Только
  manifest metadata было прочитано; market values/outcomes не наблюдались.
- D2 config SHA
  `f928e58b0bacce4d80c7d77fab7b399b3aba4650034bd3d518f45ef2f5c92c83`, module SHA
  `2e01c3fcbfb2c9ff7043bc68f4f2345918600c6f9d0d17866fae777fc34983fe`.
  Он pin-ит D1 config/module и меняет только boundary interpretation.
- Source request bounds остаются `2008-01-01..2011-12-31`, acquisition protection —
  `2026-01-01`; отдельно каждая loaded market row обязана быть `<2012-01-01`.
  Contract cycles/counts, 781-session master, 727 MIX masks, roll/spec rules и zero
  unresolved gates byte-identical D1.
- Separate immutable rejected output:
  `data/processed/futures_pre2012/moex-core3-late-mix-causal-derived-2008-2011-v2/`.
  Seal commit `fa61763` был pushed до первого daily load. Build завершил source-only
  transformation, но final audit остановил acceptance на двух representation checks;
  artifact не повторять и не перезаписывать.

## MOEX-PRE2012-DERIVED-D1: sealed, failed before daily load/output

- Source-only config SHA
  `8f5737bc44b21a8777b55de037da7ad7cf925f652e3b715115e46d4765b1f959`, module SHA
  `d0c22df731b64c32211f1b92b771ff1d61b7892f31ff6385856ea8649f9c0e33`.
  Он pin-ит source manifest/daily/raw и panel/roll/spec/io implementations; до первого
  derived build читались только contract IDs, dates и validity flags, не price values.
- Official-cycle admission заранее оставляет SI/RI/BR/MIX = 16/16/38/1 contracts,
  daily rows = 3 397/2 390/2 170/54; исключаются только 10 nonquarterly SI serials.
- Master calendar — factual intersection SI/RI/BR: exact 781 sessions
  `2008-10-08..2011-12-15`. MIX имеет exact 54 source sessions
  `2011-09-30..2011-12-15`; первые 727 master sessions публикуются как explicit
  `asset_not_yet_available`, flat/masked, market fields missing. Backfill запрещён.
- Две parent inert rows лежат до master start и не создают gap/return bridge. Roll
  defaults byte-identical existing panel; publication требует zero unresolved roll/exit,
  rectangular 3 124-row panel/active map и отсутствие outcome columns.
- D1 output path (не создан):
  `data/processed/futures_pre2012/moex-core3-late-mix-causal-derived-2008-2011-v1/`.
  Seal `45e55af` был pushed. Build прочитал только manifest и fail-closed на ошибочной
  boundary equality; canonical manifest отсутствует, D1 не повторять.

## MOEX-PRE2012-SOURCE-V2: canonical source complete, replay exact

- V1 был sealed/pushed commit `49467bc` до первого daily response, но collection
  остановилась без output на `RIM9_2009/2008-09-12`. В строке присутствовали identity,
  но все OHLC/WAP/settlement/activity/OI были NULL. Ни одно market value не печаталось,
  returns/targets/PnL не вычислялись; V1 bytes и его каталог не изменяются.
- V2 config SHA
  `74847dd3c2ba89fcbc436301df4a7df29759877d53330b37ec94b7236da65cb3`, module SHA
  `acc547f57d42466f1acd1ddc43cb823573c37b09e06f6f2acc7f6769eb150bd2`. Он pin-ит
  V1 config/module и reusable parent module, сохраняя exact 81 contracts, период,
  endpoints, request order, cursor и raw payload byte-identical.
- Единственная correction: строка с шестью NULL price fields и NULL/zero
  VALUE/VOLUME/NUMTRADES сохраняется с identity/missing values и всеми market/trade/
  execution flags false. Она не является баром, fill или zero return. Все остальные
  строки проходят исходный byte-pinned parser.
- Seal commit `617ce72` был pushed до V2 collection. Canonical immutable path:
  `data/processed/futures_pre2012/moex-core3-mix-daily-current-vintage-2008-2011-v2/`.
  Manifest file SHA `e06fd978d7382a36be760e5d4bbee517a5e7a4d28c7fae8acf0112de4f43ff0b`,
  payload SHA `521ac82b...`, daily SHA `1c5eee45...`, coverage SHA `9d46db02...`, raw
  SHA `e8a97876...`.
- Собрано 8 381 daily rows по 81 contracts и 224 raw requests; source coverage
  `2008-01-09..2011-12-16`, maximum per-contract calendar gap 12 дней. By asset rows:
  BR 2 170, MIX 54, RI 2 390, SI 3 767.
- Exact total inert rows заранее не выбирался и фактически равен двум:
  `RIM9_2009/2008-09-12` и `SiU9_2009/2008-09-12`. Обе строки missing/nonexecuting;
  RI/SI inert counts 1/1, BR/MIX 0/0.
- Встроенный и отдельный offline replay потребили все raw records и дали 41/41 true:
  manifest/config/implementation/raw identities, source checks и все шесть Parquet
  tables exact. Returns/PnL не вычислялись. Collection не повторять; следующий шаг —
  отдельный causal derived-source seal без outcome columns.

## MOEX-PRE2012-SOURCE-V1: sealed, collection failed without output

- Metadata-only audit без daily market endpoint нашёл exact 81 expired contracts
  2008–2011: BR 38, MIX 1, RI 16, SI 26. FRSTTRADE/LSTDELDATE и ровно один overlapping
  RFUD segment есть у 81/81; LSTTRADE отсутствует у всех и не восстанавливается из цен.
- Source-only config SHA
  `92c7f3249e4bd0363a65af78fccd3871929ea04e2ec7d187c8b6522a8fc71997`, wrapper SHA
  `55965d9cb068a23c4d9310c91e03e95e7f65dedeec4ec06d247d3958613dfb4e`, reused parent
  SHA `7dd25e01d28303988190123fc57c70fd3d93d938c207d219a03e837484833fc7`.
  Код/config должны быть pushed до первого daily response.
- Wrapper pin-ит exact names/months, RFUD, closed daily schema, cursor pagination,
  `2008-01-01..2011-12-31`, protected boundary, immutable external output и обе code
  identities. Он сохраняет exact raw responses и требует, чтобы replay заново построил
  все шесть Parquet tables; outcome-like columns запрещены.
- V1 external path (не создан):
  `data/processed/futures_pre2012/moex-core3-mix-daily-current-vintage-2008-2011-v1/`.
  Canonical manifest отсутствует. Первый run прочитал часть sealed daily source, но
  напечатал только parser error и source identity; ни цены, ни returns/PnL не раскрыты.
- Следующий collection разрешён только под V2. После source/replay нужен отдельный
  derived-source seal, затем новая strategy family должна разрабатываться только на уже
  открытом 2012–2017. 2008–2011 outcomes остаются закрыты до отдельного pre-outcome push.

## MOEX-MULTILEG-SOURCE-V1: parser sealed, licensed bytes pending

- Source-only config SHA
  `464cce7af683cea260d658dfc20d92c2b8ddf650886c7adbc366b929f2d9c462`, module SHA
  `5e64ba6a305d74ff37bcb67a7d4500057f65a066c0ae390ba693747d116a26df`.
  Он зафиксирован до чтения первого licensed/member archive и не содержит network
  downloader, return, target, signal или PnL engine.
- До открытия bytes обязателен ровно один package `YYYYMMDD` в относительном пути.
  Дата вне `2021-01-01..2025-12-31`, особенно `>=2026-01-01`, reject-ится до CSV/ZIP
  open. Undated flat files и 7z без предварительной распаковки в dated directory также
  reject-ятся.
- Market-wide `multileg_deal`/`multileg_dict`, participant `multilegf04`/
  `multilegordlog` и linked `f04.ID_MULT` разделены по пяти closed schemas. Participant
  users/codes/comments не публикуются; отрицательные spread prices и missing values
  сохраняются. Order log участника явно не называется full-market queue.
- Full canonical build требует совместное core coverage всего 2021–2025, maximum gap
  14 дней, exact две разные signed legs `−1/+1`, unique deal IDs, same-day dictionary и
  две linked technical legs на participant fill, если member reports присутствуют.
  Pilot month допускается только к preflight без canonical и без economic verdict.
- Synthetic ZIP проверил все пять parsers, privacy/temporal gates, atomic build и exact
  replay. Реальных licensed bytes пока нет, intended output
  `data/processed/info_radar/moex-multileg-execution-2021-2025-v1/` не создан. Следующий
  внешний шаг описан в [MOEX_MULTILEG_DATA.md](MOEX_MULTILEG_DATA.md).

## CALENDAR-SPREAD-EV4: completed post-selection cost-aware test, NO_GO

- Config SHA `b7ddc0ac977c61d7c4547ce978182d2a178422ee694ce1178d4d2d5c174677b9`,
  module SHA `173518088542f64658d3e734720504b2cb68eef2d1831fc6315a27fb070e5e2d`.
  Parent V3 config/code/manifest/metrics byte-pinned. Candidate
  `cross_sectional_extremes` выбран после V3, поэтому V4 — post-selection adaptive,
  а не новая confirmation.
- Все десять rules остаются в отчёте, но каждый preplanned interval проходит один
  новый fixed admission. Expected remaining points =
  `max(|entry score| − strategy exit_abs, 0) * entry_scale`; cash proxy умножается на
  `min(near, far)` causal sizing point value.
- Stress round-trip заранее равен двум сторонам, каждая из которых включает 4 ticks на
  обе ноги и 2x conservative fee обеих ног. Entry допускается только при opportunity /
  stress round-trip `>=2,0`; missing/nonpositive dependency reject. Rejected interval
  не retry-ится и не ищет другой threshold.
- Signal/MLP/thresholds/exits/holding, split, equal quantities, 1% two-leg capacity,
  1,6x gross, 2x margin buffer, actual three cost ledgers и numeric gates не меняются.
  Успех мог дать лишь `ADAPTIVE_LEAD_REQUIRES_NEW_UNSEEN_MULTILEG_VALIDATION`; live
  остаётся запрещён.
- Seal commit `a6929ce` был pushed до outcomes. Canonical path
  `runs/calendar_spread_economic_2021_2025_v4/`; manifest SHA
  `e9b4e3016a65fa96c868fafa5cd36688135d07b7f226384635453a913612fefc`, metrics SHA
  `0b683ce0e3620f8d7ead42457b0a5e73a88571c75ba633935767354e577c54a9`. Получено
  1 029 plans и 3 734 causal MLP predictions; initial audit и отдельный replay,
  включая exact cost-hurdle checks, полностью true.
- Selected primary `cross_sectional_extremes` сохранил 38 evaluation trades. Primary
  2024–2025: total `+0,3095%`, CAGR `+0,1528%`, Sharpe `0,3416`, MDD `0,4463%`,
  2024 `+0,2014%`, 2025 `+0,1078%`, profit factor `1,2857`. При doubled costs total
  лишь `+0,0675%` и один положительный год; stress total `−0,1664%`, CAGR
  `−0,0823%`, Sharpe `−0,1776`, тоже только один положительный год.
- Development 2021–2023 отрицателен: primary total `−1,2291%`, Sharpe `−0,8059`,
  0/3 positive years; full 2021–2025 total `−0,9234%`, stress `−1,7505%`.
  Execution complete во всех cost scenarios: 64 completed trades, 22 zero-capacity
  skips, 9 exit retries, 0 terminal/missing entry dates. Promotion прошёл MDD, trade
  count и оба evaluation years, но провалил CAGR, Sharpe и positive stress return.
- Verdict `NO_GO`: cost-aware admission не превратил слабый gross edge в устойчивую
  доходность. Порог hurdle, leverage, asset/year filters или exits по этим же outcomes
  больше не подбирать. Следующий допустимый шаг — новый exact multileg trade/order source
  либо действительно unseen период, а не V5 threshold tweak.

## CALENDAR-SPREAD-EV3: completed adaptive test, NO_GO

- V3 config SHA `c38a7356385baeb75be7f0f206f757d49ff192284239630aed1aee72a79f8f57`,
  implementation SHA `fb9b4e1556ee848fa93f1173cf70e1ab92ac9b4cc628ee0956f793dcc6383f86`.
  Parent V2 config/implementation/manifest/metrics byte-pinned; его no-exposure result
  уже известен, поэтому V3 явно post-outcome adaptive и не independent confirmation.
- Единственная связанная source-semantics correction: same-spread signal строится по
  factual reported `Last`, а closing EOD quote width сохраняется как MLP feature, но не
  допускает/запрещает next-open entry. D1 уже требует reported activity; две locked
  quote rows всё ещё запрещены для новых позиций.
- Реальная liquidity admission не ослаблена: equal-quantity pair, первый следующий
  common factual outright open, минимум 1% lagged-volume capacity обеих ног, buffered
  margin 2x и full-exit retries неизменны. Все 10 thresholds/horizons/directions,
  monthly MLP, split, 1,6x gross, costs и promotion gates byte-identical V1/V2.
- Canonical path `runs/calendar_spread_economic_2021_2025_v3/`; seal `58ba05c` был
  pushed до V3 outcomes. Manifest SHA `a7de7e04333eb24a16f4c6862503d9a20a09095abc547305476326c2bab91adc`,
  metrics SHA `665e13cb...`; initial 37/37 и повторный 29/29 audits true.
- Source correction восстановила экспозицию: 1 666 plans, 3 734 MLP predictions;
  strategy plan counts 86/160/287/64/66/172/167/166/114/384. Все primary-strategy
  scenarios execution-complete, missing entry dates и terminal positions 0.
- Predeclared primary `volatile_corridor_far_stop` провалился: evaluation 2024–2025
  total `−0,2160%`, CAGR `−0,1068%`, Sharpe `−0,3495`, MDD `0,3680%`, 17 trades,
  оба года отрицательны; stress total `−0,4818%`. Full total `−2,6506%`.
- Exploratory best-of-ten — `cross_sectional_extremes`: evaluation total `+0,2074%`,
  CAGR `+0,1024%`, Sharpe `0,2281`, MDD `0,4465%`, 38 trades и оба года positive;
  однако stress `−0,3174%`, development `−1,1892%`, full `−0,9843%`. Второй
  `slow_corridor_40`: evaluation `+0,1514%`, stress `−0,1077%`, development `−2,2133%`.
  Ни один вариант не прошёл costs/stability gates; verdict `NO_GO`.
- Post-run decomposition: cross-sectional evaluation gross `+5 448,55 ₽`, primary
  trade costs `2 391,65 ₽`, net completed-trade sum `+3 056,90 ₽`; slow corridor gross
  `+2 494,52 ₽`, costs `1 296,00 ₽`. Edge мал и нестабилен: у cross-sectional SI
  положителен, RI в 2025 дал `−3 529,03 ₽` net. Следующий тест может быть только явно
  adaptive cost-aware admission с новым seal; увеличение плеча не исправляет economics.

## CALENDAR-SPREAD-EV2: completed, NO_GO_NO_EVALUATION_EXPOSURE

- V1 seal commit `ee7e311` был pushed до первого outcome computation. Первый run
  остановился до создания canonical или temporary output: у одной strategy не было
  completed trades, поэтому `DataFrame.get("net_pnl")` вернул scalar NaN и metrics
  reporter завершился с `AttributeError`. В stdout не было ни metric/return, ни market
  value — только exception и stack trace. V1 bytes не изменяются и run не повторяется.
- V2 config SHA `e986530265ab6c87c39fbb6315dcb39d1eb80b971ff58d8614bff5966bb4a1eb`,
  correction module SHA `9d96dfe361f519fe5311751c7b0c3237db802e54a18e9bc6097e8bb61e29468e`.
  Единственная delta — добавить typed empty `status`/`net_pnl` Series перед parent
  metric function. При непустых trades функция exact parent-identical; hypotheses,
  MLP, signals, thresholds, splits, ledger, costs и gates наследуются byte-identical.
- V2 output отдельный и immutable:
  `runs/calendar_spread_economic_2021_2025_v2/`. Новый seal должен быть pushed до
  resumed run; seal commit `e1a519d` был pushed. Canonical manifest SHA
  `facc159f6c8aa063d2cdd584de414f3cf28970c7c6fc8e63b231ded39cb9ed88`, metrics SHA
  `c43a3f0b...`; initial audit 37/37 true, отдельный artifact audit 29/29 true.
- Получено 3 734 causal MLP predictions, но всего 13 plans за всю историю и ни одного
  entry decision в 2023–2025. Поэтому у всех десяти evaluation 2024–2025 return/CAGR/
  Sharpe/MDD и trades равны нулю; primary gate закономерно `NO_GO`. Это отсутствие
  экспозиции, а не доказательство нулевого или отрицательного edge.
- Development 2021–2022 слишком мал для вывода: primary corridor одна сделка и
  `+0,3602%`; exploratory slow corridor две сделки `+0,7793%`; fast одна `+0,4028%`;
  MLP три `−0,2584%`, breakout одна `−0,5200%`, momentum одна filled `−0,6220%`.
  Все primary strategy scenarios execution-complete, но minimum trades и year gates
  не пройдены. V2 не является independent confirmation и не разрешает live.
- Post-run signal-only diagnosis: abs(z20)>=1,5 встречался 112/181/117/139/135 раз по
  2021–2025, но `quote_width <= 2*prior spread sigma` прошёл лишь 16/19/0/0/0 строк.
  Именно non-execution EOD closing-width filter уничтожил 2023–2025 exposure. Следующая
  версия может быть только явно adaptive source-semantics correction: signal от factual
  reported Last и без использования stale closing width как proxy будущего leg-open fill;
  thresholds, ledger, costs и gates менять нельзя.

## CALENDAR-SPREAD-EV1: FAILED_CLOSED before output

- Config SHA `e74dab97ab65a28d4fc16f0061952545606ccccd1df7a8c677a8c8bc2af2b3bc`,
  implementation SHA `f8d0108e87c0c1eed5e841aab35e1bc2f59485e67ce3bd18aed9920c16213282`.
  Seal подготовлен после immutable D1 manifest `b5e15c2e...`, но до первого spread
  change, return, target, strategy equity или PnL. Реальные outcomes ещё не читались.
- Семейство ровно из 10 заранее заданных гипотез: четыре corridor mean-reversion
  варианта, volatile breakout, 5-observation momentum, convergence-to-zero,
  cross-asset residual fade, cross-sectional extremes и expanding causal MLP по всем
  четырём активам. Primary заранее задан как `volatile_corridor_far_stop`; лучший из
  десяти всегда exploratory и не может быть объявлен подтверждённым.
- MLP предсказывает нормированное изменение midpoint через пять factual observations,
  refit только раз в месяц. В train допускаются лишь метки с target-end строго раньше
  refit/prediction date; missing cross-asset fields получают training-median и indicators,
  но никогда zero. Architecture `[16,8]`, seed 1729, search отсутствует.
- Decision после complete EOD archive, entry/exit не раньше следующего factual common
  open обеих outright legs. Buy spread = long far + short near, количества строго равны;
  PnL каждой ноги использует собственный session point value. Entry clip по минимуму
  1% lagged-volume capacity обеих ног; exit требует полной pair capacity и causally
  retry-ится. Gross cap 1,6x, pair target 0,4x, buffered margin 2x.
- Costs фиксированы до outcome: primary 1 tick/leg + 1x fee, doubled 2 ticks + 2x fee,
  stress 4 ticks + 2x fee. Development `2021–2023`; primary internal evaluation
  `2024–2025`. Gate primary: CAGR >=10%, Sharpe >=1, MDD <=15%, 2/2 positive years,
  stress positive, >=20 completed trades и complete execution. Это не independent
  confirmation и никогда не разрешает live.
- Seal commit `ee7e311` был pushed, затем V1 остановился на пустой trade-metric schema
  до любого output или напечатанного результата. V1 immutable; operational correction
  вынесена только в V2.

## CALENDAR-SPREAD-DERIVED-D1: completed source-only panel, no PnL

- Source-derived config SHA
  `657fd42b472797028f5b0194c7b159ac1538ddab5caea8f9c416f0a403e34cd0`, implementation
  SHA `d04f7d8f23ec5fce45d7b8879d41c130201e93695bceb3ca8891e6bd465c6f11`. Protocol
  был pushed seal commit `35ab387` до первого derived build и до любого spread change,
  return, target, signal, equity или PnL.
- Inputs byte-pinned: calendar source V3 manifest SHA `94d5fab4...`; causal spec proxy
  manifest SHA `b1cada60...`, parquet SHA `8494235f...`, 66 052 rows, только strictly
  prior sizing observation. Все historical exchange/broker exact flags false: proxy
  остаётся приближённым и не разрешает live admission.
- Structural mask задан до outcomes: regular-adjacent catalog row, near expiration
  совпадает с spread last-trade date, reported activity, row внутри official series,
  complete uncrossed Bid/Ask и неотрицательный days-to-near. Active row — уникальный
  minimum days-to-near по asset/date; tie — reject. Last outside reported range не
  фильтруется, locked/zero quote сохраняется и flag-ится, missing не заполняется.
- Source-only preflight counts sealed: clean spreads SI/RI/BR/MIX `16/13/51/18`;
  candidate rows `1 986/1 994/3 096/1 205` (8 281); active rows
  `1 129/918/1 200/1 119` (4 366); ties 0; zero/locked 2; strict-positive width 4 364;
  обе leg specs usable и causally prior 4 366/4 366; equal point value лишь 1 218.
- Canonical immutable path:
  `data/processed/info_radar/moex-calendar-spread-derived-2021-2025-v1/`. Этот protocol
  вычисляет только eligibility, quote geometry и leg-specific sizing metadata. Для
  первого изменения цены и PnL обязателен новый отдельный economic config+SHA.
- Build и отдельный `--audit-only` оба дали 29/29 true. Manifest SHA
  `b5e15c2ef846ab051db6d78c4074db2e03f56faa9aac71ae86bcf3d82034b234`;
  candidates SHA `58d1b1bc...`, active SHA `fc9257ad...`, coverage SHA `04f34029...`,
  audit SHA `484c2707...`. Closed schemas, bytes/rows/SHA, exact logical rebuild,
  unique active identity, protected boundary и causal spec joins подтверждены.
- Derived verdict `COMPLETE_SOURCE_ONLY`. Никакой доходности ещё не просмотрено; период
  `2021-01-04..2025-12-18` остаётся development/current-vintage, EOD quotes не являются
  order-time execution evidence, а все spec values approximate.

## CALENDAR-SPREAD-SOURCE-V3: completed source bundle, no PnL

- V2 seal `7c8d45a` был pushed до resumed bulk history. Blank-ASSETCODE correction прошла,
  затем parent collector остановился без output на единственном empty ISS interval:
  `BR:BRF1BRG1:2020-12-31:2021-02-01`. Exact official metadata: series starts
  `2020-12-14`, spread last trade `2021-01-04`, RFUD board ends `2020-12-30`; поэтому
  sealed lower bound даёт `from=2021-01-01 > till=2020-12-30`.
- Metadata-only scan 110/110 boards подтвердил exact empty count 1. Public archive code
  `BR-1.21-2.21` остаётся отдельным официальным источником и не должен теряться из-за
  отсутствия admissible ISS interval.
- V3 config SHA
  `3d89c51fe674f3b55282aba808ad6f0336cae502956681203f02b0218022f19c`, implementation
  SHA `3f344899...`. Единственная delta: для exact pinned identity сохранить official
  board dates, сделать 0 ISS requests/rows и обязательно продолжить обычный public archive
  collection. Любой другой empty interval — fail-closed. V2 parser и все V1 gates
  наследуются byte-identical; output отдельный `-v3`.
- Source V1/V2/V3 + encoding tests 23/23, scoped Ruff clean. Seal `ed16ca3` был pushed
  до collection. Canonical external path:
  `data/processed/info_radar/moex-calendar-spreads-current-vintage-2021-2025-v3/`;
  manifest SHA `94d5fab4b799ac9a73b359c7350df7ccd30572e6dba8b9ae8cf5d41f5080ee0b`.
- Все 47 audit checks true в collection process и в отдельном `--audit-only`: artifact
  bytes/SHA/rows, closed schemas, identities, dates, availability, series/boards, ISS
  pages, exact HTML/CSV bodies и archive-code lists полностью replayed.
- Artifacts: catalog 110 rows SHA `db92ebe2...`; ISS 9 997 SHA `a14cd7fa...`; public
  archive 10 157 SHA `be29b06d...`; coverage 110 SHA `307018a5...`; raw 487 responses,
  5 400 633 bytes, SHA `ccaba170...`.
- Public archive содержит 8 887 reported-trade rows и покрывает 110/110 spreads; ISS
  activity fields равны нулю при 9 997 settlement rows. Activity есть у 109 spreads;
  единственный zero-activity `RIH2RIU2 / RTS-3.22-9.22` — сохранённый non-adjacent
  exchange exception. Exact empty-ISS `BRF1BRG1` имеет одну archive/trade row.
- Source disagreements сохранены, а не скрыты: overlap 9 968; ISS-only 29;
  archive-only/outside-ISS 189; outside-series 85; last outside reported range 451;
  crossed quote 0. Archive range `2021-01-04..2025-12-18`, protected rows 0.
- Source verdict `COMPLETE_SOURCE_ONLY`. Ни returns, targets, signals, equity, PnL, ни
  стратегия не вычислялись. Следующий допустимый шаг — отдельный sealed derived-source
  panel, затем новый economic protocol; этот bundle immutable и не перезапускается.

## CALENDAR-SPREAD-SOURCE-V2: FAILED_CLOSED, no output

- V1 seal commit `293e54e` был pushed до bulk history. Первый collection остановился
  fail-closed без canonical output на `SiZ5SiH6`: expected `Si`, official page содержал
  только классы `NULL` и empty string в `ASSETCODE`. Market values не печатались и не
  сохранялись, returns/targets/PnL не вычислялись; temporary output удалён.
- V1 config SHA `72687539...` и module SHA `db217488...` остаются byte-identical.
  Отдельный V2 config SHA
  `be770102469677a3d5b88c79e976799298072aa77c45c405b31387a9fb809173`, correction
  module SHA `d0c865a4...`, новый immutable output path оканчивается на `-v2`.
- Единственная parser delta: blank/whitespace `ASSETCODE` копируется в missing перед
  parent parser, после чего действует прежний catalog fill. Exact raw JSON не мутируется;
  NULL policy не меняется, любой непустой mismatched code всё ещё reject. Discovery,
  counts, archive mapping, cursors, dates, WebForms/CSV, schemas и protected boundary
  полностью наследуются V1.
- Source tests V1+V2 18/18, encoding 2/2, scoped Ruff clean. Seal `7c8d45a` был pushed;
  resumed collection прошёл parser correction, затем остановился на exact empty ISS
  interval без output. V2 не менять и не повторять; operational correction только V3.

## CALENDAR-SPREAD-SOURCE-V1: FAILED_CLOSED, no output

- Новая target family принципиально отделена от V12/V27: exchange-listed same-root
  calendar-spread carry/convergence должен уменьшать общий directional beta и допускает
  атомарное двухстороннее исполнение через отдельный биржевой инструмент. Источник сам
  по себе не считается доказательством прибыли.
- Source-only config SHA
  `7268753933efb4c9633f3e314ebc1d67cf4a7d63e4290e0f3a0142bacce8048e`, implementation
  SHA `db217488...`; period `2021-01-01..2025-12-31`, protected from `2026-01-01`.
  Returns, targets, signals, equity и PnL запрещены схемой и именами колонок.
- Metadata preflight обнаружил 110 dated RFUD spreads: SI/RI/BR/MIX = 16/15/59/20;
  101 regular-adjacent и 103 exact near-expiry/date matches. Два metadata rows без дат
  (`SiZ2SiH3`, `MXU2MXZ2`) сохраняются как exact excluded set; exchange exceptions не
  исправляются догадками.
- Archive code строится только из official names двух outright legs и проверяется через
  official `ArchiveSpreads.asmx/GetSpreadList`: 110/110 exact matches, включая семь
  нестандартных BR expiration-date cases, без manual aliases.
- Bounded `MXZ4MXH5` probe показал дефект одного ISS слоя: шесть ordinary history rows,
  но ноль reported activity. Public WebForms CSV даёт 71 unique dates
  `2024-09-12..2024-12-19` и labels Last/Bid/Ask/High/Low/Amount/Volume/Trades.
- Collector поэтому публикует два несмешанных artifacts: `iss_daily.parquet` для
  settlement/OI и `public_archive_daily.parquet` для archive labels. Exact GET HTML и
  Windows-1251 CSV bodies сохраняются в raw gzip; даты public archive вне ISS board/
  series interval не отбрасываются молча, а flag-ятся. Любая CSV date `>=2026-01-01`
  останавливает collection до публикации output.
- Целевые tests 12/12, encoding 2/2, scoped Ruff clean. Полный baseline: 844 passed,
  7 skipped и ровно две известные legacy V8 anti-junction failures из-за внешнего data
  junction; repo-wide Ruff также имеет прежние несвязанные V8/V9 нарушения. Следующий
  V1 seal commit `293e54e` был pushed до bulk history. Первый collection затем остановился
  без output на blank `ASSETCODE`; V1 не менять и не повторять, correction только в V2.
  Economic protocol появится только после source manifest и будет отдельным SHA.

## V29: post-V28 risk-first roll-capacity correction — FAIL, execution fixed

- Config SHA `d92f8cf2...`, implementation SHA `ea5aa37f...`; V29 создан только после
  наблюдения execution failure V28, поэтому это post-V28 adaptive correction, а не
  независимый holdout и не повторная unseen validation.
- Parent неизменяем: V28 config SHA `4f9e6663...`, canonical metrics SHA `73b614b8...`.
  Seal дословно фиксирует 5 129 critical failures, 1 251 rejected legs и пять
  capacity-cancelled rolls; V28 не исправляется и не перезаписывается.
- Меняется ровно одно правило admission при roll. Если factual open и lagged volume
  доказывают полный выход из старого контракта в неизменном лимите 1%, old leg должен
  быть закрыт. New leg независимо clip-ится к собственному 1% capacity или превращается
  в cash. Если полный old exit недоказуем, позиция сохраняется и execution остаётся
  invalid; synthetic liquidity запрещена.
- Signal, V25/V27 governors, exact 2x, RUONIA no-credit policy, margin/gross limits,
  costs, период и gates byte-identical по смыслу V28. Ни один threshold или market
  outcome V29 до seal не читался.
- Synthetic и связанные tests: `20 passed`; encoding/V29 slice: `8 passed`; Ruff и
  py_compile clean. Расширенный futures baseline: `832 passed, 7 skipped`, плюс две
  известные legacy V8 ошибки anti-junction guard, не затрагивающие V29.
- Seal commit `478a246` был pushed до первого V29 outcome. Canonical immutable run:
  `runs/v29_risk_first_roll_20260901T085436Z_d92f8cf2/`; metrics SHA
  `1c0e2dd79ce4ece79271c1e27e5919bcf30e684384ec8c972e88fb2b706bbd0c`, identity SHA
  `ca97579d2472e8463a758c007916eac06e08205d5b97a900c2636684d4dfc4d5`.
- Execution correction сработала: 639/639 nonzero targets covered, primary 527 filled
  legs, 15 capacity clips, `0` cancelled rolls, rejected legs, critical failures и
  unresolved. Проблемный roll `2014-05-12` factual закрыл 14 BRK4 и открыл только один
  BRM4; `2014-05-19` позиция причинно расширилась до 25 после появления capacity.
- Экономика цель не подтвердила. Primary combined total return `+24,8749%`, CAGR
  `4,6133%`, Sharpe `0,3191`, MDD `−47,3846%`; doubled/stress CAGR
  `3,9907%/3,7117%`, stress MDD `−48,6822%`. Costs primary/stress
  `44 774,83/120 908,94 RUB`.
- По годам primary: 2013 `−2,8109%`, 2014 `+90,9463%`, 2015 `−17,0900%`,
  2016 `−1,0636%`, 2017 `−17,9680%`. Положителен только 1/5 лет; worst year,
  Sharpe, MDD и all-scenario CAGR gates провалены. Ни 20%, ни 50% не поддерживаются.
- Artifact audit 26/26, checks 139/139. Verdict `FAIL_POST_V28_20`; это полезное
  исправление ledger, но не стабильный edge. V29 не перезапускать и не подбирать на
  2013–2017 signal/governor/leverage/capacity. Live trading запрещён.

## V28: frozen V27 economics on unseen 2013–2017 — FAIL/INVALID

- Config SHA `4f9e6663...`, implementation SHA `b9c290f6...`; это первое использование
  D3 prices/returns в strategy experiment. До seal прочитаны только hashes, schemas,
  calendars и external macro states, но не `open/close/settle`, returns или PnL.
- Период `2012-01-03..2012-12-31` — warm-up frozen V12, validation
  `2013-01-01..2017-12-01`. Signal, weekly schedule, V25 STLFSI4, V27 key-rate boundary,
  exact 2x, V26 `cancel_and_clip`, margin/capacity и три cost scenarios не меняются.
- Source-only counts запечатаны: 254 validation weeks = 147 pass + 70 STLFSI4 cash +
  37 missing/stale key-rate cash + 0 key-rate >=20% cash. Порог 20% в этом периоде
  не испытывается и не может считаться независимо подтверждённым.
- RUONIA publication timing доказан только для 56/1 224 accrual intervals (79 calendar
  days). Остальные 1 168 intervals сохраняют missing rate/timing и получают no credit,
  без zero-imputation.
- Отдельные gates требуют во всех cost scenarios CAGR `>=20%` или, для aspirational
  support, `>=50%`, MDD `<=30%`, primary Sharpe `>=0.80`, 4/5 positive years, worst year
  `>=-15%`, complete execution и no breaches. Даже pass остаётся research-only.
- Seal commit `4310bc3` был pushed до первого market outcome. Canonical run:
  `runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/`; metrics SHA `73b614b8...`,
  identity SHA `d7210826...`. Artifact audit 103/103, protocol/source checks 137/137.
- Primary combined return `−11,3985%`, CAGR `−2,4271%`, Sharpe `−0,2682`, MDD
  `−17,6953%`; doubled/stress CAGR `−2,5362%/−2,5950%`. Ни 20%, ни 50% не
  поддерживаются.
- Execution invalid: 5 capacity-cancelled atomic rolls оставили старые контракты;
  первый необратимый trap — BRK4 после отменённого roll `2014-05-12`, затем contract
  отсутствует с `2014-05-19`. Итог: 5 129 critical failures, 1 251 rejected legs,
  execution incomplete. Метрики не разрешены для promotion.
- Диагноз задаёт отдельную V29 hypothesis: на roll сначала полностью закрывать причинно
  исполнимый old leg, а new entry независимо clip-ить к 1% capacity или cash. V28 не
  менять и не перезапускать; V29 является post-V28 adaptive execution correction.

## PRE2018-MACRO-S3: preserve unknown RUONIA timing — completed

- Config SHA `ae575962...`, implementation SHA `5f2e4e09...`; наследует exact S2
  requests, bounds, transport, STLFSI4/key-rate parsers и меняет только обработку
  исторических RUONIA publication markers.
- Source-only S2 diagnosis до любого market outcome зафиксировал exact 1 478 rows:
  78 explicit publication dates и 1 400 unknown markers. S3 сохраняет для последних
  `publication_date/available_at = missing`, не выводит дату косвенно и запрещает
  credit collateral income при неизвестной доступности.
- Seal был pushed commit `1f9c343` до первого collection. Canonical immutable V3:
  `data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/`, manifest SHA
  `949bc7bf...`, raw archive SHA `8109f157...`.
- Coverage: STLFSI4 312/312 complete rows, RUONIA 1 478 rows (78 explicit/1 400 unknown
  timing), key rate 1 065 rows. Raw replay exact, все artifact hashes/rows/columns и
  protected availability прошли audit; outcome-free schema подтверждена.

## PRE2018-MACRO-S2: transport-only retry — failed parse, no output

- Config SHA `4ad7f034...`, implementation SHA `0cf46a51...`; наследует все S1 source
  and temporal rules и меняет единственное поле HTTP User-Agent на `curl/8.10.1`.
- Diagnostic после failed S1: research User-Agent timeout, curl User-Agent HTTP 200 and
  5 878 bytes на том же exact URL. Values/market outcomes не печатались, S1 output нет.
- Seal был pushed commit `5bec23f`. Все три responses были получены in-memory, но parser
  fail-closed остановился на неизвестном historical RUONIA publication marker; output и
  raw archive не опубликованы, market outcomes не читались. Parser correction вынесена
  в отдельный S3 seal.

## PRE2018-MACRO-S1: STLFSI4/RUONIA/key rate — failed transport, no output

- Config SHA `3daa3c40...`, implementation SHA `6fcb5318...`; source-only collector не
  имеет доступа к MOEX outcomes.
- Exact bounded requests `2012-01-01..2017-12-31`: official FRED STLFSI4 CSV, official
  CBR RUONIA HTML with publication dates, official CBR KeyRateXML SOAP.
- Conservative availability byte-identical по смыслу V25/V27/V15; rows available from
  2018 onward excluded, missing preserved, raw response bytes/hashes mandatory.
- Seal был pushed commit `9a5ff96` до request. FRED first request трижды завершился
  read timeout; CBR requests не выполнялись, output не опубликован. Correction не вносить
  в S1; отдельный S2 фиксирует transport-only change.

## MOEX-PRE2018-D3: gap-aware official-cycle source — completed

- Config SHA `d21dd650...`, implementation SHA `c04d8224...`; полностью наследует
  source/admission/roll/spec D2 и меняет только source quality gate до strategy outcome.
- Exact SI discontinuity: factual exit `2016-12-09`, flat sessions
  `2016-12-12..2016-12-15` и `2017-01-03`, causal re-entry `2017-01-04`. Gap return не
  создаётся, неизвестные наблюдения не становятся нулями.
- Seal был pushed commit `8877b75` до единственного build. Canonical manifest SHA
  `3ab20092...`; panel/active rows 5 916, contract/spec rows 28 797, calendar
  `2012-01-03..2017-12-01`.
- Required rolls SI/RI/BR/MIX = 22/23/70/23, все action counts exact, unresolved
  roll/exit = 0, spec lag strict, outcome columns absent. Следующий этап — macro sources
  и отдельный V28 seal; D3 не является strategy result или live evidence.

## MOEX-PRE2018-D2: official-cycle causal source — failed, no output

- Config SHA `7b60afbf...`, implementation SHA `7ce4b0a9...`; это source-only correction
  после D1 operational audit, не стратегия и не outcome selection.
- Structural admission до любого return/PnL: SI/RI/MIX только квартальные H/M/U/Z,
  BR — все месяцы. Exact expected contracts: 24/24/24/71; 12 serial SI contracts
  исключаются, 29 026 parent daily rows остаются.
- Seal был pushed commit `b858d54` до build. D2 правильно не опубликовал output: exact
  rolls BR/MIX/RI = 70/23/23, SI = 22 вместо predeclared 23.
- Source-only diagnosis без return/PnL доказал clean SI flat transition, а не unfilled
  execution: нет admitted 2017 contract до `2017-01-03`, поэтому exit `2016-12-09`,
  пять flat sessions и re-entry `2017-01-04`. Correction перенесена в отдельный D3 seal.

## MOEX-PRE2018-D1: causal panel/spec source — completed, unusable

- Protocol SHA `a633883d...` и implementation SHA `0c54c232...` были pushed commit
  `ce22460` до единственного immutable build. Manifest SHA `73ffe4c3...`, audit SHA
  `1f375f87...`; hashes, row counts, causality and maximum date all passed.
- D1 не фильтровал old SI serial-month contracts. Nearest-expiry planner получил только
  3 успешных SI roll, 9 `carry_unfilled_roll` и с `2012-10-17` ещё 1 276
  `carry_unfilled_exit`; operational verdict `OPERATIONALLY_UNUSABLE_SOURCE_DERIVATION`.
- Ни return, target, signal, strategy equity, ни PnL не рассчитывались. D1 нельзя
  использовать в V28 и нельзя перезаписывать; он остаётся failed source evidence.

## MOEX-PRE2018-S3: official core-four daily source — completed

- Source-only protocol:
  [`configs/moex_pre2018_core4_source_v3.yaml`](../configs/moex_pre2018_core4_source_v3.yaml)
- Config SHA-256:
  `0b86cda4d3bddf72831075a771c3e7f6568a0a4ba2f78c64b0254c980c902b08`.
- Implementation SHA-256:
  `7dd25e01d28303988190123fc57c70fd3d93d938c207d219a03e837484833fc7`.
- V1 config SHA `5e9e5454...` и implementation SHA `015f51b4...` были pushed commit
  `9802f12`. Первый collection attempt остановился на первой metadata-only finder page:
  uppercase `securities.columns` дал empty columns array при 100 rows. Contract detail
  и daily history не вызывались, price/economic outcomes не прочитаны, output отсутствует.
  V2 наследует V1 byte-sealed через parent SHA и исправляет только lowercase query names.
- V2 config SHA `40765db1...` затем exact-discovered 155/155 aliases, но остановился на
  metadata description до daily price endpoint: `LSTTRADE` отсутствует у части истории.
  Full metadata-only audit: FRSTTRADE/LSTDELDATE 155/155, one overlapping RFUD 155/155,
  LSTTRADE 91 present/64 missing. V3 сохраняет missing LSTTRADE и использует обязательный
  LSTDELDATE как expiration/request end; остальные inherited source rules неизменны.
- Metadata-only discovery зафиксировал exact 155 contracts expiring 2012–2017:
  BR 71, MIX 24, RTS/RI 24, Si 36. Expected month sets записаны в config, поэтому
  collector не может заменить исчезнувший alias похожей строкой или ручным guess.
- Collector сохраняет closed-schema discovery/descriptions/RFUD boards, exact-cursor
  daily history, raw responses, normalized tables, coverage и hashes в immutable external
  bundle. Missing не zero; gap/roll returns не строятся; стратегии и PnL отсутствуют.
- До protocol/code commit и push реальный daily endpoint с price fields не вызывается.
  Synthetic source tests: `7 passed`; Ruff clean.
- Pre-price commit `38fc63a` был pushed до первого daily response. Canonical source:
  `data/processed/futures_pre2018/moex-core4-daily-current-vintage-2012-2017-v1/`.
  Manifest SHA-256:
  `e60d0bcacff17af0229d150552a70ac235e821c2d271970ea2567c212a5f3da6`.
- Source counts: 155 contracts/segments, 30 059 daily rows, 544 raw requests. By asset:
  BR `71/6 842`, MIX `24/6 684`, RTS `24/8 134`, Si `36/8 399` contracts/rows.
  Daily range `2012-01-03..2017-12-21`; every contract non-empty, maximum calendar gap
  11 days, 21 355 trade rows, 30 059 settlement rows, 91 activity rows with missing OHLC.
- Integrity audit recomputed manifest payload/sidecar and every artifact bytes/SHA/rows,
  replayed 18 finder + 155 description/boards + 371 exact-cursor daily responses and
  matched all 30 059 unique raw daily identities. All checks true.
- No return, target, label, strategy equity or PnL was calculated. Next allowed action:
  immutable source-derived active panel/spec proxy plus bounded macro sources, then a
  separately sealed V28 validation. Raw redistribution and live use remain forbidden.

## V27-R1: frozen path-robustness audit — completed

- Протокол:
  [`configs/futures_v27_robustness.yaml`](../configs/futures_v27_robustness.yaml)
- Config SHA-256:
  `a8d6ed420593aeb26e0bf537b402a6edba6b40ab7dd64d48947dc2a936ec8b10`.
- Parent V27 неизменяем: protocol SHA `7a9a44cf...`, metrics SHA `5fc1f271...`;
  audit читает только `session_date` и `combined_ending_equity` из трёх canonical curves.
- До time-series audit зафиксированы circular blocks 5/21/63 sessions, 20 000
  replications на scenario/block, rolling 252-session windows, leave-one-year-out,
  DSR sensitivity для 27/100 trials и отдельные критерии поддержки 20%/50%.
- Resampling frequency объявлена descriptive, не calibrated forecast. Даже положительный
  verdict разрешает только новый unseen/PIT validation и никогда live trading.
- Synthetic/encoding tests до первого audit: `8 passed`; seal commit `4bbf2bd` был
  pushed до первого чтения daily curves.
- Canonical run:
  `runs/v27_robustness_20260901T054810Z_a8d6ed42/`.
- Metrics SHA-256:
  `e5c5851f912d4ac06189dbf220ad20369dc8fa1b8d6076209f910128a208e743`.

Все 49 checks true; 8 parent artifacts повторно сверены по bytes/SHA/rows. Audit
содержит 180 000 bootstrap paths и 3 063 rolling windows, maximum date `2025-12-30`.
Худший stress-result по block lengths: joint frequency `CAGR >=20%` и `MDD <=30%`
**65,70%**, для `CAGR >=50%` и `MDD <=30%` **4,33%**, minimum q05 CAGR **8,13%**.
Rolling 252-session stress: minimum CAGR **−17,32%**, q05 **−9,96%**, median
**24,41%**; positive **87,95%**, `>=20%` **57,00%**, `>=50%` **22,82%**. Stress
leave-one-year-out CAGR: **24,21%/18,13%/26,44%/31,47%/35,81%** при исключении
2021/2022/2023/2024/2025. DSR probability для 27/100 trials: **0,746/0,554**.

Verdict: `INTERNAL_ROBUSTNESS_SUPPORTS_UNSEEN_VALIDATION`. Minimum-20 internal support
gate true, aspirational-50 false. Это post-selection descriptive audit: он не доказывает
20% в каждом будущем году, не является independent validation и не разрешает live.

## V27: official CBR key-rate extreme governor — GO to unseen validation

- Протокол:
  [`configs/futures_v27_key_rate_extreme_governor.yaml`](../configs/futures_v27_key_rate_extreme_governor.yaml)
- Config SHA-256:
  `7a9a44cf7b09c7820a514b2706e332744a3b30ced8b7d3d4c8bdf7448a3194fe`.
- Parent V26 immutable: protocol SHA `2b085890...`, metrics SHA `b4149969...`; maximum
  2x, RUONIA haircut 50%, operational buffer 10%, `cancel_and_clip`, margin/gross/
  participation и cost scenarios не менялись.
- Один новый governor: после V25 STLFSI4 latest official CBR key rate с
  `available_at <= decision_at` и age `<=7` дней. Rate `<20%` пропускает V25; rate
  `>=20%`, missing/stale или уже cash STLFSI4 дают global cash до 2x multiplier.
- Порог 20% — заранее объявленная круглая extreme monetary boundary. Levels below 20,
  changes, percentiles, hysteresis, partial scale и asset exceptions не тестировались.
- Raw SOAP source `121958` bytes, SHA `06da1497...`, exact parse восстанавливает 2 015
  filtered key-rate rows `2018-01-09..2025-12-30`; same-day использование запрещено,
  `available_at` консервативно равно следующей календарной полуночи Moscow.
- Source-only seal: all `418 = 309 pass + 68 STLFSI cash + 40 key-rate cash + 1
  missing`; OOS `261 = 197 + 24 + 40 + 0`.
- Pre-outcome tests `43 passed`; config/code/tests committed и pushed как `aca0380` до
  первого V27 PnL.
- Promotion требовал во всех primary/doubled/stress CAGR `>=20%`, MDD `<=30%`, primary
  Sharpe/worst-year не хуже V26, 4/5 positive years, complete execution и no breaches.

- Canonical run:
  `runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/`.
- Metrics SHA-256:
  `5fc1f271acf8f9df711006bca24e6bc40425bf097c21e989eb0296baeb0e7654`.

Все 115 checks true; 27 declared artifacts плюс metrics/identity прошли bytes/SHA/row
audit. Execution complete: 828/828 nonzero dependencies, primary 616 filled order legs,
0 rejected/critical/unresolved, six causal no-open target cancellations and no gross/
margin/participation breach.

| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +248,6127% | +28,3752% | 1,2119 | −20,7138% | −1,4772% | 44 141,07 | yes |
| doubled | +238,4811% | +27,6201% | 1,1918 | −20,9410% | −2,3294% | 86 607,24 | yes |
| stress | +235,1022% | +27,3643% | 1,1839 | −21,0511% | −2,6979% | 128 784,62 | yes |

Primary годы: 2021 **+40,34%**, 2022 **+72,45%**, 2023 **+30,68%**,
2024 **+11,87%**, 2025 **−1,48%**. Collateral income primary 366 595,47 RUB.
Против V26 primary CAGR выше на **4,21 п.п.**, Sharpe на **0,2356**, MDD ниже на
**12,85 п.п.**, worst year лучше на **10,79 п.п.**, costs ниже на 11 156,59 RUB.

Verdict: `GO_TO_NEW_UNSEEN_VALIDATION`; все predeclared conditions true. Это не live
promotion: V27 выбран после V26 на том же OOS, key-rate publication time заменён
консервативным next-day proxy, STLFSI4 current-vintage и specs/fees/margin не broker-
exact. Независимое подтверждение и paper/shadow forward обязательны. Same-history
20% boundary/age/scale tuning запрещён.

## V26: 2x V25 + RUONIA + capacity admission — NO-GO by MDD

- Протокол:
  [`configs/futures_v26_stlfsi_levered_ruonia_capacity.yaml`](../configs/futures_v26_stlfsi_levered_ruonia_capacity.yaml)
- Config SHA-256:
  `2b08589013f3b3387002830cad7878ef0fffc5dc808b8165fc004e724abf4c1b`.
- Frozen V25 weekly signal/governor удваивается ровно один раз. V15 collateral formula
  byte-reused; core ledger использует asset-atomic `cancel_and_clip`, known lagged volume
  и factual open до submission.
- До PnL config/code/tests были pushed commit `3b9ce95`; pre-execution mapper остановил
  первый вызов до market ledger из-за >1 base-normalizer. Routing был исправлен до PnL
  и pushed commit `5515321`: mapping выполняется на admissible V25 weights, затем 2x.
- Promotion требовал CAGR `>=20%` и MDD `<=30%` во всех cost scenarios, Sharpe не ниже
  V25, worst year `>=−15%`, complete execution и no breaches.

- Canonical run:
  `runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/`.
- Metrics SHA-256:
  `b4149969696e23a29a06b58085510d9f8c9f2bbf584ca0d2aaa883801493567d`.

Все 99 checks true; 25 artifacts прошли audit. 1 016/1 016 dependencies complete,
primary 761 filled legs, 0 rejected/critical/unresolved. Capacity policy превратила
проблемные halt targets в шесть explicit no-open cancellations.

| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +195,1384% | +24,1698% | 0,9764 | −33,5661% | −12,2686% | 55 297,66 | yes |
| doubled | +186,2080% | +23,4090% | 0,9565 | −33,9890% | −12,9643% | 108 069,21 | yes |
| stress | +181,7881% | +23,0255% | 0,9458 | −33,9672% | −14,1060% | 160 794,39 | yes |

Verdict `NO_GO`: единственный false condition — all-scenario MDD `<=30%`. Постоянное
плечо, haircut, buffer и capacity нельзя ретюнить на этом outcome. V26 остаётся
immutable capital-efficiency/execution parent V27.

## V25: weekly STLFSI4 stress governor — NO-GO by strict MDD gate

- Протокол:
  [`configs/futures_v25_stlfsi_stress_governor.yaml`](../configs/futures_v25_stlfsi_stress_governor.yaml)
- Config SHA-256:
  `dd8b60513de7261aa051c12bd5598fffd880c90c98489a5becac820b7597416b`.
- Source collector/bundle был committed/pushed отдельно как `cdfe674`: 417 weekly rows,
  processed SHA `4937b686...`, manifest SHA `1a992f64...`; one bounded raw CSV точно
  воспроизводит processed frame и не содержит observations 2026.
- Parent неизменяем: frozen V12 signal, weekly portfolio, 20% target volatility, gross
  `<=1`, active-contract next-open execution и три cost scenarios.
- Единственный governor действует только на исходных weekly V12 decisions: последний
  complete STLFSI4 с `available_at <= decision_at` и возрастом `<=14` дней пропускает
  V12 при value `<=0`; value `>0`, missing/incomplete/stale дают global cash. Scale
  только `1` или `0`, asset exceptions отсутствуют.
- Ноль — официальное определение normal financial conditions; 14 дней — два exact
  недельных интервала source cadence. Levels, percentiles, changes, smoothing,
  hysteresis, partial scale, sign inversion и комбинация с V24 запрещены.
- Source/calendar-only seal до PnL: все `2018–2025` — 418 weekly decisions, 349 pass,
  68 stress-cash, 1 missing/stale; OOS `2021–2025` — 261 decisions, `237/24/0`.
- Pre-outcome source/config/semantic/synthetic tests: `11 passed`; implementation,
  protocol и pending-status были committed/pushed как `74c5461` до market/PnL.
- Promotion: CAGR `>=5%`, Sharpe не ниже V12 `0,7624`, MDD не хуже V12 `14,1526%`,
  не менее 4/5 positive years, positive doubled/stress, complete execution и no breaches.

- Canonical run:
  `runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/`.
- Metrics SHA-256:
  `c2518d17b4e945ef921fa8dbaa8bd330645131acddd73fc01a45c44c0aacfa86`.

Все 82 input/raw-replay/source/calendar/runtime checks true; 18 declared artifacts плюс
metrics/identity прошли bytes/SHA/row audit. Execution complete: 1 016/1 016 nonzero
dependencies, primary 438 filled legs, 0 rejected/critical/unresolved и no capacity/
gross/margin breaches. Maximum participation **0,11287%**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +49,0720% | +8,3137% | 0,8177 | −14,2262% | 4/5 | 13 835,17 | yes |
| doubled | +47,1768% | +8,0368% | 0,7932 | −14,4163% | 4/5 | 27 605,96 | yes |
| stress | +46,8571% | +7,9898% | 0,7913 | −14,1659% | 4/5 | 41 154,16 | yes |

Primary годы: 2021 **+17,53%**, 2022 **+14,01%**, 2023 **+12,08%**,
2024 **+1,54%**, 2025 **−2,26%**. Terminal positions carry; primary exit reserve
178,40 RUB оставляет post-reserve return **+49,05%**.

Против V12 V25 улучшил total return на **3,96 п.п.**, CAGR на **0,58 п.п.**, Sharpe на
**0,0553**, worst year на **0,37 п.п.** при costs всего на 447,89 RUB выше. Семь stress
episodes дали 24 cash weeks. Equity V25 ни в одной из 1 272 ledger sessions не была ниже
V12; после первого отличия 2023-03-27 она выше 707 sessions и заканчивает на 39 606 RUB
выше. Но MDD **14,2262%** хуже V12 **14,1526%** на **0,0736 п.п.**: peak/trough dates
совпадают (`2024-11-26 → 2025-03-03`), а V25 имеет более высокие и peak, и trough.

Verdict остаётся `NO_GO`: единственный обязательный MDD gate false, ослаблять его после
outcome нельзя. STLFSI4 — current-vintage Version 4, которая не существовала в точном
виде на всей истории; V25 является сильным adaptive development lead, но не независимой
PIT validation и не live-системой. Same-history threshold/age/state/scaling/combination
tuning запрещён.

## V24: daily Cboe VIX/VIX3M risk governor — NO-GO

- Протокол:
  [`configs/futures_v24_cboe_vix_term_structure_governor.yaml`](../configs/futures_v24_cboe_vix_term_structure_governor.yaml)
- Config SHA-256:
  `f81b5aaa666346fa049b550e5dfc92c24ecf6ef2790a2cb00fb83235f24c064c`.
- Parent неизменяем: frozen V12 signal, weekly portfolio, 20% target volatility, gross
  `<=1`, exact active-contract next-open execution и три cost scenarios.
- Один governor: на каждой factual MOEX decision date последняя строка с
  `available_at <= 23:59:59 Europe/Moscow` допускает frozen V12 weights только при
  complete pair и строгом contango `VIX/VIX3M < 1`. Backwardation, exact flat,
  incomplete/missing и возраст старше четырёх календарных дней переводят все assets в
  cash. Scale только `1` или `0` и никогда не увеличивает V12 risk.
- Четыре дня — заранее наблюдаемый maximum complete-pair gap source bundle, а граница
  `1` — определение term-structure inversion. VIX levels, percentiles, smoothing,
  hysteresis, partial scale и asset exceptions запрещены.
- Source-only/calendar-only seal до OOS PnL: все `2018–2025` — 2 024 decisions,
  1 785 contango pass, 167 backwardation cash, 72 missing/stale cash; OOS `2021–2025` —
  1 270 decisions, 1 170/53/47 соответственно, exact flat 0.
- Canonical V2 source: 2 087 grid rows, 2 011 complete pairs, 76 missing; processed SHA
  `6ffe7daa...`, raw SHA `d11aa637...`. Два bounded raw CSV точно воспроизводят parquet,
  не содержат observations 2026 и консервативно доступны только после Chicago day-end.
- Pre-outcome source/config/semantic/synthetic tests: `11 passed`; implementation,
  protocol и pending-status были committed/pushed как `34023c1` до первого market/PnL.
- Promotion требует CAGR `>=5%`, Sharpe не ниже V12 `0,7624`, MDD не хуже V12
  `14,1526%`, не менее 4/5 положительных лет, positive doubled/stress, complete
  execution и отсутствие breaches. Даже GO разрешит только новую unseen validation.
- Canonical run:
  `runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/`.
- Metrics SHA-256:
  `1da1b995fd432c938f62745abcc71f7e85af5a5d20735b9a98631a41d21d2f98`.

Все 83 input/raw-replay/source/calendar/runtime checks true. Все 18 declared artifacts
плюс metrics/identity существуют и повторно прошли bytes/SHA/row audit; market-derived
timestamps заканчиваются `2025-12-30`. Execution complete во всех сценариях:
3 722/3 722 nonzero next-open dependencies, primary 774 filled legs, 0 rejected,
critical/unresolved, capacity/gross/margin breaches. Maximum participation **0,13643%**,
maximum post-mark gross leverage **0,9443**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +38,8855% | +6,7910% | 0,7394 | −14,2777% | 4/5 | 26 009,44 | yes |
| doubled | +37,1342% | +6,5203% | 0,7163 | −14,4019% | 4/5 | 51 708,38 | yes |
| stress | +33,5409% | +5,9561% | 0,6643 | −15,2709% | 4/5 | 74 152,75 | yes |

Primary годы: 2021 **+16,56%**, 2022 **+8,66%**, 2023 **+7,62%**,
2024 **+10,50%**, 2025 **−7,80%**. Terminal positions carry; conservative primary exit
reserve 173,40 RUB оставляет post-reserve total return **+38,87%**.

Относительно frozen V12 primary: total return ниже на **6,23 п.п.**, CAGR на
**0,94 п.п.**, Sharpe на **0,0231**; MDD хуже на **0,125 п.п.**, worst year хуже на
**5,16 п.п.**, costs выше на **12 622,16 RUB**. Сто cash sessions образовали 67 episodes
и 133 scale transitions; filled legs выросли с 429 до 774. Governor помог 2024, но
ухудшил 2021/2022/2023/2025.

Verdict: `NO_GO`. CAGR, positive-year и cost-stress gates пройдены, но обязательные
Sharpe и MDD improvements над V12 провалены. Это один adaptive same-history stability
test, не независимое подтверждение. После outcome запрещено менять boundary/age,
инвертировать state, добавлять levels/thresholds, smoothing/hysteresis/partial scale или
выбирать asset-specific исключения на 2021–2025.

## V23: CBR household inflation/sentiment confirmation — NO-GO

- Протокол:
  [`configs/futures_v23_cbr_household_confirmation_regime.yaml`](../configs/futures_v23_cbr_household_confirmation_regime.yaml)
- Config SHA-256:
  `2a8a35a898eddae72694bce159282ced6f72230b537613ad224c0d2b6001f2ee`.
- Source был независимо собран и pushed commit `3d18a03` до протокола: 48
  release-specific страниц, PDF и XLSX за `2022-01..2025-12`; processed SHA
  `70711272...`, manifest SHA `b132a45e...`, 146/146 raw responses проходят
  byte/SHA/reparse audit.
- Единственная гипотеза: expected-inflation delta `<0` и sentiment delta `>0` даёт
  risk-on (long RI/MIX, short SI); обратная согласованная пара даёт risk-off; mixed/zero
  всегда cash, BR zero. Observed inflation, magnitudes и thresholds запрещены.
- Source-only seal: 48 releases, 1 warmup, 47 scored (`11/12/12/12`), 16 risk-on,
  17 risk-off, 14 mixed, 99 nonzero asset directions и два expiry states.
- Availability — конец более поздней publication/last-update date. Collision сентября и
  октября 2022 обязан оставить октябрь. Fill — следующий factual active-contract open;
  active legs имеют 1/3 risk budget, prior 60-session volatility и 45-day expiry.
- Promotion gates: complete execution во всех cost scenarios, 0 critical/unresolved,
  CAGR `>=5%`, Sharpe `>=0,75`, MDD `<=20%`, 3/4 positive active years и положительные
  doubled/stress results. Даже GO разрешит только новую unseen validation, не live.
- Pre-outcome source/config/semantic/synthetic tests: `6 passed`; implementation и
  pending-status были pushed commit `4ac40df` до первого market outcome.
- Canonical run:
  `runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/`.
- Metrics SHA-256:
  `33614e391a547a636ed3ef1a2df44653d05669c24495aacb43f73125cbc9b839`.

После первого outcome запрещены sign inversion, single-series selection, thresholds,
trading mixed states, risk/expiry changes и post-hoc blend на тех же 2021–2025 данных.

Все 92 input/source/temporal/runtime checks true, 19/19 run files повторно прошли
bytes/SHA/row audit. Из 47 scored releases было 33 confirmations; одинаковые September/
October 2022 states корректно оставили October. Три confirmed releases `2022-03..05`
fail-closed не получили targets из-за недоступной prior-60-session volatility во время
рыночного разрыва. Поэтому mapped confirmed states — 29/32 после collision; downstream
ledger для сформированных targets полностью исполнен: 111/111 dependencies, 109 filled
legs, 0 rejected/critical/unresolved. Maximum participation **0,03956%**, maximum gross
notional **830 572,84 RUB**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −5,3484% | −1,0935% | −0,1589 | −13,6190% | 1/5 | 2 775,79 | ledger yes |
| doubled | −5,6260% | −1,1515% | −0,1685 | −13,8318% | 1/5 | 5 551,59 | ledger yes |
| stress | −5,9180% | −1,2128% | −0,1787 | −14,0594% | 1/5 | 8 471,18 | ledger yes |

Primary годы: 2021 **0,00%**, 2022 **−3,77%**, 2023 **−2,42%**,
2024 **−1,19%**, 2025 **+2,01%**. Terminal position отсутствует.

Verdict: `NO_GO`. Return, CAGR, Sharpe, active-year и cost-robustness gates провалены;
единственный положительный active year — 2025. Household confirmation family закрыта для
same-history sign/single-series/threshold/mixed-state/risk/expiry/blend tuning.

## V22: CBR printed Business Climate Index regime — NO-GO

- Протокол:
  [`configs/futures_v22_cbr_business_climate_regime.yaml`](../configs/futures_v22_cbr_business_climate_regime.yaml)
- Config SHA-256:
  `97b2aa74416eae4ebbce28d018a460f98ade4993cfb086487d28515976c18fbe`.
- Source был независимо собран и pushed commit `7fee819` до создания протокола: 44
  release-specific страницы и PDF за `2022-05..2025-12`, processed SHA `b312f4e5...`,
  manifest SHA `99ad128b...`, 90/90 raw responses прошли byte/SHA/reparse audit.
- Pre-outcome commit: `eb0891a`; implementation, config, tests и pending-status были
  pushed до первого чтения RI/MIX/SI outcomes.
- Canonical run:
  `runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/`.
- Metrics SHA-256:
  `10d7b0bf1b84d46b7cfe6fac784ba8e279bd22bd277fa76c2c8f51238f274214`.
- Единственный signal — знак последовательного изменения one-decimal composite BCI,
  напечатанного на endpoint страницы конкретного выпуска. Chart exact decimals, текущие
  оценки и ожидания сохранены для аудита, но исключены из V22 signal.
- Улучшение BCI заранее означает long RI/MIX и short SI; ухудшение — симметрично наоборот,
  exact zero — cash. BR всегда zero. Threshold, magnitude scaling, fitting и search нет.
- Source-only seal: 44 releases, 1 warmup, 43 scored (`7/12/12/12`), 21 positive,
  18 negative и 4 zero delta, 117 nonzero asset directions и два expiry states.
- Availability — конец московского дня более поздней из publication/last-update dates.
  Две строки с одинаковым `available_at` `2022-11-24` обязаны оставить November release;
  три prior-month chart endpoints хранятся отдельно от release month.
- Три active legs имеют фиксированный risk budget 1/3, prior 60-session volatility,
  target 20%, floor 10%, gross `<=1`. State живёт до следующего release или 45 дней.
  Fill — только следующий factual active-contract open; ledger portfolio-atomic.
- Promotion требует complete execution во всех cost scenarios, 0 critical/unresolved,
  CAGR `>=5%`, Sharpe `>=0,75`, MDD `<=20%`, 3/4 positive active years и положительный
  doubled/stress result. Даже GO разрешит только новую unseen validation, не live.

Forbidden after outcome: sign inversion, BCI threshold/magnitude tuning, component
selection, exact-decimal use, risk/expiry changes и blend с V12 на этой же истории.

Все 91 input/source/temporal/runtime checks true. Из 43 scored releases получено 43
mapped states; October 2022 корректно superseded November при одинаковом availability,
terminal expiry 2026 остался `no_future_active_decision_session`. Добавлено 13 causal
roll decisions, 224 target rows и 153 nonzero dependencies; coverage **153/153**.
Все три ledger complete, 147 filled legs, 0 rejected, 0 critical/unresolved. Maximum
participation **0,12048%**, maximum gross notional **938 731,05 RUB**.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | +13,3661% | 2,5411% | 0,3569 | −8,8570% | 2/5 | 4 873,13 | yes |
| doubled | +12,8788% | 2,4528% | 0,3454 | −8,9610% | 2/5 | 9 746,26 | yes |
| stress | +11,9558% | 2,2846% | 0,3248 | −9,1829% | 2/5 | 15 090,51 | yes |

Primary годы: 2021 **0,00%**, 2022 **−3,78%**, 2023 **+1,52%**,
2024 **+20,84%**, 2025 **−3,96%**. Terminal carry reserve **34,65 RUB** оставляет
post-reserve total return **+13,3627%**.

Verdict: `NO_GO`. Сигнал положителен во всех cost scenarios и заметно ограничивает MDD,
но не проходит sealed CAGR, Sharpe и 3/4 positive-active-years gates; результат слишком
сильно сосредоточен в 2024. Это полезнее отрицательных V17–V21, но ещё не стабильный
доход. Direct printed-BCI delta family закрыта для same-history tuning; продолжение
требует нового forward периода или заранее иной независимой информации.

## V21: CBR next-year macro revision breadth — NO-GO

- Протокол: [`configs/futures_v21_cbr_macro_revision_breadth.yaml`](../configs/futures_v21_cbr_macro_revision_breadth.yaml)
- Config SHA-256:
  `5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc`.
- Pre-outcome commit: `5414251`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI/RI/BR/MIX outcomes.
- Canonical run:
  `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/`
- Metrics SHA-256:
  `cfc704e757393760cabcddeb6f3d1614f43df8ee8523b46db0fccd0ac8b92c0e`.
- Новый официальный current-vintage source: 11 787 non-missing записей макроопроса ЦБ,
  37 survey months, 17 indicators; до protected boundary причинно доступны 36 releases.
- Используется только медиана прогноза следующего календарного года. Revision всегда
  равна текущей медиане минус медиана предыдущего survey для строго того же indicator и
  forecast year; первый выпуск без предыдущего значения — source warmup.
- Независимые direct signs объявлены до outcomes: рост USD/RUB = long SI, рост GDP =
  long RI и MIX, рост oil = long BR; снижение даёт симметричный short, exact zero — cash.
- Нефть выбирается по неизменной очереди `oil tax > Brent > Urals`, только если у той же
  серии есть предыдущее значение того же target year. Cross-series bridge запрещён.
- Source-only seal: 36 available releases, 1 warmup, 35 scored (`4/8/8/8/7` по survey
  years), 102 ненулевых asset revisions. Magnitude scaling, threshold, fitting и
  outcome training отсутствуют.
- Каждый asset имеет отдельный абсолютный risk budget 1/4, prior 60-session volatility,
  target 20%, floor 10%. Missing component получает target zero, его бюджет не
  перераспределяется. State живёт до следующего release или 70 календарных дней.
- `available_at` намеренно поздний: 23:59:59 мск последнего дня месяца после survey
  month; fill возможен только на следующем factual active-contract open. December 2025
  исключён, потому что становится доступен в 2026.
- Current-vintage workbook не содержит original historical release vintages. Даже
  положительный результат будет adaptive development evidence и потребует нового unseen
  или forward-vintage подтверждения; live trading запрещён.

Из 35 scored releases 32 получили полную prior-60-session volatility; три выпуска
весны 2022 уснули из-за отсутствующей истории RI/MIX после остановки рынка. Получено
32 source decisions и 34 дополнительных causal roll decisions, 264 target rows.
Coverage ненулевых зависимостей — 200/202: на `2022-03-24` у RI и MIX отсутствовал
доказуемый lagged volume. Portfolio-atomic rebalance был отклонён с
`unknown_lagged_volume`; каждый scenario имеет 2 critical failures
(`unknown_liquidity_count=1` плюс `atomic_rejection_count=1`) и incomplete ledger.

| Scenario | Mechanical total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −3,1730% | −0,6429% | −0,0788 | −18,7868% | 3/5 | 4 501,83 | no |
| doubled | −3,9029% | −0,7932% | −0,1076 | −19,1190% | 3/5 | 8 868,22 | no |
| stress | −4,4273% | −0,9017% | −0,1264 | −19,5327% | 3/5 | 13 070,06 | no |

Primary годы: 2021 **+1,68%**, 2022 **−1,27%**, 2023 **+0,79%**,
2024 **+2,03%**, 2025 **−6,21%**. Mechanical метрики приведены только для forensic
полноты и недействительны для promotion из-за critical execution failures.

Verdict: `NO_GO`. Даже механический ledger отрицателен во всех cost scenarios и не
проходит CAGR/Sharpe/positive-years gates. Не инвертировать signs, не выбирать magnitude
thresholds, другие indicators/oil priority, risk/expiry или blend с V12 на этих же
outcomes. Macro-survey source сохраняется для forward vintages и иных вопросов, заранее
обоснованных новой информацией, но это семейство direct revisions закрыто.

## V20: Minfin OFZ-PD prior-rank demand strength — NO-GO

- Протокол: [`configs/futures_v20_minfin_ofz_demand_strength.yaml`](../configs/futures_v20_minfin_ofz_demand_strength.yaml)
- Config SHA-256:
  `788fadbd9c499483c560488a5a3d9d2e95f7e95496e5736ed4465eca889341ed`.
- Pre-outcome commit: `4e52378`; config, implementation, tests и pending-status docs были
  pushed до первого чтения RI/MIX/SI outcomes.
- Canonical run:
  `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/`
- Metrics SHA-256:
  `cbfa0c8803e631697400813d3fb4ba8a2ba2eda00a38cc5114dd652472d33d78`.
- Новый официальный current-vintage source: 410 Minfin events, 364 primary results и
  283 successful fixed-coupon ОФЗ-ПД rows; processed SHA
  `a8c5c02457e3fadc19e617f42ad5a0c644672689a4c9bd8759d20d4a84d5d480`.
- Все успешные ОФЗ-ПД одного дня агрегируются через total demand, total placed и
  `bid_to_cover = demand/placed`. Каждый показатель ранжируется только относительно
  предыдущих 26 successful auction days; минимум 13, ties получают half-rank.
- Единственный score: `percentile(bid_to_cover) + percentile(placed) − 1`, без threshold,
  clipping, outcome training и failed-auction imputation. Первые 13 auction days — warmup.
- Знак заранее фиксирован: strength = long RI/MIX и short SI, weakness — обратная
  корзина; BR zero. Три active legs имеют равный 1/3 risk budget, prior 60-session vol,
  target 20%, floor 10%; gross `<=1`.
- Date-only result доступен только в 23:59:59 мск publication day, fill — следующий
  factual open. Score живёт до следующего score или семь календарных дней, затем zero.
- Corrections, failed/cancelled, supplemental, announcement, ОФЗ-ПК и ОФЗ-ИН исключены
  до outcomes. Current-vintage pages не являются original publication vintages.
- Source сформировал 179 aggregated auction days: 13 warmup и 166 scored
  (`28/13/40/37/48` по годам), из них 82 positive, 76 negative и 8 zero. Добавлено
  29 causal expiry states и 10 roll decisions; 504/504 nonzero execution dependencies
  полны.
- Все 86 input/temporal/runtime checks true. Все три ledger complete, 0 critical и
  unresolved; primary содержит 128 filled legs, costs 1 409,28 RUB, maximum participation
  0,01358% и maximum gross notional 470 109,58 RUB.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −5,3468% | −1,0931% | −0,6313 | −6,1937% | 1/5 | 1 409,28 | yes |
| doubled | −5,4877% | −1,1226% | −0,6473 | −6,2418% | 1/5 | 2 818,57 | yes |
| stress | −5,4430% | −1,1132% | −0,6434 | −6,1057% | 1/5 | 4 139,14 | yes |

Primary годы: 2021 **−0,01%**, 2022 **−3,95%**, 2023 **−0,29%**,
2024 **+0,78%**, 2025 **−1,93%**.

Verdict: `NO_GO`. Prior-rank bid-to-cover плюс placed volume не дали cross-asset edge;
маленькая MDD объясняется умеренным gross, а не положительным expectation. Не
инвертировать asset signs, не выбирать extreme scores, другой rank window/expiry и не
добавлять failed/PK/IN по увиденному результату. Source остаётся полезным для иных новых
заранее обоснованных вопросов и forward vintages, но это семейство score закрыто.

## V19: CBR-reported Minfin FX-flow persistence для SI — NO-GO

- Протокол: [`configs/futures_v19_cbr_minfin_fx_persistence.yaml`](../configs/futures_v19_cbr_minfin_fx_persistence.yaml)
- Config SHA-256:
  `1340ffacae93b514fe4605262d8946a6a87cbc4619c1748b48ac45b9a9b19946`.
- Pre-outcome commit: `0558e7e`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI outcomes.
- Canonical run:
  `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/`
- Metrics SHA-256:
  `dff0016e3501136714f66b3237dfb66f37449bde69c77ab489efdc777446b08d`.
- Новый source: 1 238 current-vintage daily CBR factors `2021-01-11..2025-12-30`,
  processed SHA
  `88885d3695a88fb910d5a6ad9f3d8fd2cbd69eedaec779d4cef3048cd854c864`.
- Единственный сигнал: `sign(minfin_fx_operations_bln_rub)`; official positive FX
  purchase = long SI, negative sale = short SI, exact zero = cash.
- Observation day используется только после 10:31 мск следующего датированного рабочего
  дня ЦБ; решение — close первой factual MOEX session после availability, fill — только
  следующий factual active-contract open. Same-session collisions оставляют последний
  доступный observation.
- SI sizing: prior 60-session annual volatility, 20% target, floor 10%, absolute cap 1;
  RI/BR/MIX всегда zero. Amount scaling, threshold, smoothing, training и blend отсутствуют.
- Историческая таблица допускает revisions и не содержит original publication bytes:
  даже положительный результат будет development-only и потребует forward vintages.
- Все input/temporal checks true. Из 1 238 source rows 1 235 отображены на factual
  decision sessions; одна same-session collision причинно оставила более свежий record,
  два последних records не имели будущей active session. Получено 937 nonzero mapped
  decisions и 4 940 target rows; 937/937 execution dependencies полны.
- Все три ledger complete, 0 rejected/critical/unresolved; primary содержит 162 filled
  legs, costs 4 154,95 RUB и maximum participation 0,01155%.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −0,0316% | −0,0063% | 0,0501 | −30,7614% | 2/5 | 4 154,95 | yes |
| doubled | −0,2403% | −0,0481% | 0,0460 | −30,7447% | 2/5 | 8 249,91 | yes |
| stress | −0,5687% | −0,1140% | 0,0396 | −30,7933% | 2/5 | 9 971,81 | yes |

Primary годы: 2021 **−4,65%**, 2022 **+3,49%**, 2023 **−20,13%**,
2024 **−5,32%**, 2025 **+33,97%**.

Verdict: `NO_GO`. Лагированный прямой знак фактических операций Минфина не дал
устойчивого edge для SI: почти нулевая итоговая доходность скрывает просадку свыше 30% и
сильную зависимость от одного 2025 года. Не инвертировать знак, не выбирать magnitude/
change-day thresholds, smoothing или иной lag по увиденному результату. Следующий PnL
допустим только для новой независимой source family и заранее запечатанного protocol.

## V18: CBR forward-liquidity forecast для SI — NO-GO

- Протокол: [`configs/futures_v18_cbr_liquidity_forecast.yaml`](../configs/futures_v18_cbr_liquidity_forecast.yaml)
- Config SHA-256:
  `ee2d7fd77037eccf15237f827ed357e0b8608c96fae1f393e8a3478945b8b10a`.
- Pre-outcome commit: `0c3fc80`; config, implementation, tests и pending-status docs были
  pushed до первого чтения SI outcomes.
- Canonical run:
  `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/`
- Metrics SHA-256:
  `b67423433a03ebcd4cdebac5df33754e62be94b4719a430f1642596c357e9f28`.
- Новый source: 458 датированных CBR forecasts `2017-01-10..2025-12-30`, processed SHA
  `a8faab048579cc5449173b3f2d4ea0e2abd447095d9144ad5004a52b351a8d07`.
- Единственный сигнал: `sign(government_accounts_change_bln_rub)`; positive liquidity
  contribution = long SI, negative = short SI, exact zero = cash.
- Availability: конец напечатанного publication day Moscow; entry только следующий
  factual open. Двадцать source intervals требуют явного expiry-to-zero, потому что
  successor release появляется после напечатанного конца периода либо отсутствует.
- SI sizing: prior 60-session annual volatility, 20% target, floor 10%, absolute cap 1;
  RI/BR/MIX всегда zero. Threshold, normalization и outcome training отсутствуют.
- Все input/temporal checks true. Получено 240 OOS release decisions
  (`51/37/51/51/50` по годам), 10 expiry-to-zero и 18 roll decisions; 257/257 nonzero
  execution dependencies полны. В 2022 ещё 14 releases исключены из-за отсутствия
  prior 60-session SI volatility после остановки рынка; последний release 2025 не имел
  будущей factual decision session.
- Все три ledger complete: 183 primary filled legs, 0 critical, 0 unresolved,
  maximum participation 0,01155%; один factual halt корректно carried.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---:|---|
| primary | −41,9547% | −10,3092% | −0,5137 | −55,7292% | 1/5 | 8 289,95 | yes |
| doubled | −44,5908% | −11,1392% | −0,5650 | −57,5354% | 1/5 | 16 259,90 | yes |
| stress | −44,4906% | −11,1070% | −0,5616 | −57,3925% | 1/5 | 19 391,80 | yes |

Primary годы: 2021 **−1,77%**, 2022 **−46,94%**, 2023 **−9,47%**,
2024 **−1,33%**, 2025 **+24,67%**.

Verdict: `NO_GO`. Прямой экономический знак будущего изменения government accounts не
является самостоятельным edge для SI. Не инвертировать знак, не выбирать extreme weeks,
не менять lag/expiry/volatility/costs по увиденному результату. Допустима только новая
информационная гипотеза, заранее запечатанная независимо от V18 outcomes.

## V17: EIA seven-component physical balance for BR — NO-GO

- Протокол: [`configs/futures_v17_eia_supply_demand.yaml`](../configs/futures_v17_eia_supply_demand.yaml)
- Config SHA-256:
  `1d8eee3f7aa99aff5798aeaf6a946d110cfa4e4b451b57580b1d9ef6cd17b37a`
- Pre-outcome commit: `a8b8407`; config, implementation и tests были pushed до первого
  чтения BR outcomes.
- Canonical run:
  `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/`
- Metrics SHA-256:
  `fbd3b74e44ce91d484bb9e1594130ee2dd4d6589c0e50cabb34f3345b898f255`
- Новый input family: 38 248 строк из 727 release-specific EIA WPSR Table 1 vintages;
  source manifest SHA `aac389628b...`, processed SHA `5fccfa968a...`.
- Signal: семь заранее названных inventory/supply/refinery/demand changes, prior-only
  156-release z-score с минимумом 104, fixed economic signs, без trade threshold;
  BR target — знак composite с causal prior-60-session 20% vol scaling.
- Timing: conservative end-of-release-day New York, затем завершение первой factual MOEX
  decision session и только следующий factual active-contract open. Ни `Last-Modified`,
  ни same-day response не использованы.
- 623 source releases получили достаточную source history; 245 OOS release decisions и
  49 causal roll decisions; 1 176 target rows, 294 nonzero dependencies, coverage
  294/294. В 2022 13 releases уснули из-за отсутствия prior-60-session BR volatility;
  последний release 2025 не имел будущего decision session.
- Все 74 preflight/source checks true. Все три ledger полны: 0 critical, 0 unresolved,
  maximum participation 0,1383%; один factual halt был корректно carried.

| Scenario | Total return | CAGR | Sharpe | MDD | Costs RUB | Complete |
|---|---:|---:|---:|---:|---:|---|
| primary | −33,1422% | −7,7373% | −0,1893 | −48,8033% | 82 842,43 | yes |
| doubled | −39,9714% | −9,7044% | −0,2734 | −49,6065% | 153 735,82 | yes |
| stress | −42,6776% | −10,5337% | −0,3237 | −51,6054% | 221 578,82 | yes |

Primary годы: 2021 **+7,80%**, 2022 **−31,73%**, 2023 **+59,58%**,
2024 **−19,83%**, 2025 **−28,99%**. Только 2/5 лет положительны.

Verdict: **NO-GO**. Это валидный отрицательный результат, а не execution failure. Не
инвертировать signs, не менять семь компонентов, 156/104 normalization, lag, vol target
или threshold на тех же outcomes. Возвращение к EIA возможно только с действительно новой
информацией, например point-in-time analyst consensus/forecast surprise, либо на новом
forward периоде по заранее запечатанному протоколу.

## V16: FUTOI crowding + capacity-aware 2x trend — INVALID, FUTOI look-ahead

- Протокол: [`configs/futures_v16_futoi_crowding_governor.yaml`](../configs/futures_v16_futoi_crowding_governor.yaml)
- Config SHA-256:
  `d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070`
- Pre-outcome Git commits: общий capacity-aware admission `1323781`; sealed V16
  protocol/code/tests `8fd2abf`. Оба отправлены в `origin` до первого PnL.
- Canonical run:
  `runs/v16_futoi_governor_20260831T220539Z_d0461775/metrics.json`
- Metrics SHA-256:
  `8246e155843dad0928c1ae283b9023622fc19fe9ed11ca956753bfbe92c6d73f`
- Invalidation audit: 932/1 044 OOS asset states имели recorded FUTOI `available_at`
  позже decision. Все 832 states 2021–2024 недоступны; первый допустимый state только
  `2025-06-27`. MOEX определяет `SYSTIME` как время публикации, а historical rows
  2020–2024 в current-vintage response имеют `SYSTIME=2025-06-21`.
- Root cause: join требовал `source_date < decision_date`, но не проверял обязательное
  `available_at <= decision_at`. Pre-outcome seal не компенсирует look-ahead; run
  недействителен и текущий entry point остановлен `RuntimeError` до PnL.
- Signal: frozen V12 weekly trend. Для каждого asset последний FUTOI строго с
  `source_date < decision_date` переводит нормальное/contrarian состояние в 2x, а
  trend-aligned crowding не менее одной robust sigma — в 1x. Median/MAD зафиксированы
  только на 168 наблюдениях каждого asset 2020 года.
- Collateral: полностью неизменные V15 RUONIA rules — 50% причинно известной ставки,
  ACT/365, двойной modeled-IM reserve, 10% buffer и отсутствие reinvestment.
- Capacity contract: неизвестный factual open или lagged volume отменяет только текущую
  попытку; известный participation excess заранее clip-ится. Нет скрытого GTC retry и
  специальных дат марта 2022.
- Artifact integrity: все 23 артефакта и 19 parquet row counts совпали с manifest.
  Предыдущий аудит проверял только отсутствие 2026 и потому не заметил, что timestamp
  2025 всё равно позже решений 2021–2024.

OOS содержит 261 weekly и 53 roll decision, 1 256 target rows и 1 040 ненулевых
targets с coverage 1 040/1 040. Из 1 044 weekly asset states: 253 crowded 1x, 577
aggressive 2x и 214 neutral/zero-signal base-risk; stale/missing не было. Primary ledger
содержит 730 filled legs, 0 rejected, 0 critical и 0 unresolved; шесть попыток были
причинно отменены из-за отсутствия factual open, позиция сохранялась до следующего
самостоятельного target.

| INVALID forensic scenario | Futures CAGR | Combined return | Combined CAGR | Sharpe | MDD | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 20,1280% | 170,3301% | 22,0082% | 0,9678 | −31,3402% | 45 074,70 |
| 2 ticks + 2x fee | 19,9683% | 168,5542% | 21,8474% | 0,9624 | −30,8848% | 89 323,92 |
| 4 ticks + 2x fee | 19,1924% | 160,3881% | 21,0971% | 0,9378 | −31,0004% | 132 148,39 |

Primary collateral income — 201 950,38 RUB. Combined годы: 2021 `+39,1146%`,
2022 `+70,4325%`, 2023 `+15,2018%`, 2024 `+9,0275%`, 2025 `−9,2234%`. Эти числа
сохранены только для forensic reproducibility: их нельзя сравнивать с V15/V12,
использовать для выбора следующей гипотезы или называть performance.

Главная просадка шла от `2024-11-26` до `2025-04-07`: RI дал около −482 тыс. RUB,
SI −270 тыс., MIX −173 тыс., BR −56 тыс. В этом окне FUTOI уже уменьшал RI/MIX/BR,
но оставлял SI в 2x во всех 19 weekly states. Это outcome-diagnostic, не разрешение
подбирать новый FUTOI/RVI threshold на том же периоде.

Verdict: `INVALID_FUTOI_LOOKAHEAD`, не `NO_GO`. Ни один promotion gate не оценивается
по недоступным признакам. Daily/intraday FUTOI current-vintage можно использовать только
после его conservative retrieval time либо с лицензированным original-vintage archive;
V16.1 и любые post-outcome FUTOI/RVI thresholds запрещены.

## V15: 2x frozen V12 + causal RUONIA — цель CAGR достигнута, stability/execution нет; NO-GO

- Протокол: [`configs/futures_v15_levered_ruonia_collateral.yaml`](../configs/futures_v15_levered_ruonia_collateral.yaml)
- Config SHA-256:
  `8cbcf30712684607e16cde27a9bca333e4740bd3bdb119646890d0b28d00a50d`
- Pre-outcome Git commits: `f68226f`; инфраструктурный 2x admission fix до PnL:
  `85b1074`.
- Canonical run:
  `runs/v15_levered_ruonia_20260831T205040Z_8cbcf307/metrics.json`
- Metrics SHA-256:
  `3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4`
- Signal: frozen V12; mapped target weights умножены на 2, gross cap 2x, modeled-IM
  reserve остаётся 2x. Первый технический запуск остановился до расчёта PnL на старом
  1x admission guard и не создал run; economics/config не менялись.
- Collateral: последняя RUONIA, консервативно доступная до начала интервала, haircut 50%,
  ACT/365; начисление только на положительный остаток после двойного IM и 10% operational
  buffer. Процент не участвует в sizing и не капитализируется в будущую базу.
- Coverage: 1 040/1 040 nonzero target dependencies; 1 271/1 271 RUONIA intervals,
  1 824 календарных дня. Все 23 run-артефакта совпадают с записанными hashes; 25
  временных полей не пересекают защищённую границу 2026.

| Scenario | Futures CAGR | Combined return | Combined CAGR | Sharpe | MDD | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 19,9802% | 162,8703% | 21,3272% | 0,8826 | −34,4823% | 51 931,22 |
| 2 ticks + 2x fee | 19,1440% | 154,0721% | 20,5038% | 0,8609 | −34,9389% | 101 335,27 |
| 4 ticks + 2x fee | 19,0763% | 153,4561% | 20,4453% | 0,8605 | −34,5370% | 151 941,78 |

Primary collateral income — 142 698,54 RUB, или 14,2699% начального капитала. Combined
годы: 2021 `+40,3432%`, 2022 `+73,0253%`, 2023 `+19,8218%`, 2024 `+6,6062%`,
2025 `−15,2535%`. Главная просадка шла от пика 2024-11-26 до минимума 2025-10-20.
Maximum post-mark gross leverage 2,1862 и maximum 2x modeled-margin/start-cash ratio
1,0831 возникали после рыночного движения; order-time gross/margin rejections равны нулю.

Execution не является полным: primary содержит 756 filled и 12 rejected legs, восемь
critical order events и ноль unresolved на конце. Все отказы сосредоточены в RI/MIX
`2022-03-09..2022-03-23`, когда требуемого factual open/mark не было; дополнительно три
случая не имели lagged volume и один превысил participation. Поэтому даже численно
высокие return/CAGR имеют `metrics_valid=false`.

Verdict: `NO_GO`. Sealed 20% CAGR gate пройден, но MDD 25% gate и complete-execution
gate провалены. V15 доказал полезность capital efficiency как направления, но не
стабильный исполнимый доход. Нельзя менять leverage, RUONIA haircut, buffer или правила
марта 2022 по этому outcome; следующий вариант обязан быть отдельной заранее
запечатанной risk/execution гипотезой и всё равно потребует независимой проверки.

## V14: previous-session RVI risk governor — просадка ниже, edge слишком ослаблен; NO-GO

- Протокол: [`configs/futures_v14_rvi_risk_governor.yaml`](../configs/futures_v14_rvi_risk_governor.yaml)
- Config SHA-256:
  `9f680ebfcfcd6aae98a1e39eb44b9c51b59aa73067edc32e7a558399a8a29a53`
- Pre-outcome Git commit: `677c713`.
- Canonical run:
  `runs/v14_rvi_governor_20260831T201919Z_9f680ebf/metrics.json`
- Metrics SHA-256:
  `1a236f0698ab906532e5381d8ecbc5c7b896c742533ad9b1e95df1096c8aa3ea`
- Signal/portfolio/execution: frozen V12. После portfolio construction все четыре target
  умножаются на `min(1, 24.135 / previous_session_RVI_close)`. Медиана `24.135`
  рассчитана только по 756 RVI строкам 2018–2020 и запечатана до OOS PnL.
- Causality: только RVI точной предыдущей factual core-four сессии; same-day запрещён,
  missing переводит все четыре target в cash с отдельным mask.
- OOS: RVI доступен для 259/261 weekly decisions, 219 решений downscaled, 2 missing;
  minimum/mean scale `0,1810/0,7308`.
- Execution: 261 weekly + 53 roll decisions, 1 256 target rows, 1 040 nonzero,
  coverage 1 040/1 040; primary 330 filled legs, 0 rejected, 0 critical, 0 unresolved.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 25,6242% | 4,6687% | 0,7342 | −9,3980% | 4/5 | 8 313,85 |
| 2 ticks + 2x fee | 25,5055% | 4,6489% | 0,7293 | −10,2238% | 4/5 | 16 390,64 |
| 4 ticks + 2x fee | 24,6763% | 4,5103% | 0,7072 | −10,4019% | 4/5 | 24 254,85 |

Primary годы: 2021 `+15,4005%`, 2022 `+3,1454%`, 2023 `+6,2241%`,
2024 `+2,1197%`, 2025 `−2,7066%`. Относительно V12 MDD лучше на 4,7545 п.п. и costs
ниже на 5 073,43 RUB, но CAGR ниже на 3,0631 п.п., Sharpe ниже на 0,0283 и worst year
немного хуже. Maximum post-mark gross leverage 0,9049, maximum 2x margin ratio 0,4545.

Verdict: `NO_GO`. RVI действительно уменьшил tail exposure, но не повысил
risk-adjusted edge и нарушил sealed minimum CAGR 5%. Не перебирать RVI thresholds,
floors или same-day joins на 2021–2025.

## V13: trend + front/next carry confirmation — больше return, хуже stability; NO-GO

- Протокол: [`configs/futures_v13_trend_carry_confirmation.yaml`](../configs/futures_v13_trend_carry_confirmation.yaml)
- Config SHA-256:
  `94841c0baa1f4c7e0f88302467dfde3bc8104b2e662382b9224bbaf9b75f07ef`
- Pre-outcome Git commit: `2c51cef`.
- Canonical run:
  `runs/v13_trend_carry_20260831T190300Z_94841c0b/metrics.json`
- Metrics SHA-256:
  `783b0a7ec9dd613df9b7f38c3070eb33ee980358a69ec4a11f4e411e079a6039`
- Parent V12 metrics были известны и byte-pinned до V13; это adaptive same-period
  challenger, а не независимая проверка.
- Signal: полный frozen V12 trend сохраняется только при строгом совпадении его знака со
  знаком annualized `(front / next - 1)` carry. Противоположный/нулевой наблюдаемый знак
  даёт cash; недоказанная кривая остаётся missing.
- Curve proof: `observed_through == decision_date`, availability `decision_close`,
  positive simultaneous settles, ordered expiries и независимый пересчёт каждого
  `roll_yield`.
- Coverage: 8 100/8 100 curve-valid source rows; OOS 5 084, из них 2 681 confirmed,
  1 363 observed-not-confirmed и 1 040 missing trend inputs.
- Execution: 261 weekly + 47 roll decisions, 1 232 target rows, 841 nonzero,
  coverage 841/841; primary 431 filled legs, 0 rejected, 0 critical, 0 unresolved.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 52,4579% | 8,8013% | 0,7081 | −20,6861% | 4/5 | 17 436,92 |
| 2 ticks + 2x fee | 51,8483% | 8,7142% | 0,7022 | −20,7601% | 4/5 | 34 753,47 |
| 4 ticks + 2x fee | 51,6187% | 8,6813% | 0,6999 | −20,8382% | 4/5 | 51 412,64 |

Primary годы: 2021 `+21,4803%`, 2022 `+20,0836%`, 2023 `+5,1862%`,
2024 `+1,2208%`, 2025 `−1,8406%`. Относительно V12 total return выше на 7,3465 п.п.,
CAGR на 1,0695 п.п. и worst year лучше на 0,7912 п.п.; одновременно Sharpe ниже на
0,0543, MDD хуже на 6,5336 п.п., costs выше на 4 049,64 RUB.

Maximum participation 0,1590%, maximum post-mark gross leverage 1,0524 и maximum 2x
modeled-margin/start-cash ratio 0,5043. Order-time gross/margin admission не отклонял
заявки; значение gross выше единицы возникло пассивно после mark/cash move между
ребалансировками. Terminal exit reserve 99,29 RUB оставляет return 52,4479%.

Sealed stability gate не пройден: и Sharpe, и MDD хуже frozen V12. Verdict: `NO_GO` как
replacement/стабилизатор. V13 можно помнить как агрессивный return-challenger, но нельзя
теперь подбирать carry threshold, blending weight или asset subset по тем же 2021–2025.

## V12: core-four correlation-aware trend — GO к unseen validation

- Протокол: [`configs/futures_v12_core4_correlation_trend.yaml`](../configs/futures_v12_core4_correlation_trend.yaml)
- Config SHA-256:
  `0b1a79d5c09cf40330886ebfba84bb9a7a8a84973301d59627200050e61b3e53`
- Canonical run:
  `runs/v12_core4_trend_20260831T182210Z_0b1a79d5/metrics.json`
- Metrics SHA-256:
  `c989377f7de65c3ef0a8dd52a1f5fcbf11c6ad8048119ea0a7b4402f47b23288`
- Input: byte-pinned V5 causal panel, active map, 66 052 contract observations и
  frozen conservative spec proxy; maximum factual date `2025-12-30`.
- Signal: одинаковый для BR/MIX/RI/SI risk-adjusted trend по 21/63/126/252 sessions;
  weekly last-session decision, covariance 60 sessions, 20% target vol, gross `<= 1`,
  five weekly turnover sleeves.
- Execution: exact next factual open, целые контракты, asset-atomic explicit rolls,
  participation `<= 1%`, current cash sizing, modeled 2x IM buffer, settlement VM.
- Counts: 261 weekly + 53 roll decisions, 1 256 target rows, 1 040 nonzero targets,
  coverage 1 040/1 040, 1 272 sessions, 429 primary filled legs, 0 rejected,
  0 critical failures и 0 unresolved halts.

| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB |
|---|---:|---:|---:|---:|---:|---:|
| 1 tick + 1x fee | 45,1114% | 7,7318% | 0,7624 | −14,1526% | 4/5 | 13 387,28 |
| 2 ticks + 2x fee | 40,8019% | 7,0841% | 0,7116 | −14,3150% | 4/5 | 26 601,80 |
| 4 ticks + 2x fee | 41,7324% | 7,2253% | 0,7207 | −14,3289% | 4/5 | 38 812,65 |

Primary yearly returns: 2021 `+17,5345%`, 2022 `+14,0141%`, 2023 `+7,7762%`,
2024 `+3,1900%`, 2025 `−2,6318%`. Stress не обязан быть монотонно хуже doubled,
потому что каждый scenario заново применяет integer sizing к собственному cash path;
fixed-primary-position cost diagnostic также остался положительным, но не участвует в gate.

Максимальная participation 0,1129%, gross leverage 0,9544, 2x modeled-margin ratio 0,4688;
нарушений cap нет. Terminal positions carried; exit reserve 173,40 RUB оставляет primary
return 45,0941%.

Verdict: `GO_TO_NEW_UNSEEN_VALIDATION`. Это adaptive same-period результат после уже
увиденных V5–V11 исследований, не независимый holdout и не разрешение на live. Запрещено
подбирать V12 параметры на 2021–2025. Следующее допустимое действие — byte-identical
проверка на новой unseen истории/рынке с broker/exchange exact specs и отдельный sealed
paper-forward protocol.

## V10/V11: triangular RI/MIX/SI relative value — закрыто, NO-GO

### V10: adverse-window execution

- Протокол: [`configs/futures_v10_triangular_relative_value.yaml`](../configs/futures_v10_triangular_relative_value.yaml)
- Config SHA-256:
  `4ff5c4cb84e5ecd608d69f5673a0e8af6e4f8103cea8f9cb348530e525e6103c`
- Canonical run:
  `runs/v10_triangular_20260831T171000Z_4ff5c4cb/metrics.json`
- Metrics SHA-256:
  `71ea94ec170544e35bb6e2896536d328bae71256537b84eec2990a98c4a0bb65`
- Signal: `log(RI) − log(MIX) + log(SI)`, prior 72 common observations, entry 2σ,
  take-profit 0,5σ, adverse stop 4σ, maximum 18 completed bars.
- Execution: exact next bucket; buy high/sell low; integer contracts; equal 30% leg
  budgets; signal and realized participation cap 1%; ordinary and doubled costs.
- Coverage: 169 071 common bars, 109 143 OOS bars, 31 953 eligible signal bars and
  3 329 raw threshold events.
- Fail-closed stop: after 4 completed trades, `2022-03-29 08:00 UTC`,
  `insufficient_entry_window_capacity`.
- Partial diagnostic only: return −2,5806%, CAGR −0,5230%, Sharpe −0,6344,
  MDD −2,5806%, 0/4 winners, costs 697,15 RUB. Full-period metrics are invalid.
- Verdict: `NO_GO_UNRESOLVED_EXECUTION`; live promotion forbidden.

### V11: liquidity-buffered next-open sensitivity

- Протокол: [`configs/futures_v11_liquidity_buffered_open.yaml`](../configs/futures_v11_liquidity_buffered_open.yaml)
- Config SHA-256:
  `584bf28977238681bfd90a39fa886eb0d1e1691a4799e041c4321d5bb02f400c`
- Canonical run:
  `runs/v11_buffered_open_20260831T171200Z_584bf289/metrics.json`
- Metrics SHA-256:
  `338fd41a35b64fe661112af389f17a1e4616c52d91cd8d41b4616aff0acb6ca1`
- Alpha and thresholds inherited unchanged from V10. Execution uses factual next-bucket
  open plus fee/one-tick cash cost, sizes from 0,25% of causal signal-bar volume, keeps a
  1% factual cap, cancels unfilled entries and retries a triggered exit for at most six
  exact same-contract buckets.
- V11 is explicitly adaptive after reading V10 on the same 2021–2025 period. It is
  hypothesis generation only and cannot make a confirmatory claim on this interval.
- Fail-closed stop: 10 completed trades, 12 exit retries, then
  `2022-06-06 11:10 UTC`, `exit_capacity_retry_limit`.
- Partial diagnostic only: return −0,6768%, CAGR −0,1361%, Sharpe −0,9736,
  MDD −0,6768%, win 20%, profit factor 0,1189, costs 1 899,99 RUB. At doubled costs:
  return −0,8668%, Sharpe −1,0571. Full-period metrics are invalid.
- Verdict: `NO_GO_UNRESOLVED_EXECUTION`. Семейство закрыто; не перебирать thresholds,
  stops, holding или capacity на уже просмотренной истории.

## V9: текущая серия challenger-экспериментов

### Structural futures breadth — условный lead

- Протокол: [`configs/futures_v9_structural.yaml`](../configs/futures_v9_structural.yaml)
- Config SHA-256:
  `c9aa50d3ea3f16e0aa8d729aef238b2d316e249c8277d39f573046880ea3ef68`
- Canonical run:
  `runs/futures_v9_structural/structural_c86d4852729d4c8a/results.json`
- Данные: official MOEX ISS, 22 candidate roots; warmup 2018–2020, OOS 2021–2025.
- Portfolio: weekly, 12% volatility target, gross `<= 1`, asset cap 15%, 5/10 bps.
- Среднее число eligible assets 17,71; минимум 15; максимум 20.

| Strategy | CAGR 5 bps | Sharpe | MDD | CAGR 10 bps | Verdict |
|---|---:|---:|---:|---:|---|
| `risk_adjusted_momentum` | 6,7745% | 0,7840 | −15,1293% | 5,3463% | Exact-execution candidate |
| `tsmom_multi` | 6,3111% | 0,7943 | −14,2108% | 4,7127% | Exact-execution candidate |
| `tsmom_6m` | 5,3410% | 0,8091 | −11,9518% | 4,1414% | Exact-execution candidate |
| `carry_momentum_confirmation` | 4,8860% | 0,5316 | −16,0089% | 3,2997% | Не продвигать |
| `tsmom_3m` | 4,7356% | 0,6598 | −13,0447% | 3,3803% | Не продвигать |
| `curve_carry` | 3,5365% | 0,5505 | −11,3214% | 2,0455% | Не продвигать |
| `tsmom_1m` | 1,4684% | 0,2344 | −16,1880% | −0,3376% | NO-GO |
| `tsmom_12m` | 1,2494% | 0,2032 | −17,4967% | 0,2733% | NO-GO |

Ограничение: это fractional daily proxy с flat-bps costs, не broker-exact PnL.

### Structural robustness — предупреждение

- Протокол: [`configs/futures_v9_structural_robustness.yaml`](../configs/futures_v9_structural_robustness.yaml)
- Config SHA-256:
  `49553bc70e36f842fb89ea387d202b4c918cda7ae327b756e101cdcfe3184daa`
- Canonical run:
  `runs/futures_v9_structural_robustness/robustness_870183b62323f8bb/audit.json`
- CSCV splits: 252; PBO-style risk 69,84%; selected OOS Sharpe `<= 0` — 22,22%.
- Median selected OOS Sharpe: 0,4038.
- RAM и `tsmom_multi` коррелируют на 0,9641; `tsmom_multi` и `tsmom_6m` — 0,8883.
- Verdict scope: promotion только к exact-execution validation, никогда прямо к live.

### Structural execution — NO-GO/blocker

- Протокол: [`configs/futures_v9_structural_execution.yaml`](../configs/futures_v9_structural_execution.yaml)
- Config SHA-256:
  `5619d5798e66360d84cc8d81e103f6d2deb5f864edc3ea01418a3a7d1f2e8f45`
- Canonical run:
  `runs/futures_v9_structural_execution/execution_8a934dfae72c769c/results.json`
- Input coverage: official daily OPEN 69,58%; realized point-value proxy 86,86%; sizing
  proxy 64,09%.
- RAM ordinary: 308/1 259 sessions; stopped `2022-03-18` на
  `GBPU:GUH2:missing_settle_or_contract`; full-period metrics invalid.
- Причина NO-GO: нет historical exchange/broker specs, fees и IM для 21 root; existing
  5/10/20 bps и 25% IM являются сценариями.

### Event Alpha V1 — маленький lead

- Протокол: [`configs/event_alpha_v1.yaml`](../configs/event_alpha_v1.yaml)
- Config SHA-256:
  `91f61abea2e4ca53179c9d5d085cbe98a8b6b863404050af547873c49cca7330`
- Canonical run:
  `runs/event_alpha_v1/development_20260818T155959Z_91f61abe/`
- Ridge `alpha=10`, purged expanding years 2021–2025, 10 bps round trip.
- Key-rate 1d: 31 events, 14 trades, CAGR 1,17%, Sharpe 0,523, MDD −0,38%, hit 71,43%.
- Corporate reporting и 30-minute horizon sleeping; synthetic documents не использовались.

### Frozen event + 10m timing hybrid — timing не помог

- Протокол: [`configs/futures_v9_event_timing_hybrid.yaml`](../configs/futures_v9_event_timing_hybrid.yaml)
- Config SHA-256:
  `92e98a7252d74bc099ef93a86d8f37eb011b11bebbe2c42b870568236b0f3465`
- Canonical run:
  `runs/futures_v9_event_timing_hybrid_development_20260818T170400Z_92e98a72/`
- Key-rate baseline: 10 trades, CAGR 0,99%, Sharpe 0,82, MDD −0,47%, hit 90%.
- Combined baseline: 36 trades, CAGR 0,42%, Sharpe 0,18, MDD −4,68%.
- Все четыре timed variants сделали 0 trades; neural gate не улучшил вход.

### Corridor competing risk — NO-GO

- Протокол: [`configs/futures_v9_corridor.yaml`](../configs/futures_v9_corridor.yaml)
- Config SHA-256:
  `aeb3b24fbb21b9400a6643815a9ad9488b91ef714358ea880cdb71c83c952053`
- Canonical run: `runs/futures-v9-corridor-development-v1/`
- Primary TP/SL: 0,8/2,8 ATR; same-bar stop-first; five-session exact time exit.
- 1×: 58 trades, CAGR 0,4574%, Sharpe 0,3480, MDD −2,4487%, win 65,52%.
- Nominal break-even win rate 77,78%; deficit −12,26 percentage points.
- 2× CAGR 0,4275%; safer 1,2/1,6 diagnostic CAGR −1,1075%, Sharpe −0,748.

### Continuous 10m timing — NO-GO

- V1 config: [`configs/futures_v9_intraday_timing.yaml`](../configs/futures_v9_intraday_timing.yaml),
  SHA `fd6ee70086bc7056ca60c73a91490362aae37c4caf053091cc73e2e0924159cf`.
- V2 config: [`configs/futures_v9_intraday_timing_v2.yaml`](../configs/futures_v9_intraday_timing_v2.yaml),
  SHA `4268723dbeca5408592399b680af36216f8f70cd7ca6439811d706e7977d3dcc`.
- Canonical V1 run: `runs/futures_v9_intraday_timing_full_20260818T163148Z/`.
- Canonical V2 run: `runs/futures_v9_intraday_timing_v2_full_20260818T164623Z/`.
- 440 094 OOS asset-decisions, 2021–2025, three fixed seeds.
- V1 attention/independent: 0 trades из-за sealed SNR; maximum SNR 0,584/0,680.
- Даже top 0,1% prediction tail имел отрицательное realized net action value.
- Breakout baseline: 6 894 trades, CAGR −53,71%, Sharpe −9,97, MDD −97,84%.
- V2: все 60 fold/variant/side/horizon gates sleeping; 0 trades.

### Market graph — NO-GO

- V1 config: [`configs/market_graph_v1.yaml`](../configs/market_graph_v1.yaml), SHA
  `4ced820c7ec5f589a5fe7f6cc4a797b65ed3013d6b4aaa3a169d0ca225819344`.
- Canonical V1 run: `runs/market_graph_v1_20260818T164732Z/`.
- Full graph IC −0,00639 против no-attention −0,00436; paired difference −0,00203,
  normal 95% interval `[−0,01180; 0,00775]`.
- Full graph: CAGR −10,32%, Sharpe −1,398, MDD 43,86%; promotion false.
- Relative momentum имел IC 0,04890, но sealed long/short CAGR −4,83% после costs/borrow.
- V2 config: [`configs/market_graph_v2_long_only.yaml`](../configs/market_graph_v2_long_only.yaml),
  SHA `50ff5688535b852a16b40e34aaf630935c9425259bdf45b3677d496aee554a01`.
- Canonical V2 run: `runs/market_graph_v2_long_only_20260819T074638Z/`.
- Top5/keep10: CAGR 1,2877%, Sharpe 0,1803, MDD 49,34%, worst year −38,09%,
  passive beta 0,901; at 2× costs CAGR 0,2672%. Исследовательское решение — NO-GO.

## V8: сохранённый, но незавершённый контур

- Base run: `runs/v8_20260818T111317Z_83135473/`.
- 15/15 моделей, 5 076 OOS predictions, SHA
  `ca7dae8d856e512a6b3e476662b73d7d7f4f87521f0c103606b147f117acd437`.
- Regime V2: `runs/v8_20260818T111317Z_83135473_enrichment_regime_v2/`.
- Raw-10m context V2:
  `runs/v8_20260818T111317Z_83135473_context_raw10m_v2/`.
- Authoritative PnL не рассчитан: admission trust anchor остаётся placeholder, admission
  certificate отсутствует. Не трактовать training completion как trading result.

## Legacy-результаты

| Контур | Результат | Решение |
|---|---|---|
| SBER MVP | 2026 уже участвовал в iterative selection | Только legacy/exploratory |
| Alpha50 XGBoost ranker | validation CAGR 34,42%; просмотренный 2026 holdout −15,84% | NO-GO |
| Daily residual TCN | CAGR −2,23%, Sharpe −0,148, MDD 28,99%, IC 0,0258 | NO-GO |
| Fixed 15-rule probe | best +7,01%, но selected на тех же folds и positive 2/4 | NO-GO |
| Futures V6 | CAGR 2,396%, Sharpe 0,300; worst fold отрицателен | NO-GO |
| Futures V7 | CAGR 0,670%, Sharpe 0,117; 2× costs CAGR −0,023% | NO-GO |

## Superseded и недействительные run

| Path относительно external root | Статус |
|---|---|
| `runs/futures_v9_structural/structural_bb356559262f8fb7/` | INVALIDATED: accounting bug |
| `runs/futures_v9_structural/structural_a3ffe0286b44b38c/` | Superseded implementation revision |
| `runs/futures_v9_structural/structural_d1f5eac9c2cf9ddb/` | Superseded implementation revision |
| `runs/futures_v9_structural_robustness/robustness_f87dc82859c38fb6/` | Superseded audit |
| `runs/futures_v9_structural_robustness/robustness_e0e18f1cd8284e62/` | Superseded audit |
| `runs/futures_v9_structural_execution/execution_4585b145edf0d4e8/` | Superseded incomplete execution |
| `runs/futures-v9-corridor-development-v1.invalid-carry-fx-causality/` | INVALID: carry/FX causality |
| `runs/futures_v9_event_timing_hybrid_development_20260818T170000Z_92e98a72/` | Byte-identical duplicate; use 170400Z |
| `runs/market_graph_v2_long_only_20260819T074419Z/` | Superseded; final cap diagnostics are in 074638Z |

Остальные timestamp-run считаются legacy/scratch, пока явно не внесены в этот реестр.
