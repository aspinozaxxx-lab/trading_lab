# V71 — ошибка прогноза бюджетной ликвидности → SI

Новая Stage1-гипотеза, 2026-09-13, до просмотра её signals/outcomes. Не достигнутая
цель20–50%, не live/paper admission. Config `configs/v71_cbr_liquidity_surprise_v1.json`.

## Механизм и отличие

Непредвиденный приток рублей через счета расширенного правительства может вызвать
последующий спрос на валюту: положительная ошибка → long SI, отрицательная → short SI.
V18 уже отверг торговлю самим недельным прогнозом, V19 — persistence ежедневного
компонента Minfin FX. Здесь новая информация: прогноз сопоставляется с завершившимся
фактическим периодом; ни один из старых сигналов не повторяется/не переворачивается.
Одна primary hypothesis, один диагностический контроль, без выбора лучшего знака.
Контроль — направление сопоставимого фактического потока без вычитания прогноза.
Возможная причина отсутствия эффекта: операции тонкой настройки ЦБ нейтрализуют ошибку,
а валютный рынок реагирует раньше нашего консервативного исполнения.

## Сопоставимость источников

[Прогноз ЦБ](https://www.cbr.ru/statistics/pffl/) содержит средние накопленных изменений
за напечатанный период, а не простую недельную сумму. [Определения ежедневных
факторов](https://www.cbr.ru/statistics/flikvid/definitions/) задают дневные вклады;
положительный government component — снижение государственных остатков и приток
ликвидности банкам. Minfin FX уже входит в этот компонент, повторно не добавляется.
[Методика ЦБ](https://www.cbr.ru/Content/Document/File/17135/DKP_limit.pdf), раздел3.1,
формулы на странице7 и визуально проверенный пример1 на странице9 показывают
накопление дневных потоков и усреднение пяти рабочих остатков среды–вторника.

Фиксированное сопоставление: `mean(cumsum(G_wed, G_thu, G_fri, G_mon, G_tue))` внутри
напечатанного периода. Не календарное усреднение, не сумма, не накопление с даты
публикации. Включаем только обычный вторничный release со стартом на следующий день,
концом через6 календарных дней и точным наличием пяти weekday observations без extras.
Праздничные/нестандартные периоды, missing dates/cells остаются в coverage denominator
как unavailable; их не заполняем и не подменяем последней удачной неделей. Это
консервативный development matching convention, не восстановление неопубликованного
дневного прогноза ЦБ и не market consensus.

До дизайна проверены лишь metadata/schema/date columns и методика; errors/signals/PnL
не вычислялись. Два уже approved current-vintage bundle локально присутствуют и передаются
на сервер неизменными; это не новый collector/download истории. Hash/bytes/rows/raw
manifests фиксирует config и runtime preflight. Исторические revisions возможны,
original point-in-time releases не доказаны; положительный screen потребовал бы новых
prospective данных. Raw/data не публикуются в Git.

## Часы, исполнения, ограничения

Source availability = max(forecast clock, все совпавшие actual clocks,
23:59:59 Moscow следующего календарного дня после конца периода).
EOD decision использует только последний matured state, даже если он invalid;
исполнение на следующем фактическом active-contract open. Обычная неделя становится
известна не раньше конца среды, вход не раньше четверга. TTL10 календарных дней от
конца периода на fill, decision→fill максимум7; превышение/missing → flat intent,
не искусственный zero return. Будущий forecast end2026 — known schedule, но period
outside window, никогда не обращаемся к actual/market2026. Rolls/halts/unresolved
обрабатывает существующий portfolio ledger; последний factual effective day flat.

Только SI,1 млн рублей, gross≤1, integer contracts, margin buffer2, participation1%,
base1tick/fee1 и double2ticks/fee2, collateral interest0. Daily target sizing, weekly
information changes. Исторические открытие/fees/margin — research proxies, не BBO/fills.
V64 используется только как sealed input catalog/ledger, V68 — generic targets/metrics;
старые economic runs не запускаются. Все вычисления реальных результатов на gpu-mlserver.

## Отсев до результата

2021–2025 целиком, пять annual reports; уже открытая development history, не holdout.
Fit/labels/normalization/search отсутствуют. В обоих costs: CAGR≥5%, Sharpe≥0.5,
MDD≤25%, минимум4/5 положительных лет, худший год≥−15%, ≥50 round trips,
CAGR primary выше контроля минимум на2 процентных пункта. Ready≥60% всех releases с
полностью pre2026 периодом, включая irregular/missing. Все4 executions complete,
critical/unresolved0, terminal flat. Только `STAGE2_CANDIDATE`, не цель20–50%.

Сохраняем states, masks, обе серии targets, все4 orders/positions/ledger, counts,
coverage, annual/CAGR/Sharpe/MDD/gross/net/costs, verdict и SHA identity.
После результата запрещены смена знака/агрегации/week filter/TTL/control/leverage,
выбор хорошего года, повтор canonical. Следующий этап — только при полном PASS.
Иначе закрыть и искать иной механизм. Protected2026/paper/collectors не менять.
