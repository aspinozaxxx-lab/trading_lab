# V93 R1: исправление единиц, не перенастройка стратегии

V1 completed2026-09-15T17:21:48.623300UTC, manifest
8e7c1cf9463f98b9109d083b2a19ca665c4db21a41dfd2565bb4a6c100f4c638.
1271 кандидатов/arm. Overnight598requests/595entries/0completed:
591 `UNRESOLVED_POINT_VALUE_CHANGE`,4 unknown exit. Control1053completed/97unresolved,
mean net−5.7420/−8.4145bp. Ночных gross/net результатов не было. V1 сохранён неизменно,
вердикт INCOMPLETE_SOURCE_NO_PROMOTION; это не отрицательная доходность overnight.

Причина ошибки в нашем адаптере: `sizing_point_value` — lagged оценка из
VALUE/(VOLUME*WAPRICE), с fallback по OI и settle, а не точный неизменный параметр
контракта. В `spec_proxy.py:293` она сдвинута на одну сессию; точное междневное
равенство такого float не является корректным gate изменения биржевых units.

В R1 оценивается только **безразмерный ценовой компонент**, не рублёвая VM.
Gross bp =10000×(P_exit/P_entry−1). Каждый tick/fee amount делится на собственный
strictly-prior point proxy соответствующей даты, приводясь к пунктам котировки:
cost bp =10000×[ticks×(tick_cash_entry/p_entry+tick_cash_exit/p_exit)
+fee_multiple×(fee_entry/p_entry+fee_exit/p_exit)]/P_entry.
Это всё ещё research-proxy costs, не точные исторические комиссии и не гарантия
неизменного контрактного multiplier. Cash fields переименованы в quote-points;
никакого RUB PnL, CAGR/Sharpe/MDD, sizing, margin или portfolio admission из R1 нет.

Старый pure endpoint evaluator переиспользуется в нормированных единицах; все requests
строятся по исходным specs **до** нормирования. Время, знак, universe, даты, thresholds,
capacity, cost multipliers, неопределённые exits и gates не меняются. Проверки:
инвариантность к смене денежной шкалы; прежние requests; сохранение unavailable
exit; отсутствие cash fields; эквивалентность V1 при point=1. Никакой подобранной
допустимой погрешности нет. Новый hash/run до первого normalized overnight результата.

Контроль уже виден, поэтому correction явно post-observation; её нельзя считать новой
независимой гипотезой, повторять до успеха или переводить в Stage2. Формально unresolved
и низкое покрытие по-прежнему блокируют продвижение. Цель20–50% не подтверждена.
