# Forward-протокол пула фондов денежного рынка V1

## Назначение

Источник сравнивает исполнимые котировки фиксированного до данных пула из четырёх
рублёвых биржевых ПИФов денежного рынка: `LQDT`, `SBMM`, `AKMM`, `TMON`. Он нужен,
чтобы после независимого периода выбрать реальный инструмент для неактивной части V41,
а не автоматически считать LQDT или условные 50% RUONIA лучшим вариантом.

Это source-only контур. Он не вычисляет доходность, рейтинг, сигнал, сделку или PnL и
не разрешает live trading.

## Зафиксированный контракт

- Protocol SHA-256: `37a3baeb7d0b0062139cb6afe7db7d5cba4e7f02e547a32c90b5f1cabf52e884`.
- Seal commit: `ac299a7`, сделан до первого MOEX quote/depth snapshot пула.
- Граница: только текущая московская дата не раньше `2026-09-02`; backfill запрещён.
- Universe и идентичности: `LQDT/RU000A1014L8/3915`,
  `SBMM/RU000A103RF1/4607`, `AKMM/RU000A104X08/5012`,
  `TMON/RU000A106DL2/5229`; замена после значений запрещена.
- Два среза TQBR: `decision=15:49:00`, `fill=15:59:00` МСК.
- Каждый фонд обязан иметь точную identity, положительные не locked BID/OFFER,
  положительную лучшую глубину с обеих сторон, LOTSIZE, MINSTEP, SETTLEDATE и clock.
- Raw ISS JSON сохраняется без потери полей; processed Parquet и manifest должны точно
  восстанавливаться replay-аудитом.

Котировка не доказывает сделку, очередь или отсутствие market impact. Фонд нельзя
одновременно считать принадлежащим idle sleeve и свободным залогом cash-carry.

## Этапы без подглядывания

1. `60` полных decision/fill пар — discovery качества, задержки, spread и depth.
   Ранжирование и экономика на этом этапе запрещены.
2. После discovery отдельно запечатать правило выбора, учитывающее покупку по OFFER,
   продажу по BID, комиссии брокера, налог, settlement и необходимость полной продажи
   перед активной cash-carry позицией.
3. `20` следующих пар — calibration зафиксированного правила.
4. `60` ещё не просмотренных пар — evaluation. До его завершения annualized доходность
   и вывод о замене условных 50% RUONIA запрещены.

## Эксплуатация

```powershell
.\scripts\register_forward_money_market_fund_pool_tasks.ps1
.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_money_market_fund_pool_readiness `
  --output-root `
  D:\Projects\trading_lab_data\data\forward\moex-money-market-fund-pool-v1
```

Ручной запуск допустим только после времени соответствующего stage:

```powershell
.\scripts\collect_forward_money_market_fund_pool.ps1 -Stage decision
.\scripts\collect_forward_money_market_fund_pool.ps1 -Stage fill
```

Повтор существующего snapshot выполняет только audit и `SKIP`; повреждённый snapshot
не перезаписывается. Данные остаются вне Git.
