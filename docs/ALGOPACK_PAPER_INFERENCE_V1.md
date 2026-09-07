# AlgoPack future-paper inference core V1

2026-09-07. Продолжение [trained pair](ALGOPACK_PAPER_TRAINING_V1_RESULT.md), не новый fit
и не допуск к2026 prices. Реализован вычислительный компонент; полноценного future
runtime/source/execution/evaluation seal пока нет, F не назначена.

## Что реализовано

`src/market_lab/futures/algopack_paper_inference_v1.py`:

- `load_fixed_models` читает только pinned training manifest и две model JSON. Проверяет
  exact manifest/model SHA, статус, completion time,20/40feature schemas,4targets,
  alpha10/SVD/training_rows56996 и numeric model/scaler structure. Price/label tables
  не читаются. Родительские модели, normalization и training code не изменяются.
- `ContractPlan` имеет effective date, expiry, exact contract/SECID, actual available_at
  и provenance SHA. Принимается последний план, реально доступный на cutoff, только
  для текущей Moscow date и вне expiry day. Конфликт одновременных версий — ошибка.
  Политика metadata discovery/выбора контракта остаётся обязанностью future source.
- `prepare_features` принимает только plans/prices/flow, без labels/targets/PnL.
  Information E остаётся weekdays10:10–17:00Moscow на10m grid. Это математическое окно,
  НЕ замена official trading calendar/session admission.
- Prices выбираются last-as-of input_cutoff; одинаковый receipt с разными версиями
  отклоняется. Невалидная последняя версия не заменяется удобной более старой.
  Exact-contract seven-bar lookback и fixed price formulas взяты из sealed model core.
  Pre-F price objects запрещены целиком; reader обязан отсеять их ДО IO, а не только
  после создания объектов. Roll/gap/partial receipt сохраняются masks.
- Flow использует online `select_flow`, НЕ archive `select_training_flow`. Требуются
  actual receipt<=input_cutoff, paired buckets E−5/E, их начала>=F. Поздние revisions
  не изменяют подготовленный snapshot. Old flow может читаться source-only, но не
  используется для warmup будущего model arm до F.
- Price-only и price+flow имеют отдельную eligibility: нет flow — baseline всё ещё
  может прогнозировать. Нет любого joint price input — обе модели sleep. Future
  label validity никак не влияет на eligibility или candidate denominator.
- `predict_prepared` проверяет обе frozen модели и возвращает `UNPUBLISHED` result:
  per-arm status/predictions, exact target order, source/plan/version provenance и
  feature values. Это ещё не записанный рыночный прогноз и не заявка.
- `complete_forecast` вызывается ПОСЛЕ вычисления с фактическим clock. Если завершение
  не раньше E+10m, обе prediction=null/MISSED_PUBLICATION_DEADLINE. Успешный результат
  имеет `COMPUTED_NOT_PERSISTED`, planned entry E+10, target exit E+70; execution=false.
  Будущий writer должен отдельно подтвердить durable publication до entry; одной
  этой функции недостаточно для допуска сделки. Нельзя менять эти clocks на schedule.

## Проверки и ограничения

20synthetic tests: separate-arm missingness, gaps/rolls, price invalid revision, tied
version conflicts, поздние plan/flow/price versions, pre-F refusal, entry deadline,
no target API, model byte changes и isolated three-file model reader. Synthetic F и
synthetic model SHA подставлены ТОЛЬКО в fixtures; это не действующий paper admission.

Ни network requests, ни collectors/timers, ни forecasts на реальных2026 данных этим
изменением не включаются. Успешный decode обученных моделей не является прогнозом.
Нужны future source/runtime/protocol: pre-request F gate, witnessed candles, append-only
forecasts/receipts, official sessions, exact quotes/specs/fees, quantity/capacity,
costs1x/2x и фиксированные economic/coverage/stability критерии ДО новых outcomes.

## Проверенный путь к своевременным ценам

Официальная [документация futures candles](https://moexalgo.github.io/docs/api/get-futures-candles/)
различает authorized apim real-time и anonymous ISS с15мин задержкой. Для нашего E+10
entry нельзя молча перейти на задержанный источник: итогом были бы пропуски, а не
доказательство отрицательного сигнала. [Futures orderbook](https://moexalgo.github.io/docs/api/get-futures-orderbook/)
описан как subscriber real-time,20уровней каждой стороны. Наличие доступа нашего
конкретного account ещё НЕ проверено запросом: цены до F по-прежнему закрыты.

[Описание полей](https://moexalgo.github.io/docs/description/realtime/) задаёт begin/end
свечей, PRICE/QUANTITY/SEQNUM/UPDATETIME стакана и metadata MINSTEP/STEPPRICE/LOTVOLUME/
INITIALMARGIN/BUYSELLFEE. UPDATETIME без даты и SEQNUM нельзя самовольно объявить полным
exchange timestamp. Нужны отдельные receipt/session/freshness gates; advertised real-time
не является доказательством exact fill или гарантированной задержки.

[Futures session API](https://moexalgo.github.io/docs/api/calendar-iss-calendars-futures-session/)
даёт направление для официального расписания. Это docs review, не проведённый source
test. Страница магазина data.moex.com при проверке вернула502; покупать ещё что-либо
или выводить фактический тариф/entitlements из этого нельзя.

Следующий шаг: реализовать новый bounded authenticated candles/orderbook/specs source
с pre-request future boundary и synthetic schema/time guards; соединить с immutable
forecast writer и fixed execution/evaluation. До единого executable admission F=null.
