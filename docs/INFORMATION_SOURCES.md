# Дополнительные источники информации

Этот документ — очередь новых point-in-time данных, а не список готовых торговых
сигналов. Источник допускается к PnL только после фиксации прав, raw-архива, SHA-256,
схемы, `available_at` и отдельного sealed-протокола. Техническая доступность API не
означает право на перераспространение данных.

## Что уже есть

### MOEX calendar spreads — source complete, derived panel sealed

Официальные календарные спреды дают новую relative-value family, экономически отличную
от directional trend. [MOEX описывает](https://www.moex.com/en/spreads) покупку одного
фьючерса и одновременную продажу другого как единую календарную spread transaction;
[страница параметров](https://www.moex.com/en/derivatives/spreads/spreads_parameters.aspx)
и [публичный архив](https://www.moex.com/en/derivatives/spreads/archive-spreads.aspx)
содержат listed instruments и EOD archive.

Source-only V1 seal SHA `72687539...` фиксирует 110 RFUD spreads SI/RI/BR/
MIX и exact mapping в public archive через official leg names. Ordinary ISS history
сохраняет settlement/OI, но bounded probe не отражает фактическую торговую активность;
public archive CSV отдельно даёт Last, Bid, Ask, High, Low, Amount, Volume и Trades.
Поэтому значения никогда не coalesce-ятся между источниками. Exact HTML/CSV bytes и
ISS JSON архивируются, missing/zero/signed prices сохраняются, а расхождения официальных
интервалов получают flags. После pre-collection push `293e54e` V1 корректно остановился
без output: последний Si spread вернул blank `ASSETCODE`. Отдельный V2 seal SHA
`be770102...` меняет только parser blank-to-missing, не мутирует raw и не допускает
непустой чужой код. После push `7c8d45a` V2 прошёл этот участок, но fail-closed выявил
единственный пустой RFUD interval `BRF1BRG1`; output снова не создан. V3 SHA
`3d89c51f...` сохраняет его official metadata, пропускает только невозможный ISS request
и всё равно требует public archive. V1/V2 остаются неизменяемыми. После pre-collection
push `ed16ca3` V3 успешно опубликован: manifest SHA `94d5fab4...`, raw SHA
`ccaba170...`, 110 spreads, 9 997 ISS rows, 10 157 archive rows и 8 887 rows с reported
trades; все 47 raw/schema/temporal checks true, protected rows 0. Source-only bundle
immutable, returns/PnL не считались.

Следующий source-only D1 seal SHA `657fd42b...` заранее фиксирует 98 regular-adjacent
и date-consistent spreads, 8 281 eligible candidate rows и 4 366 active asset/date rows.
Active выбирается только по минимальному неотрицательному времени до near expiry; две
locked quotes не удаляются, missing days не синтезируются. Near/far legs соединяются с
лагированным spec proxy раздельно: их point value совпадает лишь в 1 218 случаях из
4 366, поэтому последующий PnL обязан считать ноги отдельно. D1 всё ещё не содержит
returns, targets, signals или PnL. После push seal `35ab387` D1 опубликован отдельно от
raw source: manifest SHA `b5e15c2e...`; build и повторный audit дали 29/29 checks true.

Economic EV1 SHA `e74dab97...` использует этот источник только после seal. Помимо
собственной истории каждого spread он добавляет exact-date cross-asset состояние всех
SI/RI/BR/MIX и causal expanding MLP; отсутствие соседнего актива сохраняется indicator,
а не превращается в нулевую цену. Это проверка гипотезы, не новый источник и не лицензия
на live. Для подтверждения исполнения по-прежнему нужны historical multileg trade/order
reports, действовавшие contract specs, margin, tariffs и broker fees.

EV2 показал, что closing Bid/Ask нельзя использовать как универсальный liquidity gate:
условие width `<=2` prior spread sigma прошло 16/19/0/0/0 строк по годам, хотя reported
Last менялся существенно чаще. Это согласуется с ограничением источника: archive Bid/Ask
— финальный EOD snapshot, а EV2 исполняется по следующему synchronized outright open.
EV3 отделил factual traded Last для signal от lagged outright volume для capacity, но
primary и stress оказались отрицательными. EV4 затем заранее потребовал expected move
не меньше 2x stress round-trip cost: evaluation primary вырос до `+0,3095%` на 38
сделках, однако stress остался `−0,1664%`, development `−1,2291%`. Поэтому дальнейший
same-history threshold tuning закрыт; главный неизвестный теперь — exact multileg
execution, а не ещё один фильтр EOD proxy.

Официальная страница synthetic matching прямо перечисляет более точные вечерние отчёты:
`multilegf04_XXYY.csv` (сделки участника), `multileg_deal.csv` (все spread trades),
`multilegordlog_XXYY.csv` (добавление/matching/снятие заявок) и `multileg_dict.csv`
(состав ног). TWIME отдельно подтверждает, что filled multileg order порождает один
`ExecutionMultilegReport` и два технических `ExecutionSingleReport`. Публичные ссылки
на странице выглядят как sample-файлы; доказанного бесплатного исторического архива
2021–2025 пока нет. Это P0 источник для licensed/member access: он нужен, чтобы заменить
synchronized next-open proxy фактической spread price, leg allocation, queue и fees.

Текущая спецификация уточняет границы: `multilegordlog_XXYY` — действия собственных
заявок участника/брокерской фирмы и не доказанная full-market queue. Публичный shortened
Type A sample за `2024-10-01` содержит outright `fut/opt` deal/order files; exact поиск
четырёх listed BR/MIX/RI/SI spread symbols дал 0 совпадений. Поэтому у MOEX надо отдельно
запросить market-wide multileg order history. Зато `multilegf04` содержит participant
fill/order IDs и fees, а `f04.ID_MULT` связывает fill с technical leg trades; TWIME для
того же события возвращает один multileg и два single execution reports.

До первого licensed archive sealed локальный parser: config SHA `464cce7a...`, module
SHA `5e64ba6a...`. Он не скачивает данные, запрещает undated/2026+ package до чтения,
поддерживает пять раздельных schemas, удаляет participant identifiers и требует exact
leg/deal links. Synthetic build/replay прошёл, но canonical source отсутствует. Сначала
запрашивается January 2021 pilot только для schema/coverage; точный список и шаблон — в
[MOEX_MULTILEG_DATA.md](MOEX_MULTILEG_DATA.md).

Внутренние расхождения важны для следующего seal: 189 archive rows лежат вне ISS
interval, 85 — вне series interval, 451 last не попадает в reported daily range, crossed
quotes нет. `RIH2RIU2` — единственный spread без reported activity и одновременно
non-adjacent exchange exception. Эти факты допускают заранее заданный eligibility mask,
но не разрешают подбирать его по будущему PnL.

Источник current-vintage и не содержит historical order-time queue. EOD Bid/Ask не
доказывает исполнимый spread в момент решения; исторические fees, IM и broker rules также
не доказаны. Он пригоден только для отдельного development test после manifest. Для
live admission нужен [MOEX Historical Data](https://www.moex.com/a2863) либо broker
archive с лицензией, order book/trade log и действовавшими параметрами.

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

Sealed V17 уже проверил один допустимый use case и получил `NO_GO`: delayed weekly
direction из семи raw changes дал CAGR −7,74%, Sharpe −0,19 и MDD −48,80% при полном
исполнении. Это закрывает raw-change composite, но не сам источник. Следующая экономически
иная EIA-гипотеза требует point-in-time consensus/forecast для измерения surprise; простая
инверсия signs, новый threshold или более ранний lag на тех же outcomes запрещены.

### CBR weekly liquidity forecasts — release-keyed forward bundle

Официальные датированные прогнозы факторов банковской ликвидности для недельного
аукциона собраны без market prices/returns/targets/PnL:

- path: `data/processed/info_radar/cbr-liquidity-forecast-releases-2017-2025-v1/`;
- 458 releases `2017-01-10..2025-12-30` из 470 календарных недель; 537 HTTP requests с
  Tuesday-first и holiday fallback, maximum release gap 16 дней;
- processed: 50 830 bytes, SHA-256
  `a8faab048579cc5449173b3f2d4ea0e2abd447095d9144ad5004a52b351a8d07`;
- coverage SHA-256:
  `38ea35bfe8914a6a490245fff5bd8b327eb793b5c94c068bbef8665ea5a5681d`;
- manifest SHA-256:
  `8f452f2dd963752eab4183e8f80dd2a07398588f9f87124ae913dff6c2a88c9a`;
- raw archive: 458 pages, SHA-256
  `b01200fa2a827a1c0eb7708695a0cf1af6ace9bed3a2b81f8d9c3281839bd3a6`;
- `available_at = 23:59:59 Europe/Moscow` дня, напечатанного внутри release record;
  максимум `2025-12-30T20:59:59Z`;
- источник содержит будущий forecast period и отдельно `government_accounts_change`,
  куда по определению ЦБ входят операции Минфина с валютой.

Критичный audit: на несуществующую дату сайт молча возвращает последний доступный
выпуск. Collector поэтому не доверяет input/query и допускает страницу только если дата
в строке аукциона совпадает с запросом. Один отсутствующий weekly record `2025-09-09`
подтверждается разрывом страницы, хотя официальный repo-аукцион в этот день проводился;
стратегия обязана sleep/carry только по явному protocol, а не выдумывать forecast.

Это исторические records, выбранные по publication date, но retrieved сейчас: original
response bytes и криптографическая неизменность с даты публикации не доказаны. Поэтому
bundle допускается только к development challenger; независимое подтверждение требует
forward collection. Raw не публикуется до отдельной проверки прав, ссылка на сайт ЦБ при
цитировании обязательна.

### CBR daily liquidity factors — current-vintage фактические валютные потоки

Официальная дневная таблица ЦБ собрана отдельно от недельного forecast и без чтения
market outcomes:

- path: `data/processed/info_radar/cbr-liquidity-factors-current-vintage-2021-2025-v1/`;
- 1 238 admitted rows `2021-01-11..2025-12-30`; исходная таблица содержит 1 239 строк,
  последняя исключена, потому что её публикация уже относится к 2026;
- processed: 66 943 bytes, SHA-256
  `88885d3695a88fb910d5a6ad9f3d8fd2cbd69eedaec779d4cef3048cd854c864`;
- manifest SHA-256:
  `f1701ec330fce9813d75bd711de235744dd8a9daf5f192325efe64f16e98e61a`;
- raw current-vintage snapshot SHA-256:
  `96901a15619561118719f8b4635bde97f964b806d59c609be9d40c0110dae95f`;
- 939 дней имеют ненулевые операции Минфина: 249 positive purchases, 690 negative sales,
  299 zero; по годам nonzero `242/12/226/228/231`;
- `publication_date` — следующий датированный рабочий день таблицы, `available_at` —
  10:31 мск этого дня; maximum `2025-12-31T07:31:00Z`.

ЦБ определяет положительный знак как покупку иностранной валюты, отрицательный — как
продажу. Это даёт заранее фиксируемый причинный знак для SI, но не гарантирует прибыль:
поток эндогенен нефтегазовым доходам и может быть заранее учтён рынком. Историческая
таблица прямо допускает уточнения, original publication bytes отсутствуют, поэтому
snapshot — только development source. Независимое подтверждение требует forward
архивирования страницы после каждой публикации. Raw не распространяется без проверки
прав; при цитировании нужна ссылка на ЦБ.

### Minfin OFZ auction results — current-vintage официальный event corpus

Официальный архив Минфина содержит датированные карточки результатов первичных
аукционов ОФЗ, а также отдельные corrections, несостоявшиеся и дополнительные размещения:

- path: `data/processed/info_radar/minfin-ofz-auction-results-current-vintage-2021-2025-v2/`;
- 410 карточек `2021-01-13..2025-12-24`: 364 успешных primary results,
  30 failed/cancelled, 8 supplemental, 7 corrections и 1 announcement;
- успешные primary rows по годам: `80/34/88/69/93`; 364 уникальных пары
  `auction_date × issue_code`, из них 283 fixed-coupon ОФЗ-ПД;
- processed: 73 794 bytes, SHA-256
  `a8c5c02457e3fadc19e617f42ad5a0c644672689a4c9bd8759d20d4a84d5d480`;
- manifest: 4 152 bytes, SHA-256
  `c6fcf390b728ebfd55c32b3a20880908bd4eb5ebfcff18bcaf150f568b607d52`;
- raw archive: 490 listing/detail responses, 6 214 948 bytes, SHA-256
  `f56af34a15a284e74f8364daf3abd6ae7d2978a01b22443e33ced079d72133c7`;
- все карточки классифицированы, обязательные поля 364 primary results полны, archive
  reverse chronology и неизменность result-index первой страницы во время сбора проверены;
- `available_at = 23:59:59 Europe/Moscow` напечатанного publication day: точного времени
  сайт не даёт, поэтому same-day market decision раньше этого момента запрещён.

Primary record хранит demand, placed volume, proceeds, cutoff/weighted price и yield;
`bid_to_cover` вычисляется как demand/placed. Для ОФЗ-ПК yield закономерно nullable,
для ОФЗ-ИН распознаётся real yield. Это current-vintage HTML, original publication bytes
не доказаны, поэтому источник допускается только к development challenger и требует
forward collection для независимого подтверждения. Сайт указывает лицензию CC BY 4.0;
raw всё равно остаётся вне Git. Первый bundle `...-v1` сохранён как superseded discovery:
одна ошибочно помещённая в result group карточка announcement ещё имела класс `other`.

### CBR macro survey — current-vintage ожидания аналитиков

Официальный workbook агрегирует медиану и распределение прогнозов аналитиков, то есть
добавляет forward-looking expectations, а не ещё один фактический flow:

- path: `data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1/`;
- 11 787 non-missing records, 37 выпусков `2021-05..2025-12`, по годам
  `5/8/8/8/8`, 17 indicators и девять statistics;
- processed: 78 291 bytes, SHA-256
  `a139ead81d1e06495afcd680ff1cb7903f2a102165c9f7bd7a074577c7069d6a`;
- manifest: 4 405 bytes, SHA-256
  `faae8927add739b0cf91dfdc9b7d8e7265d080f88685fd691e973ac907c4fdfe`;
- raw XLSX: 294 970 bytes, SHA-256
  `a715edf614799186278656970380aa0ba6abcfb801bfa2e92806cdc9fdb06944`;
- ключевые непрерывные каналы: USD/RUB, CPI, key rate и GDP; oil sheets менялись во
  времени, поэтому их нельзя бесшовно склеивать или считать пропуски нулями;
- точные исторические release timestamps и original workbook vintages не опубликованы.
  `available_at` намеренно отложен до `23:59:59 Europe/Moscow` последнего дня следующего
  месяца; 36 из 37 выпусков доступны до protected boundary, December 2025 — уже нет.

Это development-only источник. Он не может дать независимое подтверждение без forward
versioned snapshots. Единственный тест V21 был заранее запечатан SHA `5d97fd51...`:
same-target-year next-year median revisions, fixed direct signs и oil priority без
cross-series bridge. Он завершён `NO_GO`: mechanical return −3,17%, Sharpe −0,08 и
200/202 execution coverage с двумя critical failures. Direct revisions family закрыт.

### CBR Business Climate Index — release-specific опережающий режим

Официальный архив «Мониторинга предприятий» даёт отдельную датированную страницу и PDF
для каждого выпуска. Сводный индекс объединяет текущие оценки выпуска/спроса и ожидания,
поэтому это новая forward-looking информация для режима RI/MIX/SI, а не настройка
провалившегося V21:

- path:
  `data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1/`;
- 44 release pages и 44 release-specific PDF за `2022-05..2025-12`, по годам
  `8/12/12/12`; в каждой строке сохранены сводный BCI, текущие оценки и ожидания;
- processed: 17 471 bytes, SHA-256
  `b312f4e5ed0b0c7cdac2e2112068a5046a8bab4c272aa6f5edda7f03bf026de4`;
- coverage: 15 597 bytes, SHA-256
  `742e5a5a825952e28c4507b5d248aa5c4044e99ecce3c1cf253ec36312e131e8`;
- manifest: 4 216 bytes, SHA-256
  `99ad128b930b713cdda7988daa25f5dc763005eea768ccd4bd56ef89500835c8`;
- 90 raw responses (две archive snapshots, 44 HTML и 44 PDF): 56 153 797 bytes,
  SHA-256 `e362918e5554cf4e9ddb25c4378113dadc6129ffaa3b1dbfcb28af06468c2286`;
- три первых выпуска имеют явно сохранённый prior-month chart endpoint; это не missing и
  не искусственный сдвиг. Остальные 41 endpoint относятся к release month;
- только страница октября 2022 была обновлена позже публикации. Её `available_at`
  консервативно перенесён на конец `2022-11-24`, где она сталкивается с ноябрьским
  выпуском; downstream обязан оставить более новый `release_month`;
- source-only изменения сводного BCI: 21 positive, 18 negative и 4 zero после warmup.

Для сигнала разрешена только подпись с одним десятичным знаком на endpoint графика
конкретного выпуска. Более точное внутреннее значение Highcharts хранится лишь для
аудита и не должно давать скрытый порог. `available_at` — конец московского дня более
поздней из header publication date и footer last-updated date. Исторические страницы
получены сейчас, original bytes времени публикации не доказаны, поэтому источник годится
только для одного заранее запечатанного development challenger; независимое подтверждение
потребует forward snapshots. Единственный sealed V22 direct-delta test уже завершён
`NO_GO`: total return +13,37%, CAGR 2,54%, Sharpe 0,36, MDD −8,86% при полном execution.
Положительный результат сосредоточен в 2024 и не разрешает same-history threshold,
component, exact-decimal, sign, risk/expiry или blend selection.

### CBR inflation expectations and consumer sentiment — household regime

Официальный архив «Инфляционных ожиданий и потребительских настроений» содержит для
каждого месяца отдельные страницу, PDF и статистический XLSX. Это независимая от BCI
семейная/потребительская информация: ожидаемая инфляция отражает риск обесценения рубля,
а индекс потребительских настроений — направление спроса и склонность домохозяйств к
крупным покупкам.

- path:
  `data/processed/info_radar/cbr-inflation-expectations-release-pages-2022-2025-v1/`;
- 48 полных выпусков за `2022-01..2025-12`, по 12 в каждом году; 48 HTML, 48 PDF,
  48 XLSX и две archive snapshots, всего 146 raw responses;
- processed: 20 690 bytes, SHA-256
  `707112727156b4dbf61f115e53a19de0eb7474804c9d57cab55fe2829d9663c3`;
- coverage: 20 765 bytes, SHA-256
  `dd4444e2af0bfee1b4685fb2f8fde5b3ffa6245d93341096999da4facb1dad87`;
- manifest: 4 635 bytes, SHA-256
  `b132a45ee8170fc07c92dbf5be4c7b70833d07754c7abfd5d5ccc7ac6c3dce92`;
- raw responses: 116 941 747 bytes, SHA-256
  `fa2ecf58cc70588cb29089e96e47204f4bad1012aca131a809e5874cd0cd1c11`;
- все 48 HTML endpoints совпадают с XLSX после округления до отображаемой десятой;
  43/48 совпадают и без округления. Для стратегии разрешены точные release-specific
  XLSX values, а HTML остаётся отдельным extraction audit;
- после одного warmup expected-inflation delta: 25 positive и 22 negative; consumer
  sentiment delta: 24 positive и 23 negative. Согласованное подтверждение даёт 16
  risk-on, 17 risk-off и 14 mixed/zero source states до collision handling;
- страница сентября 2022 была обновлена позже публикации и имеет один `available_at` с
  октябрём 2022; causal downstream обязан оставить октябрь как новый release month.

`available_at` — конец московского дня более поздней из header publication date и footer
last-updated date. Исторические release-specific файлы получены сейчас, поэтому это один
development challenger, а не независимое подтверждение: для validation нужны собственные
forward snapshots. Sealed V23 завершён `NO_GO`: −5,35%, Sharpe −0,16, MDD −13,62%; эта
family закрыта для same-history sign/single-series/threshold/mixed-state tuning.

### Cboe VIX/VIX3M — глобальный forward-volatility term structure

FRED распространяет официальные Cboe daily closes `VIXCLS` и `VXVCLS` и позволяет
серверно ограничить CSV датой 2025. Это даёт независимый глобальный risk-state для
регулирования frozen V12 без подбора magnitude threshold: structural inversion проходит
ровно при `VIX/VIX3M > 1`.

- canonical path:
  `data/processed/info_radar/fred-cboe-vix-term-structure-current-vintage-2018-2025-v2/`;
- 2 087 exact shared-grid rows, 2 011 complete pairs и 76 preserved missing pairs;
- complete pairs по годам: `251/252/253/252/251/250/252/250` за 2018–2025;
- processed: 71 840 bytes, SHA-256
  `6ffe7daa623d01c4fd23562e05d317e6b5a778d32838db37f25b562a170ab567`;
- coverage: 7 545 bytes, SHA-256
  `a57e863cbe22734c59f410d9d66b0f0dc4af424f1a7db99edde9f4c3ac2bfc38`;
- manifest: 4 223 bytes, SHA-256
  `0aecc29fdc9181a0af6941fa4f3778487ba0b5d6dedce07aa843b1b0eb32b2d1`;
- два bounded raw CSV: 25 013 bytes, SHA-256
  `d11aa63712a9f4c85f1c6801c4821fcec058af6f617e48cc6c751076a9d247ef`;
- 174 backwardation, 1 837 contango, 0 exact flat; до protected availability допускаются
  2 010 pairs: 174 backwardation и 1 836 contango;
- максимум gap complete pairs — 4 календарных дня; missing не заполнены;
- V1 superseded из-за timestamp-unit replay mismatch. V2 повторно разобран из raw и
  точно совпал с processed frame; raw не содержит строк 2026.

Availability консервативно равна концу Chicago observation day. Поэтому для московского
решения используется только уже завершившийся US close; 2025-12-31 становится доступен
в 2026 и исключается. Ряды current-vintage и copyrighted/citation-required: bundle
пригоден для development challenger, не для независимой validation или raw
redistribution. Единственный sealed V24 дал +38,89%, но не улучшил V12 Sharpe/MDD и
завершён `NO_GO`; same-history boundary/freshness/scaling tuning закрыт.

### STLFSI4 — недельный глобальный financial-stress state

ФРБ Сент-Луиса описывает STLFSI4 как агрегат 18 weekly series: семь interest-rate,
шесть yield-spread и пять других финансовых индикаторов. Среднее индекса по истории
сконструировано равным нулю: positive означает стресс выше среднего, zero — normal,
negative — ниже среднего. Это даёт structural threshold без calibration по MOEX.

- canonical path:
  `data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1/`;
- 417 Friday-ending rows `2018-01-05..2025-12-26`, missing 0;
- 416 rows доступны до protected boundary; последняя допустимая observation
  `2025-12-19`, available `2025-12-26T05:59:59Z`;
- processed: 15 427 bytes, SHA `4937b686...`;
- coverage: 6 876 bytes, SHA `ec5e3aeb...`;
- manifest: 4 215 bytes, SHA `1a992f64...`;
- raw gzip: 3 670 bytes, SHA `d9ebef72...`; decoded CSV 7 882 bytes, SHA
  `7ec82dee...`, строк 2026 нет;
- 66 above-average и 351 normal-or-below rows; OOS 24 positive weeks:
  20 в 2022, две в 2023 и две в 2025;
- strict raw decode/hash/parse/build совпадает с processed DataFrame точно.

Availability — конец следующего Thursday Chicago, через шесть дней после Friday-ending
observation и с однодневным запасом после обычного Wednesday update. Current STLFSI4
Version 4 применена ретроспективно, original historical vintages и неизменность history
не доказаны; источник допускается только для adaptive development. NFCI и ANFCI были
отсеяны source-only: оба дали 0 above-zero weeks в OOS и потому не меняли бы V12.

Sealed V25 был pushed до outcome и дал +49,07%, CAGR 8,31%, Sharpe 0,818 при complete
execution. Return/Sharpe/worst year лучше V12, но MDD хуже на 0,0736 п.п.; strict verdict
`NO_GO`. Version 4 current-vintage limitation остаётся главным барьером: следующий тест
возможен только на новой forward/PIT history, без изменения zero/age/state mapping.

### CBR key rate — raw-replayed extreme monetary regime

V27 использует уже сохранённый официальный SOAP `KeyRateXML`, а не новостной proxy:

- raw: `raw/info_radar/cbr-dev-2018-2025-v1/0001_cbr_key_rate_soap_key_rate_xml.xml`,
  121 958 bytes, SHA `06da1497c...`;
- request-body SHA `04c6f1fc...`; manifest и processed CBR panel byte-pinned через V26;
- exact raw parse воспроизводит 2 015 rows `2018-01-09..2025-12-30`, range
  `4,25..21,00%`; другой CBR series parquet predicate не допускает;
- точного historical publication timestamp feed не даёт, поэтому
  `available_at = effective_date + 1 calendar day, 00:00 Moscow`;
- source-only weekly V27 state использует круглый boundary `>=20%`, age `<=7` дней:
  OOS 40 дополнительных cash weeks после STLFSI4, 0 missing/stale.

V27 был sealed/pushed до PnL и прошёл development gates, но rule выбран после V26 на
том же периоде. Поэтому current/history плюс conservative timestamp достаточны для
adaptive research, не для независимого live evidence. Требуется forward archive с
actual retrieval/publication time; boundary/age/partial scale по 2021–2025 не менять.

### Новый закрытый holdout — официальный metadata route к 2008–2011

После отрицательной проверки 2012–2017 выполнен новый metadata-only поиск, не
обращавшийся к daily history. Exact shortname filters нашли 81 expired contract с
экспирациями 2008–2011: BR 38, MIX 1, RTS 16 и Si 26. Все 81 descriptions содержат
FRSTTRADE/LSTDELDATE, ни одно не содержит LSTTRADE; для каждого найден ровно один
пересекающий период RFUD. Всего audit сделал 18 finder и 81 detail request. Минимальный
FRSTTRADE — `2007-03-15`, максимальный LSTDELDATE — `2011-12-16`; это metadata, не
market outcome.

До первого daily response exact source rules и replay wrapper были pushed commit
`49467bc`: config SHA `92c7f324...`, wrapper SHA `55965d9c...`, reused parent SHA
`7dd25e01...`. V1 остановился без output на identity-only NULL row
`RIM9_2009/2008-09-12`; значения не печатались, outcomes не считались. Parser-only V2
SHA `74847dd3...`/`acc547f5...` сохраняет такие source rows missing с false flags,
ничего не меняя в universe/dates/endpoints/raw. После push `617ce72` V2 collection
завершена: 8 381 rows, 81 contracts, 224 requests, `2008-01-09..2011-12-16`; manifest
SHA `e06fd978...`, raw SHA `e8a97876...`, 41/41 audit checks true. Вторая inert identity
оказалась `SiU9_2009/2008-09-12`; точное число заранее не выбиралось. Returns/PnL не
читались и остаются закрыты до отдельного strategy seal.

Следующий outcome-free D1 seal SHA `8f5737bc...` заранее решает проблему позднего MIX:
не сжимать весь период до 54 общих сессий и не backfill-ить несуществующий инструмент.
Master строится по SI/RI/BR (781 factual sessions), MIX маскируется до `2011-09-30` и
включается только по своим 54 factual dates. Derived build ещё не выполнялся; сначала
обязателен commit/push SHA.

D1 был pushed `45e55af`, но не дошёл до daily load: source `protected_from=2026` — это
защита acquisition, не дата допустимого market row. D2 SHA `f928e58b...`/`2e01c3fc...`
разделяет эти границы и по-прежнему требует все derived market dates `<2012`; никаких
price/outcome фактов для correction не использовано. После seal `fa61763` D2 создал
immutable source-only output, но audit принял только 25/27 checks из-за двух
serialization representations; market values совпали точно. D3 SHA
`93b1d3fb...`/`438f2dd5...` заранее фиксирует только bool и JSON-list normalization.
После pre-build seal `afaa278` canonical D3 manifest `ff9b2771...` прошёл 27/27 replay
checks и отдельное строгое values+dtypes comparison всех frames.
Экономическое преимущество этого маршрута — 2008–2011 пока не использовались для выбора
стратегии и включают кризис/восстановление. Они останутся закрытым holdout до того, как
новая strategy family будет разработана на 2012–2017 и отдельно запечатана.

V30 development family использует дополнительную информацию уже внутри canonical market
source: причинный front/next curve carry и одновременный cross-asset trend snapshot.
Она сознательно не добавляет current-vintage macro governor: V28/V29 показали плохую
переносимость и неполный PIT timing. Любой новый внешний macro/positioning/news source
для 2008–2011 должен быть отдельно запечатан до чтения его значений и outcomes.

### Unseen validation audit — официальный metadata route к 2012–2017

Первичная проверка текущего `/statistics/.../series` catalog была ложно-пессимистичной:
этот listing неполон для старых expiries. Повторный metadata-only audit без price/PnL
нашёл официальный `/iss/history/engines/futures/markets/forts/boards/RFUD/securities`
и expired-security search. Exact contract-name filters обнаружили 155 core-four
contracts в 2012–2017: BR 71, MIX 24, RI 24 и SI 36. Per-security description/boards
возвращают исторические `FRSTTRADE`, `LSTTRADE`/`LSTDELDATE` и RFUD board history.

До первого price request был committed/pushed source-only V3 protocol с exact discovery
filters, interval, pagination, raw archive, hashes, missing policy и temporal ceiling.
Official bundle содержит 30 059 daily rows по 155 contracts, manifest SHA `e60d0bca...`;
raw cursor replay и maximum date `2017-12-21` проверены. Returns, targets и PnL ещё не
считались. Первый immutable derived-source D1 выявил purely operational defect: exact
search включил 12 старых serial-month Si contracts, и nearest-expiry chain застрял на
неисполненном roll/exit. Официальные
[параметры срочного рынка](https://www.moex.com/en/derivatives/parameters.aspx) задают
quarter cycle для Si/RTS/MIX и month cycle для BR, а
[спецификация кодов](https://www.moex.com/s1085) подтверждает month codes. Поэтому D2
до любого strategy outcome фиксирует H/M/U/Z для SI/RI/MIX и все месяцы для BR и требует
ноль unresolved roll/exit. Его preflight не опубликовал output только из-за слишком
строгого ожидания непрерывного SI roll: source причинно закрывает позицию в декабре 2016,
остаётся flat до первой строки 2017 и затем re-enters. D3 отдельно pin-ит exact gap dates
и запрещает синтетически переносить через них return. Canonical D3 завершён с manifest
SHA `3ab20092...`: 1 479 common sessions, exact 22/23/70/23 roll и ноль unresolved
roll/exit; strategy outcome не читался.

Для frozen governors/collateral подготовлен отдельный bounded macro collector:
[FRED STLFSI4](https://fred.stlouisfed.org/series/STLFSI4),
[CBR RUONIA dynamics](https://www.cbr.ru/hd_base/ruonia/dynamics/) и official CBR
KeyRateXML. S1 SHA `3daa3c40...` фиксирует request bounds, raw archive и conservative
availability до HTTP. S1 не получил response из-за User-Agent-specific timeout; S2 SHA
`4ad7f034...` изменил только transport identity на `curl/8.10.1` и после seal получил
все responses, но не опубликовал output из-за неизвестного marker в старых RUONIA rows.
S3 SHA `ae575962...` predeclares единственную parser correction: 78 explicit publication
dates сохраняют causal availability, 1 400 unknown dates остаются missing без inference
и без collateral credit. Seal `1f9c343` предшествует collection; canonical manifest SHA
`949bc7bf...`, exact raw replay и temporal/schema audit прошли полностью.
Ограничение существенное: STLFSI4 — current-vintage history, а не архив оригинальных
weekly vintages; это нужно явно учитывать в verdict V28.

После успешного D3 derived-source и отдельного V28 seal этот период можно использовать
как новую независимую проверку byte-identical V27 trend/capital/execution path. Он не
проверит уникальное
действие monetary governor: официальная key rate не достигала 20% (maximum 17% в 2014).

[MOEX Historical Data](https://fs.moex.com/f/3431/available-data-types.pdf) и отдельные
[тарифы/условия MOEX](https://www.moex.com/files/4qp9vgzvtcvj33w14js8gxd3n3) остаются
авторитетным путём к broker/exchange-exact EOD, trade log, order book, historical specs,
fees и IM. Анонимный HTTP-доступ сам по себе не доказывает право на перераспределение и
не заменяет licensed data для live admission.

### Уже использованные источники

- MOEX daily futures/active map: OHLC, settlement, volume, OI, front/next curve и
  participant OI;
- CBR: ключевая ставка, RUONIA и официальный USD/RUB с publication semantics;
- CFTC: weekly positioning с Friday release lag и отдельными holiday overrides.

RUONIA использована в V15/V26/V27; key rate — в V27. Причинная collateral часть V16 не
исправляет недоступный FUTOI signal, поэтому V16 combined metrics недействительны.

Эти признаки уже встречались в V6/V8/V9. Их нельзя выдавать за новую информацию лишь
потому, что изменён threshold или модель.

## Приоритеты получения

| Priority | Источник | Потенциальная польза | Главный барьер | PIT-правило |
|---|---|---|---|---|
| P0 | Historical MOEX/broker specs, fees, IM, spread/order book | Отделить реальную исполнимость от ложной прибыли | Лицензия/подписка и broker archive | Использовать только запись, действовавшую до order time |
| P1 | MOEX RVI | Forward-looking risk regime для RI/MIX и общего gross | Current-vintage history; нужен один sealed test | Только предыдущая source date |
| P1 | MOEX FUTOI daily-last | Forward crowding/risk regime для всех core-four | V16 INVALID; historical publication vintages не доказаны | Только `available_at <= decision_at`, source date недостаточно |
| P1 | Полный MOEX FUTOI 5m | Будущий forward timing/момент сделки | Current-vintage, 1 000-row cap, offset игнорируется; historical PIT отсутствует | `max(SYSTIME + buffer, retrieval_at) <= decision_at` |
| P1 | CBR weekly liquidity forecast | Заранее известный рублёвый liquidity/fiscal-flow regime для SI | Bundle готов; original response bytes не доказаны | Только дата внутри record и `available_at <= decision_at` |
| P1 | CBR daily Minfin FX operations | Прямой persistent FX flow для SI и будущего intraday timing | Current-vintage revisions; original publication bytes отсутствуют | Следующий рабочий день, не раньше 10:31 мск |
| P1 | Minfin OFZ auction results | Causal demand/liquidity shock для RI/MIX/SI | Date-only и current-vintage; нужен sealed test и forward vintages | Только конец publication day, затем следующий factual open |
| P1 | CBR macro survey | Forward consensus revisions для SI/BR/RI/MIX | Current-vintage, historical release time неизвестен | Только конец месяца после survey month; original vintages нужны для confirmation |
| P1 | CBR Business Climate Index | Опережающий режим выпуска/спроса для RI/MIX и рубля | Release pages retrieved сейчас; original bytes не доказаны | Конец max(publication, last-update) day; collision оставляет latest release month |
| P1 | CBR household inflation/sentiment | Согласованный потребительский risk-on/off regime для RI/MIX/SI | Release files retrieved сейчас; нужен sealed test и forward vintages | Конец max(publication, last-update) day; collision оставляет latest release month |
| P1 | Cboe VIX/VIX3M via FRED | Глобальный structural stress governor для frozen V12 | V24 NO-GO; новый тест только forward/unseen, source current-vintage/copyrighted | Только complete pair после Chicago day-end и `available_at <= decision_at` |
| P1 | STLFSI4 via FRED | Редкий broad financial-stress switch для frozen V12 | V25 strong but strict NO-GO; только forward/PIT, Version 4 current-vintage | Только после following-Thursday Chicago end и `available_at <= decision_at` |
| P2 | EIA Weekly Petroleum Status Report | Независимые supply/demand shocks для BR | Bundle готов; consensus отсутствует, delayed edge ещё не проверен | Только `available_at <= decision_at`; stale issue исключён |
| P2 | CBR publication calendar, RUONIA term structure, key-rate text | Forward confirmation V27 funding/monetary state | Числовые RUONIA/key-rate уже использованы; V27 требует unseen | Actual publication/retrieval timestamp, не observation date |
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
- [CBR macroeconomic survey](https://www.cbr.ru/eng/statistics/ddkp/mo_br/) — медианы,
  диапазоны и история прогнозов аналитиков;
- [CBR Business Monitoring archive](https://www.cbr.ru/analytics/dkp/monitoring/) —
  датированные страницы и PDF индекса бизнес-климата;
- [CBR inflation expectations archive](https://www.cbr.ru/analytics/dkp/inflationary_expectations/) —
  датированные страницы, PDF и статистические XLSX ожиданий и настроений домохозяйств;
- [Cboe VIX term structure](https://www.cboe.com/tradable-products/vix/term-structure/),
  [VIX historical data](https://www.cboe.com/tradable-products/vix/vix-historical-data),
  [FRED VIXCLS](https://fred.stlouisfed.org/series/VIXCLS) и
  [FRED VXVCLS](https://fred.stlouisfed.org/series/VXVCLS);
- [CBR liquidity forecast](https://www.cbr.ru/eng/statistics/pffl/),
  [daily liquidity-factor definitions](https://www.cbr.ru/statistics/flikvid/definitions/)
  и [historical publication-schedule notice](https://www.cbr.ru/eng/press/pr/?file=120516_104301eng_liq-ind.htm);
- [CFTC COT description](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
  и [release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm);
- [EIA WPSR schedule](https://www.eia.gov/petroleum/supply/weekly/schedule.php),
  [release archive](https://www.eia.gov/petroleum/supply/weekly/archive/) и
  [copyright/reuse](https://www.eia.gov/about/copyrights_reuse.php).

## Следующая проверяемая гипотеза

V16 имеет статус `INVALID_FUTOI_LOOKAHEAD`: 932/1 044 signal states не были доступны к
decision. Новые daily FUTOI/RVI thresholds на тех же 2021–2025 закрыты.

Current-vintage FUTOI bundle уже завершён и fail-closed закрыт для historical PnL. EIA
V17 и прямой CBR liquidity-forecast signal V18 завершены отрицательно. Сам CBR bundle
остаётся пригодным target-free PIT-кандидатом, но увиденный V18 outcome нельзя
использовать для инверсии знака или выбора другой строки/порога.
Следующие незаблокированные действия:

1. запросить у MOEX licensed original-vintage/bulk history либо начать отдельный forward
   collector, который timestamp-ит получение каждого нового 5m response в реальном
   времени; до этого FUTOI timing sleeping;
2. не публиковать raw FUTOI до проверки лицензии, несмотря на анонимный HTTP 200;
3. V18 CBR forecast test завершён `NO_GO`: primary CAGR −10,31%, Sharpe −0,51,
   MDD −55,73%, 1/5 positive years при полном исполнении. Не создавать V18.1 с
   противоположным знаком, extreme-week threshold или другой строкой того же release;
4. CBR daily-factors snapshot и V19 завершены: direct persistence знака фактических
   операций Минфина для SI дал total return −0,03%, Sharpe 0,05 и MDD −30,76% при
   полном исполнении. Не инвертировать знак и не выбирать magnitude/change days,
   smoothing или иной lag по увиденному outcome;
5. для stability RI/MIX приоритетнее licensed MOEX/broker specs/order-book и новый unseen
   forward период; старые RVI/FUTOI thresholds по 2021–2025 не перебирать;
6. официальный Minfin OFZ corpus собран: 410 events, 364 primary results, все primary
   fields полны, processed SHA `a8c5c024...`, manifest SHA `c6fcf390...`. V20 causal
   OFZ-PD demand-strength test завершён `NO_GO`: total return −5,35%, CAGR −1,09%,
   Sharpe −0,63, MDD −6,19% при полном исполнении. Не подбирать sign, extremes,
   rank window, expiry и failed/PK/IN по этому outcome;
7. CBR macro-survey source готов: 37 survey months, 17 indicators, 11 787 records,
   processed SHA `a139ead8...`, manifest SHA `faae8927...`; только 36 releases causal до
   2026. V21 direct revisions завершён `NO_GO`: −3,17%, Sharpe −0,08, 2 critical;
   same-history signs/indicators/oil priority/threshold/risk/expiry tuning закрыт;
8. CBR Business Climate Index bundle готов: 44 versioned releases, 90 raw responses,
   processed SHA `b312f4e5...`, manifest SHA `99ad128b...`. V22 direct printed-delta
   завершён `NO_GO`: +13,37%, CAGR 2,54%, Sharpe 0,36, 2/4 positive active years при
   полном execution. Exact decimals/components/signs/risk/expiry не подбирать;
9. CBR household inflation/sentiment bundle готов: 48 release-specific XLSX/PDF/pages,
   146 raw responses, processed SHA `70711272...`, manifest SHA `b132a45e...`. V23
   запечатан SHA `2a8a35a8...` и проверяет только один confirmation regime: expected
   inflation down + sentiment up = risk-on, обратная согласованная пара = risk-off,
   mixed = cash. Canonical result `NO_GO`: −5,35%, Sharpe −0,16, MDD −13,62%; не
   инвертировать signs, не выбирать один ряд и не торговать mixed states post-hoc;
10. Cboe VIX/VIX3M V2 bundle готов: 2 087 rows, 2 011 complete pairs, processed SHA
    `6ffe7daa...`, manifest SHA `0aecc29f...`; 174 structural backwardation days до
    protected boundary. V24 был запечатан/pushed до outcome и завершён `NO_GO`:
    +38,89%, Sharpe 0,739, MDD −14,28%; same-history tuning запрещён;
11. любой следующий PnL начинается только после source manifest, `available_at` audit и
   нового sealed protocol. Continuous model может решать чаще суток, но не раньше
   фактического получения bucket.
