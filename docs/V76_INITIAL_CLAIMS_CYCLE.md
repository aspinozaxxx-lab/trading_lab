# V76 — US initial claims как самостоятельный demand-cycle signal

До market outcomes: новый US labor information set, не модификация V74 drilling,
российских опросов или старого governor. Гипотеза: снижение числа новых обращений
за пособием год к году поддерживает мировой спрос/risk appetite, рост ослабляет.
Это предположение для проверки, а не установленная связь с российскими активами.

Источник [US ETA / FRED ICNSA](https://fred.stlouisfed.org/series/ICNSA): число обращений,
без сезонной корректировки, недели заканчиваются в субботу. Исходный CSV не изменён:
522 недели 2016-01-02…2025-12-27,9439bytes, SHA
`c80c5d1660ea514a23c8c04d8377445eb0892bce518b29ef86d7cda9ee3ab64f`.
Дата observation — конец отчётной недели, НЕ публикация. FRED прямо предупреждает
о revisions. Public Domain: Citation Requested; файл остаётся вне Git.

Навык таблиц используется read-only: проверка headers, numeric count units, уникальных
weekly-ending dates и missing против genuine zero. Комплектный Python читает CSV;
экономический код исполняется только в уже существующем server environment с pyarrow,
без установки/изменения dependencies и без авторинга workbook.
Первый неверный graph-page URL дал HTML200, сохранён отдельно без parsing/перезаписи;
V2 использует существующий в проекте `graph/fredgraph.csv` route.

Фиксированное правило: сравнить среднее последних4 недель с4 неделями52недели ранее.
Risk-on = минус знак разности. Ноль означает flat. Все56 weekly observations должны
быть известны и иметь55 промежутков ровно7дней. Missing/gap маскирует окно, а не
сокращает историю. BR/MIX получают direction risk-on, SI opposite, по0.3nominal.
Control всегда risk-on при тех же source/availability/freshness/market masks.
Это одна joint basket hypothesis, не три независимо найденные стратегии.

Условная availability — конец Saturday+7days в New York, с корректным DST. Только
после этого MOEX EOD decision и следующий factual open. Original releases/revisions
этот lag не доказывает: historical causal admission=false. Source-age at fill<=14days,
decision-to-fill<=7days. Даты source с предполагаемой availability>=2026 не создают
asset states/targets; raw остаётся полным. Market period2018–2025 не обрезается.

Исходный капитал1млнруб., gross0.9 target /1risk cap, integer contracts, margin reserve2,
participation1%lagged volume, collateral yield0. Base1tick+1fee/double2ticks+2fees.
Готовые V72 targets/V64 ledger/V68 summaries, без нового engine, fit или сервиса.
Все halts/cancelled targets/carried positions сохраняются, terminal flat обязателен.

Gates обоих costs: source coverage>=90%, >=24closed asset episodes для медленного
цикла, CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=5/8positive years, worst>=−15%, excess над
control>=2pp. Все4execution complete, critical0/unresolved0. Asset episodes не равны
независимым макроциклам. PASS допускает лишь тщательную Stage2 проверку компонента,
не подтверждает исходную цель20–50%. Все годы/arms/costs и failed gates публикуются.

Config/code/tests/doc и transitive parent seal фиксируются и push до цен. Один
canonical server run `runs/v76_initial_claims_cycle_v1_<seal12>`; read-only audit
rawCSV→states→targets, hashes, metrics/annual/count/cash. Не менять знак, активы,
окна, lag, плечо или gates после исхода. Protected2026, старый paper и collectors
не затрагиваются; никаких live orders.
