# V71 R1 — исправление scope спецификаций до первой симуляции

2026-09-13. V1 после pre-outcome push `f6cffe8` прошёл20server tests, source preflight
и построил macro states, затем остановился **до вызова portfolio ledger**: observations
уже SI/2021–2025, а specs переданы для всего recent bundle. Strict join отклонил
55 915 right-only rows; 10 137 совпадают, left-only0. Это input assembly bug, не
экономический провал стратегии. Orders/positions/ledger/metrics не созданы.

Parent output `runs/v71_cbr_liquidity_surprise_v1_ed9b8bc81357` содержит только
`inputs.json` и `liquidity_surprise_states.parquet`; точные SHA закреплены в R1 config.
V1 config/code/seal/артефакты не редактируются и не повторяются как canonical.

R1 добавляет единственный process-local adapter: отфильтровать specs по тем же
**SI / 2021-01-01..2025-12-31**, которые V1 уже применяет к observations. Не inner join
с молчаливым удалением unmatched; исходные exact-key/causal/fee/margin validators
сохранены. Никакие значения строк не меняются. Runtime adapter восстанавливает
исходные ссылки после выхода; общие файлы не перезаписываются.

Экономический config наследуется из byte-sealed V1: единственное отличие protocol_id
для нового output. Signals, aggregation, periods, masks, clocks, control, sizing,
execution, gates — прежние. Это не вторая гипотеза и не post-outcome tuning: PnL
V1 отсутствует и не просматривался. R1 seal/push обязательны до первого portfolio run.

Audit требует идентичных parent inputs/states bytes, проверяет source-state replay,
четыре metrics/count/cost/cash series и все artifact hashes. Обычный экономический
отсев остаётся V71; goal/live=false. Не менять frozen V1 для оформления результата.
