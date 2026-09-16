# V96 — внешняя премия за риск волатильности

Протокол зафиксирован 2026-09-16 до новых SP500 values/features/targets/PnL.
Один Stage1 screen, не новая модель, engine или обещание дохода.

Механизм: высокая разница implied и realized variance может отражать более высокую
премию за риск акций. [Исследование Bollerslev et al.](
https://www.federalreserve.gov/pubs/feds/2011/201152/index.html) мотивирует знак и
трёхмесячный горизонт, но не доказывает эффект в России. В статье realized variance
строится по intraday данным; здесь дешёвый daily-close proxy. Российская финансовая
изоляция после2022 может разрушить связь; эти годы не исключать.

Новая информация — SP500 closes2018–2025 из bounded FRED endpoint. Старый VIX
архив используется без повторного HTTP. Это не V24 VIX/VIX3M и не V14 RVI governor.
Не читать2026 цены; source collector проверяет все даты до numerical conversion.
Raw CSV, session calendar и manifest хранятся только вне Git на gpu-mlserver.
Новый source root immutable; после сбора его manifest SHA фиксируется в invocation
economic run. Config/code seal один и до HTTP/outcomes; source response SHA заранее
неизвестен, но endpoint, bounds, parser и правила источника уже фиксированы.

Proxy = (VIX/100)^2 − 252/21 × сумма квадратов21соседнего log return SP500.
Требуется21полная XNYS сессия, никакого пропуска unknown quotes. Сравнение с медианой
предыдущих252proxy states, без текущего дня. Calendar exchange_calendars4.13.2
изолирован вне общего venv; economics читает только уже сохранённый date calendar.
GoodFriday/Bush2018/Juneteenth2022/Carter2025 и открытый2021-12-31 проверяются до HTTP.

Один новый cohort в первый завершённый MOEX день месяца, decision18:45Moscow.
Берётся последняя строка source, а не последняя удобная ready строка. Обе US quotes
допускаются лишь после конца следующей XNYS сессии; archived VIX clock также обязателен.
Source age при выборе <=7дней. Lag — консервативное допущение, не PIT proof.
High proxy cohort даёт gross0.3, low даёт0. Три последовательных месяца складываются,
итог делится поровну MIX/RI. Нужны все3ready cohorts; иначе оба arms flat.
Контроль gross0.45 постоянно на тех же masks, не подгоняется по observed exposure.
Роллирование и integer rebalancing выполняет прежний ledger. Fill gap>7дней masked.
Новый портфель1млнRUB в2021; warmup2018–2020. Окончание2025terminalflat.

Base/double costs; без процентов на cash. Gates: CAGR>=5%, Sharpe>=0.5, MDD<=25%,
>=3positive years из5, worstyear>=−15%, coverage>=80%, primary>control при обоих costs,
all4executioncomplete/unresolved0/terminalflat. Для двух slow index sleeves заранее
>=30round trips; это не изменение старых gates/run и не снижение цели20–50%.

Сначала synthetic tests, pushed seal, server byte checks; затем один source fetch
и один immutable paired economic run с готовым V78/V64 учётом. Сохранять все arms,
годы, missing masks, counts, cash PnL и verdict. Никакого post-hoc sign/window/size/
market selection/control promotion. Goal_verified=false даже при Stage2 candidate.
