# V77 — ограниченный census первых наблюдений, без цен

Объявлено 2026-09-14 после двух date-specific metadata responses и до запроса
all-time catalogue. Родитель: [двухдневная проверка](V77_INDEX_MEMBERSHIP_FEASIBILITY.md),
SHA a36fd81a71d3e69af7ba64cd4ea50ca2acc22a3270558244966db5b962068b08,
pre-source commit 91a18f3. Родитель immutable, news sample остаётся paused.

Два среза дали по45тикеров; from=till=requested date. Это поддерживает date filtering,
но не даёт исторических интервалов, всех изменений и publication time.

## Отдельная гипотеза и дешёвый gate

Возможный новый механизм: delayed demand после ПЕРВОГО включения акции в IMOEX;
покупка только после подтверждённого effective membership, не до объявления.
Это не прежний announcement-to-effective trade и не short/borrow стратегия.
Первое появление в аналитике — лишь candidate, не доказанное первое включение:
переименования, redomiciliation, восстановление источника надо отличать от новых событий.

До любой такой экономической проверки нужно не менее30различных first-inclusion
security events за полный2018–2025. Повторные включения относятся к иной гипотезе;
не добавлять их после подсчёта ради достижения gate. Если даже metadata upper-bound
первых появлений меньше30, остановиться до prices. Если >=30, это лишь основание
проверить original events/identities, не разрешение PnL.

## Единственный дополнительный запрос

Тот же документированный `/IMOEX/tickers.json`, но date отсутствует, как предусмотрено
[reference141](https://iss.moex.com/iss/reference/141) для all-period ticker list.
Query tradingsession=3,iss.meta=off,iss.only=tickers,tickers.columns=ticker,from,till.
Разрешены только ticker и first/last metadata dates, включая metadata dates2026;
prices/weights/returns/labels/targets/PnL2026 по-прежнему запрещены. Universe нельзя
фильтровать по till, нынешней торгуемости или последующему исходу.

Один GET, anonymous/no credentials, no retries/redirects, timeout30s, max128KiB.
Raw/manifest в НОВОМ внешнем server directory, без overwrite/изменения parent.
Проверить exact columns, уникальность ticker, ISO from/till и from<=till; считать
all rows и from>=2018-01-01 AND from<2026-01-01, группировку по году, missing/conflicts.
Отдельно metadata intersection с existing30stock universe из manifest
`data/processed/stocks_10m_pre2026_v1/manifest.json`, SHA
5a7a4873f01141682c9c53d0714d235187eec6b57e5449b23bb04e68c4593042.
Это покрытие, а не разрешённая выжившая economic subset; цены не читать/не переносить.

При пригодном количестве всё ещё требуются полный event census, historical ISIN/board,
original publication/revisions, price/source boundary manifests и отдельный economic
seal, контроль, costs1x/2x, unresolved и весь календарный период. Никакого нового
portfolio engine, model, service или paper activation для этого census.
