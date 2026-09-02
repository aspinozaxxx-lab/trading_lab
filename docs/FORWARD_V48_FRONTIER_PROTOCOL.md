# Независимый forward-протокол V48 frontier

## Что зафиксировано

Historical exact replay V48 дал `38,46–39,86%` CAGR после integer contracts, costs,
1% capacity и doubled margin reserve, но использовал уже просмотренную историю
2021–2025. Поэтому config `configs/v48_frontier_forward_validation_v1.yaml`, SHA
`1fbc8c10...`, запечатан до первого V27 snapshot и до любого V48 forward PnL.

В forward допускается ровно один режим, выбранный историческим presealed gate:

- frozen V39 target умножается на `1,50`, не меняя знак и zero states;
- gross notional ограничен `3,00x` equity;
- captured initial margin умножается на `2,00`;
- размер не превышает `1%` strictly prior official volume;
- broad carry отсутствует;
- позиции — целые контракты SI/RI/BR/MIX.

Выбирать stability после результата, менять scale/cap/buffer, V39 window/quantiles/sign,
universe или execution mark запрещено.

## Данные и исполнение

Протокол наследует только audited forward sources V39/V27:

- option OI state — последняя завершённая неделя строго до decision week;
- signal prices — official MOEX daily `CLOSE`;
- specs, fees и initial margin — последний captured state до order;
- следующий execution snapshot обязателен: buy отмечается observed `OFFER`, sell —
  observed `BID`; missing side/depth отменяет asset order;
- gross, margin или participation failure вызывает cancel/clip, не bypass;
- никакого backfill, forward-fill, midpoint или historical OPEN вместо quote.

Transport compatibility SHA `ae70f0d4...` разрешает только exact retry текущего
запроса. Source-mapping correction SHA `019f970e...` переводит V48 на component source
SHA `242d2684...`: persistent FRED outage отклоняет только FRED component, а уже
записанные MOEX/CBR не удаляются. Старое значение не подставляется; поздний FRED
доступен лишь решениям после его actual retrieval.

Authenticated FRED route запечатан отдельной correction SHA `b638ee93...`: официальный
API component SHA `2954c5a4...`, implementation `4a283074...`. Он сохраняет тот же
`STLFSI4` и ту же causal availability. Выбор route зависит только от валидности
`FRED_API_KEY`; ключ никогда не сохраняется, а fallback после authenticated failure
запрещён. V48 parameters, execution, costs и promotion gates не менялись.

## Последовательные границы

1. Source warmup: `54` option weekly levels и `253` common official CLOSE.
2. Только после более поздней границы разрешён paper ledger.
3. Independent evaluation: минимум `504` futures sessions, `104` weekly decisions и
   два полных календарных года.
4. До завершения evaluation CAGR и annualization запрещены.
5. Gates: CAGR `>=20%` во всех costs, Sharpe `>=1`, MDD `<=40%`, worst full year
   `>=-15%`, два positive years, participation `<=1%`, zero critical/unresolved.
   `35%` all-cost CAGR — stretch gate, а не обещание.
6. Numeric pass всё равно требует второго unseen confirmation и reconciliation с
   broker statements; live trading после первого pass запрещён.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v48_frontier_forward_readiness_v3 `
  --option-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v1 `
  --component-root D:\Projects\trading_lab_data\data\forward\v27-validation-v3-components
```

Текущий state: option `1/54`, V27 CLOSE `0/253`, execution dates `1`, CBR `1`, FRED
anonymous/authenticated `0/0`, key configured `false`, invalid snapshots `0`,
`paper_economics_may_start=false`,
`annualization_allowed=false`, `live_trading_allowed=false`.
