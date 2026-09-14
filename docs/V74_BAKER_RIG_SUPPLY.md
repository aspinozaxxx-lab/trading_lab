# V74 — upstream drilling supply signal для Brent

Новая гипотеза: сокращение числа нефтяных буровых США предшествует ограничению
будущего предложения и поддерживает Brent, рост числа установок действует наоборот.
Это проверяемое предположение, не установленная причинность. Бурение может само
запаздывать за уже учтённой ценой/спросом, а эффективность, незавершённые скважины и
ОПЕК могут перекрывать этот эффект. Не повтор EIA V17 inventory/refinery composite,
CFTC positioning, OHLCV конкурса или старого risk governor.

## Исходная таблица и ограничения

Источник — [Baker Hughes North America archive](https://rigcount.bakerhughes.com/na-rig-count),
`North America Rig Count New Report (2013-Aug 2025)`, опубликован2025-08-29.
[FAQ](https://bakerhughesrigcount.gcs-web.com/rig-count-faqs/) описывает активные буровые,
еженедельный выпуск в полдень Central Time и разрешение публичного использования с
атрибуцией, subject to website terms. Это личный research; исходник вне Git.

Неизменённый XLSX11 790 192bytes, SHA
`38ceac39bb7d791d3cf739de68a3c267c626198f695e2fea47c6dd9d6d501f0f`.
`NAM Weekly!A11:L11` задаёт поля Country, County, Basin, GOM, DrillFor, Location,
State/Province, Trajectory, Year, Month, US_PublishDate, Rig Count Value.
`A12:L169320`:169309 исходных строк,661 публикационная дата2013-01-04…2025-08-29.
Фильтр до outcomes: только UNITED STATES/Oil, без выбора региона/скважины по результатам.

PDF/Excel macros, формулы, external links и data refresh не выполняются. Читаются
cached source cells из XML; actual source не переэкспортируется. По навыку таблиц
проверены исходные labels, типы, календарные поля и сверка суммы с итогами издателя.
Комплектный Python не имел pyarrow для project imports; read-only проверка перенесена
в существующий server environment, без изменения dependency directories.

До market outcomes первые проверки выявили11 повторов subgroup identity на11датах2013
и13 пустых County у канадских записей. Не дедуплицировать и не принимать спорную сумму:
вся неделя повторяющегося ключа получает unknown oil/total count, дата и исходные
строки сохраняются. Любая такая неделя маскирует все зависящие14-observation windows.
County — необязательная географическая деталь, его null не заменяет известный count
нулём и не удаляет строку; прочие обязательные поля продолжают fail closed.
Latest US total/oil/date сверяются с `NAM Summary!D11,D22,D4` и `B11,B22` labels.

Критическое ограничение: XLSX — поздний архив, не доказанные original vintages всех
661выпусков. Использование конца US_PublishDate как момента доступности — явно
условное development-допущение. Ни байтовый hash, ни официальный календарь не доказывают
отсутствие последующих revisions. Historical causal admission=false, goal_verified=false.
Положительный screen потребует отдельной original-source/independent проверки.

## Зафиксированное правило

Сигнал `-sign(oil_rigs[t] - oil_rigs[t-13])`; нулевая разность означает flat.
Все14 counts должны быть известны, все13 промежутков публикаций —5…9calendar days,
что допускает holiday shifts, но не пропуск недели. Никакой imputation или shortened window.
Публикация доступна после конца её даты в America/Chicago; решение — MOEX EOD,
исполнение только на следующем фактическом active-contract open. Latest unknown/neutral
состояние вытесняет старое. Максимальный возраст source при fill14calendar days,
decision-to-fill gap<=7days. После2025-08-29 новых releases нет: полный2025calendar
остаётся, stale targets flat. Нельзя продлить последнюю рекомендацию или обрезать плохие даты.

Control всегда long BR при тех же source/history/freshness masks; не продвигать его
после просмотра. No fit/нейросети/vol scaling/grid. Daily allocation/causal rolling
переиспользуют неизменный V72 target adapter, учёт — общий V64 futures ledger.
2018–2025, исходный1млнруб., requested gross1, integer contracts, margin reserve2,
participation1%, collateral interest0, base1tick+1fee и double2ticks+2fees.
Все halts/cancellations/carried positions сохраняются, terminal flat обязателен.
Daily open/spec/fee proxies не означают доказанное BBO или реальные broker tariffs.

## Отсев и сохранение

В обоих costs: >=60closed episodes, CAGR>=5%, Sharpe>=0.5, MDD<=25%, минимум5/8
положительных лет, worst year>=−15%, CAGR excess надcontrol>=2pp. Source-ready coverage
>=90% всех BR factual effective dates; обе arms/costs полны, critical/unresolved0,
terminal flat. Это gate потенциального компонента Stage2, не замена цели20–50%.
Все8годов, counts, costs, coverage, CAGR/Sharpe/MDD и failed gates публикуются.

Config/code/tests/doc и parent V72 transitive identity запечатываются и отправляются
в GitHub до market outcomes. Canonical server run
`/srv/trading_lab_data/runs/v74_baker_rig_supply_v1_<seal12>` создаётся один раз.
В нём rig counts/states, targets, все4 ledger/order/position outputs, metrics/identity.
Audit сверяет raw workbook→states→targets, artifact hashes, metrics/annual/count/cash.
Новый знак/окно/пул/плечо/затраты после результата запрещены. Не менять2026 protection,
старый paper bootstrap, collectors или sealed parents. Никаких реальных сделок.
