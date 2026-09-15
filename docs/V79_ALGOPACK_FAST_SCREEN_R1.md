# V79 R1 — correction of archival readiness tag, not economic tuning

2026-09-15. Parent V1 f2aa4f47daea выполнился, но все4arms имели0eligible opportunities,
0signals/0events. Metrics4fee492544624ce3e9570984a8a03d05b26eec2a57e0475494cc62700c7cbd7d
остаются неизменными. Его machine REJECT_STAGE1 некорректно трактовать как проверку
трёх экономических гипотез: authoritative verdict INVALID_SOURCE_STATUS_MAPPING.
V1 output сохранён; счётчик экономических screens от этих пустых arm не увеличивается.

Причина доказана старым frozen producer, не просмотром доходных окон: функция
select_training_flow в algopack_paper_alignment_v1.py возвращает
READY_ARCHIVE_ASSUMPTION, а V1 consumer ошибочно требовал READY у flow_status.
Price status действительно READY. V1 numeric features/labels были прочитаны,
но ни один outcome не был присоединён к intent и все economic means=null.

R1 допускает исключительно исходный flow_status=READY_ARCHIVE_ASSUMPTION в
отдельном conditional adapter по разрешению2026-09-15. Техническая копия колонки
отображается на предикат parent make_signals; исходный Parquet/его статусы, actual
availability и original-version flags не меняются. Online READY, missing и другие
статусы НЕ получают архивного допуска. В отчёте сохраняются counts исходных status.

Все parent formulas/signs/0.2/asinh1, four assets, full2020–2025, separate labels,
60min nonoverlap events, costs5/10bps per side, gates и controls byte-identical.
Parent config/code остаются frozen и входят в transitive closure. Нет source reload,
training fit, поиска threshold/часа/года или portfolio engine. Новая output root,
новый config/code seal и synthetic regression до повторного numeric load.
Feature eligibility0 теперь технический failure до labels, не экономический reject.
Условность current-vintage и null CAGR/Sharpe/MDD первого event-screen сохраняются.
