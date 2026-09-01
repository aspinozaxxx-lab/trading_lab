# Forward-протокол для equity microstructure

## Зачем нужен новый период

V35 показала, что price-only residual reversion имеет слишком маленький gross edge:
`0,858 bp` на исполненной primary выборке против `20 bp` round trip. Новая версия не
имеет права ослаблять threshold, менять знак или horizon по этому результату. Проверять
можно только новую информацию, которой V35 не видела: aggressive trade flow, постановки
и снятия заявок, глубину/спред, реальные short locate/borrow и paper fills.

Этот документ не разрешает live trading и не разрешает читать protected prices 2026.
Он задаёт source collection и будущую последовательность решений. Economic protocol
может быть создан только отдельным seal при соблюдении действующей границы данных.

## Обязательные источники

1. MOEX ALGOPACK equity `tradestats`, `orderstats`, `obstats` через authorized `apim`.
2. Actual broker short-locate availability и borrow rate с timestamp для каждой бумаги.
3. Point-in-time lot size, комиссии и тарифы брокера/биржи.
4. Paper orders/fills: decision, submit, acknowledgement, partial fills, rejects,
   cancellation, realized spread и latency. Candle value не заменяет fill evidence.

Bearer token хранится только в `MOEX_ALGOPACK_TOKEN`. Его нельзя помещать в `.env`, Git,
manifest, raw response, log или документацию.

## Сбор MOEX

Collector:
`market_lab.stocks.moex_forward_equity_microstructure_source`.

- cadence: каждые пять минут в торговые часы;
- frozen universe: 30 tickers из V35, без post-hoc исключений;
- каждый invocation создаёт новый immutable `snapshot_*`;
- request: три full-universe `latest=1` endpoint;
- сохраняются raw gzip, URL, bytes/SHA, exchange `SYSTIME`, actual retrieval и
  `available_at=max(SYSTIME+1 minute,retrieval_at)`;
- запрещены `pr_*`, все price VWAP, return, label, target, PnL;
- пропущенный snapshot не backfill-ится и не заменяется соседним.

Минимальные source gates до любого model design review:

- 60 полных торговых сессий discovery collection;
- scheduled snapshot coverage `>=95%`;
- доля rows с `available_at` не позже следующего planned decision `>=95%`;
- exact три datasets; отсутствие одного — mask/sleep для ticker-time;
- universe coverage отдельно по ticker/dataset/day;
- raw replay и artifact identity checks должны быть 100%;
- ни одного persisted token или forbidden price/outcome column.

## Заранее ограниченный пул механизмов

После source gates допускаются ровно три экономически разные модели; список должен быть
sealed до первого разрешённого label/PnL read:

1. `flow_continuation`: aggressive buy/sell imbalance подтверждается book imbalance и
   net order addition (`put - cancel`) в ту же сторону;
2. `liquidity_vacuum_reversal`: price-independent экстремальный spread/depth shock и
   cancel imbalance иссякают, а противоположный aggressive flow восстанавливается;
3. `cross_asset_lead_lag`: masked model одновременно видит causal state всех 30 акций и
   оценивает, какой ticker ещё не отреагировал на synchronized sector/market flow.

Price-only V35 rule обязателен как frozen baseline. Нельзя добавлять четвёртый механизм
по результатам первых двух и нельзя инвертировать их sign post-hoc.

## Последовательная оценка

1. `collection/discovery`: первые 60 полных сессий. Их можно использовать только для
   schema, missingness, scaling и обучения после отдельного economic seal.
2. До любого результата фиксируются universe, features, model seeds, labels, thresholds,
   horizon, execution, capacity, borrow, costs, folds и gates.
3. `paper calibration`: следующие 20 сессий, только причинный выбор одного из заранее
   заданных thresholds; параметры модели не подбираются по paper PnL.
4. `paper evaluation`: ещё 40 полностью unseen сессий. Никакого retrain/threshold change
   внутри окна; skipped/rejected/partial orders считаются.
5. Даже успешные 40 сессий дают только `GO_TO_LONGER_FORWARD_VALIDATION`, не live.

Минимальный evaluation report: decision/signal/trade counts, coverage и unresolved,
gross/net PnL, CAGR как явно нестабильная annualization, Sharpe, MDD, daily distribution,
turnover, commissions, spread/slippage, borrow, capacity, per-year/phase breakdown,
1x/2x costs и сравнение со frozen price-only baseline.

## Promotion gates

Предварительные, но обязательные для будущего seal верхнего уровня:

- full microstructure model лучше price-only и aggregate-only baseline по unseen net
  return и Sharpe;
- primary и doubled-cost net positive;
- primary Sharpe `>=1` и MDD `<=15%` на paper evaluation;
- zero unresolved exits, zero locate violations, zero forbidden backfill;
- не менее 200 completed baskets и не менее 30 distinct sessions with trades;
- neither a 20% nor 50% annual claim may be made from 40 sessions alone.

## Текущий blocker

На 2026-09-02 `MOEX_ALGOPACK_TOKEN` отсутствует. Synthetic collector tests проходят,
но real-time source rows равны нулю. Первый практический шаг — оформить ALGOPACK access,
задать token только в process environment и включить внешний five-minute scheduler.
