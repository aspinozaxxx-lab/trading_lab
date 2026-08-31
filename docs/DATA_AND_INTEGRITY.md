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

Для текущих V8–V14 исследований `2026-01-01` — protected boundary. Запрещено:

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
