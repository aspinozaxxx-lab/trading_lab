# V113: широта частного спроса, pre-outcome Stage1

17 сентября 2026. Предыдущий goal turn — PROGRESS: exporter-FX source review
сохранён, исключена небезопасная склейка разных рядов, но прибыль не найдена.
Цель остаётся относительно предсказуемые 20–50% годовых; source PASS её не заменяет.

## Одна новая гипотеза

Одновременное расширение номинальных поступлений в потребительских,
инвестиционных и экспортно-ориентированных группах может быть более полезным
сигналом будущих денежных потоков компаний, чем один суммарный рост платежей.
Это фактические платежи через систему ЦБ, не survey V22 и не US manufacturing V101.
Механизм может не работать: цены акций уже учли информацию, инфляция/курс и
ставки сильнее, а веса экономики не совпадают с составом индекса.

Фиксируем до полного корпуса/новых outcomes:

- **Primary: MIX long 0.9**, только если все три опубликованных темпа роста
  (потребление домашних хозяйств, инвестиционный спрос, внешний спрос) строго >0.
  Иначе cash. Ноль не рост, нет magnitude threshold, модели, grid или тренда цен.
- **Control: MIX long 0.9**, если общий взвешенный входящий поток строго >0,
  при идентичной готовности всех четырёх cells. Диагностический, не новый alpha.
- Только первый (последний полный месяц) столбец **таблицы 1** каждого выпуска.
  Не предыдущие месяцы, квартальные cells, региональные таблицы, графики или XLSX.
- Full **2021–2025**, включая начальный cash до появления первой принятой публикации.
  2020 не склеивается с методологией сезонной корректировки, введённой с2021.
  Начало monthly corpus May2021: первый полный месяц после перехода с weekly.
- 56 dated releases May2021–Dec2025, по одному в месяц; уже взятые три PDF
  переиспользуются, не скачиваются повторно. Никакого выбора выпусков по значениям.

## Источник и ограничения

Официальный [индекс](https://www.cbr.ru/analytics/finflows/) и три layout samples:
[13May2021](https://www.cbr.ru/Collection/Collection/File/32280/finflows_20210513.pdf),
[10Apr2025](https://www.cbr.ru/Collection/Collection/File/55541/finflows_20250410.pdf),
[11Dec2025](https://www.cbr.ru/Collection/Collection/File/59481/finflows_20251211.pdf).
Их source cells уже видены и не являются unseen. Полная history directions,
targets и новый PnL не читались. В April2025 sample pypdf извлёк все74pages, вывод
был truncated; нельзя считать непоказанные этим вызовом таблицы untouched.

Это **номинальные**, seasonally-adjusted, winsorized платежи, не реальный ВВП/
продажи. Периметр — менее половины платежей, без полного внутрибанковского и
прочего платёжного оборота. Веса отраслей основаны на ВДС2018, распределение
по категориям спроса — на input-output2017. Группы пересекаются; три положительных
числа не три независимых подтверждения. Отрасль определяется основным ОКВЭД.
Региональный TRAMO/SEATS не смешивается с national daily SBL.

Границы winsorization пересматриваются; методология допускает пересмотр истории.
Выпуск Dec2025 прямо говорит, что общее приложение содержит всю историю в
**актуальной** версии. Поэтому current XLSX не открываем/не используем. Берём
ровно последнюю monthly cell каждого датированного PDF. Это current copies of
dated releases, а не witnessed original-vintage доказательство; замена PDF по тому
же URL не исключена. Header/index dates и PDF metadata проверяются отдельно.
Методологические изменения, уже включённые в конкретный выпуск, остаются частью
его опубликованного индикатора; нельзя ретроспективно обновлять старые cells.

Publication availability условно EOD даты выпуска Europe/Moscow. Это не выдуманный
точный intraday timestamp. Signal после этой границы, fill на следующем фактическом
open. Observation month обязан быть ровно предыдущим календарным месяцем.
Source age на fill <=66 calendar days, decision-to-fill <=7. Missing latest cell
маскирует оба arm; ни zero fill, ни older-good fallback. Неоднозначный label/date,
дубликат, gap в месячном корпусе, нечисловой selected cell — fail closed, кроме
трёх заранее перечисленных ниже **unavailable**, а не исправленных source events.
Положительные/нулевые значения не используются для выбора source eligibility.

Private research с атрибуцией Банку России, без raw redistribution/продажи данных.
CBR terms/agreement переиспользуются из cbr_bank_funding_20260917_v2/capture.
2026 PDFs/XLSX, market prices/returns/labels/targets/PnL не открываются.

## Исполнение и дешёвые gates

Существующий V72/V78/V64 EOD-next-open integer ledger, без нового engine:
RUB1m, gross admission1, target0.9, margin buffer2, participation1%, cash interest0.
Base1tick/1xfees и double2ticks/2xfees. Halt/roll/capacity/missing/unresolved
сохраняются. Research specs/fees, не broker-exact/live доказательство.

До Stage2: оба cost CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=20 roundtrips,
>=3positive calendar years из2021–2025, worstyear>=−15%, CAGR excess overcontrol>=2pp;
readiness>=80%; все4executioncomplete/critical0/unresolved0/terminalflat.
Сигнальные episodes и rolls показать отдельно. 5% — отсев потенциального компонента,
не замена цели20–50. История development/already-seen, не независимый holdout.

До economic run: source metadata/hash checks, synthetic tests, полный code/config/
source seal и commit/push. После результата не менять sign, asset, zero threshold,
три выбранные категории, weights, clock, TTL, period, control, costs или gates.
Никаких paid/broker/demo/live действий, Windows collectors, credential reads или
расширения AlgoPack economic scope. Main archive работает независимо.

## Source transport, до outcomes

Corpus V1 завершился FAILED_SOURCE_NO_RETRY06:35:27UTC на первом новом request:
June2021 HTTP200, curl28, получено1383617из2474945bytes за30seconds. Partial raw и
manifest сохранены, не допускаются. Это подтверждённый terminal HTTP transfer failure,
не истечение времени наблюдения SSH. Один отдельный corpus_v2 с теми же56URL,
тремя reused samples и max53HTTP увеличивает transfer ceiling до120seconds.
Нет автоматических retries, редиректов, изменения admission или экономического правила.

V2 COMPLETE06:47:08.659793UTC,56PDF/53HTTP/3reuse; manifest
`150c43f460928ee7d824c8fab88d1029295d5b4731235347dd920d3c2b3cf06c`.
На полном metadata-only прогоне первоначальный parser принял35/56. Большинство
остальных — abbreviations/two-digit years, переносы слов и арабские номера кварталов.
June2021 имеет два столбца May21: **первый**, с поправкой на дополнительные нерабочие
дни, остаётся selected согласно заранее выбранному first-column rule, без выбора по
величинам. Ни направление полных source states, ни рыночные outcomes не читались.

До seal уточнена политика неизвестных clocks (экономическое правило/gates не меняются):

- 11Aug2022: selected table page4 печатает2021, index/cover2022. Не исправлять молча.
- 7Mar2024: creation/modification11Mar2024, позднее заявленной публикации.
- 9Oct2025: creation13Oct2025/modification14Oct2025, позднее заявленной публикации.

Все три выпуска дают **unavailable event** на index-date EOD, обе стратегии уходят
в cash до следующего допустимого источника. Месяцы/дни не удаляются, они входят в
coverage denominator, порог80% остаётся. Никаких guessed timing/year repairs.
Любая другая ошибка останавливает экономический запуск. Это заранее оформленная
source-admission revision до полного numerical state и PnL, не post-outcome tuning;
условность current-copy backtest остаётся. Первоначальный all-or-nothing draft
не являлся sealed/canonical economic run. Дубликат May21 не две публикации.

V2 capture wrapper сохраняется в точных исполненных bytes; Ruff I001 сообщает только
порядок imports. Core/tests lint проверяются отдельно; не переписывать capture SHA
задним числом ради косметики. pypdf6.10.0 preinstalled local/server, новых packages нет.

## Metadata preflight перед seal

56 releases,53complete/3unavailable; **1271** календарных решений/arm,
joint source readiness **87.804878%**,155feature-unavailable/91stale flags
(перекрываются; не складывать). Для расчёта readiness использованы только
metadata/нулевые dummy directions, настоящие направления и PnL не вычислялись.
15 futures manifest/hash/schema/boundary checks PASS, inputs заканчиваются2025.
Metadata report `source_evidence/cbr_sector_payments_20260917_v1/metadata_v1.json`,
SHA `dc1fb029f82a0842de8ac75bae893d917b26a1d0d6c94c48f5269138db890ec1`.
42 новых /190 combined synthetic tests PASS. Разбор не сдвигает пустой первый
столбец на второй: количество tokens сверяется с date/quarter headers.
Printed PDF pages1/3/70–74 April2025,3/68–71 May2021,2/68–72 Dec2025
проверены визуально. Pypdf xref warnings Dec2025 зарегистрированы, raw не менялся.
