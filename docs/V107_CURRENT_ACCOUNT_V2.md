# V107 V2 — единственное исправление старого формата, экономика неизменна

2026-09-17. [V1](V107_CURRENT_ACCOUNT.md) source stopped 01:41:28.055987 UTC на
первом PDF 2020Q3 с `wrong unit`. Один GET, 0 parsed releases; до states/targets/
market load/PnL. Economic root отсутствует. Original invocation
`53da1b8c6885483495967378ac11f9ec`, source journal exit1/FAILURE. Поздний transient
unit not-found с default success не означает успех.

V1 pre-outcome commit `841a022`, seal
`1c9775b7b11e043060a38e39c10cca1565af0ab522e2866a0fdd82f1630d8470`.
Failed source `source_evidence/v107_cbr_current_account/1c9775b7b11e`, manifest
`abee48cc62bcbf397d747941ee657b9131e93f04b46ee213f58d9604a55c6cb5`.
Six hashes + manifest verified, local backup seven regular files, archive
529643 bytes SHA `212948f64593103f563b018fea1fb6e5da71a9c2fdd1739b60167b8e8db44ece`.
Root сохранён, не перезапускается. Server tests после исправления только ownership
нового task temp folder: 85 PASS 0.98s; первая попытка имела 78 PASS / 7 fixture setup
permission errors, до source запуска. Sealed code/экономика при этом не менялись.

## Узкая причина и исправление

Визуально проверена table page4 PDF 2020Q3, SHA
`f66dc754bb3be2316e0b823b2dec6b2bde378c788f74af4334b7ce1f5527ebff`.
Старый compact layout не имеет annual totals и содержит последнюю отдельную
YoY-difference column. Unit/title идут ПОСЛЕ таблицы в text extraction, хотя
на странице находятся над ней. Число 22,1 разбилось на `22, 1` при extraction.
Два нужных balances читаются по year/quarter headers, не из difference column.
Разница отдельно округлена: она может не равняться разности отображённых balances.

V2 добавляет только этот explicit format: проверяет title/unit в той же странице,
строгие year/quarter headers и обе даты comparison column; optional annual columns
учитываются только при явной метке `Год`. Убирается whitespace внутри decimal comma,
не между отдельными числами. Difference column проверяется как число, но не становится
feature. Новый parser не принимает другой номер квартала, единицы или неизвестный ряд.
Прежний annual-table parser остаётся неизменным.

AST tests подтверждают равенство всех non-parser functions и всех economic/config
parameters V1/V2. Правило SI short0.9/cash, constant-short control, TTL120, periods,
costs, gates и risk limits не менялись. 8 новых / 93 combined tests PASS 3.75s,
Ruff clean. Все три уже прочитанных samples повторно разобраны; full source ещё нет.

## Reuse, границы и дальнейший шаг

Новый cached probe `source_evidence/cbr_bop_probe_20260917_v2/capture` содержит прежние
source artifacts, failed raw/metadata и оба parent manifests; **0 новых HTTP**.
Manifest `ae97954255ce05db340a78e36a929bf440f39f260dc998aa33013d68a8f4cb6d`;
15 hashes + manifest проверены server/local. Composite capture не означает original
PIT. Archive 1371015 bytes SHA
`5a44f716cb8cb99524b568bd1d5966f525f2d457e770638ec3521ce953175332`.
Строгий V1 calendar остаётся20 releases; повторно используются3PDF, новыхGET17.
Остальные source/rights/2026 ограничения V1 сохранены, commercial/live rights false.

Новый V2 config/code/test/protocol/seal и commit/push до remaining source/outcomes.
Затем одна source assembly, только после COMPLETE и полного raw/header replay —
один economic run. **Следующий distinct format failure приостанавливает ветку**,
без V3 parser или экономики на partial corpus. Пока V107 не portfolio entrant;
37portfolio/0activeStage2/3, goalactive и main AlgoPack archive продолжаются отдельно.
