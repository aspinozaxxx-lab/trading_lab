# V79: быстрый условный конкурс трёх flow/depth механизмов

2026-09-15. [Явное разрешение](ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md).
Первый уровень воронки, independent new information относительно V65–V78, но не unseen
holdout. Final-vintage AlgoPack мог исправляться позднее: это conditional assay,
а не causal/PIT backtest. Старые historical admission flags остаются false.

## Дешёвый тест до портфельного усложнения

Переиспользуются immutable calendar/features/labels сохранённого training run;
числовые модели и training_mask не загружаются, fit не запускается. Calendar63588
10min opportunities ×BR/MIX/RI/SI,2020–2025,10:10–17:00MSK. Вся история и все4актива,
без отбора лучшего года/тикера/часа после outcomes. Manifest и4input hashes в config;
metadata dates каждого Parquet проверяются отдельно до чтения числовых колонок.

Exact feature semantics — [training spec](ALGOPACK_PAPER_TRAINING_SPEC_V1.md) и
первоначальная implementation closure bb95784a169f. Flow использует две5min агрегации,
depth — их среднее; imbalances=(buy−sell)/(buy+sell), pressure=asinh(signed volume/L10 depth).
Это vendor buy/sell proxy, не доказанный individual aggressor/queue replay.

Общая feature eligibility всех4arms per asset: plan_eligible, price/flow READY,
finite return_1/trade imbalance/volume imbalance/depth_l1/depth_l10/pressure;
предыдущий exact10min row того же дня и контракта также valid. Labels не участвуют.
Это matched-information coverage baseline: price_momentum видит только price direction,
но сравнивается на той же доступности источников, не независимый price-only deployment.

## Замороженные правила

1. Pressure: |volume imbalance|>=0.2, |pressure|>=asinh(1), signs trade imbalance и
   depth_l10 совпадают со знаком volume imbalance. Направление=sign(volume imbalance).
   Механизм: направленный поток относительно доступной глубины и согласованная сторона
   стакана могут предшествовать продолжению движения.
2. Absorption: |volume imbalance|>=0.2, sign(return_1) и sign(depth_l10) противоположны
   sign(volume imbalance). Направление=−sign(volume imbalance). Механизм: поток не
   продвигает цену в своём направлении при противоположной поддержке стакана.
3. Depth change: |depth_l10−previous_depth_l10|>=0.2, sign изменения L1 совпадает
   с sign изменения L10. Направление=sign изменения L10. Это изменение относительного
   баланса глубины, не абсолютного размера/очереди.
4. Control price_momentum: sign(return_1) на той же feature-eligible сетке.
   Flat control не совершает сделок и имеет нулевые затраты/доход, не missing imputation.

Все nonzero signals получаются и сохраняются ДО открытия numeric labels. На актив
выбирается первое решение, затем новые entry не раньше предыдущего planned exit.
Entry=E+10мин, exit=E+70мин; same-contract exact7open target из отдельной label table.
Это nonoverlap planned event assay, не реальный order ledger. Будущий missing target
не удаляет intent/следующие кандидаты и не превращается в0: event unresolved и
Stage2 запрещён при любом unresolved. Нет моделирования переносимого открытого риска.

## Costs, отчёт, gates

Signed underlying simple return=direction*expm1(log target), НЕ expm1(direction*target).
Research hurdle5/10bps на сторону, то есть10/20bps за полный эпизод. Это консервативное
заранее выбранное приближение, не подтверждённый broker/exchange tariff, BBO или fill.
Нет целых контрактов, margin/capacity/sizing/MTM: события не переводятся в рублёвый
портфель. CAGR, Sharpe, MDD=null с явной причиной; event means не annualize-ятся.
На этом этапе отчёт включает selected/completed/unresolved, coverage, gross/net/median/
hit-rate/break-even cost, все6лет и4актива, оба costs и baseline. Коррелированные
события не называются независимыми наблюдениями и не дают вероятности будущей прибыли.

Stage2 conditional candidate только если >=200completed, unresolved0, double-cost
mean>=5bps, >=4/6positive yearly means, худший yearly mean>=−10bps. Пустой год не positive.
Структурно отрицательный net mean отсекает гипотезу даже при неполной части labels;
positive-but-incomplete получает INCOMPLETE_NO_PROMOTION. Flat не кандидат на20–50%.
Цель20–50% НЕ заменяется5bps gate. Нужны портфельная устойчивость, source/execution
проверка и новый forward для прошедшего механизма. No live, no2026, no fit.
После результата не менять signs/0.2/asinh1/costs/horizon/активы/годы ради спасения.

Raw archive download идёт отдельным service и не нужен для V79. Никакого нового
сборщика, feature pipeline или универсального execution engine для этого конкурса.
