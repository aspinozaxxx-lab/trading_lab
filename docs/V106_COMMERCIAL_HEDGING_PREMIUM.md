# V106 — reported commercial risk-supply premium

Stage1, одна новая гипотеза, до новых числовых признаков/targets/outcomes. Предыдущий
goal turn — PROGRESS: V105 завершён отрицательным результатом и закрыт. Worktree
на старте e1de9b5344f880868200fdf1b31eb577fb5e31dc clean; цель20–50%active/unverified.

## Механизм и novelty review

Проверяем premium за принятие риска у commercial hedgers: повышенная чистая короткая
позиция этой группы может означать более сильный спрос на перенос downside-risk.
[Acharya/Lochstoer/Ramadorai](https://www.nber.org/papers/w16875) связывают hedgingcosts
с demand и ограниченной riskcapacity. Но capacity имеющимся набором не измеряется:
total_traders — не капитал, spreading — не свободная возможность нести риск.
Эти поля исключены из numerical read. Мы проверяем reported risk-supply proxy,
а не утверждаем, что определили реальный спрос или ограничения капитала.
[Gorton/Hayashi/Rouwenhorst](https://www.nber.org/papers/w13249) дают counterpoint:
в их выборке positions-based hedgingpressure не объясняет riskpremia. Использованы
primary abstracts; правило не репликация чужой доходности.

[Определения CFTC](https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm)
относят producer/merchant/processor/user к общей физическойcommercial группе,
не только добывающим производителям. Классифицируются участники, не каждое их
действие; возможны смешанная деятельность и изменения категорий. Spreading —
взаимно компенсирующие позиции, не капитал. Это существенно ограничивает вывод.

V58/V59использовали managed-money net-flow/crowding, V87 — GOLDmanaged-money.
В старом generic radar действительно собираются producer_merchant rows, но
`CFTC_CHANNEL_COMPONENTS` energychannel выбирает только managed_money WTI/Brent.
Поиск по aliases и прямым названиям не нашёл прежнего экономического использования
producer long/short. Новый annual-relative commercial risk-supply state не
переворот знака или новое окно старого managed-money signal и не V104inventory.

## Frozen rule

WTI exactcode067651. Pressure=(producer_short−producer_long)/OI. Baseline — median
строго предыдущих52reports, текущий не входит. LongBR0.9 только если pressure>0
и pressure>baseline; иначеcash, equalitycash. Controlconstantlong0.9 на том же
readiness/fillcalendar. 52reportannual baseline выбран до values, не параметрsearch.
Дробные сравнения точные рациональные; published contractcounts nonnegative integer,
<=2^53−1, OI>0, каждыйlong/short<=OI. Все53rows должны быть valid, adjacentgap<=10days,
windowspan<=371days. Любая missing/invalidrow маскирует весь зависимый window;
нет skip/zero/shorterhistory или fallback к старому хорошему состоянию.

Источник уже сохранён,836rows/418WTI2018–2025, metadata maxgap8days; numerical
completeness пока не исследована. Точные manifest/audit/raw/processed identities
и projection в config; byte/schema/date/unit/code checks до числовой загрузки.
No HTTP/CSVparser/collector. Current-vintage archive, не original revision chain.

Clock = EODNewYork max(report+7days, pinned special-release date), затем maxclock
всех53dependencies. Оригинальная uniform7day column не используется. Shutdown2018/19,
ION2023 и shutdown2025 overrides сохраняются; GOLDcorrection2019 не относится кWTI.
Report clocks>=2026 исключаются Arrowpredicate ДО values. Latest report wins at
same availability; delayedolder не перезаписывает уже более новый state. Unknown
source остаётся unready, не backfill. TTL21calendar days от reportasof, fillgap<=7.

## Execution, gates, scope

Полный2021–2025development,2018–2020sourcewarmup, без fit/calibration/seed/normalization/
search/purge-dependent training; не независимыйholdout. Sourcevalues и рынок2026
защищены. Прежний V72EODdecision/nextfactualopen/V78/V64integerledger; initial1mRUB,
signalgross.9/riskcap1.0, marginbuffer2, participation1%, zero cashinterest.
Base1tick+1xfee и double2ticks+2xfee, no samebar/futureexit eligibility.
Halted exposure/missing marks/unresolved не удалять. Broker-exact доказательств нет.

Allfour executioncomplete/critical0/unresolved0/terminalflat обязательны. Primary
обаcosts: CAGR>=5%,Sharpe>=.5,MDD<=25%,>=20trips,>=3positiveyears из2021–2025,
worstyear>=−15%, excessovercontrol>=2pp; readiness>=.8. ИначеStage1reject, execution
failure — INVALID/no promotion. Gate5% лишь компонент, цель20–50%не заменяется.
Никаких sign/horizon/baseline/asset/cost/risk/freshness/control retunes послеoutcomes.

Доrun syntheticcausality/gap/clock/rational-sign/missing/nextopen/costledger tests,
immutable code/config/test/protocol/CFTC-clock/parentseal, commit/push. Одинserverrun,
all states/targets/4ledgers/metrics/annual/costs/counters + read-only replay. Full
results и backup outsideGit. Stage2 только послеgates; no demo/live or broadAlgoPack
scope expansion. Mainarchive продолжается, TICpaused,V105closed. At most one bounded
structural correction if necessary before economics; не бесконечная подготовка.
