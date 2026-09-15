# V91 — точная связь опциона с фьючерсом, только static metadata

2026-09-15. Продолжение V90, не новая экономическая гипотеза. Пока V89 сохраняет
описания, подготовлен mapper к прежнему правилу и ledger. Код не делает HTTP,
не читает OI/цены/labels/targets/PnL и не запускает стратегию.

## Договорная связь

`option_contract_mapping.map_description` принимает raw bytes и ожидаемый SHA;
будущий full runner обязан брать SHA из закрытого source manifest, не из произвольной
таблицы flags. Проверяются точный SECID, ASSETCODE, GROUP, TYPE и MARGINSTYLE.

Для margined future option необходимы одновременно:

1. Явные FRSTTRADE/LSTTRADE/LSTDELDATE типа date; последний имеет определение
   «Дата экспирации». Не угадывать день по коду месяца или третьему четвергу.
2. Точное имя фьючерса в конце NAME и тот же буквальный префикс SERIES_NAME.
   Имя ищется в сохранённом датированном futures catalog. Дату фьючерса брать оттуда,
   а не из серии опциона, active map или совпадения одной цифры года.
3. UNDERLYINGASSET согласуется с SECID этого фьючерса. Исключение SI: поле
   USD000UTSTOM допускается только вместе с точным именем/серией и тем же cash root
   в независимом catalog. Сам по себе USD000UTSTOM не определяет фьючерс.
4. Option lifecycle целиком внутри underlying lifecycle. Aliases одного exact
   canonical ID объединяются; одинаковое имя у разных canonical ID — gap.
5. Положительные конечные STRIKE/LOTSIZE, явные OPTIONTYPE/EXECTYPE/UNIT/series.
   STRIKE имеет определение «Цена Страйк». DELIVERYTYPE явно говорит, что при
   исполнении заключается базовый фьючерс по цене исполнения опциона.

Последнее условие доказывает сравнимость страйка с ценой этого фьючерса. Опционное
поле UNIT может описывать **премию**, поэтому его текст не сравнивается с quote unit
фьючерса и не используется для выдуманного lot/currency multiplier. Это не доказывает
исторические option fees/margin или исполнение опционом: V90 торгует самим фьючерсом.

Явный premium currency option исключается с отдельным class/count, даже при том же
SI cash root. Неизвестный класс, потерянный field или конфликт остаются unavailable.
`metadata_ready=true` у currency означает доказанную классификацию для исключения,
не futures mapping. Все результаты сохраняют `economic_admission=false` и
`original_publication_proved=false`: сегодняшняя карточка не original PIT vintage.

## Имеющийся справочник вместо нового скачивания

Найдены четыре V5 manifest + четыре raw catalog + четыре normalized Parquet.
Все 12 exact paths/bytes/SHA включены в `configs/v91_option_contract_mapping_v1.json`.
Объём исходных files **255660 bytes**, 228 alias rows / 220 canonical futures.
Источник обнаружен через V7 manifests, но новая зависимость фиксирует непосредственно
V5 manifests и их catalog_artifacts; candles/OI/spec-price artifacts не читаются.

`load_catalogs` проверяет файлы, manifest period2018–2025/protected2026, schemas,
raw→normalized equality и канонический ID. Читаются семь static columns; текущий
`is_traded` не используется как историческая доступность. Сведения о будущих
экспирациях контрактов, введённых до конца2025, допустимы как static metadata,
**не** как разрешение читать их рыночные значения2026.

Локальное read-only сопоставление всех этих catalog rows выполнено, evidence SHA
`ca7fb707635608c186685f8463977e64df36f3014826e90df5102bb9d0a5505e`.
Для server будет скопирован только этот маленький subset в отдельный внешний leaf
`/srv/trading_lab_data/source_evidence/v91_static_futures_catalogs_v1`.
Исходные данные не добавляются в Git и не запрашиваются заново.

## Проверки и граница этого шага

57 первых synthetic tests PASS; вместе с V90/V89/V88 —124 local PASS, Ruff clean.
Два дополнительных malformed-field tests включены до seal; итоговый count в result note.
Проверены оба side/четыре assets, повторяющиеся по десятилетиям SECID, aliases/ambiguity,
identity/schema/hash/lifecycle conflicts, cash currency exclusion, explicit definitions,
premium-unit independence и передача mapped fields в строгую V90 feature schema.
Loader tests используют только generated fake catalogs, включая hash-valid raw/Parquet
расхождение. Это тесты кода, не 57 торговых гипотез и не историческая прибыль.

После byte seal — один новый static binding check на восьми уже сохранённых V88
description responses. Это новая проверка связи с фьючерсом, не повтор HTTP/probe.
Результаты сохранять отдельно от protocol; пока здесь они **не заявлены**.
Нельзя выбирать по ним активы или допускать economic subset из первых BR responses V89.

Полный mapping/coverage pass ждёт terminal immutable V89 manifest. Далее нужны полный
source calendar261×4, отдельный economic code/config/input seal и один V90
2arms×2costs run на готовом daily ledger. Весь development2021–2025 уже не unseen
holdout. Economic screens остаются25, Stage2=0; цель20–50% не подтверждена.
