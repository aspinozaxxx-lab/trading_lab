# Forward-протокол LQDT для idle cash sleeve

## Гипотеза

Historical V41 начисляет неактивным cash-carry sleeves только 50% причинно доступной
RUONIA, но не называет исполнимый инструмент. LQDT — БПИФ денежного рынка с ISIN
`RU000A1014L8`, правила №3915. По материалам управляющей компании его цель — доход
через сделки РЕПО с центральным контрагентом. Паи торгуются на MOEX; после миграции
22 июня 2026 основной активный board — TQBR.

Официальное сообщение НКЦ/MOEX, действующее с 15 июля 2026, не включает LQDT в
расширенный список бумаг, принимаемых в обеспечение сделок с частичным обеспечением.
Поэтому протокол не считает LQDT залогом: пай может находиться только в неактивном
asset sleeve и должен быть продан перед включением stock-futures cash-carry.

Config `configs/moex_forward_lqdt_idle_cash_source_v1.yaml`, SHA-256
`15fb471a2a940b1dabeab6d16f82a8c1fd3e8b863b28936202c42eb4f8f4e1fa`, seal commit
`8ae3dc3` предшествует первому official LQDT quote snapshot. Boundary — `2026-09-02`,
backfill запрещён.

## Сбор

Два immutable snapshot по рабочим дням:

- `decision` в 15:49:00 МСК — котировка потенциальной ликвидации после решения 15:40;
- `fill` в 15:59:00 МСК — следующее наблюдение, не гарантированный fill.

Сохраняются точный raw ISS JSON, TQBR `BID/OFFER`, `LOTSIZE`, `MINSTEP`, `SETTLEDATE`,
exchange clock и retrieval time. Missing, one-sided или locked quote становится invalid,
а не нулём. Источник не считает yield, return, signal, trade или PnL. Значения iNAV
LQDTM намеренно не собираются: MOEX указывает отдельные условия коммерческого
использования индексной информации, договор не подтверждён.

Данные находятся вне Git:
`D:\Projects\trading_lab_data\data\forward\moex-lqdt-idle-cash-v1`.

## Команды

```powershell
scripts\register_forward_lqdt_idle_cash_tasks.ps1
scripts\collect_forward_lqdt_idle_cash.ps1 -Stage decision
scripts\collect_forward_lqdt_idle_cash.ps1 -Stage fill
.venv\Scripts\python.exe -m market_lab.futures.forward_lqdt_idle_cash_readiness
```

Readiness: 60 complete ordered decision/fill pairs, затем 20 calibration и 60 unseen
evaluation. До 60 пар запрещена paper-экономика; до завершения unseen evaluation —
annualization. Будущий economic protocol обязан покупать по OFFER, продавать по BID,
обнулять LQDT в активном sleeve и отдельно фиксировать брокерскую комиссию, биржевой
сбор, налоги и правила settlement netting. Quote source не доказывает доступность денег,
очередь, размер, rejection или fill и не разрешает live trading.
