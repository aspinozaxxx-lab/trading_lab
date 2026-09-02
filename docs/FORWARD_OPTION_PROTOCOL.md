# Forward-протокол опционной премии

Цель — проверить независимый механизм дохода: продажу дорогой реализуемой волатильности
через конструкции с заранее ограниченным убытком. Это не разрешение продавать голые
опционы и не обещание 20–50% годовых.

## Источник

Каждый EOD snapshot `moex-options-surface-v1` сохраняет original MOEX JSON для
`Si/RTS/BR/MIX`, actual retrieval time и нормализованные contract metadata, bid/offer,
settlement, underlying settlement, volume, OI и действующие комиссии. `available_at`
равен фактическому получению. Historical backfill этим endpoint запрещён; старые
эксперименты не могут читать forward-каталог.

Первый snapshot:
`data/forward/moex-options-surface-v1/snapshot_20260901T230311250639Z/`, 2 062 rows,
source date `2026-09-01`, manifest SHA `a4040403...`, processed SHA `579211bb...`,
audit SHA `5954d258...`, 17/17 checks true. Двусторонние положительные quotes: 532.

## Замороженная последовательность

1. Первые 60 уникальных EOD snapshots — discovery только для schema, liquidity,
   стабильности серий и определения достижимых delta/moneyness buckets.
2. Следующие 20 — calibration. На них разрешается выбрать один вариант только из
   заранее описанного bounded family и один фиксированный risk budget.
3. Следующие 40 — полностью unseen evaluation. Их нельзя использовать для изменения
   strikes, expiry, stop/wings, filters, sizing или execution assumptions.
4. Даже успешный результат остаётся paper-only до broker quotes, margin/exercise audit
   и нового forward confirmation.

## Допустимое семейство гипотез

- defined-risk iron condor: short внутренние call/put и long дальние wings той же серии;
- delta-aware или moneyness-aware hedged short straddle/strangle только при наличии
  фактических двусторонних котировок всех ног;
- corridor premium: фиксация прибыли при сжатии/истечении премии, дальние wings задают
  максимальный убыток; дополнительный stop не может считаться гарантированным fill.

Голые short options, синтетические quotes, THEOR_PRICE как исполнимая цена, перенос
ликвидности между strikes/сериями и выбор лучшей стратегии по evaluation запрещены.

## Execution и gates будущего economic seal

- решение только после сохранённого snapshot, entry не раньше следующего observable
  snapshot/сессии;
- short fills по bid, long fills по offer; отсутствие любой ноги означает no trade;
- fees/exercise, slippage, margin и expiry cashflows считаются для каждой ноги;
- maximum loss конструкции известен до entry, risk per position ограничен;
- обязательны primary/doubled/stress costs, tail-gap stress и zero unresolved exits;
- promotion: all-cost CAGR `>=20%`, Sharpe `>=1`, MDD `<=25%`, достаточное число сделок,
  положительные независимые подпериоды и отсутствие доминирования одной даты;
- `50%` остаётся aspirational и требует тех же gates, а не повышенного плеча.

Экономический код/параметры нельзя создавать до завершения discovery window; этот файл
фиксирует порядок и предотвращает преждевременное чтение будущих labels/PnL.

## Автоматическое накопление

Server timer `trading-lab-option-surface.timer` запускает
`market_lab.ops.forward_collector --job option-surface` Mon–Fri в 23:55 UTC+3. Dispatcher сначала
запрашивает только текущую `TRADE_SESSION_DATE`; существующая дата означает clean skip,
новая — единственный полный snapshot. Task использует `StartWhenAvailable`, запрещает
параллельные экземпляры и останавливает зависший run через 15 минут. Состояние timer и
число уникальных source dates нужно проверять при каждом продолжении исследования.
Проверка выполняется модулем `market_lab.futures.forward_option_readiness`: он повторяет
raw replay audit, исключает invalid/duplicate dates из прогресса и держит явные gates
`economic_protocol_may_be_sealed`, `calibration_complete` и
`unseen_evaluation_complete`. Даже последний gate не разрешает live trading автоматически.
