# V101 — промышленное производство как сигнал спроса на нефть

Новая информационная гипотеза после завершённого V100, не настройка V99. Цель
остаётся относительно предсказуемая доходность 20–50% годовых. Census M3 не
тестировался из-за [source blocker](CENSUS_M3_FEASIBILITY_20260917.md); V101 использует
отдельный датированный источник, G.17 ФРС. До новых исходов фиксируется одно правило.

## Механизм и неизменяемый конкурс

Опубликованный рост реального выпуска обрабатывающей промышленности может указывать
на увеличение потребления промышленной энергии. Проверка: BR long 0.9 gross, если
последнее опубликованное месячное изменение manufacturing >0; иначе cash.
Нулевой показатель не положительный. Это проверяемая гипотеза о режиме спроса,
не утверждение причинности, новости-surprise или готовой диверсификации. V76 claims
и другие macro families могут отражать тот же цикл; иная информация ещё не означает
независимый источник дохода. При прохождении быстрого отбора это проверит Stage2.

Контроль — BR long 0.9 на том же календаре допустимого источника. Период 2018–2025,
1 млн RUB, нулевой доход свободных денег. Costs base 1 tick/1× fee и double
2 ticks/2× fee. Прежний integer daily ledger: gross cap1, margin buffer2,
participation<=1%, фактические роллы, пропуски и halt carry. Ни новый engine,
ни обучение модели, ни подгонка thresholds/окон/активов/плеча не нужны.

Те же Stage1 gates: coverage>=80%, >=20 round trips, каждый cost CAGR>=5%,
Sharpe>=.5, close-MDD<=25%, >=5 положительных лет из8, worst year>=−15%,
CAGR excess над контролем>=2pp, полное исполнение. Порог5% только для отбора
компонента, не замена цели20–50%. Ноль сделок, проигрыш контролю и провалы сохраняются.
Только Stage1-кандидат может перейти к Stage2; никакого demo/live/goal completion.

## Источник и календарь

[Official archive](https://www.federalreserve.gov/releases/g17/) содержит monthly
HTML, supplement и annual revisions. Берутся только точные dated monthly paths.
96 releases 2017-12..2025-12, включая один warmup. Отсутствуют October/November2025
публикации, в December2025 их две. December3 link без финального slash не терять.
[Technical Q&A](https://www.federalreserve.gov/releases/g17/g17_technical_qa.htm)
подтверждает: September preliminary вышел December3, October/November совместно
December23. В последнем выпуске семь месячных колонок вместо шести; берётся
последняя, November, а не средняя/выбранная по результату. November24 annual revision
не отдельный сигнал. Не создавать выдуманных выпусков по observation month.

Из первой summary table — только Manufacturing (see note below) / Manufacturing*, latest preliminary
month-on-month percent change. Header references отличают его от index level,
capacity utilization, mining/utilities, year-on-year и previous estimates.
Предыдущий месяц внутри текущей публикации может быть пересмотрен: используется
именно опубликованное изменение, без переписывания ранних signal states.
Корпус current-retrieved dated archives: original receipt/revision chain не доказаны.
Старые страницы содержат более поздние общие notices, они не становятся признаками.
[Условия ФРС](https://www.federalreserve.gov/disclaimer.htm): собственные материалы
Board обычно public domain; сторонние материалы не приравниваются к ним. Атрибуция
Board of Governors, G.17 и датированному выпуску; торговые выводы — только TradingLab.

Доступность: конец фактического release day New York плюс1час, не месяц наблюдения
и не выдуманный witnessed timestamp. Decision18:45МСК; исполнение не раньше next
factual daily open. Release TTL40 календарных дней, expiry fill gap3 дня; во время
долгого отсутствия публикаций состояние истекает. Задержанный exit не исключается.
Это условный development clock; лаг не доказывает первоначальную версию данных.

## Pre-outcome provenance и проверки

Probe `/srv/trading_lab_data/source_evidence/g17_probe_20260917_v1`, manifest
`07f75bd6ff4a1b2a6fe54c1a24f62fcd2393bf1393addade3e6b4a44670b7bf8`,
COMPLETE_FEASIBILITY_ONLY 2026-09-16T21:27:39.805171UTC. Index330836 bytes,
SHA `c252022c8c7ba23d45bf3fee534070d682c909475765de17cd77a35dfcfe0056`.
До seal прочитаны calendar metadata и три format samples: 2018-04-17,
2020-04-15, 2025-12-23; их значения manufacturing тоже уже известны. Рыночные
результаты V101, targets и полные source states ещё не считались.
Три raw release/metadata пары переиспользуются по SHA, остальных HTTP ровно93,
последовательно не чаще1/s, max3MB, без retry/redirect/auth. Любой отказ сохраняется
и блокирует economics; failed root не перезапускать/переписывать.

Code/config/tests/protocol и прямые зависимости запечатываются до полной source
сборки и нового расчёта; transitive V64 closure сохранён. Market inputs — прежние
recent manifests с границей<=2025, не произвольные актуальные файлы. Source manifest
фиксируется при economic invocation после проверки всех raw hashes и повторного
разбора всех96 releases. Четыре ledgers: primary/control × base/double.
Source->target, cash continuity/daily identity, order costs, performance, годы и
число позиций проверяются повторно. Нет будущих признаков, label-based eligibility,
нулевого заполнения неизвестного исполнения или independent-holdout утверждения.

Это один новый участник воронки только после economic run, не 96 гипотез.
После исхода запретить смену sign/asset/TTL/порога/размера/контроля и выбор годов.
Macro filters могут опоздать к ценам; actual production не гарантирует будущую
доходность нефти. Независимость и точная broker исполнимость пока не подтверждены.
Никаких 2026 market outcomes, расширения AlgoPack economics, покупок, сообщений,
broker/demo/live, ключей или Windows collectors; main archive продолжает свою работу.

Pre-seal checks: 17 новых / 102 combined synthetic tests PASS (12.31s), Ruff clean.
Реальные samples 20180417/20200415/20251223 разобраны: .1%/−6.3%/.0%, latest
observations March2018/March2020/November2025, 6/6/7 columns. До seal обнаружена
и явно поддержана новая подпись Manufacturing*; общий смысл показателя не менялся.
Первый synthetic calendar test правильно отклонил malformed inventory, но ожидал
другую строку ошибки; исправлена проверка текста исключения, не проверяемый gate.
Полные source states, targets и новые market outcomes ещё не вычислены.
