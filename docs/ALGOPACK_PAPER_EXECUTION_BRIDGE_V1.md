# Execution bridge V1

2026-09-07. Новый integration adapter, не новая стратегия. Код
`src/market_lab/futures/algopack_paper_execution_bridge_v1.py`.
Frozen execution/source/portfolio/anchor parents не меняются. F=null.

## Обязательный путь команд

Bridge принимает настоящий `AnchoredPortfolio` и отдельный source journal root;
production activation должна включать SHA самого bridge. Public methods принимают
ссылки на сохранённые наблюдения, а не произвольные цены, Fill, intent или часы.

`reserve`: consume_forecast с фактическими часами → execution_source.observe с полным
raw replay quote/calendar → quote/terms/session → актуальное portfolio valuation →
fixed make_intent → anchored RESERVE. Неизвестная стоимость портфеля или непригодные
источники не разрешают новую позицию. Final reducer повторно проверяет общий бюджет,
уникальность позиции и своевременность reservation; stale competing writers fail.

`fill_due`: intent и его durable timestamp берутся только из проверенного ledger.
До срока — NOT_DUE. В пределах30сек нужен post-boundary quote, source replay и fixed
simulate_fill. Только полученный таким путём Fill записывается как ENTRY/EXIT.
В команду сохраняются source references с actual observed_at, checked_at и source root.
Conditional simulation не является подтверждением сделки на бирже.

Пропущенный вход после30сек: CANCEL только неисполненной reservation, seen-slot остаётся.
Пропущенный выход: UNRESOLVED, позиция/капитал не обнуляются, новых входов в этом arm
нет. Повторный вызов для уже UNRESOLVED ничего не дописывает. Это консервативная
terminal policy текущего V1, не разрешение backdated/late fill. Экономический результат
такого arm остаётся неполным; будущий recovery policy нельзя выбирать по увиденному PnL.

## Что ещё требуется до запуска

Adapter не scheduler и не complete runtime. Нужны обновление MTM для открытых позиций,
durable журнал всех READY/sleep/failure/missing решений, daily ledger-derived snapshots,
offline evidence replay с исходными observation clocks, полная evaluation/report wiring
и publication/config/seal до F. Публичный low-level portfolio reducer всё ещё принимает
данные; применять его напрямую в future runtime для экономических событий запрещено.
Эта интеграция не делает существующий произвольный ledger source-admitted автоматически.

No HTTP, broker API, historical outcomes, model fit или реальные результаты в этой работе.
Тариф broker3RUB остаётся допущением. Никакого promise/verification20–50%годовых.

## Tests

8 synthetic tests: activation refusal, full conditional roundtrip/restart/evidence,
missing quotes, no early/invented fill, missed entry, unresolved exit/idempotence,
source integrity error, caller-supplied fill/clock refusal.
Linux tests используют настоящий durable anchored ledger, но source observations
stubbed. Полный raw replay проверяется отдельным parent execution-source suite;
реальные account schema/entitlement в этих тестах не наблюдаются.
