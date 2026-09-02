# Независимый forward-протокол V27

## Зачем

V27 — сильнейший development-кандидат лаборатории: primary CAGR `28,3752%`, Sharpe
`1,2119`, MDD `20,7138%`; doubled/stress CAGR `27,6201%/27,3643%`. Но V27 был создан
после просмотра V26 на том же периоде 2021–2025. Это `GO_TO_NEW_UNSEEN_VALIDATION`,
не доказательство будущих 20% и не разрешение live trading.

Forward protocol SHA `c1acf97b...` запечатан `2026-09-02` до post-seal market prices.
Он byte-pin-ит V27 SHA `7a9a44cf...` и запрещает менять сигнал, 2x multiplier,
STLFSI4 boundary `0`, key-rate boundary `20%`, RUONIA haircut `50%`, costs, buffer,
capacity или universe по forward outcome.

До первого сохранённого snapshot выявлена семантическая ошибка источника: current
MOEX `LAST` — последняя внутрисессионная сделка, а byte-identical V12/V27 требует
official daily `CLOSE`. Поэтому V1 source не используется. Корректирующий V2 SHA
`f4a7d016...`/commit `941e0b9` не меняет экономику или параметры и был запечатан до
просмотра post-seal CLOSE. Реализация commit `09e73c4` имеет SHA `f38a41f0...`.

До первого V2 snapshot в collector добавлены только повторы exact HTTP request после
transport exception. Чтобы не переписывать sealed V2/paper/V39 protocols, создан
отдельный compatibility protocol SHA `ae70f0d4...`: original build `f38a41f0...`,
approved build `7a6f5732...`. Он fail-closed запрещает новые endpoints/query,
normalization/schema/availability changes, cache, backfill, partial persistence и любое
изменение economics. Первый запуск `2026-09-02 10:05` не сохранил snapshot, поскольку
FRED сбросил соединение после всех retries; readiness поэтому остаётся `0`, без
подстановки старого/current-vintage значения.

## Источник

`market_lab.futures.moex_v27_forward_validation_source` сохраняет два immutable вида
snapshot по будням:

- `execution_observation` в 10:05 мск: фактический next-session open и bid/offer;
- `decision_eod` в 23:45 мск: полные текущие цепочки SI/RI/BR/MIX после сессии.

Каждый snapshot содержит raw MOEX JSON всех listed contracts, current specs/IM/fees,
actual retrieval и exchange timestamp. Для `decision_eod` V2 дополнительно сохраняет
raw official daily history каждого unexpired контракта; только его `CLOSE` идёт в
сигнал, а `VOLUME/OPENPOSITION` — в causal roll. Missing history row отклоняет весь
snapshot; `LAST` и `SETTLEPRICE` никогда не подменяют `CLOSE`. Одновременно сохраняются
raw current-vintage FRED `STLFSI4`, CBR RUONIA и KeyRateXML. Для macro history
`forward_available_at = max(model_available_at, actual_retrieval)`, поэтому текущий
vintage не выдаётся за исторически известный оригинал.

Market date раньше `2026-09-02` запрещена; market backfill за январь–август 2026 и
pre-2026 warmup запрещены. Missing session/contract/quote остаётся missing.

## Последовательная проверка

Paper protocol SHA `d68f0595...`/commit `51acd4c` запечатан до первого valid snapshot;
preflight commit `05a1f74` ничего не вычисляет кроме source/readiness checks.

1. Для 252 return observations нужны 253 common `decision_eod` price sessions. Это
   warmup четырёх momentum horizons и covariance; PnL периода не является результатом.
   Partial current `W-SUN` week не считается завершённой.
2. Следующие минимум 504 sessions / 104 weekly decisions / два полных календарных года —
   первая независимая evaluation без изменения параметров.
3. Требуются CAGR `>=20%` во всех трёх cost-сценариях, Sharpe `>=1`, MDD `<=30%`, два
   положительных года, неотрицательный худший год, zero critical/unresolved и
   положительный observed-quote paper ledger.
4. Даже numeric GO требует ещё одного unseen confirmation и broker-exact audit.

Короткая annualization до 504 evaluation sessions не может доказывать стабильные
20–50% годовых.

## Операции

```powershell
.\scripts\register_v27_forward_tasks.ps1
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_validation_readiness `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v2
```

Tasks: `TradingLabV27ForwardExecution` и `TradingLabV27ForwardDecision`. Wrapper не
создаёт второй audited snapshot одинакового `kind + source_date`. Каталоги forward data
и будущего paper PnL находятся вне Git.

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_paper_preflight `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v2
```

Hard fallback за пять сессий до expiry требует official machine-readable calendar
MOEX. Он доступен через `https://iss.moex.com/iss/calendars/futures`, но текущая среда
не имеет `MOEX_ALGOPACK_TOKEN`; без него endpoint вернул HTML. Generic business days и
календарь, восстановленный из будущих цен, запрещены. Source продолжает накапливаться,
но paper economics/promotion остаётся fail-closed до авторизации календаря.
