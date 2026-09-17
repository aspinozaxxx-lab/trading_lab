# V107 — источник приостановлен, экономического результата нет

2026-09-17. Две source attempts завершились до сборки signals/targets, чтения
market values и запуска ledger. Это **SOURCE_PAUSED_NO_ECONOMICS**, не отрицательная
доходность и не Stage 1 entrant. CAGR, Sharpe, MDD, decisions, trades и результаты
1×/2× costs **не вычислялись**, а не равны нулю. 37 portfolio и 0 active Stage2/3
не изменились. Цель 20–50% active и не подтверждена.

## Две сохранённые попытки

| Версия | Завершение UTC | Успешно разобрано / новых GET | Место отказа |
| --- | --- | --- | --- |
| V1 | 01:41:28.055987 | 0 / 1 | 2020Q3: compact table, unit/title после строк в extraction |
| V2 | 01:52:09.293474 | 3 / 2 | 2021Q2: narrative heading с номером сноски ошибочно принят за строку таблицы |

Обе manifests имеют `FAILED_SOURCE_NO_ECONOMICS`, error `wrong unit`. Одинаковая
строка ошибки скрывает разные причины. V2 действительно разобрал 2020Q3, 2020Q4
и 2021Q1, затем остановился на четвёртом документе. Download/parser success для
префикса не даёт права торговать по неполному corpus из planned 20 releases.

V1 protocol/seal и [единственная коррекция V2](V107_CURRENT_ACCOUNT_V2.md)
сохраняются неизменными. Предварительно установленный лимит исправлений исчерпан:
**не создавать V3, не подменять failed corpus ручной таблицей и не повторять
canonical source/run в следующей сессии**. Вернуться можно только по отдельному
обоснованному решению о приоритете, не автоматически ради окончания этой ветки.

## Проверка причины V2

В [официальном PDF II квартала 2021](https://cbr.ru/Collection/Collection/File/35478/Balance_of_Payments_2021-02_8.pdf)
на page1 zero-based есть заголовок `Счет текущих операций` с верхним индексом 1.
Extraction делает его строкой с числом, соответствующей слишком широкому regex.
`parse_pdf` вызывает `parse_table` для каждой страницы; этот ложный match вызывает
unit guard до фактической таблицы на page5. Визуальный просмотр обеих полных страниц
подтвердил: в настоящей таблице единицы есть, это **не доказанная ошибка источника**.
Title, year/quarter headers, annual column и footnotes сохранены. Навык PDF помог
отделить ошибку extraction/parser от неверных единиц в самом документе.

Raw 599201 bytes, SHA
`dac6ae8c54eec0540a909be66eb8c6d484fa33cb6788c3c223c30967b04d45e0`.
Received 01:52:08.361376 UTC; CreationDate 2021-07-14, ModDate 2021-07-15.
Metadata dates не доказывают original publication/receipt. Никаких PDF edits.

## Identity и резервные копии

V1 pre-outcome commit `841a022`, seal
`1c9775b7b11e043060a38e39c10cca1565af0ab522e2866a0fdd82f1630d8470`.
Root `source_evidence/v107_cbr_current_account/1c9775b7b11e`, manifest
`abee48cc62bcbf397d747941ee657b9131e93f04b46ee213f58d9604a55c6cb5`.
6 artifact hashes + manifest verified server/local; backup 529643 bytes, SHA
`212948f64593103f563b018fea1fb6e5da71a9c2fdd1739b60167b8e8db44ece`.

V2 pre-outcome commit `1e407b20afd0203a4f8c9c3eac70a8878b4351fc`, seal
`9f417b375a4fdba1238624947e54a76969db438130c01b08c014e8d467f9c370`.
Root `source_evidence/v107_cbr_current_account_v2/9f417b375a4f`, manifest
`46df3f4d1f00e79e16ee86ff531433819ea0beb6a12c1d178abee201e593edc4`.
12 artifact hashes + manifest verified server/local. Backup 2119131 bytes, SHA
`e9c1f47f97aa9edb689795d77fee4c8ce605d5f3d14646c4fd354c090942efda`.
Archive `tmp/v107_current_account_v2_9f417b375a4f/failed_source.tar.gz` на обоих hosts;
13 regular members checked before non-overwriting local extraction.
Server prefix `/srv/trading_lab_data`; local prefix `D:\Projects\trading_lab_data`.
Probe/cache V1/V2, failed roots и оригинальные manifests не изменялись.

V2 unit `trading-lab-v107-current-account-source-v2-9f417b375a4f.service`, original
invocation `1f770ff21ad54d06b8bbfad189e2273a`, observed PID 1734638.
Journal explicitly exit1/FAILURE, 2.607s CPU / 65.7M peak. Поздний transient unit
not-found/inactive/PID0 сам по себе не означает success. Оба expected economic
roots отсутствуют; economic service не создавался.

До collection: 93 local tests / 93 server tests PASS (3.75s / 1.03s), Ruff clean.
Closure: 93 local PASS 3.62s; оба seals и все 7/12 pinned file hashes unchanged,
Ruff clean. Synthetic tests не доказывают работоспособность на всех PDF layouts.

Original receipts/revision completeness и commercial/live rights не доказаны;
private research scope не расширен. 2026 outcomes не использованы. Main AlgoPack
unit, credentials и Windows collectors не менялись. Следующий bounded review
зафиксирован в [очереди источников](NEXT_SOURCE_REVIEW_20260916.md).
