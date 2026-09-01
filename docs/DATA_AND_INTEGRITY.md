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

Для текущих V8–V19 исследований `2026-01-01` — protected boundary. Запрещено:

- читать 2026 prices, returns, targets, labels или PnL;
- выбирать universe, признаки, thresholds или execution assumptions по 2026;
- вычислять статистику по файлу, включающему 2026, а затем подавать её в development;
- выдавать старый уже просмотренный 2026 период за новый независимый holdout.

Legacy `data/processed/sequence_10m` и ряд top-level equity файлов имеют имена до
`2026-08-16` и могут содержать protected rows. Не открывать их в V8/V9. Файлы контрактов
с maturity 2026 могут содержать допустимую историю, но использовать их можно только через
manifest-bound loader, который физически отклоняет timestamps `>= 2026-01-01`.

## Основные разрешённые development artifacts

Пути относительны к external root. Hash относится к указанному файлу либо canonical
identity и должен проверяться перед чтением.

| Роль | Path | SHA-256 |
|---|---|---|
| 30-stock daily panel | `data/processed/daily_v4/development_panel.parquet` | `a8759c2c9d1670c667d1d22125c6fd423f4b57c55103530ee44d542a253c0bbe` |
| Daily panel manifest | `data/processed/daily_v4/panel_manifest.json` | `873916a268dae55c3ac6537d1a02f7d773ea7f0276c7377389c494d7996e492f` |
| Futures 10m top manifest | `data/processed/futures_v7_10m/manifest_2018-01-01_2025-12-31.json` | `f620ff77a5368c93d6415fc1b5785f9eaaba6cef873a4425fcd98e9b69f3ba01` |
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
