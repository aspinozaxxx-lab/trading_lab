# Точный источник исполнения календарных спредов MOEX

## Зачем он нужен

EV3 и EV4 обнаружили небольшой gross edge у `cross_sectional_extremes`, но он исчезает
при stress costs и отрицателен на development-периоде. Текущий backtest исполняет
спред через следующий синхронный open двух отдельных фьючерсов. Это проверяемый proxy,
но он не знает фактическую цену связки, момент matching, очередь и точные комиссии.

Следующий качественно новый тест требует exchange/member multileg history. Это не
обещание, что точные данные улучшат результат: они могут как подтвердить edge, так и
окончательно сделать его отрицательным. Их ценность в устранении главной неопределённости.

## Какие файлы различать

| Уровень | Файл/поток | Что доказывает | Чего не доказывает |
|---|---|---|---|
| Market trades | `multileg_deal.csv` | Фактические spread price, volume, time и trade ID | Очередь до сделки и комиссии конкретного участника |
| Dictionary | `multileg_dict.csv` | Две ноги и signed quantity каждой ноги | Историческую спецификацию/стоимость шага |
| Participant fills | `multilegf04_XXYY.csv` | Fill, order IDs, exchange/clearing fees участника | Полную анонимную очередь рынка |
| Participant actions | `multilegordlog_XXYY.csv` | Добавление, matching и снятие собственных заявок | Все заявки других участников |
| Technical legs | `f04_XXYY.csv`, поле `ID_MULT` | Связь spread trade с фактическими сделками двух ног | Самостоятельно не восстанавливает spread queue |
| Live gateway | TWIME `ExecutionMultilegReport` + 2× `ExecutionSingleReport` | Точный online fill и две технические ноги | Историю до начала собственного capture |

Стандартный публичный shortened sample MOEX Type A за `2024-10-01` содержит только
`fut_deal`, `fut_ord`, `opt_deal`, `opt_ord`. Проверка четырёх listed spread symbols
BR/MIX/RI/SI того дня не нашла их в futures deal/order files. Поэтому Type A нельзя
автоматически считать историей multileg queue: это надо отдельно подтвердить у MOEX.

## Что запросить сначала

Первый заказ/выгрузка должен быть только pilot за январь 2021, без расчёта PnL:

1. Все ежедневные `multileg_deal.csv` и `multileg_dict.csv`, включая header-only дни.
2. Пояснение, входят ли они в Derivatives Type C и как получить архив за весь период.
3. Если доступен отчёт участника: `multilegf04_XXYY.csv`, `multilegordlog_XXYY.csv` и
   соответствующий `f04_XXYY.csv` с `ID_MULT`.
4. Письменный ответ, существует ли historical full-market multileg order log либо
   архив Plaza/TWIME multileg stream; если да — format, timestamps, sequence semantics.
5. Historical contract/reference data, шаг цены/стоимость шага, IM, exchange/clearing
   tariffs и правила комиссий, действовавшие в каждый момент.
6. Условия внутреннего research use, хранения и запрет/разрешение перераспределения.

Pilot считается полезным, только если для каждой даты `multileg_deal` и
`multileg_dict` приходят вместе, dictionary раскрывает ровно две разные ноги со знаками
`−1/+1`, market trade IDs уникальны и все trade instruments находятся в dictionary.
После schema/coverage audit можно заказывать 2021–2025; pilot сам по себе не допускается
к economic verdict.

## Шаблон запроса MOEX/брокеру

> Нужен исторический архив биржевых календарных спредов срочного рынка для внутреннего
> исследования исполнения. Просим подтвердить доступность `multileg_deal.csv` и
> `multileg_dict.csv` за январь 2021 и 2021–2025, а также указать продукт Historical Data,
> в который они входят. Отдельно просим уточнить, содержит ли Type A полную книгу заявок
> именно multileg instruments; публичный sample показывает только outright fut/opt
> files. Если доступен participant/member archive, нужны `multilegf04_XXYY.csv`,
> `multilegordlog_XXYY.csv` и `f04_XXYY.csv` с `ID_MULT`, включая historical schema
> versions, timestamps, fees и права внутреннего хранения/использования.

## Подготовленный ingestion contract

`market_lab.futures.moex_multileg_execution_source` читает только локальный licensed
archive. До открытия bytes он требует ровно одну дату `YYYYMMDD` в относительном пути и
отклоняет дату `>=2026-01-01`. Flat CSV или ZIP допустимы; 7z сначала распаковывается в
отдельный датированный каталог. Raw bytes остаются во внешнем хранилище и не попадают в
Git или processed bundle.

Parser поддерживает core-поля исторических schema variants, сохраняет отрицательные
spread prices и missing значения, исключает participant codes/users/comments и создаёт
отдельные таблицы для market trades, dictionary, participant fills/actions и linked leg
trades. `event_at` разрешён только для replay заранее принятого решения; агрегации этих
отчётов нельзя использовать как same-day signal. Консервативный `report_available_at` —
00:00 мск следующего календарного дня.

Полный canonical build дополнительно требует совместное покрытие 2021–2025 с максимум
14 календарных дней между core packages, exact dictionary, unique trade IDs и exact
две ноги на каждый participant fill, если participant reports присутствуют. До получения
licensed bytes canonical output отсутствует.

## Официальные основания

- [Synthetic Matching of Calendar Spreads](https://www.moex.com/en/spreads) перечисляет
  четыре multileg reports и объясняет, что позиции учитываются в outright legs.
- [MOEX Historical Data](https://www.moex.com/a2863) описывает Type A (all trades/all
  orders), Type B (all trades/top of book) и EOD/transaction registers по подписке.
- [Clearing/exchange report specification](https://ftp.moex.com/Reports/FORTS/CL_CSV_reports.pdf)
  задаёт поля dictionary, participant fills, fees и participant order actions.
- [TWIME specification](https://ftp.moex.com/pub/TWIME/Spectra/prod/doc/backup/spectra_twime_en.pdf)
  фиксирует `ExecutionMultilegReport` и две технические `ExecutionSingleReport` на fill.
