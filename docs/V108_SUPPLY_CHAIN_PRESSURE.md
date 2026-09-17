# V108 — одна гипотеза премии при ограничениях мировых поставок

2026-09-17, до чтения source magnitudes, signals/targets и нового PnL. Stage1,
не новый engine или перенастройка V101/V104. V107 source paused, не ремонтируется.
Предыдущий goal turn — PROGRESS по source feasibility и отсеву, не доходный результат.

## Правило и опровержение

BR long0.9/cash: GSCPI строго положителен и больше значения предыдущего месяца
**в той же колонке версии**. Иначе cash. Control — постоянный BR long0.9 на том же
readiness calendar, не кандидат для последующей promotion. Decimal, без обучения,
подбора порогов, смены знака, актива, окна, TTL, риска или control после результата.

Механизм: persistent cost-push scarcity может поддерживать нефтяную премию.
Но GSCPI не измеряет непосредственно crude supply или tanker freight; ослабление
спроса может перевесить supply effect. [Исследование NY Fed](https://www.newyorkfed.org/research/staff_reports/sr1017)
связывает индекс с producer inflation, не доказывает доходность BR. Его PMI/transport
information отличается от G.17 manufacturing output V101 и inventory/use V104.

## Источник и честная временная граница

Один raw CSV, 115873 bytes, SHA
`723e8dc81728176dea10e7d685478bfe888516ec68d1d2cc1b77d6fea8177c55`.
Capture root `source_evidence/gscpi_probe_20260917_v1/capture`, manifest
`69b8f0daadb50fb512c7486fc8a6e23db19d5b3fbf93a8179111b1a96a879831`.
348 dated rows + blank footer / 58 columns, включая Date. Header/date/lexical-only
review нашёл 48 vintage labels до2026. `#N/A` — missing, настоящий 0 сохраняется.
Первые nonblank counts ошибочно включали #N/A: для admission они не использовались.
Проверка с корректной missing semantics показала последовательные monthly endpoints.

Берём 43 версии May2022–Nov2025. Regular publication началась May2022;
retrospective pre2022 не доступный тогда сигнал. Availability = конец labelled
vintage month, America/New_York. Это **условное консервативное допущение**, не
наблюдавшееся время получения оригинальной публикации. Пример May2022:
2022-06-01 03:59:59 UTC. December2025 maps to2026UTC и excluded BEFORE numeric read,
как и later columns / observation rows>=2026. Числа raw2026 не features или outcomes.
Current-vintage сохранённая matrix не доказывает неизменность original columns.

[GSCPI](https://www.newyorkfed.org/research/policy/gscpi) описывает PCA/imputation,
demand adjustment и revisions. Сохраняются URL, authors, raw terms/description.
Private derived-index research по [условиям](https://www.newyorkfed.org/privacy/termsofuse),
без исходных vendor feeds, публичной перераздачи, endorsement или broker/live.

## Исполнение и gates

2022-06-01…2025-12-31 полностью, partial2022 отдельно от full2023–2025. История уже
просматривалась в других тестах, не независимый holdout. Старый V72 EOD → next
factual open / V78 / V64 integer ledger, capital1mRUB, grosscap1, marginbuffer2,
participation1%, cashinterest0; costs1tick/1xfee и2ticks/2xfee. SourceTTL62days,
decision→fill<=7days. Missing pair abstains; malformed schema/tokens fail closed.

Все 4 cases executioncomplete/critical0/unresolved0/terminalflat. Primary при
обоих costs: CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=12roundtrips, >=3positive year
segments/4, worst segment>=−15%, excess over matchedcontrol>=2pp; readiness>=80%.
Trades включают rolls, не независимые monthly shocks. 5% — лишь component gate,
не замена требуемым предсказуемым20–50%. Положительный исход требует Stage2 и
проверки clocks/vintages/исполнения до нового demo; real-money trading запрещён.

До запуска: synthetic tests, source/futures metadata preflight, code/config/input
seal + commit/push. Один economic run и полный audit/backup всех исходов. Больше
HTTP/source parser не требуется; главный AlgoPack archive продолжает работать.
