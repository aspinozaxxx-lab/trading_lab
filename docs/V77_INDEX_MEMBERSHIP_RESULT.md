# V77 — first-inclusion drift: SOURCE_FEASIBILITY_REJECTED

2026-09-14. Только предварительный отсев по данным, **без экономического run**.
Прибыльная стратегия не найдена; 17 прежних economic screens / 0 Stage2 не меняются.

## Что проверено

[Первый протокол](V77_INDEX_MEMBERSHIP_FEASIBILITY.md) pushed `91a18f3` до двух
date-specific requests. [Census](V77_INDEX_FIRST_OBSERVATION_CENSUS.md) pushed
`5c32398` до отдельного all-period request. News sample остаётся paused.

Документированный [ISS ticker route](https://iss.moex.com/iss/reference/141) позволил
запросить только `ticker,from,till`. Ровно 3 anonymous HTTP200, без retries/redirects,
credentials, цен или index weights. Первый setup остановился на PermissionError до
HTTP; root создал только новый leaf directory с owner trading-lab. Parent permissions
и службы не менялись. Каждый raw сохранён до разбора, HTTP повторно не выполнялся.

На 2018-01-03 и 2025-12-30 получено по 45 уникальных tickers, from=till=requested date.
Пересечение 28, объединение 62; по 17 имён только в первом/втором срезе. Это не 34 сделки:
между датами могли быть повторные изменения, а ticker не тождественен ценной бумаге.
Проверка поддерживает historical date filtering, но не original vintage/полноту.

All-period catalogue: 127 unique tickers, first metadata date 2001-01-03,
last metadata date 2026-09-11. Чтение только metadata dates 2026 явно предусмотрено
вторым протоколом; market values 2026 не запрашивались. По till/нынешней торгуемости
ничего не отбиралось. Предикат from>=2018-01-01 AND from<2026-01-01 даёт:

| Год | Первые появления тикера в каталоге |
| --- | ---: |
| 2018 | 2 |
| 2019 | 1 |
| 2020 | 6 |
| 2021 | 3 |
| 2022 | 0 |
| 2023 | 5 |
| 2024 | 7 |
| 2025 | 5 |
| Всего | 29 |

Это 29 ticker candidates на 18 датах, НЕ 29 подтверждённых первых включений разных
ценных бумаг. Переименования, redomiciliation и изменения coverage могут уменьшить
число независимых событий. Каталог не доказывает отсутствие пропущенных исторических
записей и не содержит времена ранних объявлений или revision chain.

Прежний price manifest для 30 акций проверен только как metadata, SHA
`5a7a4873f01141682c9c53d0714d235187eec6b57e5449b23bb04e68c4593042`.
Intersection с 29 candidates: **только ENPG**, 28 не покрыты ready bundle.
Market Parquet, включая legacy2026 paths из manifest, не открывались и не переносились.

## Решение

Вариант — delayed demand ПОСЛЕ первого effective включения, long-only, не покупка
заранее после announcement. Предварительно установленный minimum 30 security events
не достигнут даже на 29 неочищенных candidates каталога. Ready price universe даёт
лишь 1/29 coverage; выбирать только ENPG нельзя. `SOURCE_FEASIBILITY_REJECTED`,
`economic_admission=false`, economic runs 0; trades/CAGR/Sharpe/MDD/annual returns=null.

Не понижать gate, не добавлять re-entries ради числа, не считать aliases независимыми.
Это НЕ доказательство убыточности индексных стратегий вообще. Исходная announcement
гипотеза всё ещё требует полный original news/event corpus; его blocker не устранён.
Нового portfolio engine, model, collector, paper activation или реальных сделок нет.

## Evidence

Реальные bytes только во внешнем server storage, не в Git.

- Два среза: `/srv/trading_lab_data/source_evidence/v77_index_membership_20260914_a36fd81a`.
  Manifest SHA `4fa0d0d3229e94fc7784517c335060be7e9f4ddc1b7f44b42d8f8cf4ffd8a5a5`.
  Raw2018: 1876 bytes, SHA `c0eabe040eeaaad13461d686bbab6113b8888a219ac95fcd4d3bfad05d1286fc`.
  Raw2025: 1872 bytes, SHA `e2dcd1219eada311834f95c7ec51bf4fbf393e629c17c4bd97575f025d74f17a`.
  Receipt 13:59:56.924615Z / 13:59:57.198683Z.
- Census: `/srv/trading_lab_data/source_evidence/v77_index_first_observation_20260914_be81cb45`.
  Manifest SHA `aa0163cde378844b224c3a74cbb0688537fca17388a6a0da57c057d3313c9b20`.
  Raw 5158 bytes, SHA `0f8c1d37d645ade071ecc11356be7571f939bcdb18c3b83350303a51d6bf1fb3`.
  Receipt 14:03:06.505212Z. Audit `audit.json` SHA
  `faf4331cc463975feefde9ea4113ab15eea99912bc901d81758c9f1a7bd2ab38`.

Отдельный replay проверил 2 manifest / 3 raw hashes и размеры, exact columns,
даты срезов, unique tickers, raw→manifest records, candidate predicate/year counts,
union/intersection и пересечение с 30 manifest tickers. PASS_METADATA_REPLAY_ONLY
не означает экономическую пригодность. Scripts исполнены одноразово через server
Python stdin; постоянного кода/процесса не установлено. Paper/collectors неизменны.

Frozen protocol SHA:
`a36fd81a71d3e69af7ba64cd4ea50ca2acc22a3270558244966db5b962068b08` и
`be81cb45e8417105c449a74626451ead2d8bd35beaf954bf53c34d5ca65b8f83`.
Planned в frozen объявлениях — pre-run состояние; актуальный verdict здесь.
