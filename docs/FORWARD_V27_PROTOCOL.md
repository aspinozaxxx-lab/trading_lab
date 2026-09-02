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
изменение economics. Первый atomic запуск `2026-09-02 10:05` не сохранил snapshot,
поскольку FRED сбросил соединение после всех retries; никакое старое/current-vintage
значение не подставлялось.

Чтобы outage одного провайдера не стирал независимо полученный официальный рынок,
до первого decision snapshot запечатан component source SHA `242d2684...`. Реализация
`026fef9f...` сохраняет `market_execution`, `market_decision`, `macro_fred` и
`macro_cbr` в отдельных immutable каталогах; readiness `d7b4d30a...` аудитит каждый.
Компонент остаётся atomic внутри себя. При этом completed MOEX не удаляется из-за FRED,
а macro можно присоединить только если его actual `retrieved_at <= decision_at`;
будущий snapshot не ремонтирует прошлое решение.

Старый anonymous `fredgraph.csv` route с research User-Agent стабильно зависал, тогда
как тот же exact URL с browser-compatible User-Agent отвечал. До чтения первого ответа
запечатан transport-only config SHA `8a26480d...` и общий admission SHA `62ca9450...`.
Source V2 (`5cf38c92...`) меняет только HTTP headers; endpoint, query, `STLFSI4`, parser,
availability и macro join неизменны. При валидном process environment `FRED_API_KEY`
по-прежнему выбирается authenticated config SHA `2954c5a4...`; без ключа выбирается
только anonymous header V2. После ошибки выбранного route fallback на другой запрещён,
а ключ не передаётся через CLI и не пишется в config/raw/manifest/log.

Dispatcher/readiness V3 deployed commit `799656f`. Первый V2 component
`snapshot_macro_fred_transport_v2_20260902T221948066517Z` содержит 57 current-vintage
rows, прошёл source replay `15/15`; manifest/audit SHA
`e1d7b83c.../5d34f36f...`. Readiness: 4 valid, 0 invalid, execution/decision/FRED/CBR
`1/1/1/1`, macro ready true. Causally joinable decisions пока `0`: FRED retrieved
позже уже сохранённого decision, и это прошлое решение намеренно не исправляется.

## Источник

Scheduled source теперь использует
`market_lab.futures.moex_v27_forward_component_source` и сохраняет два immutable market
component:

- `execution_observation` в 10:05 мск: фактический next-session open и bid/offer;
- `decision_eod` после публикации official history: retry grid 00:45/01:15/06:00 мск
  Tue–Sat для предыдущей торговой даты.

Первый server attempt в 23:45 мск `2026-09-02` правильно завершился без output: хотя
current chain уже существовал, хотя бы у одного listed контракта ещё не было exact
official history row. Не читая market/PnL values, повторный неизменный запрос в 00:45
получил полный component на 25 contracts и прошёл raw replay. Operational schedule V2
SHA `48f16f2c...` запечатан до будущих session outcomes. Повторные 01:15/06:00 attempts
аудитят и пропускают уже сохранённый `kind + source_date`; они не создают дубликат и не
меняют время доступности первого успешного snapshot.

Каждый snapshot содержит raw MOEX JSON всех listed contracts, current specs/IM/fees,
actual retrieval и exchange timestamp. Для `decision_eod` V2 дополнительно сохраняет
raw official daily history каждого unexpired контракта; только его `CLOSE` идёт в
сигнал, а `VOLUME/OPENPOSITION` — в causal roll. Missing history row отклоняет весь
snapshot; `LAST` и `SETTLEPRICE` никогда не подменяют `CLOSE`. Отдельно пытаются
сохраниться raw current-vintage FRED `STLFSI4` и paired CBR RUONIA+KeyRateXML. Для macro
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
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_component_readiness_v3 `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v3-components
```

Legacy Windows registration script не запускать при активном `gpu-mlserver`; локальные
tasks отключены и не являются authoritative scheduler.

Server timers: `trading-lab-v27-execution.timer` и
`trading-lab-v27-decision.timer`. Dispatcher не
создаёт второй audited market component одинакового `kind + source_date`; macro
сохраняется максимум один раз на текущую UTC/source date. Required market failure
останавливает task, optional FRED/CBR failure остаётся явным в readiness. Каталоги
forward data и будущего paper PnL находятся вне Git.

Для authenticated FRED route ключ задаётся только вне репозитория в server file
`/etc/trading-lab/collector.env`. Не вставлять его в командную строку, YAML или
документацию. Следующий service process сам выберет API route; readiness показывает
только boolean `configured` и раздельные anonymous-v1/anonymous-v2/authenticated counts.

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v27_forward_paper_preflight `
  --output-root D:\Projects\trading_lab_data\data\forward\v27-validation-v2
```

Старый paper preflight пока указывает на пустой atomic V2 и сохраняется только как
sealed reference. До реализации component-aware paper ledger economics всё равно
запрещена.

Hard fallback за пять сессий до expiry требует official machine-readable calendar
MOEX. Direct ISS без авторизации возвращает HTML, однако публичная страница календаря
содержит server-side structured `__NEXT_DATA__.offDays.futures`. Новый transport
запечатан SHA `8380d1a0...`, admission SHA `9dc8ef1f...`; первый immutable server
snapshot `snapshot_calendar_20260902T225345007058Z` прошёл replay `18/18` и содержит
`485` дат до `2027-12-31`, unknown `0`. Daily timer работает в `00:20` МСК.

Calendar readiness выбирает только snapshot с `retrieved_at <= decision_at`, требует
непрерывные известные calendar dates и как минимум шесть следующих trading sessions,
чтобы причинно решить правило `<=5`. Generic business days, `null` substitution,
восстановление из цен и backfill запрещены. Source blocker снят только для решений
после первого retrieval; component-aware paper ledger по-прежнему не разрешён до
остальных warmup/execution/macro условий.
