# V81 — два положительных funding components, ещё не прибыль портфеля

2026-09-15. [Зафиксированный протокол](V81_STOCK_PERPETUAL_FUNDING.md).
SBERF и GAZPF прошли предварительный фильтр величины и знака фандинга.
Это зацепка для полной проверки «акция + короткий вечный фьючерс», не готовая стратегия,
не Stage2, не доказательство минимальных20% и не разрешение торговли.

## Что измерено

Два независимых фиксированных100-share номинала. Исходная база — первая SETTLEPRICE
2024-10-01; её funding исключён. Учтены все последующие выплаты до2025-12-30.
Источник current-vintage,320сессий/319выплат на контракт,455calendar days.
Все320proxy calendar dates покрыты, missing sessions/payments0. У обоих все319выплат
положительны, нулевых/отрицательных0, все15calendar months с положительным потоком.
Это наблюдение в данном периоде, не контрактная гарантия будущего положительного знака.

| Показатель | SBERF | GAZPF |
| --- | ---: | ---: |
| Начальный proxy номинал100акций, RUB | 26685.00 | 13490.00 |
| Фандинг за455дней на1контракт, RUB | 7594.653 | 4196.656 |
| Кредит / начальный номинал за весь период | 28.4604% | 31.1094% |
| Простая годовая нормировка выплат (APR) | 22.8465% | 24.9730% |
| APR после иллюстративного20bps fee hurdle | 22.6859% | 24.8124% |
| APR после иллюстративного40bps fee hurdle | 22.5254% | 24.6519% |
| Положительные месяцы | 15/15 | 15/15 |
| Вердикт компонента | FUNDING_COMPONENT_CANDIDATE | FUNDING_COMPONENT_CANDIDATE |

APR здесь = funding-credit / initial-notional ×365.25/455. Никакого компаундирования,
роста счёта, плеча или полного знаменателя «акция + обеспечение» здесь нет.
Иллюстративный fee hurdle не включает все экономические эффекты и не является net PnL.
Decisions/fills=0; portfolioPnL/CAGR/Sharpe/MDD=null. Не подменять ими таблицу выше.

## Все месяцы: кредит фандинга на100-share номинал, RUB

| Месяц | SBERF | GAZPF |
| --- | ---: | ---: |
| 2024-10 | 449.702 | 290.642 |
| 2024-11 | 486.736 | 256.129 |
| 2024-12 | 525.153 | 278.009 |
| 2025-01 | 387.078 | 224.261 |
| 2025-02 | 470.355 | 330.546 |
| 2025-03 | 707.443 | 431.215 |
| 2025-04 | 571.392 | 326.257 |
| 2025-05 | 467.236 | 263.218 |
| 2025-06 | 583.689 | 331.793 |
| 2025-07 | 661.363 | 290.771 |
| 2025-08 | 322.112 | 240.748 |
| 2025-09 | 496.677 | 262.615 |
| 2025-10 | 579.724 | 248.183 |
| 2025-11 | 379.028 | 181.244 |
| 2025-12 | 506.965 | 241.025 |

Суммы за2024(неполный) /2025: SBERF1461.591/6133.062RUB,
GAZPF824.780/3371.876RUB. Это суммы cashflow, не годовые portfolio returns.
Полный период лишь15месяцев и один полный календарный год, устойчивость по режимам
и долгосрочная воспроизводимость ещё не проверены. Исторический фандинг может упасть
или сменить знак; нельзя обещать эти APR пользователю как будущий доход.

## Provenance и проверка

- Pre-value commit90b4db8 pushed до первого source response.
- Config SHA cb456322c6b4624592a05559f201d29c9e8be71402fcc043df9ccc671e635081.
- Seven-file seal a9e4299e3a8846d6dba8d19588af18baaf63b7b2818e107e13b59b587e5ac89a.
- Canonical /srv/trading_lab_data/source_evidence/v81_stock_perpetual_funding_v1.
- Metrics SHA 6b90b9fb66a4b146156c28ed31ead1a7b6ff78cfd1d779ce12211f612fe68874.
- 8raw pages/640rows, всеHTTP200/attempt1; raw SHA/URL/receipt preserved outside Git.
- Source+component started10:31:36.409723UTC; raw replay complete10:31:41.339614UTC.
- Local49tests(21new+28V80)/server21PASS,Ruff clean. Audit8raw pages/cursor/date/unit/
  missingness/calendar/month/year arithmetic and2summaries PASS, без повторного HTTP.
- Calendar source500949bytes/8100rows pinned; projection только effective_date,
  текущий период320unique dates. Это factual-core4 proxy, не полный official calendar.
- Anonymous public ISS, без AlgoPack key или новых расходов; archive services не менялись.

## Следующий допустимый шаг

V82 должен проверить оба компонента как полные хеджированные позиции, без выбора GAZPF
по более высокому увиденному APR. Сначала отдельный protocol/seal до новых price inputs:
next-factual paired fills,100share units, funding/VM/dividend adjustment, actual dividends
и tax assumptions, margin buffer и cash principal,1x/2xcosts, halts/forced conversion,
сравнение с денежным benchmark на тех же датах. Ни current margin, ни начисленные
дивиденды, ни RUONIA нельзя выдавать за реально доступный брокерский cash income.

После V81 выполнен только price-free schema probe стандартной SBERF history:
HTTP200/803bytes,iss.data=off,0data rows. OPEN/CLOSE/SETTLEPRICE/SWAPRATE присутствуют,
но dividend-adjustment field нет. Для V82 нужен отдельный подтверждённый источник этой
поправки; нельзя просто считать short-perpetual PnL как обычный future плюс funding
или подставлять RMS forecasts вместо фактической выплаты акционеру. Missing cash
liability не ноль. Новые paired PnL/stock prices/dividend outcomes ещё не читались.

Existing spot references находятся в configs/moex_stock_futures_cash_carry_source_v2.yaml:
stocks_10m_pre2026_v1 SBER/GAZP, source/asset hashes уже зафиксированы. Локально повторно
проверены actual bytes/SHA (без чтения цен): manifest15515bytes,
SBER4776211bytes,GAZP4714157bytes, все совпали с декларацией. Полные SHA:

- Manifest5a7a4873f01141682c9c53d0714d235187eec6b57e5449b23bb04e68c4593042.
- SBER7fdbbd98d00d0b3daf36951075a75769ad1037523e882f6e63263c32021c1a62.
- GAZP2db5078e58f307704ab32eb7cf9160ef0ee696f172586116d1976d73c4174eda.

Для следующего этапа ещё проверить нужные timestamps/price projection и соответствие
execution, не копировать весь30-stock bundle без нужды. Фактического переноса ещё нет.
Read-only server probe после V81 подтвердил отсутствие exact root manifest и обоих
SBER/GAZP files. Это локально решаемая подготовка данных, не разрешение повторять
весь acquisition или считать торговую систему заблокированной внешней стороной.
Исторический causal entry/mark/exit и отдельный fee/margin/дивидендный учёт обязательны.
Длинная позиция в акции поглощает капитал; positive funding alone не подтверждает
доходность20% на ВСЁМ капитале и не снимает риск обеспечения/базиса/исполнения.

V65–V80 сравнительный реестр остаётся23economic screens/0Stage2; отдельно V81 содержит
2прошедших предварительных funding-component tests, но0paired portfolio backtests.
Цель20–50% не достигнута. Crypto-scope question остаётся optional/unanswered; не расширять
market/data scope автоматически. Реальные счета, сделки и подписки не менялись.
