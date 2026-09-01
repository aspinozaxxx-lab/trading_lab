# Данные и исследовательская целостность

## Физическое размещение

GitHub хранит только код, configs, tests, docs и маленькие synthetic fixtures. Реальные
данные, модели и run outputs лежат в:

```text
D:\Projects\trading_lab_data\
  data\
    raw\
    processed\
  runs\
  models\              # если появятся отдельно от runs
```

В корне working copy `data/`, `runs/` и `models/` являются игнорируемыми NTFS junctions.
Не добавляй их содержимое, `.pt`, `.pth`, `.parquet`, `.npz`, `.npy`, archives или transfer
bundles в Git. Для воспроизводимости в Git сохраняются относительный путь, bytes/rows и
SHA-256. Если external root отличается от sibling-каталога `<repo>_data`, задай
`MARKET_LAB_STORAGE_ROOT` до загрузки config.

## Защищённая временная граница

Для текущих V8–V25 исследований `2026-01-01` — protected boundary. Запрещено:

- читать 2026 prices, returns, targets, labels или PnL;
- выбирать universe, признаки, thresholds или execution assumptions по 2026;
- вычислять статистику по файлу, включающему 2026, а затем подавать её в development;
- выдавать старый уже просмотренный 2026 период за новый независимый holdout.

Legacy `data/processed/sequence_10m` и ряд top-level equity файлов имеют имена до
`2026-08-16` и могут содержать protected rows. Не открывать их в V8/V9. Файлы контрактов
с maturity 2026 могут содержать допустимую историю, но использовать их можно только через
manifest-bound loader, который физически отклоняет timestamps `>= 2026-01-01`.

## Запечатанный источник MOEX 2012–2017

`configs/moex_pre2018_core4_source_v3.yaml` (SHA `0b86cda4...`) наследует sealed V1 и
был pushed до первого price response и фиксирует exact 155 expired BR/MIX/RI/SI
contracts, только RFUD, закрытые metadata/
daily schemas и exact cursor pagination. Collector обязан сохранить raw responses и
normalized discovery/contracts/boards/segments/daily/coverage во внешнем immutable
bundle. До появления и аудита manifest этот источник не входит в разрешённые strategy
inputs; после source audit для любого return/PnL всё равно нужен отдельный sealed V28.
Raw archive нельзя публиковать без проверки актуальных прав MOEX.
Canonical bundle завершён: 30 059 rows `2012-01-03..2017-12-21`; manifest SHA
`e60d0bca...`, daily SHA `00a9a872...`, raw SHA `b7d10f99...`. Он разрешён только как
source для следующего заранее запечатанного research protocol, не как live evidence.

## Ещё не открытый источник MOEX 2008–2011

`configs/moex_pre2012_core_source_v1.yaml` (SHA `92c7f324...`) зафиксировал до первого
daily response exact 81 contracts BR/MIX/RI/SI = 38/1/16/26 и физические границы
`2008-01-01..2011-12-31`. Metadata-only audit прочитал только finder/description/boards:
FRSTTRADE/LSTDELDATE и один RFUD segment есть у каждого, LSTTRADE отсутствует у 81/81 и
остаётся missing. Wrapper SHA `55965d9c...` и parent SHA `7dd25e01...` pin-ятся вместе.

V1 был pushed commit `49467bc`, затем fail-closed остановился без output на official
identity-only daily row `RIM9_2009/2008-09-12`. V2 SHA `74847dd3...`/`acc547f5...`
разрешает только её структурный класс: NULL prices и NULL/zero activity сохраняются
missing с false flags, не как zero return/бар. Exact universe, dates, requests и raw
payload не меняются. V1 output не создан; V2 использует отдельный suffix `-v2`.

V2 bundle завершён только через внешний `data` junction и immutable: manifest SHA
`e06fd978...`, daily SHA `1c5eee45...`, coverage SHA `9d46db02...`, raw SHA
`e8a97876...`. Получено 8 381 rows, 81 contracts, 224 requests, factual date coverage
`2008-01-09..2011-12-16`; все 41 replay/hash/schema checks true. Две inert rows
`RIM9_2009`/`SiU9_2009` на `2008-09-12` остаются missing/nonexecuting. До отдельного
strategy seal запрещено вычислять или даже просматривать 2008–2011 returns/PnL;
collection coverage сама по себе не является валидацией и не разрешает менять exact
contract set.

Derived D1 `configs/moex_pre2012_core_derived_v1.yaml` SHA `8f5737bc...`, module SHA
`d0c22df7...` подготовлен до первого price-bearing build. Он pin-ит source manifest,
daily/raw bytes и exact transformation modules. Metadata-only preflight задаёт 781
master session по factual SI/RI/BR и 54 поздних MIX sessions; 727 pre-listing MIX rows
обязаны быть flat/masked со всеми market values missing. D1 не содержит и не допускает
return/target/signal/equity/PnL columns; zero unresolved roll/exit требуется до atomic
publication.

D1 seal `45e55af` остановился до source artifact load: acquisition `protected_from`
равен 2026, а D1 сравнил его с derived ceiling 2012. Output отсутствует. D2 config SHA
`f928e58b...`, module SHA `2e01c3fc...` исправляет только это: manifest обязан доказать
requests до конца 2011 и acquisition boundary 2026, затем каждая market row независимо
reject-ится при дате `>=2012-01-01`. Остальные D1 gates неизменны.

Derived-source D1 зафиксирован в `configs/moex_pre2018_core4_derived.yaml` (SHA
`a633883d...`) и pin-ит source manifest/daily/raw плюс точные SHA модулей panel/roll/spec.
Его immutable output с manifest SHA `73ffe4c3...` прошёл byte/causality checks, но
запрещён как V28 input: old serial-month SI chain породил 9 unfilled roll и 1 276
unfilled exit. D1 не перезаписывать и не использовать для PnL.

D2 config SHA `7b60afbf...` pin-ит D1 diagnosis и фиксирует official-cycle admission:
H/M/U/Z для SI/RI/MIX, месячный BR; 143 contracts и 29 026 source rows. D2 build был
fail-closed и не опубликовал output: clean SI exit/flat/re-entry source gap дал 22 roll
вместо ошибочно ожидавшихся 23, при этом unresolved roll/exit уже были нулевыми.

D3 SHA `d21dd650...` сохраняет D2 byte-identical и pin-ит единственный gap: exit
`2016-12-09`, пять exact flat sessions, re-entry `2017-01-04`, без return bridge. Его
единственный output —
`data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/`; publication
требует exact action counts и ноль unresolved roll/exit. Build завершён: manifest SHA
`3ab20092...`, panel SHA `d1043ea7...`, active-map SHA `b3ce75f9...`, spec SHA
`d7cecd86...`; 1 479 common sessions и 16 explicitly invalid/masked active rows.
Outcome columns, zero-imputation и PnL до отдельного V28 seal запрещены.

Macro source S1 `configs/pre2018_macro_source.yaml` (SHA `3daa3c40...`) фиксирует до
первого HTTP request три bounded external series: FRED STLFSI4, CBR RUONIA и CBR key
rate. S1 transport attempt завершился до response persistence и output отсутствует. S2
SHA `4ad7f034...` изменил только HTTP User-Agent, получил три responses после seal, но
fail-closed до publication: output отсутствует. Source-only audit показал 78 explicit и
1 400 unknown RUONIA publication dates. S3 SHA `ae575962...` меняет только parser policy:
unknown `publication_date/available_at` остаются missing и не дают collateral income.
Его pending immutable bundle —
`data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/`. Processed
nonmissing `available_at` обязан быть строго до `2018-01-01 Europe/Moscow`; raw bytes/hash
обязательны. Current-vintage STLFSI4 не является доказанным original historical vintage.
Ни macro source, ни D3 не разрешены для PnL до отдельного V28 seal.

S3 завершён после pre-collection push `1f9c343`: manifest SHA `949bc7bf...`, STLFSI4
SHA `343c7636...`, CBR monetary SHA `bf18a53c...`, coverage SHA `db32971e...`, raw SHA
`8109f157...`. Exact raw replay, artifact hashes/rows/columns, unknown timing policy и
nonmissing availability before 2018 прошли audit. Bundle теперь разрешён только как
input отдельного запечатанного V28 research protocol.

V28 config SHA `4f9e6663...` pin-ит D3/S3 manifests и каждый читаемый artifact. До его
seal разрешены только identity/schema/date/macro-state checks; первый `open/close/settle`,
return или PnL 2013–2017 можно читать только после commit/push. Protocol сохраняет
1 400 RUONIA unknown availability rows missing: 1 168 validation intervals явно
`no_credit_unknown_availability`, а не zero-filled yield.

V28 canonical run завершён после seal commit `4310bc3`: metrics SHA `73b614b8...`,
identity SHA `d7210826...`, declared artifact audit 103/103. Run immutable и invalid
для promotion: отменённый capacity roll оставил expired contract, execution complete
false, critical failures 5 129. Не исправлять V28 in-place и не выдавать его частичную
equity curve за чистый unseen economic verdict.

V29 config SHA `d92f8cf2...` pin-ит V28 config/metrics, все V28 inputs и implementation
closure. Seal commit `478a246` предшествует canonical run
`runs/v29_risk_first_roll_20260901T085436Z_d92f8cf2/`: metrics SHA `1c0e2dd7...`,
identity SHA `ca97579d...`, artifact audit 26/26 и checks 139/139. Все ledgers complete,
critical/unresolved отсутствуют. Это post-V28 correction без новой temporal границы и не
independent holdout; экономический verdict `FAIL_POST_V28_20` не разрешает live use.

## Основные разрешённые development artifacts

Пути относительны к external root. Hash относится к указанному файлу либо canonical
identity и должен проверяться перед чтением.

| Роль | Path | SHA-256 |
|---|---|---|
| 30-stock daily panel | `data/processed/daily_v4/development_panel.parquet` | `a8759c2c9d1670c667d1d22125c6fd423f4b57c55103530ee44d542a253c0bbe` |
| Daily panel manifest | `data/processed/daily_v4/panel_manifest.json` | `873916a268dae55c3ac6537d1a02f7d773ea7f0276c7377389c494d7996e492f` |
| Futures 10m top manifest | `data/processed/futures_v7_10m/manifest_2018-01-01_2025-12-31.json` | `f620ff77a5368c93d6415fc1b5785f9eaaba6cef873a4425fcd98e9b69f3ba01` |
| Pre-2018 core-four daily | `data/processed/futures_pre2018/moex-core4-daily-current-vintage-2012-2017-v1/daily.parquet` | `00a9a872557d1450c38ace291449ab6a1de17679c8fc12d57bf3b1738cd50e38` |
| Pre-2018 core-four manifest | `data/processed/futures_pre2018/moex-core4-daily-current-vintage-2012-2017-v1/manifest.json` | `e60d0bcacff17af0229d150552a70ac235e821c2d271970ea2567c212a5f3da6` |
| Pre-2018 core-four raw archive | `data/processed/futures_pre2018/moex-core4-daily-current-vintage-2012-2017-v1/official_moex_iss_responses.jsonl.gz` | `b7d10f9949e65f330f738f789e6fcb69262a0fe9f549252323c6f18ec666e464` |
| Pre-2018 causal D3 manifest | `data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/manifest.json` | `3ab20092dbe4fd8a58211d11db1b6dcd6a8335f98051146da76a0f3c0c82fa71` |
| Pre-2018 causal D3 panel | `data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/panel.parquet` | `d1043ea73a1f4f86e7477c2a3664d08b409148d879435de2889560a1c2a8579c` |
| Pre-2018 causal D3 active map | `data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/active_contract_map.parquet` | `b3ce75f9f7a67a2176741ebb7491ebc760070ef03c9ec3cf28a076542a7f728f` |
| Pre-2018 causal D3 spec proxy | `data/processed/futures_pre2018/moex-core4-causal-derived-2012-2017-v3/spec_proxy.parquet` | `d7cecd862229d6564bd5657d96e867c3e9984c6fd47ed671d0121293cef2ab2a` |
| Pre-2018 macro S3 manifest | `data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/manifest.json` | `949bc7bf5cbbd0973913a41df24f73a778a628997a9855e9c14a4b830c994151` |
| Pre-2018 STLFSI4 current-vintage | `data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/stlfsi4.parquet` | `343c76363fe3093da159a6cdfde5d8912fe6dedeab8f0c7e5e13eafdbe0c9c7a` |
| Pre-2018 CBR monetary | `data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/cbr_monetary.parquet` | `bf18a53cb85ad1417c504ed68797ea96ecb0bbdda270e40846f0dd2c8ac84164` |
| Pre-2018 macro raw archive | `data/processed/info_radar/pre2018-macro-current-vintage-2012-2017-v3/official_macro_responses.jsonl.gz` | `8109f157f314da53a7d93d9bf1f39fb12fb75c30dd6cd4e07b03ef52eacd3024` |
| Active-contract map | `data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet` | `40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823` |
| Futures spec proxy | `data/processed/futures_v5_specs_v1/spec_proxy_2018-01-01_2025-12-31_87372f337a75eeb4/spec_proxy.parquet` | `8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682` |
| CBR PIT daily | `data/processed/info_radar/cbr-dev-2018-2025-v1/cbr_daily.parquet` | `bc2352fa7de89ca6a3bdbf3bd291cbd62f817bde8c93455536727d583e9e535d` |
| CFTC PIT positions | `data/processed/info_radar/cftc-dev-2018-2025-v1/processed/cftc_positions.parquet` | `fa83ee60008b75b38da8bd3bc0007cd014ae38da5870f5084133e0df3be1a23` |
| MOEX RVI daily, current-vintage | `data/processed/info_radar/moex-rvi-dev-2018-2025-v1/rvi_daily.parquet` | `ac709b76ad7f2a03e48f8feb2b11248418e90d53d88d2b06d94fc35aea5b84b7` |
| MOEX RVI manifest | `data/processed/info_radar/moex-rvi-dev-2018-2025-v1/manifest.json` | `22573e6bba290a34aeee44bba3bb159f38d9e93014e78f9bd5367df8d0dd56fa` |
| MOEX FUTOI daily-last, current-vintage | `data/processed/info_radar/moex-futoi-dev-2020-2025-v1/futoi_daily_last.parquet` | `a6758388bc311c2c474ad4260337d8fc97f87aa5a9d5bb1f52217940421c1560` |
| MOEX FUTOI manifest | `data/processed/info_radar/moex-futoi-dev-2020-2025-v1/manifest.json` | `5320875a02441e9844138fc24f85a631b1521061b2ef839403d5b98ebab6e9ee` |
| MOEX FUTOI intraday current-vintage (not historical-PIT) | `data/processed/info_radar/moex-futoi-intraday-dev-2020-2025-v2/futoi_intraday.parquet` | `5f496a48c8359acb151eb2806d0705b4ee4197eda42ea43705bb805c70287744` |
| MOEX FUTOI intraday manifest | `data/processed/info_radar/moex-futoi-intraday-dev-2020-2025-v2/manifest.json` | `cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed` |
| MOEX FUTOI intraday raw archive | `data/processed/info_radar/moex-futoi-intraday-dev-2020-2025-v2/official_moex_iss_pages.jsonl.gz` | `f7bdab6f35884da5d6731134262b381c88a87f0ffebdac40139989e2a85d6056` |
| EIA WPSR Table 1 release vintages | `data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2/eia_wpsr_table1.parquet` | `5fccfa968ac88f04806df87bd7179a992f0f7c57137ba46db049d67350b54f3e` |
| EIA WPSR source manifest | `data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2/manifest.json` | `aac389628b61df446616cd171084af81482d09a7d4b403337a8332b5373c142b` |
| EIA WPSR raw release archive | `data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2/official_eia_wpsr_table1_releases.jsonl.gz` | `dce96ee233ed5cac153ab086f514a69688f28830749c4dc223dc66c79454b297` |
| CBR dated liquidity forecasts | `data/processed/info_radar/cbr-liquidity-forecast-releases-2017-2025-v1/cbr_liquidity_forecasts.parquet` | `a8faab048579cc5449173b3f2d4ea0e2abd447095d9144ad5004a52b351a8d07` |
| CBR liquidity forecast manifest | `data/processed/info_radar/cbr-liquidity-forecast-releases-2017-2025-v1/manifest.json` | `8f452f2dd963752eab4183e8f80dd2a07398588f9f87124ae913dff6c2a88c9a` |
| CBR liquidity forecast raw archive | `data/processed/info_radar/cbr-liquidity-forecast-releases-2017-2025-v1/official_cbr_pffl_releases.jsonl.gz` | `b01200fa2a827a1c0eb7708695a0cf1af6ace9bed3a2b81f8d9c3281839bd3a6` |
| CBR daily liquidity factors, current-vintage | `data/processed/info_radar/cbr-liquidity-factors-current-vintage-2021-2025-v1/cbr_liquidity_factors.parquet` | `88885d3695a88fb910d5a6ad9f3d8fd2cbd69eedaec779d4cef3048cd854c864` |
| CBR daily liquidity factors manifest | `data/processed/info_radar/cbr-liquidity-factors-current-vintage-2021-2025-v1/manifest.json` | `f1701ec330fce9813d75bd711de235744dd8a9daf5f192325efe64f16e98e61a` |
| CBR daily liquidity factors raw snapshot | `data/processed/info_radar/cbr-liquidity-factors-current-vintage-2021-2025-v1/official_cbr_liquidity_factors_current_vintage.html.gz` | `96901a15619561118719f8b4635bde97f964b806d59c609be9d40c0110dae95f` |
| Minfin OFZ auction events, current-vintage | `data/processed/info_radar/minfin-ofz-auction-results-current-vintage-2021-2025-v2/minfin_ofz_auction_events.parquet` | `a8c5c02457e3fadc19e617f42ad5a0c644672689a4c9bd8759d20d4a84d5d480` |
| Minfin OFZ auction manifest | `data/processed/info_radar/minfin-ofz-auction-results-current-vintage-2021-2025-v2/manifest.json` | `c6fcf390b728ebfd55c32b3a20880908bd4eb5ebfcff18bcaf150f568b607d52` |
| Minfin OFZ auction raw pages | `data/processed/info_radar/minfin-ofz-auction-results-current-vintage-2021-2025-v2/official_minfin_ofz_auction_pages.jsonl.gz` | `f56af34a15a284e74f8364daf3abd6ae7d2978a01b22443e33ced079d72133c7` |
| CBR macro-survey forecasts, current-vintage | `data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1/cbr_macro_survey_forecasts.parquet` | `a139ead81d1e06495afcd680ff1cb7903f2a102165c9f7bd7a074577c7069d6a` |
| CBR macro-survey manifest | `data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1/manifest.json` | `faae8927add739b0cf91dfdc9b7d8e7265d080f88685fd691e973ac907c4fdfe` |
| CBR macro-survey raw workbook | `data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1/official_cbr_macro_survey_current_vintage.xlsx` | `a715edf614799186278656970380aa0ba6abcfb801bfa2e92806cdc9fdb06944` |
| CBR macro-survey raw page | `data/processed/info_radar/cbr-macro-survey-current-vintage-2021-2025-v1/official_cbr_macro_survey_page.html.gz` | `a5555e741cbb5185f21135464d97c32d819f134e95899b4593f54a8d94f630d3` |
| CBR business-climate releases | `data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1/cbr_business_climate_releases.parquet` | `b312f4e5ed0b0c7cdac2e2112068a5046a8bab4c272aa6f5edda7f03bf026de4` |
| CBR business-climate coverage | `data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1/coverage.parquet` | `742e5a5a825952e28c4507b5d248aa5c4044e99ecce3c1cf253ec36312e131e8` |
| CBR business-climate manifest | `data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1/manifest.json` | `99ad128b930b713cdda7988daa25f5dc763005eea768ccd4bd56ef89500835c8` |
| CBR business-climate raw responses | `data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1/official_cbr_business_climate_responses.jsonl.gz` | `e362918e5554cf4e9ddb25c4378113dadc6129ffaa3b1dbfcb28af06468c2286` |
| CBR household inflation/sentiment releases | `data/processed/info_radar/cbr-inflation-expectations-release-pages-2022-2025-v1/cbr_inflation_expectations_releases.parquet` | `707112727156b4dbf61f115e53a19de0eb7474804c9d57cab55fe2829d9663c3` |
| CBR household inflation/sentiment coverage | `data/processed/info_radar/cbr-inflation-expectations-release-pages-2022-2025-v1/coverage.parquet` | `dd4444e2af0bfee1b4685fb2f8fde5b3ffa6245d93341096999da4facb1dad87` |
| CBR household inflation/sentiment manifest | `data/processed/info_radar/cbr-inflation-expectations-release-pages-2022-2025-v1/manifest.json` | `b132a45ee8170fc07c92dbf5be4c7b70833d07754c7abfd5d5ccc7ac6c3dce92` |
| CBR household inflation/sentiment raw responses | `data/processed/info_radar/cbr-inflation-expectations-release-pages-2022-2025-v1/official_cbr_inflation_expectations_responses.jsonl.gz` | `fa2ecf58cc70588cb29089e96e47204f4bad1012aca131a809e5874cd0cd1c11` |
| FRED/Cboe VIX term structure | `data/processed/info_radar/fred-cboe-vix-term-structure-current-vintage-2018-2025-v2/cboe_vix_term_structure.parquet` | `6ffe7daa623d01c4fd23562e05d317e6b5a778d32838db37f25b562a170ab567` |
| FRED/Cboe VIX term-structure coverage | `data/processed/info_radar/fred-cboe-vix-term-structure-current-vintage-2018-2025-v2/coverage.parquet` | `a57e863cbe22734c59f410d9d66b0f0dc4af424f1a7db99edde9f4c3ac2bfc38` |
| FRED/Cboe VIX term-structure manifest | `data/processed/info_radar/fred-cboe-vix-term-structure-current-vintage-2018-2025-v2/manifest.json` | `0aecc29fdc9181a0af6941fa4f3778487ba0b5d6dedce07aa843b1b0eb32b2d1` |
| FRED/Cboe VIX term-structure raw responses | `data/processed/info_radar/fred-cboe-vix-term-structure-current-vintage-2018-2025-v2/official_fred_cboe_responses.jsonl.gz` | `d11aa63712a9f4c85f1c6801c4821fcec058af6f617e48cc6c751076a9d247ef` |
| FRED STLFSI4 financial stress | `data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1/stlfsi4.parquet` | `4937b6862e864c0a09202182e09ebe28b8f2eacc40fe0ebc435cca40f054a09c` |
| FRED STLFSI4 coverage | `data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1/coverage.parquet` | `ec5e3aeb0850664906c9ce8a16e3336a539243dc9f8e2c7f6165ab0d6077d9be` |
| FRED STLFSI4 manifest | `data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1/manifest.json` | `1a992f64d9bf05d7bcb55cb2d31de9d0b16477cd1080f4d9da3df136576aa868` |
| FRED STLFSI4 raw response | `data/processed/info_radar/fred-stlfsi4-current-vintage-2018-2025-v1/official_fred_stlfsi4_response.jsonl.gz` | `d9ebef723a3d5f795fe1ce94f24f7721eba6e43fe18888b12f036b52eef5c3d1` |
| Structural raw archive | `data/processed/futures_v9_structural/official_moex_iss_source.jsonl.gz` | `c29bf969a551f6805e4d79d6e9152ce8be2a0e9ba92c8c29f133f742f259bc20` |
| Structural source manifest identity | canonical run identity | `b5b38505657bd3e879cc758f56d2acd989a37fb970727be7c71ddca2adcada68` |
| Structural history identity | canonical run identity | `dfa0537822f639c7af381ca5512efcd81cc4921b5139e4449de9384549b76b31` |
| Structural causal panel | canonical run `causal_asset_panel.parquet` | `71b4f509585416c9f8001234d53c5f12f959e74f2cd15226a1547e9611064ec5` |
| Intraday timing tensor | `data/processed/futures_v9_intraday_timing/development_2018_2025.npz` | `7bf3397864e44a13fa2ce841c206ed3c33974439e32bd439625b40df12014b21` |

Дополнительные sealed identities:

- V8 base predictions:
  `ca7dae8d856e512a6b3e476662b73d7d7f4f87521f0c103606b147f117acd437`;
- V8 regime ensemble:
  `4fd847f49f837516e637c81c81d17344ccf3ff781c808d1318da7ce17f40c14a`;
- V8 context parquet:
  `767c830d7943ea324e4b069da875dd4a51486ededa3a13195d5b5062b847a746`;
- market-graph sealed momentum predictions:
  `351c33c0c04696b48e57a60ba4f3f4cd6f0c149a5e464dcf708b3addcf6a2b6c`.

## Point-in-time правила

- Для каждого признака хранить `observation_date`, `publication_date`, `available_at`,
  revision/source identity и `known_at`.
- Training row может видеть только значение, доступное к `decision_at`.
- RVI current-vintage допускается только при `source_date < decision_date`; значение RVI
  того же дня запрещено даже если стратегия формально решает после close.
- FUTOI current-vintage **не допускается** по одному `source_date`. Требуется одновременно
  `source_date < decision_date` и `available_at <= decision_at`. MOEX определяет
  `SYSTIME` как publication time; 10 456/11 744 строк daily-last опубликованы/republished
  более чем через сутки после observation. Именно пропуск второй проверки инвалидировал
  V16: 932/1 044 states были недоступны.
- Для будущего FUTOI 5m ответ ровно из 1 000 строк считается обрезанным, даже если HTTP
  успешен: `start` на analytical endpoint фактически игнорируется. Интервал нужно делить
  до bounded ответа короче лимита, затем проверять каждый trading day и пару FIZ/YUR.
  Intraday feature доступен только после
  `max(official SYSTIME + delivery buffer, actual archive retrieval time)`. Без original
  publication-vintage archive весь скачанный в 2026 current-vintage FUTOI запрещён для
  backtest 2021–2025.
- EIA WPSR допускается только из release-specific v2 bundle и только при
  `available_at <= decision_at`. `available_at` задан концом официальной даты выпуска в
  `America/New_York`; issue `2019-07-03` помечен stale и не входит в processed rows.
  `Last-Modified` не является временем публикации и для join запрещён.
- CBR liquidity forecast допускается только по дате, напечатанной внутри конкретной
  forecast/auction record, и при `available_at <= decision_at`; query date сама по себе
  не доказательство, потому что сайт возвращает последний выпуск для отсутствующей даты.
  В source bundle availability равна `23:59:59 Europe/Moscow` дня публикации. Это
  release-keyed forecast будущего периода, но исходные байты времени публикации не
  сохранились и их неизменность не доказана: источник годится для development, не для
  независимого подтверждения без forward vintage collection.
- CBR daily liquidity factor допускается не раньше 10:31 мск следующего датированного
  рабочего дня таблицы. Официально данные предыдущего рабочего дня публикуются до 10:30,
  но сами исторические значения могут уточняться. Поэтому current-vintage snapshot не
  доказывает исходные publication bytes и остаётся development-only; `Last-Modified` для
  availability не используется.
- Minfin OFZ auction result допускается только в конце напечатанного publication day:
  `23:59:59 Europe/Moscow`, затем fill не раньше следующего factual open. Точное время
  публикации и original historical bytes не доказаны; current-vintage record пригоден
  только для development. Supplemental/correction/failed/announcement нельзя смешивать
  с successful primary result или нулевым bid-to-cover.
- CBR macro survey допускается только в консервативный конец месяца, следующего за
  `survey_month`. V21 использует только median следующего календарного года и считает
  revision внутри точной пары indicator/forecast year. Different oil series не
  соединяются; missing component остаётся missing в source и лишь получает явный zero
  target без перераспределения риска. December 2025 доступен только в 2026 и исключён.
- CBR business-climate release допускается только после `available_at`, равного концу
  московского дня более поздней из напечатанной publication date и last-updated date.
  При одинаковом `available_at` остаётся только максимальный `release_month`. Для сигнала
  разрешена напечатанная one-decimal endpoint label; chart exact хранится только для
  аудита. Три prior-month observation endpoints сохраняются как такие, без forward-fill.
- CBR household inflation/sentiment release допускается по такому же conservative
  `available_at`: конец московского дня более поздней из publication и last-updated
  dates. При collision остаётся максимальный `release_month`. Стратегия может читать
  точные значения только из release-specific XLSX; one-decimal HTML endpoints нужны для
  cross-check. Missing не превращается в zero, а current-retrieved historical files
  остаются development-only до накопления собственных forward vintages.
- FRED-distributed Cboe close допускается только после `23:59:59 America/Chicago`
  observation day и при `available_at <= decision_at`. VIX и VIX3M должны одновременно
  присутствовать на одной exact date; missing pair нельзя forward-fill. Raw queries
  server-bounded через `coed=2025-12-31`; пара 2025-12-31 консервативно доступна уже в
  2026 и поэтому исключается из development decisions. Current-vintage history остаётся
  development-only, а copyrighted raw нельзя публиковать без отдельного права.
- STLFSI4 Friday-ending observation допускается только после `23:59:59 America/Chicago`
  следующего четверга, то есть через шесть календарных дней и после обычного Wednesday
  update. State выше/не выше нуля берётся буквально из определения источника; missing не
  zero. Version 4 и retrieved history current-vintage, original vintages не доказаны.
- Scalers, winsorization, correlation graph и thresholds обучаются только на train slice.
- Test targets не участвуют в feature mask, threshold selection или early stopping.
- Universe должен быть point-in-time. Fixed 30-name equity universe сохраняет возможный
  survivorship bias и не может называться историческим index membership universe.

## Price, roll и missing-data правила

- Signal использует только завершённые свечи.
- Fill происходит не раньше следующего фактического open/полного бара.
- Для 10m successor требуется ровно 600 секунд и тот же contract id.
- Roll — две реальные ноги или explicit rejection; нельзя склеивать target через roll.
- Для feature prices допустима только causal forward adjustment, известная на дату решения.
- Missing open/exit/spec/settle/volume означает sleep или unresolved, не zero return.
- Same-bar TP/SL в corridor трактуется stop-first.
- Participation, integer quantity, gross cap и costs применяются до признания сделки.

## Protocol seals

Каждый новый config получает SHA-256 до outcome. Проверяй одновременно:

1. bytes config против `.sha256` или code-pinned hash;
2. source manifest и transitive child hashes;
3. temporal maximum;
4. exact schema и row count;
5. implementation identity, если canonical replay её требует.

Изменение CRLF/BOM может менять byte hash. Не «исправляй форматирование» sealed configs или
canonical source files без создания новой protocol/code identity.

## Корпоративные документы и LLM

Документ разрешён для метрик только при наличии:

- подтверждённых прав на автоматическое использование;
- точного времени публикации;
- revision chain и source/archive hash;
- issuer/reporting period/standard/scope;
- page-level evidence для каждого извлечённого факта.

LLM возвращает структурированные факты (`metric`, `value`, `unit`, `scale`, standard,
scope, page evidence, text fact). В её контекст запрещено передавать price, return, target,
label, strategy PnL или последующий market reaction.

## Права на данные

MOEX ISS технически доступен анонимно, но доступ не равен праву на публичное
перераспространение. До публикации datasets, коммерческого или live использования нужно
проверить актуальные ISS Terms и MOEX Market Data Policy. CBR/CFTC и issuer documents
проверяются отдельно. Если права не доказаны, в Git остаются только downloader, manifests,
hashes и synthetic fixtures.
