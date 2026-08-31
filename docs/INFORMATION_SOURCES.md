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

### Уже использованные источники

- MOEX daily futures/active map: OHLC, settlement, volume, OI, front/next curve и
  participant OI;
- CBR: ключевая ставка, RUONIA и официальный USD/RUB с publication semantics;
- CFTC: weekly positioning с Friday release lag и отдельными holiday overrides.

Эти признаки уже встречались в V6/V8/V9. Их нельзя выдавать за новую информацию лишь
потому, что изменён threshold или модель.

## Приоритеты получения

| Priority | Источник | Потенциальная польза | Главный барьер | PIT-правило |
|---|---|---|---|---|
| P0 | Historical MOEX/broker specs, fees, IM, spread/order book | Отделить реальную исполнимость от ложной прибыли | Лицензия/подписка и broker archive | Использовать только запись, действовавшую до order time |
| P1 | MOEX RVI | Forward-looking risk regime для RI/MIX и общего gross | Current-vintage history; нужен один sealed test | Только предыдущая source date |
| P1 | MOEX Futures Open Interest Intraday (FUTOI) | Потоки и crowding физлиц/юрлиц каждые 5 минут | Авторизация/коммерческие условия, история с 2020 | Только завершённый bucket плюс delivery lag |
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

V14 завершён: previous-session RVI уменьшил MDD до 9,40%, но CAGR до 4,67% и не улучшил
Sharpe. Семейство threshold-вариантов закрыто на этом OOS.

Первый незаблокированный кандидат — один V15 capital-efficiency experiment:

1. byte-identical V12 alpha, targets и exact execution;
2. официальная RUONIA допускается только после `available_at`, до начала периода
   начисления;
3. доход начисляется только на положительное обеспечение после двойного modeled IM и
   заранее фиксированного operational buffer;
4. haircut ставки, day-count, tax/fee assumptions и отсутствие reinvestment в sizing
   запечатываются до PnL;
5. отчёт отдельно показывает futures alpha, collateral income и combined equity; никакого
   post-outcome перебора haircut/leverage на 2021–2025.
