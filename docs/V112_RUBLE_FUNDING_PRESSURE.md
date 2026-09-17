# V112: рублёвое фондирование и SI, conditional Stage1

Pre-outcome, 17 сентября 2026. Цель относительно предсказуемых 20–50% годовых не
меняется и не подтверждена. Предыдущий turn — PROGRESS: V111 отсеян и сохранён,
не прибыль. Здесь один новый совместный информационный механизм, без grid search.

## Гипотеза и фиксированное правило

Дорогой overnight-рубль в условиях чистого заимствования банков у ЦБ может побуждать
сокращать short-RUB финансирование и продавать валюту, поддерживая рубль и снижая SI.
Это гипотеза о последующей передаче funding pressure, не установленная закономерность:
реакция может быть мгновенной, а санкции, ограничения капитала и экспортные потоки — сильнее.

**Primary: SI short 0.9**, если на одну observation date одновременно
`RUONIA - key_rate > 0` и `bank_deficit_excluding_correspondent_accounts > 0`.
В остальных случаях cash. Нули — cash, сравнение Decimal, без оценённых порогов.
Control: short 0.9 при том же положительном rate spread, без условия знака deficit,
но с идентичной готовностью всех трёх источников. Он диагностический, не новый alpha.

V18 использовал недельный прогноз ликвидности, V19 — фактический Minfin FX,
V71 — сопоставленную ошибку прогноза. Эти семьи закрыты. V15/V26 использовали RUONIA
для income на collateral, V27 — абсолютный key-rate governor старого портфеля.
Здесь нет старого тренда, governor, carry credit, leverage или смены знака V71.
Новая quantity/price комбинация не доказывает независимость от старых механизмов.

## Что именно измеряет источник

[FAQ ЦБ](https://www.cbr.ru/oper_br/o_dkp/liquidity/) предупреждает: структурная
позиция центрального банка сама по себе не показатель здоровья экономики или банков.
Поэтому недостаточно назвать положительный/отрицательный stock сигналом risk-on/off.

[Официальная таблица](https://www.cbr.ru/hd_base/bliquidity/?UniDbQuery.From=01.01.2018&UniDbQuery.Posted=True&UniDbQuery.To=31.12.2025)
содержит отдельный третий столбец **без учёта корсчетов**: требования ЦБ минус
обязательства по привлечению ликвидности, включая отдельно обозначенные возвратные
операции; млрд RUB на начало observation day. Берём этот именованный столбец на
всём интервале, не склеиваем analytical headline до/после November2023.
Headline с поправкой на корсчета/УОР, все его компоненты и будущие cells не читаются
для signal. Поправка УОР пересматривается ретроспективно, а whole current table
всё равно не доказывает оригинальные исторические vintages выбранного столбца.

[Schedule release 16May2012](https://www.cbr.ru/eng/press/pr/?file=120516_104301eng_liq-ind.htm)
говорит про ежедневные **факторы** ликвидности. Не переносим его deadline10:30 на
другую stock table как установленный факт. [Правила сайта](https://www.cbr.ru/about/)
и [соглашение](https://www.cbr.ru/user_agreement/) сохранены: private noncommercial
research с атрибуцией, без продажи/публикации raw или вывода о коммерческой/live лицензии.

## Источник, часы и недостающие данные

Новый server capture `source_evidence/cbr_bank_funding_20260917_v2/capture`:
4 HTTP200, без retry/redirect, COMPLETE_METADATA_ONLY 05:18:39.764847UTC.
Unit `trading-lab-cbr-bank-funding-source-20260917-v2.service`, invocation
`3e865396bbc34f34b5e12a2423275050`. 2012 dates, 15 cells на строку, 2018–2025.
Raw823663bytes, SHA `e9379222e584244af664b847a68d5995e5ecc594245f9af5a06878aa101dc860`;
manifest `6b5233ccde39baec49c7b9c467dc379f8bc27a75b41d1f1281d2d04a0798d1c0`.
10-file local backup проверен по manifest+9 hashes. V1 import failed до HTTP на
отсутствующем bs4; original script/unit/failure сохранены с SHA `39373aa1...`.
V2 переиспользует существующий stdlib parser, без установки библиотек. Между ними
SSH connection reset был проверен: V2 unit ещё не запускался, source не перезапускали.

RUONIA/key rate повторно не скачиваются. Используются ранее сохранённые официальные
HTML/XML из `data/raw/info_radar/cbr-dev-2018-2025-v1`, pinned manifest/panel/raw
hashes в config. Только дата, ставка и дата публикации RUONIA; прочие RUONIA поля и
USD/RUB official не интерпретируются. Raw rates перепарсиваются с точными clocks.

1963 admitted RUONIA observations, 2015 key-rate rows; все1963 имеют точную same-date
пару policy/stock. Key-only52 даты не превращаются в наблюдения overnight-рынка.
Это календарь опубликованных RUONIA observations, не отбор по исходам/прибыльности.

- RUONIA: 00:00 Moscow календарного дня после напечатанной publication date.
- Key rate: 00:00 Moscow дня после effective date; SOAP `+03:00` проверяется.
- Stock: **условно конец следующего календарного дня Moscow**.
- Joint availability = максимум трёх clocks; history corrections этим не лечатся.
- Same-date policy rate, а не более новый уровень на момент публикации старой RUONIA.
- Availability >= 2026 Moscow исключается до преобразования числовых cells.
- Последний missing/null/mismatched event маскирует оба arm; older-good fallback,
  interpolation и zero fill запрещены. Source age на fill <=7 calendar days,
  decision-to-fill <=7. Праздничные gaps и начальный cash входят в полную историю.

До seal полные joint numeric states, directions, targets и новый PnL не читались.
Отдельные macro cells Oct/Dec2025 и2026 уже были в web snippets; они не unseen и не
использованы для выбора правила. Protected2026 market outcomes не открывались.

## Исполнение, gates, проверка

Full2018–2025, RUB1m, idle cash interest0, прежний EOD → next factual open integer
ledger V72/V78/V64. Admission gross cap1, target0.9, margin buffer2, participation1%.
Base1tick+1xfees / double2ticks+2xfees. Halts, costs, rolls, missing marks и unresolved
не удалять. Исследовательские specs/fees/margin, не broker-exact исполнение.

Одинаковые predeclared gates в обоих costs: CAGR>=5%, Sharpe>=0.5, MDD<=25%,
>=20roundtrips, >=5positive years/8, worst year>=−15%, excess over control>=2pp.
Source-ready>=80%. Все4 execution-complete, critical0/unresolved0/terminalflat.
Rolls отдельно от независимых signal episodes. 5% — только вход в Stage2 компонента,
не замена цели20–50%. Просмотренная history — development, не независимый holdout.

34 новых /168 combined local synthetic tests PASS, 15 futures metadata checks PASS,
Ruff clean. Source-date matching1963/1963 проверен без вычисления спреда/направлений.
До единственного economic run фиксируются code/config/tests/protocol/capture/parser
и transitive V101 seal, затем commit/push и server tests. Сохраняются все planned
states, обе target series, четыре orders/positions/ledgers, annual metrics и manifests.

После результата не менять знак, актив, lag, TTL, размер, контроль, costs или filters.
Никаких broker/demo/live, paid подписок, credential reads, Windows collectors или
расширения AlgoPack economic scope. Main archive работает независимо.
