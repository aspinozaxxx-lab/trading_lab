# AlgoPack paired training V1 — executable archive-training protocol

2026-09-07. Реализация [fixed specification](ALGOPACK_PAPER_TRAINING_SPEC_V1.md)
по [явному разрешению пользователя](ALGOPACK_PAPER_AUTHORIZATION_20260907.md).
Это один новый training-only run, не historical validation и не экономический backtest.

## Гипотеза и фиксированное сравнение

Дисбаланс агрессивных сделок относительно глубины стакана может давать информацию
о следующем часовом движении, включая связь четырёх рынков. Сравнение: две joint
multioutput Ridge alpha10/SVD, price-only20 против price+flow40 признаков; схема,
окно, labels и minimum5000 joint rows полностью определены в родительской спецификации.
Ни scaler, ни model не обучаются на2026. Current-vintage2020–2025 обучается сегодня,
а не объявляется информацией, известной при историческом решении.

Training coverage<5000 — FAILED_TRAINING_COVERAGE, модели не строятся, календарь и
причины пропусков сохраняются. Успешный fit — TRAINED_NOT_EVALUATED, обе модели
сохраняются без выбора победителя. Ни alpha, ни состав строк/годов не подбираются.
В этом run нет calibration/OOS, исторических forecasts/trades и критерия GO LIVE.
Фальсификация экономической гипотезы требует отдельного заранее sealed future-paper
execution/evaluation; никакого вывода о достижении20%/50% из fit или coefficients.

## Executable identity и входы

- Config: `configs/algopack_paper_training_v1.json`, UTF8-BOM sidecar `.sha256`.
- Closure: `configs/algopack_paper_training_v1.seal.json`; CLI требует exact seal SHA.
  Включены authorization/spec, model/runner/tests, alignment/input modules и их tests,
  parent history-quality closure со всеми transitive файлами, pyproject/runtime pins.
- Price input root и assembly identity строго заданы config; внутри manifest находятся
  все662 byte-pinned price source references и active-map identity. Повторная assembly
  не выполняется. Metadata admission перед projection проверяет timestamps/contract;
  дополнительный Moscow date gate выполняется до OHLCV load.
- AlgoPack history294jobs/147pairs берётся из config-bound manifest. Перед числовой
  projection каждого job отдельно проверяются только metadata strings, даты<=2025,
  exact identity, уникальные five-minute keys и число строк. Затем разрешены только
  четыре numeric fields соответствующего TS/OB dataset. Unlisted columns игнорируются.
- Source hashes повторяются до/после projection. Source raw semantic replay в этом
  training runner=false; byte-pinned источники опираются на ранее выполненные source
  audits, а новая повторная source-only campaign не считается экспериментом.
- Для каждого файла actual available_at — время окончания нынешней проверки projection.
  Общий training_cutoff строго после всех projection. SYSTIME не подставляется вместо
  фактической доступности. Flow version SHA=SHA256(source_SHA + ':' + zero-based row).
  Flow provenance сохраняет row ordinal, source identity, exact key и available_at.
- В памяти сохраняются только bars/flow keys, требуемые заранее построенным календарём;
  этот фильтр не смотрит цены, targets или результаты fit. Price/label source SHAs
  сохраняются отдельно в feature/label tables и разрешаются через input catalog.

## Запуск и изоляция

Только gpu-mlserver, Linux UID999 trading-lab. Python3.11; numpy2.3.3,pandas2.3.3,
pyarrow23.0.1,scikit-learn1.8.0. До первого настоящего load/fit — commit/push,
deployment только новых файлов, успешные Linux synthetic tests и byte closure verification.

`python -m market_lab.futures.algopack_paper_training_v1 --seal-sha256 <exact SHA>`

Одноразовый systemd unit: User/Group trading-lab, PrivateNetwork=yes, NoNewPrivileges,
ProtectSystem=strict, PrivateTmp=yes, доступ записи только к новому output parent;
без EnvFile/credential и без Windows tasks. Все collectors продолжают работать отдельно.
Не перезапускать canonical unit/run при timeout; наблюдать единственный запуск.

Output: `/srv/trading_lab_data/runs/algopack-paper-training/algopack_paper_training_v1_<seal12>`.
Directory создаётся exclusive, STARTED marker записывается до inputs; при ошибке остаётся
FAILED marker и исходный staging, без overwrite. Завершение публикуется manifest последним.
Все данные/модели вне Git. В output сохраняются calendar/features/labels/training_mask,
flow provenance, inputs, обе model/scaler JSON, runtime, counts/reasons/by_year и hashes.

## Ограничение выводов и следующий шаг

Decisions здесь — лишь candidate calendar, не отправленные прогнозы. Predictions/trades=0;
CAGR/Sharpe/MDD и scenarios1x/2x costs=N/A, потому что экономического ledger нет.
Ни margin, ни fill, ни комиссионный threshold не подставляются фиктивными нулями.
Старые source historical_model_eligible/original_version_verified/live flags не меняются.
Новая граница F=null, старые2026 outcomes закрыты. После обучения требуется immutable
publication моделей и отдельные future source/execution/evaluation seals; F строго после
всех этих seals. Paper-only разрешение не разрешает real trades или покупку новых услуг.

Результат и реальные SHA/пути фиксировать в STATUS/EXPERIMENTS, не изменяя этот протокол
после реального load/fit. Следующий допустимый шаг — future adapter/protocol, не tuning
сохранённых моделей по старой истории.
