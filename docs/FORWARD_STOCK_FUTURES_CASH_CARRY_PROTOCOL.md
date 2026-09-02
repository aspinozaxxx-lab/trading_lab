# Forward-протокол stock–futures cash-and-carry

## Зачем он нужен

Historical V1/V2 показал низкорисковый stabilizing sleeve, но 10-минутные свечи не
доказывают исполнимость по одновременным ценам акций и фьючерсов. Этот контур собирает
новые, ранее не виденные синхронные BID/OFFER-наблюдения для frozen GAZR/SBRF/ROSN/TATN/NOTK.
Он не вычисляет basis, сигнал, сделку, доходность или PnL и не разрешает live trading.

Запечатанный config:
`configs/moex_forward_stock_futures_cash_carry_source_v1.yaml`, SHA-256
`b25fe86c1aaccb6e615647b3f84efb3c45df33185e71debee497702e5ac2c4c6`, seal commit
`a193e0d`. Начало forward-периода — `2026-09-02`; backfill до этой даты запрещён.

## Что сохраняется

По рабочим дням создаются два независимых immutable snapshot:

- `decision` в 15:49 МСК — наблюдение после frozen decision bar 15:40;
- `fill` в 15:59 МСК — следующее наблюдение, но не утверждение о гарантированном fill.

Контракт выбирается до чтения котировок: только официальный series/description,
`LSTTRADE` через 30–90 календарных дней, `LOTSIZE=100`, ближайшая дата и затем SECID.
Если контракта нет, сохраняется явный sleep. Для каждой из пяти пар требуются
положительные `BID < OFFER` и хотя бы один exchange clock. Любая неполная пара делает
весь snapshot неготовым.

Каталог данных находится вне Git:
`D:\Projects\trading_lab_data\data\forward\moex-stock-futures-cash-carry-v1`.
В каждом snapshot есть `quotes.parquet`, точный canonical-JSON raw archive,
`manifest.json`, sidecar hash и replay `audit.json`.

## Запуск и контроль

Ручной сбор после разрешённого времени:

```powershell
scripts\collect_forward_stock_futures_cash_carry.ps1 -Stage decision
scripts\collect_forward_stock_futures_cash_carry.ps1 -Stage fill
```

Регистрация задач Windows:

```powershell
scripts\register_forward_stock_futures_cash_carry_tasks.ps1
```

Проверка прогресса без экономики:

```powershell
.venv\Scripts\python.exe -m market_lab.futures.forward_stock_futures_cash_carry_readiness
```

Readiness считается только по replay-аудированным полным парам, где retrieval `fill`
строго позже `decision`: 60 discovery, затем 20 calibration и 60 полностью unseen
evaluation. До окончания discovery запрещено запечатывать paper-экономику; до окончания
unseen evaluation запрещена annualization. Отдельно остаются нерешёнными задержка
anonymous ISS, доступный размер, broker fees/margin и реально ликвидный инструмент для
доходности свободного капитала.

## Совместный depth gate

Raw responses уже включают `BIDDEPTH/OFFERDEPTH`, поэтому processed V1 не меняется.
Config `configs/v41_forward_execution_admission_v1.yaml`, SHA `8183eb50...`, seal
`293165b` фиксирует до первого значения обязательную глубину минимум для 100 акций и
одного фьючерса в обе стороны, positive LQDT depth и same-stage retrieval skew не более
30 секунд. Для V41 discovery использовать только `v41_forward_execution_admission`,
а не сумму независимых counts.
