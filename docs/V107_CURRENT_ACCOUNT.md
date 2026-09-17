# V107 — опубликованный текущий счёт как режим поддержки рубля

2026-09-17, pre-outcome. Предыдущий goal turn — **PROGRESS**: V106 завершён без
продвижения, сохранены все сценарии, backup и git closure `cbca5a2`. Цель остаётся
относительно предсказуемыми 20–50% годовых, она не достигнута. Это новый information
set, не настройка V19 Minfin FX, V21/V105 forecasts или закрытого V106.

## Один быстрый тест

Положительный и выросший год-к-году текущий счёт может отражать устойчивое изменение
внешних потоков в пользу рубля. Фиксируется **SI short 0.9**, только если последнее
опубликованное сальдо отдельного квартала положительно и строго выше того же
квартала предыдущего года **в этой же публикации**; иначе cash. Control — SI short
0.9 на том же допустимом календаре. Равенство — cash. Сравнение точных Decimal,
не округлённых текстовых заголовков и не годовых/cumulative сумм.

Это lagged regime hypothesis, не измеренный surprise или фактическая конверсия
валюты на MOEX. Current account включает начисленные операции, а встречные потоки,
валюты расчётов, ограничения капитала и лаги могут полностью нивелировать связь
с будущими futures returns. Новизна информации не доказывает независимость дохода.

Полный development 2021–2025, 1 млн RUB, нулевой cash interest. Без fit/search,
нейросети, нового execution engine или выбора удобных лет. Прежний V72/V78/V64:
EOD decision, next factual open, integer quantities/rolls, margin buffer 2,
gross cap 1, participation <=1%. Base: 1 tick / 1x fee; double: 2 ticks / 2x fee.
Source TTL 120 календарных дней от publication, decision-to-fill gap <=7 дней;
невозможный exit не удаляется. Последний portfolio target flat, missing не доход 0.

Stage1: все четыре execution-complete/critical 0/unresolved 0, ready >=80%, каждый
primary cost CAGR >=5%, Sharpe >=0.5, MDD <=25%, >=20 round trips, >=3 positive years
из 5, worst year >=-15%, excess над control >=2 pp. 5% — только отбор компонента,
не новая цель вместо 20–50%. Counts включают rolls, не независимые публикации.
Не прошедший тест закрывается без sign/asset/window/TTL/size/control tuning.

## Source review, разрешённый объём и причинность

[Официальный каталог](https://cbr.ru/analytics/dkp/bal/) содержит дату публикации
в `data-tooltip-content`, хотя обычный text extraction её не показывает.
Выбраны по метаданным **20 PDF: 2020Q3…2025Q3**, отсутствует отдельный 2022Q1.
Combined 2022Q2 issue не становится двумя releases. 2020 — лишь начальный source
warmup. 2025Q4 опубликован 19 февраля 2026 и исключён **до PDF/числового чтения**.
Не используются другие текущие таблицы, quarterly full statistical bulletin,
seasonally adjusted history или материалы с protected market outcomes 2026.

Clock — конец указанного publication day Moscow, не конец квартала, не data cutoff
и не PDF CreationDate/ModDate. Последние не доказывают доступность; если они позже
publication, source fail-closed. Original receipts и revision chain не доказаны.
[Методика пересмотров](https://cbr.ru/statistics/macro_itm/external_sector/pb/met_change/)
описывает регулярные и разовые изменения прошлых данных. Опубликованный ранее state
никогда не заменяется пересмотренными значениями из следующего PDF. История остаётся
conditional development, не original-PIT / independent holdout.

В каждой таблице проверяются unit USD billions, явные consecutive year headers,
отдельные кварталы и annual total. Из year-1 берётся тот же номер квартала, а не
соседняя колонка. Q4 не заменяется итогом года. Отсутствующая таблица/значение/unit/
identity блокирует всю source сборку; не берём успешный prefix для экономики.

Через PDF skill визуально сверены relevant cover/table/footer pages двух samples:

- [2021Q1](https://cbr.ru/Collection/Collection/File/32216/Balance_of_Payments_2021-01_7.pdf):
  publication 15.04.2021, data cutoff 09.04.2021; table page 6 zero-based.
- [2025Q3](https://cbr.ru/Collection/Collection/File/59425/Balance_of_Payments_2025-3_24.pdf):
  publication 21.11.2025, estimate cutoff 14.11.2025; table page 8 zero-based.

Их source values уже прочитаны до seal; полные states, targets и новый PnL нет.
Parser `pypdf==6.10.0` установлен local/server; в двух образцах библиотека сообщает
о коррекции non-zero-indexed xref IDs. Raw bytes не изменялись, layout/table values
сверены визуально. Два samples переиспользуются по SHA; остальных GET ровно 18,
последовательно не чаще 1/s, максимум 5 MB, без redirects/retries/auth.

[Условия ЦБ](https://cbr.ru/about/) разрешают копирование с атрибуцией, но содержат
и ограничение коммерческого использования. Здесь только личное числовое исследование:
никакой перепродажи данных, коммерческого сервиса или live-rights admission.
Правовой охват коммерческого применения не установлен и должен быть отдельно
прояснён до такого применения. Не распространять PDF/чужие тексты через Git.
[Соглашение](https://cbr.ru/user_agreement/) отдельно требует атрибуции и запрещает
нарушать нормальную работу сайта. Никаких сообщений/покупок от имени пользователя.

## Captured evidence и pre-outcome проверки

Server probe `source_evidence/cbr_bop_probe_20260917_v1/capture`, completed
01:24:25.929148 UTC, manifest
`045d22b90e383965502a8a03ae04156cafa01a942083324fb11719d8546ce03a`.
Пять GET: index, две methodology HTML, два PDF. 11 artifact hashes + manifest
проверены при локальном backup, 12 regular members, без overwrite.
Archive 850744 bytes SHA `3b4a4f189438da165fd4b07c19648eeb68b7594af4142772bfac36ff75c2cbd1`.
Source-only capture не означает economic/source-PIT admission.

Первый технический launch остановился на parent permission до mkdir/HTTP/output.
Создан только отдельный owned task parent; единственный capture затем завершён.
Точно исполненный script сохранён рядом с local capture как `executed_capture_script.py`,
SHA `6ca93e1ba20025175d4556690f854c76587e10c42ad4c8bdee7eafa69339e193`;
в Git — его отформатированная версия. Capture source hashes в started/manifest неизменны.

26 новых / 85 combined synthetic tests PASS 2.92s, Ruff clean. Проверены headers,
annual/quarter distinction, Decimal ties, false/unknown values, tooltip dates,
protected PDF rejection before reader, next open/TTL/plan masks, future invariance,
flat-price short ledger/costs и forged cash continuity. До seal проходят 15/15
старых futures byte/schema/date checks; максимум рыночных inputs 2025-12-30.

Code/config/tests/protocol/source transport/parent closure фиксируются до remaining
PDF capture и economics. Source final manifest SHA передаётся в отдельный economic
invocation; перед PnL проверяются все raw hashes, весь selected inventory и повторный
разбор всех 20 PDFs. Ledger/source-target/metrics audit после одного run.
Если возникнет format failure: максимум одно narrowly scoped исправление формата,
новая sealed version и raw reuse без изменения правила. Второй distinct format
failure приостанавливает эту ветку. Canonical output не перезаписывать/перезапускать.
37 portfolio пока неизменны; main AlgoPack архив отдельно, broad scope unanswered,
TIC paused, Windows collectors не включаются, credentials не читаются.
