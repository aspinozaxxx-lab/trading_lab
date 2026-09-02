# Независимый forward-протокол V39

## Что проверяется

V39 — лучший текущий development-кандидат: primary CAGR `28,6849%`, Sharpe `1,2515`,
MDD `20,0322%`; doubled/stress CAGR `28,2235%/27,8287%`. Он улучшил V27 во всех
заранее заданных сравнениях, но создан и проверен на той же истории 2021–2025. Это
`GO_TO_NEW_FORWARD_CONFIRMATION`, а не доказанный будущий доход.

Forward config SHA `3677bcca...`, seal commit `ba9bbb1`. Он byte-pin-ит V39 SHA
`3b5d3074...`, implementation `0dac782e...`, canonical metrics `52993f82...`, V27
forward V2 и option forward V1. После forward outcomes запрещено менять 52-week window,
q10/q90, sign, scale, universe, warmup, execution, costs или collateral.

## Источники

Используются только два уже работающих immutable контура:

- `moex-options-surface-v1` в 23:55 мск: actual retrieval, SI/RI/BR/MIX option chains,
  open interest, bid/offer и raw replay. V39 агрегирует только call/put OI по всем
  strikes/maturities/week codes и не создаёт option orders;
- `v27-validation-v2`: execution в 10:05, official daily `CLOSE` после публикации по
  retry grid 00:45/01:15/06:00 мск Tue–Sat, specs/fees/IM и captured macro vintages.
  `LAST`/`SETTLEPRICE` не заменяют `CLOSE`.

Backfill 2026 и перенос historical 2021–2025 option states в forward warmup запрещены.
Первый option snapshot `2026-09-01` был получен после source seal и может участвовать
только в warmup, никогда в evaluation.

## Последовательные gates

1. Нужны 54 unique weekly option levels: текущий change плюс 52 строго предыдущих
   changes требуют 54 уровня put-share.
2. Одновременно нужны 253 common official futures CLOSE — 252 return observations для
   frozen V27 momentum/covariance warmup.
3. Evaluation начинается только после более позднего из двух warmup boundaries.
4. Затем нужны минимум 504 futures sessions, 104 weekly decisions и два полных года.
5. Gates: CAGR `>=20%` во всех costs, primary Sharpe `>=1`, MDD `<=30%`, два
   положительных полных года, worst year `>=0`, zero critical/unresolved и положительный
   observed-quote paper result.
6. Даже numeric pass требует второго unseen периода и broker-exact audit; live false.

До выполнения пункта 4 запрещено сообщать CAGR или экстраполировать короткий период.

## Проверка readiness

```powershell
.\.venv\Scripts\python.exe -m `
  market_lab.futures.v39_forward_component_readiness_v2 `
  --option-root D:\Projects\trading_lab_data\data\forward\moex-options-surface-v1 `
  --component-root D:\Projects\trading_lab_data\data\forward\v27-validation-v3-components
```

На `2026-09-03`: option levels `1/54`, V27 CLOSE `1/253`, execution/FRED/CBR
`1/1/1`, causal join `0`, invalid snapshots `0/0`,
`paper_economics_may_start=false`, `cagr_reporting_allowed=false`. Старый atomic
readiness сохраняется только для exact replay; current successor принимает sealed
anonymous FRED V2. Implementation commit `df8c57e`.
