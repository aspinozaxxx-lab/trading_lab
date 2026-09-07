# AlgoPack paired training V1 — спецификация до executable seal

2026-09-07. Основание: [user authorization](ALGOPACK_PAPER_AUTHORIZATION_20260907.md),
[alignment](ALGOPACK_PAPER_ALIGNMENT_V1.md), [input preparation](ALGOPACK_PAPER_INPUTS_V1.md).
Это фиксируемое задание для реализации, НЕ готовый executable protocol/config seal.
Реальные price/label loads и fit до byte-sealed runner/config/input closure запрещены.

## Гипотеза и область вывода

Проверяется гипотеза: joint flow/depth BR/MIX/RI/SI содержит дополнительную информацию
о следующих60мин относительно joint price-only baseline. История2020–2025 используется
для обучения сегодня с разрешённым предположением переноса в witnessed online.
Никаких historical AlgoPack trades/CAGR или выбора лучшей модели по прошлой доходности.
Две модели сохраняются независимо от результата обучения, без перебора alpha/признаков.

## Точная первая пара моделей

- Порядок assets: BR, MIX, RI, SI.
- Training information dates2020-01-01..2025-12-31, только weekdays, из causal active map.
- Information_end E каждые10мин с10:10 до17:00 Europe/Moscow включительно.
  Это фиксированная daytime область, не синтез полного исторического calendar.
- Учебный decision label D=E+4мин; actual source available_at остаётся сегодняшним
  verified/receipt clock, не D. Для реального future D нужен timestamp исполнения
  predictor с deadline до следующей10m границы; schedule не означает фактический запуск.
- Price признаки на актив: close-to-close log returns за1/3/6 десятиминутных шагов,
  log(close/open) и log(high/low) последнего завершённого10m бара. Всего20 features.
- Для lookback нужны все семь соседних баров одного exact contract и одного local date,
  ending E−60мин..E без дыр; цена положительна, OHLC согласованы. Никакого overnight,
  gap/roll return, forward fill или back-adjustment. Invalid остаётся mask.
- Full arm добавляет20 features из alignment V1: на каждый актив четыре imbalances
  trades/volume/L1/L10 и asinh signed flow/L10 depth. Итого40 features.
- TS/OB относятся к exact SECID из effective-date plan, pair end E−5мин/E. Только
  actual available_at<=training_cutoff; использовать select_training_flow, не select_flow
  с подменённым временем. Source/calendar/missing counts сохраняются отдельно.
- Target каждого актива: log(open_exit/open_entry), entry=E+10мин, exit=E+70мин;
  семь фактических последовательных open одного SECID, по mature_label V1. Нельзя
  переносить target через дырку или roll. Последний source bar также должен окончиться
  и быть получен до training_cutoff. UTC/vendor market timestamps targets строго<2026.
- Две independent multioutput Ridge: alpha=10.0, fit_intercept=true, solver=svd.
  StandardScaler(mean/std) только на обучающей выборке; без PCA, seed/parameter search,
  calibration, early stopping, selection по predictions или скрытого третьего arm.
- Обе модели fit-ятся на одном пересечении finite price/full features и четырёх valid
  targets. Это допустимая training mask, не будущая inference eligibility.
- Минимум5000 joint training rows; меньше — явный FAILED_TRAINING_COVERAGE, без уменьшения
  gate после результата. Per-year counts сохраняются, но годы не выбираются/не исключаются.

## Разделение таблиц и provenance

API и multioutput/SVD semantics сверены с официальной документацией scikit-learn1.8:
[Ridge](https://scikit-learn.org/1.8/modules/generated/sklearn.linear_model.Ridge.html),
[StandardScaler](https://scikit-learn.org/1.8/modules/generated/sklearn.preprocessing.StandardScaler.html).
Выбор alpha=10 и состав сравнения — наши заранее заданные параметры, не рекомендация
авторов библиотеки о торговой доходности.

Candidate calendar строится из plan/session metadata до labels и сохраняет все
eligible/sleep/unresolved requests. Feature table не принимает будущие target columns.
Labels и label validity живут отдельно и присоединяются только в training table.
Online baseline не должен скрыто терять решения из-за отсутствия flow у full arm:
впоследствии нужны arm-specific coverage и matched-coverage comparison, заранее sealed.

Каждый training row ссылается на exact active-map, price и TS/OB source identities.
Хранить source information time и actual verified/receipt time раздельно.
Принимающий runner проверяет hashes до и после projection и собственную closure;
никакого auth/network в training service, работа только на gpu-mlserver.

## Артефакты и оценка

Training output: counts/reasons по calendar/price/flow/labels/joint/year, input/code
identities, immutable feature/label provenance, обе модели и scaler statistics,
runtime versions, training start/end и artifact hashes. Всё числовое вне Git.
Нет исторических equity/trade metrics; CAGR/Sharpe/MDD = N/A, не ноль.
Training fit/коэффициенты не доказывают прибыль и не выбирают победителя.

Future paper source/execution/evaluation — обязательная следующая часть, не разрешение
на её запуск сейчас. До новых prices/outcomes зафиксировать source code/config, execution
costs1x/2x, coverage и stability rules, затем immutable model publication и будущую F
строго после ВСЕХ нужных seals. Если predictor/source ещё не готовы, F не назначать
задним числом и не читать старые2026 snapshots ради ускорения разработки.
Формат forecast target не доказывает fill: для net ledger нужны separate observed
quotes/contract specs/fees/capacity. Не выдавать20%/50% обещание по training success.

## Следующая конкретная работа

Реализовать price-feature builder и paired training runner с synthetic parity/gap/roll/
label-independence tests, добавить manifest-bound flow projection и executable config.
В closure включить authorization, эту спецификацию, alignment V1, inputs V1/V2,
модельный core/runner/tests и transitive AlgoPack parent dependencies. До первого
реального fit — commit/push/seal и Linux tests. Не повторять уже завершённую сборку
price inputs; existing manifest/bytes проверять как вход, а не объявлять новым опытом.
