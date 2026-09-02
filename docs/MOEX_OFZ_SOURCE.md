# Official MOEX OFZ source and next economic protocol

## Canonical source

Новый независимый return-engine candidate подготовлен без вычисления доходности:

- protocol `moex_ofz_total_return_source_r2`, config SHA `227b1641...`;
- implementation commit `7ae803b`, R2 SHA `70f6e58c...`;
- external path
  `data/processed/ofz/moex-ofz-history-bondization-2021-2025-v1/`;
- manifest/audit SHA `102b4add.../809eef13...`, audit `all_true=true`;
- history/bondization SHA `f045482b.../d69be407...`;
- `70 896` history rows, `1 271` trade dates, `83` securities, `67 249` rows with
  positive trades/value/close, `676` coupon and `32` amortization events, `0` offers.

Source содержит official TQOB daily `OPEN/CLOSE/WAPRICE/LEGALCLOSEPRICE`, `ACCINT`,
yield, maturity/duration, coupon/face value и liquidity. Bondization отдельно хранит
coupon/amortization/offer schedules. Return, label, signal, target, order, position,
PnL и equity отсутствуют. Market rows с `2026-01-01` и позже отсутствуют.

## Исправления transport

V1 board-wide `from/till` был fail-closed до output: MOEX проигнорировал range и вернул
только `59` rows за `2026-09-01`; были просмотрены лишь dates/counts, не market values.
R1 перешёл на explicit `date=` для каждого календарного дня и embedded raw container,
но остановился до output на неверном namespaced schedule cursor. R2 заменил только
`coupons.start`/аналогичные параметры на global `start`; market fields и hypothesis не
менялись. После отдельного исправления permission output был опубликован атомарно.

Не повторять collection и не перезаписывать canonical source. Разрешён только R2
`--audit` из [RUNBOOK](RUNBOOK.md).

## Ограничения

- History и bondization — current-vintage public ISS, не original exchange feed.
- Bondization разрешён для бухгалтерского восстановления cashflow, но не как
  historical predictor: его `available_at` равен фактическому retrieval.
- Daily data не доказывают bid/ask, size, queue или broker fill.
- Historical LOTSIZE/fees/tax и eligibility OFZ as futures collateral не доказаны.
- Пропуски нельзя заменять нулями, WAP/CLOSE нельзя объявлять executable bid/ask.

## Следующий V52 seal до чтения market values

До открытия `ofz_history.parquet` и вычисления любой доходности зафиксировать ровно
один economic candidate. Рекомендуемый механизм для preseal:

1. Только fixed-coupon series `SECID` prefix `SU262`, RUB face unit.
2. Monthly decision после завершённой последней сессии месяца; execution не раньше
   следующего factual positive `OPEN`.
3. Remaining maturity `2–7` years, prior 20-observation median VALUE не ниже заранее
   заданного абсолютного floor; выбрать ровно три наиболее доходных по prior
   `YIELDATWAP`, equal weight. Threshold и top count после outcome не менять.
4. Dirty price = clean percent × face value + `ACCINT`; coupons/amortization credit
   только по explicit schedule/record entitlement. Missing cashflow/price означает
   sleep/unresolved, не zero.
5. Обязательные fixed one-way execution stresses `10/20/40` bps, integer lot only
   после отдельного LOTSIZE evidence; до него результат fractional proxy.
6. Сначала standalone OFZ metrics, затем один заранее заданный fully-funded portfolio
   с frozen V49/V42R2. Не перебирать duration, liquidity floor, top count, weights,
   rebalance day или trend filter на 2021–2025.
7. Главный gate — не только CAGR: worst bootstrap q05, rolling 252/504 fraction above
   20%, leave-2022-out, correlation with frozen V49/V42R2 and all-cost MDD.

Даже pass требует forward TQOB bid/offer collector, broker fees/tax/settlement
reconciliation и второго unseen периода; live trading остаётся запрещён.

