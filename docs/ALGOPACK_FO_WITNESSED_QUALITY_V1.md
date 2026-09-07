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

Не запущено. Статус и canonical identities обновить после фактического run.
