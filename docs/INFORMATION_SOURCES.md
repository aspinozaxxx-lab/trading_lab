# Дополнительные источники информации

Этот документ — очередь новых point-in-time данных, а не список готовых торговых
сигналов. Источник допускается к PnL только после фиксации прав, raw-архива, SHA-256,
схемы, `available_at` и отдельного sealed-протокола. Техническая доступность API не
означает право на перераспространение данных.

## Что уже есть

### MOEX RVI — новый подготовленный источник

Официальная история индекса волатильности RVI загружена 2026-08-31 из MOEX ISS только
запросами с `till=2025-12-31`:

- external path:
  `data/processed/info_radar/moex-rvi-dev-2018-2025-v1/`;
- 2 014 строки, `2018-01-03..2025-12-30`, 21 paginated request;
- processed SHA-256:
  `ac709b76ad7f2a03e48f8feb2b11248418e90d53d88d2b06d94fc35aea5b84b7`;
- raw archive SHA-256:
  `5ec9d9a19ed2d37265c3fd94cb6542f7bf1d5e84a41458825aa6c86e4886bfdb`;
- manifest SHA-256:
  `22573e6bba290a34aeee44bba3bb159f38d9e93014e78f9bd5367df8d0dd56fa`.

RVI измеряет ожидаемую 30-дневную волатильность по ближайшей и следующей серии опционов
на фьючерс RTS. Для исследования разрешён только консервативный join
`rvi.source_date < decision_date`: значение текущего дня не используется. Snapshot
current-vintage; исторический revision archive пока не доказан, поэтому источник годится
только для development, не для независимого подтверждения.

Официальные страницы: [описание RVI](https://www.moex.com/en/index/RVI),
[ISS](https://www.moex.com/a8531),
[изменение времени публикации индексов](https://www.moex.com/n93492).

### MOEX FUTOI daily-last — новый подготовленный источник

Официальные позиции физлиц/юрлиц по Si/RI/BR/MX загружены 2026-08-31 из MOEX ISS
24 ticker-year запросами с `latest=1` и `till` не позже `2025-12-31`:

- external path:
  `data/processed/info_radar/moex-futoi-dev-2020-2025-v1/`;
- 11 744 строки, ровно 2 936 на ticker, 1 468 source days,
  `2020-05-04..2025-12-30`;
- processed SHA-256:
  `a6758388bc311c2c474ad4260337d8fc97f87aa5a9d5bb1f52217940421c1560`;
- raw archive SHA-256:
  `f3b7d3d4cbc1a40ac980f78d8beb8f1838c8f493f9c85b317f50ab8b7a276035`;
- manifest SHA-256:
  `5320875a02441e9844138fc24f85a631b1521061b2ef839403d5b98ebab6e9ee`.

Каждая дата содержит пару `FIZ/YUR`, official `systime` и консервативный
`available_at = systime + 1 minute`. Семь source points имеют ненулевой reporting
imbalance; максимальный ratio 0,8246%, и он сохранён явно. Snapshot current-vintage,
revision archive не доказан. Это daily-last выборка; полный пятиминутный архив не
загружен. Официальный документ говорит о подписке/входе, хотя все 24 запроса в момент
снимка успешно прошли анонимно; это не доказывает права на перераспространение raw data.

Дополнительный аудит **инвалидировал V16**. Официальное описание определяет `SYSTIME`
как время публикации информации. У 10 456/11 744 строк оно более чем на сутки позже
observation; у всей истории 2020–2024 значение равно `2025-06-21 16:35:12 MSK`.
Следовательно, `source_date < decision_date` недостаточно: 932/1 044 V16 states не
выполняют `available_at <= decision_at`, включая все states 2021–2024. Механические
метрики V16 запрещено считать performance или использовать для отбора.

Проверка официального intraday endpoint без `latest=1` показала важную особенность:
один Si-день `2025-12-30` возвращает 348 строк, годовой диапазон обрезается ровно на
1 000 строках, а параметры `start=1000/2000` возвращают те же первые строки. Значит,
полный 5m архив нельзя доказывать обычной offset-pagination: интервалы нужно делить до
ответов короче 1 000 строк, а каждый день проверять отдельно на paired FIZ/YUR points.
Но полнота значений не создаёт PIT vintage: новый collector обязан хранить actual
retrieval time и считать
`conservative_available_at = max(SYSTIME + delivery buffer, archive_retrieved_at)`.
Такой current-vintage архив полезен для будущего forward collector, но не допускается к
историческому PnL 2021–2025.

Полный v2 bundle собран во внешнем хранилище:

- path: `data/processed/info_radar/moex-futoi-intraday-dev-2020-2025-v2/`;
- 2 015 624 строки = 1 007 812 paired sequence points, ровно 503 906 строк на ticker;
- 5 872 single-ticker/day jobs и 24 discovery requests, всего 5 896 raw records;
- source dates `2020-05-04..2025-12-30`; каждый response короче 1 000 строк и final
  sequence совпадает с отдельным daily-last proof;
- processed SHA-256:
  `5f496a48c8359acb151eb2806d0705b4ee4197eda42ea43705bb805c70287744`;
- raw SHA-256:
  `f7bdab6f35884da5d6731134262b381c88a87f0ffebdac40139989e2a85d6056`;
- manifest SHA-256:
  `cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed`;
- minimum conservative availability — `2026-08-31T22:43:34Z`, поэтому manifest явно
  содержит `historical_2020_2025_backtest_admissible=false`;
- 1 356 sequence rows делят `MOMENT` с другой последовательностью: они сохранены по
  правильному ключу `(session, seqnum)`, а не ошибочно дедуплицированы по времени;
- raw redistribution запрещена до проверки лицензии.

### EIA WPSR Table 1 — release-specific PIT bundle

Официальный архив отдельных выпусков Weekly Petroleum Status Report собран без
current-vintage API и без рыночных prices/returns/targets/PnL:

- path: `data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2/`;
- 728 официальных release links `2012-01-05..2025-12-29`, из них 727 допущены и один
  сохранён только как raw evidence;
- processed: 38 248 строк stock/supply/demand balance sheet, SHA-256
  `5fccfa968ac88f04806df87bd7179a992f0f7c57137ba46db049d67350b54f3e`;
- manifest SHA-256:
  `aac389628b61df446616cd171084af81482d09a7d4b403337a8332b5373c142b`;
- raw release archive SHA-256:
  `dce96ee233ed5cac153ab086f514a69688f28830749c4dc223dc66c79454b297`;
- conservative `available_at` — `23:59:59 America/New_York` официальной release date;
  максимум `2025-12-30T04:59:59Z`, поэтому каждый causal join обязан проверять
  `available_at <= decision_at`;
- issue `2019-07-03` ссылается на byte-identical CSV от `2019-06-26` и повторяет data
  week `2019-06-21`; он исключён как `duplicate_stale_archive_file`, но сохранён в raw и
  coverage;
- 38 036 соседних vintage comparisons дали 37 965 exact matches и 71 официально
  сохранённую revision/reclassification;
- EIA разрешает использование и распространение government publications как public
  domain с указанием источника. Криптографических release-time hashes у EIA нет, поэтому
  неизменность файла с момента публикации не объявляется доказанной.

Выпуск `2025-12-31` намеренно не загружен: конец его release day в New York уже лежит в
2026 UTC. Source audit допускает bundle к development-гипотезе, но не заменяет отдельный
pre-outcome seal и не означает, что фундаментальный сигнал прибыльный.

### Уже использованные источники

- MOEX daily futures/active map: OHLC, settlement, volume, OI, front/next curve и
  participant OI;
- CBR: ключевая ставка, RUONIA и официальный USD/RUB с publication semantics;
- CFTC: weekly positioning с Friday release lag и отдельными holiday overrides.

RUONIA использована в V15. Её причинная часть V16 не исправляет недоступный FUTOI signal,
поэтому V16 collateral/combined metrics также недействительны.

Эти признаки уже встречались в V6/V8/V9. Их нельзя выдавать за новую информацию лишь
потому, что изменён threshold или модель.

## Приоритеты получения

| Priority | Источник | Потенциальная польза | Главный барьер | PIT-правило |
|---|---|---|---|---|
| P0 | Historical MOEX/broker specs, fees, IM, spread/order book | Отделить реальную исполнимость от ложной прибыли | Лицензия/подписка и broker archive | Использовать только запись, действовавшую до order time |
| P1 | MOEX RVI | Forward-looking risk regime для RI/MIX и общего gross | Current-vintage history; нужен один sealed test | Только предыдущая source date |
| P1 | MOEX FUTOI daily-last | Forward crowding/risk regime для всех core-four | V16 INVALID; historical publication vintages не доказаны | Только `available_at <= decision_at`, source date недостаточно |
| P1 | Полный MOEX FUTOI 5m | Будущий forward timing/момент сделки | Current-vintage, 1 000-row cap, offset игнорируется; historical PIT отсутствует | `max(SYSTIME + buffer, retrieval_at) <= decision_at` |
| P2 | EIA Weekly Petroleum Status Report | Независимые supply/demand shocks для BR | Bundle готов; consensus отсутствует, delayed edge ещё не проверен | Только `available_at <= decision_at`; stale issue исключён |
| P2 | CBR publication calendar, RUONIA term structure, key-rate text | Funding/carry и режим SI/RI | Часть числовых рядов уже использована | Publication timestamp, не observation date |
| P3 | Issuer filings и corporate actions | Equity-specific fundamental events | Права, revision chain, page evidence | Только original publication/revision known by decision |

Официальные точки входа:

- [MOEX ISS developer interface](https://www.moex.com/a8531) и
  [historical data service](https://www.moex.com/a2863);
- [MOEX FUTOI fields](https://fs.moex.com/f/12828/data-description-en.pdf) —
  `MOMENT` как время последней учтённой сделки и `SYSTIME` как время публикации;
- [MOEX FUTOI access](https://fs.moex.com/f/12829/get-futoi-data-en.pdf) —
  физлица/юрлица, пятиминутный open interest и лимит 1 000 строк;
- [CBR publication schedule](https://www.cbr.ru/eng/calendar/),
  [key-rate calendar](https://www.cbr.ru/DKP/cal_mp/) и
  [RUONIA](https://www.cbr.ru/hd_base/ruonia/);
- [CFTC COT description](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
  и [release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm);
- [EIA WPSR schedule](https://www.eia.gov/petroleum/supply/weekly/schedule.php),
  [release archive](https://www.eia.gov/petroleum/supply/weekly/archive/) и
  [copyright/reuse](https://www.eia.gov/about/copyrights_reuse.php).

## Следующая проверяемая гипотеза

V16 имеет статус `INVALID_FUTOI_LOOKAHEAD`: 932/1 044 signal states не были доступны к
decision. Новые daily FUTOI/RVI thresholds на тех же 2021–2025 закрыты.

Current-vintage FUTOI bundle уже завершён и fail-closed закрыт для historical PnL. EIA
release-vintage bundle прошёл source audit, но его market outcome ещё не читался.
Следующие незаблокированные действия:

1. запросить у MOEX licensed original-vintage/bulk history либо начать отдельный forward
   collector, который timestamp-ит получение каждого нового 5m response в реальном
   времени; до этого FUTOI timing sleeping;
2. не публиковать raw FUTOI до проверки лицензии, несмотря на анонимный HTTP 200;
3. до чтения BR outcomes запечатать один EIA supply-demand composite: только семь заранее
   названных строк, prior-only normalization, conservative release availability и exact
   next-open execution; threshold/component search по результату запрещён;
4. для stability RI/MIX приоритетнее licensed MOEX/broker specs/order-book и новый unseen
   forward период; старые RVI/FUTOI thresholds по 2021–2025 не перебирать;
5. любой следующий PnL начинается только после source manifest, `available_at` audit и
   нового sealed protocol. Continuous model может решать чаще суток, но не раньше
   фактического получения bucket.
