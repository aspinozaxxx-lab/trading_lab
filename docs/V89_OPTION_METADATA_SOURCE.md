# V89 — NULL-mask census и точные спецификации для опционного теста

Declared2026-09-15T14:50:40Z. Source-only подготовка ранее отложенного pinning test,
не новый economic screen. V88 установил доступность exactSECIDdescription/expiry,
но выявил разные типы и единицы SI, неоднозначный underlying field. Нельзя применять
одну дату/спецификацию ко всем страйкам по восьми примерам.

## Фиксированный отбор запросов

Сначала проверяются SHA source manifest/audit/parquet и все metadata dates до2026.
Из числовой колонкиopenposition используется только Arrow validity bitmap через
`is_valid`: значения не конвертируются в Python, не сравниваются, не ранжируются,
не сохраняются и не печатаются. Non-NULL не означает positive/finite/usableOI.

Inventory сохраняет все108104SECIDs и все1327744source rows в агрегатных counts:
asset, first/last seen, first/last reported, числоNULL/non-NULL. Только наличие хотя
бы одного non-NULL выбирает, для каких SECIDs запросить спецификации. Все полностью
NULL-контракты остаются в denominator. Это оптимизация source acquisition, **не**
правило исторического inference: будущие reported dates не дают информации ранним
решениям и не исключают missing rows из последующего теста.

Отбор не зависит от величиныOI, страйка, цены, доходности, labels или выбранного года.
Охватываются все четыре актива и все2021–2025; порядокasset/first_seen/secid.
Immutable census публикуетcontracts.parquet,presence_by_asset_year.parquet,manifest.
Acquisition принимает точный SHA census manifest до HTTP и проверяет каждый artifact.

## Сохранение точных описаний

Каждый нужныйSECID получает собственный публичныйISSdescription или explicitgap.
Используется проверенный V88 transport, толькоpublicISS, без credentialEnvironmentFile.
Доступные8V88responses reference-reused с проверкой rawSHA, без повторного HTTP;
V88root обязательно сохранять вместе с новым source. Дополнительно читаются static
CONTRACTNAME/SERIES_NAME/EXECTYPE/DELIVERYTYPE/SETTLETYPE/EXPIRATION_TYPE/GROUPTYPE.
Никаких marketdata, position magnitudes, returns, fit, signals или PnL.

Один worker, не чаще одного logicalrequest за0.5секунды, max2transportattempts,
response cap100000bytes, total new raw cap1GB, disk reserve5GB. Максимум108104SECIDs;
фактический объём определит census, не произвольный top-K. После10consecutivefailures
остановка с сохранением raw/records. Никакого automaticrestart/повторногоwriter.
Status checkpoint не доказательство жизни: смотретьactualsystemdunit и finalmanifest.
Partial/failed roots не перезаписываются; continuation при реальном failure — отдельный
протокол с reference reuse, не повторная загрузка committed records.

Rawbytes, actualrequest/receipt clocks, source references, exact recordSHA/index и
coverage сохраняются внеGit. Source completion не доказывает underlying execution
mapping, original historical availability или полноту meaningfulOI.
Static future-expiry dates в описаниях не являются protected2026market outcomes;
historical source observations ограничены2025. Противоречивые dates/type/units
остаются явными, не заменяются active future или эвристикой третьего четверга.

## Roots и порядок запуска

- Census: `/srv/trading_lab_data/source_evidence/v89_option_metadata_census_v1`.
- Descriptions: `/srv/trading_lab_data/source_evidence/v89_option_metadata_source_v1`.
- Код: `market_lab.futures.v89_option_metadata_source`.
- Config/code/tests/этот документ и parentV88closure byte-sealed до census/HTTP.
- Сначала server-only`--census-only --seal-sha ...`; затем отдельно
  `--census-sha <observed immutable manifest SHA> --seal-sha ...`.
- Оба точных новых leaf готовятся пустыми сuid999/gid989; общий parent не менять.

После source/coverage нужно отдельное экономическое правило pinning с controls,
периодом, sign, timing, costs и gates до OI magnitudes/futures outcomes. Старые V39/V68
не исправлять/перенастраивать по их результатам. No economic/Stage2/goal increment;
цель20–50% неизменна и не достигнута. Большие AlgoPack services не меняются.
