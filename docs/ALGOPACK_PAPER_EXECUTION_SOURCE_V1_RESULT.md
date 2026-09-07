# Dated execution source V1 — synthetic server result

2026-09-07, pushed/deployed `5f86c8f`. От trading-lab UID999 на gpu-mlserver277/277
связанных тестов PASS за16,62сек, включая27новых source tests. Local25+encoding2PASS,
2Linux-only skips, Ruff/diff-check PASS. Результат engineering-only, не economic run.

Новая Linux integration цепочка: fake dated quote+specs HTTP→response journal→COMPLETE→
raw replay→Quote/Terms и fake calendar pages→journal→replay→Session→paper intent.
Request activation и CA проверка замоканы только в synthetic fixtures; fixture bundle
при этом содержит hashes текущих source/execution modules. Production registry не создан.

Также проверены целая date projection до numeric validation, маски missing/nonpositive/
crossed BBO, точные schema/identity/depth, unknown calendar title, clearing before/inside
trade interval, conflicting intervals, terminal pagination/dictionary changes/duplicates,
raw normalization tampering, empty/reflected/schema response failures, absent closure,
ambient session auth refusal. Partial calendar failure оставляет response/FAILED, без COMPLETE.

| Файл | SHA-256 |
| --- | --- |
| algopack_paper_execution_source_v1.py | 333ca747f38a28f4959ae4b315414cc7762772728fb403cc24f4f64996176849 |
| test_algopack_paper_execution_source_v1.py | 05ead2402ad87a8f8d50035f2e538e57f214d785f01c2b09fbf38af6ab9a7e15 |
| ALGOPACK_PAPER_EXECUTION_SOURCE_V1.md | 4c94a60a6f87322484fc2b3d858921a6bcefa74016a83e86109edc6e2ef59ab1 |

Все3local/server hashes совпали. Metadata-only training44/witnessed7 parent closures PASS;
production activation отсутствует, verifier REFUSED до HTTP. F=null; actual NEW market
requests/forecasts/trades0. Исходная page calendar documentation прочитана с official
host, а не с market endpoint; protected2026 цены не запрашивались.

Далее portfolio ledger/reservations/MTM/unresolved recovery, fixed evaluation и combined
sealed runtime. Post-F account entitlement, actual schema/calendar-title coverage и
практическая задержка пока неизвестны. Тесты не подтверждают реального исполнения,
broker tariff или target income20–50%. CAGR/Sharpe/MDD нового опыта N/A.
