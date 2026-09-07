# Fixed prospective daily paper evaluation V1

2026-09-07. Pure evaluation core, без IO/CLI/actual report. F=null. Не читает старые2026
outcomes, не рассчитывает historical AlgoPack economic results, не выбирает модель.

## Фиксируемый до результатов срез

Expected dates поступают из полного calendar-bound списка прошедших будних торговых
дней после F. Их нельзя выбирать по наличию equity/выгодным сделкам. Calendar SHA,
future boundary и evaluation clock сохраняются; pre-F/future/unordered/duplicate dates
отклоняются. Snapshot оценивается в окне18:20:00–18:20:30 Moscow, после последнего
планового exit18:10. Valuation≤actual observation; не разрешается backdate late snapshot.

На arm/day знаменатель42times×4assets=168 решений. Ready/sleep/failed/missing образуют
полное разбиение; rejected session/ineligible asset всё равно учитывается. Entries/closed/
open/pending/unresolved counts отдельны. Daily snapshot содержит обе arms, scenarios1×/2×
и ledger SHA. Double-cost equity не может превышать primary для одинаковых сделок.

Любой missing day лишает обе arms полной кривой. Unresolved/missing equity или оставшаяся
open/pending/unresolved position лишает полной кривой соответствующую arm, не скрывая
валидную baseline. Days не обрезаются, cash/returns не forward-fill-ятся; metrics=null.
Это отказ от полного performance claim, не утверждение нулевой доходности пропуска.
Причины, counts, coverage и closed trades по годам остаются видимы при неполной кривой.

## Показатели

Исходная точка equity — virtual1млн каждой arm. Total return и daily MDD доступны для
полной положительной кривой; initial-to-first-day loss включён в drawdown. Capital≤0
даёт CAPITAL_EXHAUSTED, total loss и drawdown, без CAGR/Sharpe.

CAGR считается только после252сессий И365календарных дней отF, по фактическому elapsed
time с365,2425days/year. До этого annualized figures=null, не экстраполяция короткого
успеха. Sharpe в том же зрелом срезе: sample std(ddof1) daily returns, sqrt252,
явное предположение risk-free=0; при нулевой variance Sharpe=null. Это не сравнение с
реальной ставкой денежного рынка. Daily MDD не является доказанной intraday MDD.
Return по каждому году не annualized, в том числе для partial years; годовые границы
переносят фактическую prior equity, не сбрасывают капитал на1млн.

Считаются обе arms и обе costs без выбора победителя. Status всегда descriptive paper;
target_income_verified, broker_fee_verified, execution_verified=false. Даже годовой
synthetic/conditional CAGR>20% не завершает пользовательскую цель. Нужны независимая
future evidence, стабильность/неопределённость, реальный тариф и execution limitations.
Нулевое число сделок — явный результат, не успех и не причина скрыть день.

## Граница доверия и оставшаяся работа

Pure core проверяет schema/time/coverage, но не открывает и не replay-ит ledger/source
records по переданным SHA. Evidence-bound runtime должен детерминированно построить
каждый daily snapshot из complete ledger, актуальных marks и полного журнала решений;
не принимать произвольные equity values за факт. Заданный SHA сам по себе не доказательство.
Actual snapshots пока нет. Нужны также matched forecast/target evaluation, stability/
uncertainty review, recovery/event builder и sealed scheduler; эти части не симулируются
наличием данного файла. Все fixed config/seals до actual NEW data иF.

17synthetic tests: initial loss, missing day, arm-specific unresolved/open/pending masks,
wrong denominator, bool/nonfinite/cost inconsistency, clock/duplicate failures,
zero-trade/empty/capital exhaustion и годовая искусственная кривая без promotion.
Server/runtime verification — в STATUS. Никаких рыночных данных/моделей в Git.
