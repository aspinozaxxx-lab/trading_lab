# V101 V2 — исправление формата до economic outcomes

Не новая торговая гипотеза: наследуется [V101](V101_MANUFACTURING_DEMAND.md) без
изменения правила, инструмента, периода, costs, TTL, controls или Stage1 gates.
V1 seal `067dc4ec60266536e57c51df322c74c7daaef9b91a3f46db5fcaad78a672f55a`
и все его файлы остаются неизменными. Economic run V1 не запускался.

## Причина и сохранённый отказ

Server17 tests PASS. Source unit `trading-lab-v101-manufacturing-source-067dc4ec6026.service`,
invocation `ab3bd4894ffa4014b65e4d33a86a3e9c`, launch21:46:50.600267UTC,
завершился 2026-09-16T21:46:53.848649UTC со статусом FAILED_SOURCE_NO_RETRY.
Три HTTP выполнены, два выпуска разобраны. Третий, 2018-02-15, имеет header
`2018 Jan. [p]` в одной ячейке вместо двух отдельных year/month headers.
V1 поэтому правильно остановился на unexpected monthly column count, не заменил
значение нулём и не перескочил на другой показатель. Это parser bug, не отказ HTTP.

Root `/srv/trading_lab_data/source_evidence/v101_manufacturing/067dc4ec6026`, manifest
`8fab5d52bda458de1e32d20ee2ecd7d5d5089f3611245c95750cb1e5e9b7cba9`.
Raw20180215 SHA `6ab2f0b7a17ebcaee26609b472ced0bfcc9ccaba6cecab5e9b38c46848ced7d0`.
Никакого V1 restart/overwrite. При диагностике прочитаны headers и source values
этой страницы; новых prices/targets/PnL не было.

## Единственное исправление

Header resolver принимает separate YYYY + Month[r/p] или exact combined
YYYY Month[r/p]. По-прежнему явные header references, unique year/month,
6/7 последовательных месячных columns, последняя preliminary. Не индекс,
не annual change, previous estimate или другое производство. V1 targets/ledger/
audit используются неизменными. Effective config наследует все economic fields V1;
меняются только protocol/source root и provenance повторного использования raw.

Перед новой сборкой проверяются оба parent manifests и все их hashes. Три probe
страницы плюс три сохранённых V1 страницы копируются по SHA в новый root:
ровно90 новых публичных GET, последовательно >=1s, max3MB, no retry/redirect/auth.
V1 failure не обходится повторной загрузкой. Новая ошибка сохраняет staging и
блокирует economics. При COMPLETE — replay всех96 raw и source manifest pin
до единственного paired economic run. V1 и V2 вместе — один участник воронки
только после расчёта, не два. Ограничения conditional archives/protected2026
и запрет demo/live/goal claim сохраняются. Main AlgoPack archive не меняется.

Pre-seal: 16 новых / 118 combined tests PASS (9.57s); Ruff clean после исправления
только порядка импортов. Все шесть сохранённых raw перепроверены без новых HTTP,
metadata HTTP200/curl0 и manifest hashes PASS. Manufacturing значения первых
трёх .2/.1/.0, остальные .1/−6.3/.0; это source data, не market outcomes.
Тесты подтверждают эквивалентность прежних formats, отказ при ambiguous/missing
headers, отсутствие подмены annual column, неизменные economic config/targets,
проверку hash/status reuse и сохранение отказа без retries. После форматирования
16 новых тестов повторены: PASS0.47s.
