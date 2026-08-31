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

### Уже использованные источники

- MOEX daily futures/active map: OHLC, settlement, volume, OI, front/next curve и
  participant OI;
- CBR: ключевая ставка, RUONIA и официальный USD/RUB с publication semantics;
- CFTC: weekly positioning с Friday release lag и отдельными holiday overrides.

RUONIA теперь использована в V15: 1 271/1 271 причинных интервалов покрыты, 50% ставки
после двойного modeled-IM reserve и 10% cash buffer дали 142 698,54 RUB за 2021–2025.
Это повысило combined CAGR до 21,33%, но не устранило MDD 34,48% и execution failures.

Эти признаки уже встречались в V6/V8/V9. Их нельзя выдавать за новую информацию лишь
потому, что изменён threshold или модель.

## Приоритеты получения

| Priority | Источник | Потенциальная польза | Главный барьер | PIT-правило |
|---|---|---|---|---|
| P0 | Historical MOEX/broker specs, fees, IM, spread/order book | Отделить реальную исполнимость от ложной прибыли | Лицензия/подписка и broker archive | Использовать только запись, действовавшую до order time |
| P1 | MOEX RVI | Forward-looking risk regime для RI/MIX и общего gross | Current-vintage history; нужен один sealed test | Только предыдущая source date |
| P1 | MOEX FUTOI daily-last | Новый causal crowding/risk regime для всех core-four | Current-vintage; права и revisions не доказаны | Только `source_date < decision_date` |
| P2 | Полный MOEX FUTOI 5m | Непрерывный crowding и момент сделки | Нужны тысячи daily requests либо лицензированный bulk archive | Только завершённый bucket плюс delivery lag |
| P2 | EIA Weekly Petroleum Status Report | Независимые supply shocks для BR | Время релиза, holidays, revision/consensus | Не раньше официального release timestamp |
| P2 | CBR publication calendar, RUONIA term structure, key-rate text | Funding/carry и режим SI/RI | Часть числовых рядов уже использована | Publication timestamp, не observation date |
| P3 | Issuer filings и corporate actions | Equity-specific fundamental events | Права, revision chain, page evidence | Только original publication/revision known by decision |

Официальные точки входа:

- [MOEX ISS developer interface](https://www.moex.com/a8531) и
  [historical data service](https://www.moex.com/a2863);
- [MOEX FUTOI description](https://fs.moex.com/f/12829/get-futoi-data-en.pdf) —
  физлица/юрлица и пятиминутный open interest;
- [CBR publication schedule](https://www.cbr.ru/eng/calendar/),
  [key-rate calendar](https://www.cbr.ru/DKP/cal_mp/) и
  [RUONIA](https://www.cbr.ru/hd_base/ruonia/);
- [CFTC COT description](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
  и [release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm);
- [EIA WPSR schedule](https://www.eia.gov/petroleum/supply/weekly/schedule.php) и
  [API documentation](https://www.eia.gov/opendata/documentation.php).

## Следующая проверяемая гипотеза

V15 завершён: combined CAGR 21,33% впервые достиг цели, но MDD 34,48% и восемь critical
halt events дали `NO_GO`. Семейство post-outcome leverage/haircut вариантов закрыто.

Теперь первый незаблокированный development-кандидат — один V16 FUTOI crowding governor:

1. frozen V12 trend и V15 RUONIA economics остаются неизменными;
2. для каждого asset используется только последний FUTOI `source_date < decision_date`;
3. retail crowding определяется из FIZ long/short/net без price/return labels, а
   normalization/границы фиксируются только по 2020 warmup до чтения V16 PnL;
4. leverage уменьшается только в заранее определённом trend-aligned crowded state;
   missing FUTOI означает консервативный base risk, не zero feature;
5. единый capacity-aware order contract задаётся до PnL: неизвестный factual open/lagged
   volume отменяет текущую попытку, известная participation ограничивает размер, без
   специальных дат марта 2022;
6. gate требует одновременно CAGR `>=20%`, MDD `<=25%` и complete execution. Это всё ещё
   adaptive development; независимое подтверждение и exact broker/exchange archive нужны.
