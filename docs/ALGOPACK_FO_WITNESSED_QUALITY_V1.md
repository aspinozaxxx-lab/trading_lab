# AlgoPack witnessed quality V1 — первые три версии источника

## Идентичность и границы

Source-only diagnostic, не экономическая гипотеза и не backtest. Проверяется один
фиксированный cohort: manual11:56:59UTC, scheduled12:03UTC и scheduled12:13UTC
2026-09-07. Completion cutoff12:14UTC. Первые два manifest SHA закреплены config;
третий выбирается только по started_at в[12:13,12:14) и available_at<12:14.
Ровно один подходящий третий capture обязателен. Ожидание/недостаток cohort не означает
разрешение запустить collector вручную или расширить выборку задним числом.

Protocol `algopack_fo_witnessed_quality_v1`; config SHA
`0c088cbe6796f6364b0b630157f539c7c9f68eb97db6c7628da3d03f26cb3bde`.
12-file closure `64cc5d369fd0e49efff57dddbfbd2657679e1abcd7453fc59f53d38b4a70c40e`.
Parent [witnessed V1](ALGOPACK_FO_WITNESSED_V1.md) closure
`67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26`.
Новые synthetic tests17/17, Ruff/closure PASS. До run обязательны commit/push и
Linux tests. На момент seal quality outcome ещё не вычислен.

## Предварительно фиксированные проверки

1. Manifest-only выбор cohort и запись exact bindings до открытия normalized rows.
2. Полный parent replay для каждого из трёх captures; все input SHA должны совпасть.
3. Exact source key: dataset/asset/SECID/tradedate/tradetime. Уникальность внутри
   capture; строго возрастающий batch available_at между captures.
4. New unique keys отдельно от повторных наблюдений. Dropped/reappeared keys не
   дополняются нулями. Gap не означает отсутствие торгов или отсутствие vendor data.
5. Hash выбранных numeric fields отдельно от vendor metadata. Feature revisions,
   SYSTIME-only changes и other metadata changes считаются раздельно. Версии не
   перезаписываются; first_observed_available_at не сдвигается к vendor timestamp.
6. Exact TS/OB joins по оставшейся части ключа, null/zero/negative field counts,
   missing/alias flags. Значения spread/flow не выводятся в human report.
7. Repeat manifest identities после анализа; hashes выходных artifacts до публикации.

Outputs: inputs.json, quality.json, versions.json.gz и manifest.json в отдельном
immutable output directory. Индекс версий содержит key/receipt/capture/hash, без
prices/returns/labels/targets/PnL. Нормализованные source fields разрешены только
родительским source-only schema. Нет модели, сделок, CAGR, Sharpe или promotion.

Три снимка проверяют работу механизма учёта версий, не стабильность источника по
сессиям и не полноту revision archive. Даже 0 revisions не доказывает отсутствие
пересмотров. SYSTIME/bucket completion остаются unresolved. Все historical model,
prediction, original-version и live flags=false. Нельзя подбирать гипотезу или
параметры торговли по этим source diagnostics.

## Runtime

Только gpu-mlserver, PrivateNetwork=yes, без EnvironmentFile/API key, source root
readonly. Output parent `/srv/trading_lab_data/data/processed/algopack_quality`,
отдельный canonical с protocol/seal suffix. Старые history/quality/captures неизменны.
Запускать один раз после12:14UTC; не перезапускать canonical ради нового результата.

```text
/opt/trading_lab/.venv/bin/python -m market_lab.futures.algopack_fo_witnessed_quality_v1 --seal-sha256 64cc5d369fd0e49efff57dddbfbd2657679e1abcd7453fc59f53d38b4a70c40e --output-root /srv/trading_lab_data/data/processed/algopack_quality
```

## Результат

Завершено один раз после pre-run commit/push `3078c31`. Local358passed/4 Windows
symlink skips, Linux360/360, Ruff/closure PASS. Run12:14:26UTC 2026-09-07,
PrivateNetwork=yes, без env/key, unit
`trading-lab-algopack-fo-witnessed-quality-v1-64cc5d369fd0.service`, terminal
success/exit0, runtime1.420s. Canonical:
`/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_witnessed_quality_v1_64cc5d369fd0`.
Manifest SHA `4b9cc6fe93d902e42c0fb817faec40c8fb3f3e523b46c86772afed6a3d2babd5`.
Inputs SHA `02356ae7a7cac4e0bb4725d218a28483f6ecd2652cbab92810e7861af9a026b0`;
quality SHA `3d57f0bd594f02d837a98c8111bd101f8c2b5a9f9a8dac82e1bfb4acc41c424b`;
versions gzip SHA `bcfd4c3ed8c192386cd5de6c4b1da9ff6d5decb6ad15be222346877b3bb67657`.

| Capture UTC | Rows | New keys | Reobservations | Shared TS/OB | OB-only |
| --- | ---: | ---: | ---: | ---: | ---: |
| 11:56:59 manual | 4865 | 4865 | 0 | 2329 | 207 |
| 12:03:00 scheduled | 4881 | 16 | 4865 | 2337 | 207 |
| 12:13:00 scheduled | 4913 | 32 | 4881 | 2353 | 207 |

Всего4913unique keys,14659version observations,9746reobservations. Feature revisions,
SYSTIME-only/other metadata changes, dropped/reappeared keys, missing/alias issues0.
TS-only0 во всех трёх. Все selected numeric поля nonnull на этом cohort, но реальные
zero buy/sell fields сохранены. Negative spread_l1/l10 =19/3 в каждом снимке: это
повторные записи, нельзя суммировать их как57/9unique anomalies или трактовать как
отрицательную стоимость исполнения. Семантика/feature admission требуют отдельного
обоснования, исходные значения не исправлены и не clipped.

Все3parent full replays PASS. Независимая report-only проверка artifact hashes,
unique/repeated cardinality, feature-revision hashes, first-observed timestamps,
capture timestamps и неизменных source manifests тоже PASS. Incomplete captures0.
Два scheduled запуска действительно наблюдены, не подменены manual commands.

Verdict: SOURCE DIAGNOSTIC COMPLETE; prediction/historical/live=false. Нулевые
revisions на коротком cohort не подтверждают отсутствие revisions вообще. Этот
cohort не переанализировать ради нового результата; не строить очередную короткую
quality версию вместо экономической проверки. Перед historical screen нужно
подтверждение causal availability или явное разрешение пользователя на exploratory
assumptions; отдельный economic seal остаётся обязательным.
