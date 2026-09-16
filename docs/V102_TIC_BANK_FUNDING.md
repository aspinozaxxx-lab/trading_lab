# V102 — банковское долларовое финансирование TIC, Stage 1

Одна новая гипотеза: опубликованное сокращение трансграничных чистых долларовых
обязательств банков может сопровождать сохраняющийся дефицит долларового
финансирования/уход от риска и рост USD к RUB. Это проверяемое предположение,
не установленная причинность. Сам поток net: изменения активов тоже влияют на него.

Правило до outcomes: SI long 0.9 gross при последнем опубликованном месячном
потоке строки 29 < 0, иначе cash. Контроль — constant long 0.9 на том же календаре
доступности источника. Контроль нельзя продвигать после просмотра результата.
Период 2018–2025, старт 1 млн рублей, idle cash без процентов. Никакого обучения,
подбора порога, rolling normalization или выбора лет. Не меняем знак/актив/окно/
размер/TTL после результата. Это не новая смесь V49/V60 или retune V101/V99.

## Источник и ограничения

[TIC releases](https://home.treasury.gov/data/treasury-international-capital-tic-system/tic-press-releases-by-topic):
96 датированных HTML, December 2017 warmup — December 2025. Только раздел 1
Monthly Releases: разделы 2/3 Annual Surveys не включаются. Индекс содержит
metadata 2026; такие ссылки исключаются до запросов source values. Короткие даты
MM/DD находятся в observation-year группе, январь/февраль относятся к следующему
году. Index typo `01/19/2023` у jy2034 исправляется только фиксированным override:
[сам release](https://home.treasury.gov/news/press-releases/jy2034) датирован
19 January 2024 и сообщает November 2023. Дата каждого HTML сверяется с article
datetime и og:url, не только с индексом.

Берём только последнюю месячную колонку строки 29 `Change in Banks' Own Net
Dollar-Denominated Liabilities`: billions USD, not seasonally adjusted. Table title,
unit, row label, восемь числовых колонок, четыре последовательных месяца и два
rolling year/month headers проверяются. Annual/12-month totals не признаки.
На [17 April 2023](https://home.treasury.gov/news/press-releases/jy1420) Treasury
объявило изменение securities reporting с February 2023, но banking reporting и
форматы оставило неизменными. Выбор банковской строки сделан из соображений
сопоставимости до outcomes, не по её доходности. Это не гарантия отсутствия иных
пересмотров/структурных изменений или сезонного window dressing.

October 2025 release отсутствует. [18 November](https://home.treasury.gov/news/press-releases/sb0317)
совместно вышли August/September; используем последний September и фактическую
November publication, не вымышленную October availability для August. TTL 40 дней
истекает в пропуске. Current archive copies могут быть отредактированы: нет
доказанного полного revision chain и original receipt. CMS datetime используется
только для идентичности даты, не как историческое время доставки.

Availability = конец publication day New York + 1 час, decision = 18:45 Moscow
завершённого дня. Fill — следующий фактический daily open. Intent старше трёх
календарных дней или release старше 40 дней на fill отменяется; отсутствующие
состояния/планы masked, не заменены известным нулевым значением. Нет future-exit
eligibility filter, незакрытые позиции/halts остаются в старом ledger. В конце flat.

[Using TIC](https://home.treasury.gov/data/treasury-international-capital-tic-system/contact-tic-using-tic)
описывает скачивание HTML/data для читателей и spreadsheet/database use. Здесь
только частный анализ официальных опубликованных чисел, без raw redistribution
или endorsement. Privacy policy не трактуется как лицензия на данные. Старый URL
`system-home-page` оказался HTML redirect; его raw сохранён отдельно, actual
canonical page получена без обхода доступа. Никаких ZIP/PDF/third-party данных.

Два completed probes: `source_evidence/tic_probe_20260917_v1`, manifest
`958c94a2c0654f24b77ea4414d22ddfd7d7d5f2eb789aa678524151186932ec7`; и
`source_evidence/tic_canonical_probe_20260917_v1`, manifest
`e411039a3ca1305048ea3f8ed38604841d3316dfb9f36a7f652bed8460fb08da`.
Четыре release samples и их значения уже просмотрены до seal; full states,
candidate targets и outcomes ещё не рассчитывались. Сбор: 92 новых public GET
serial >= 1 секунды, 4 reuse по hash с metadata, max 3 MB/page. No retry/redirect/
credentials; первый отказ/parse failure сохраняется и блокирует economics.

## Исполнение, проверка и отчёт

Используется неизменный V64/V78 integer daily spec-proxy ledger, V101 cash audit.
Parent V101 seal `067dc4ec60266536e57c51df322c74c7daaef9b91a3f46db5fcaad78a672f55a`
пинит transitive engine/code и V64 input declarations. Только recent era:
active map `40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823`,
observations `a1c650780d08e31668829bc5bb07d0aeb25239d44f8f3620cb2d054ded70acf6`,
spec proxy `8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682`.
Manifest/SHA/schema/date preflight до цен. Source reparse/HTTP/hash до economics.

Base = 1 adverse tick + fee 1x; double = 2 ticks + fee 2x. Gross cap 1.0,
target 0.9, margin buffer 2x, participation <=1%, interest 0. Нет borrow/short.
Все прежние execution validity gates, critical counters и unresolved checks
сохраняются. Audit replay подтверждает cash/costs/performance/year/count identities,
но не независимую полную реконструкцию risk counters. Exact original broker specs,
fees/margin/BBO не доказаны; это development proxy, не live readiness.

Stage 1: source readiness >=80%, >=20 round trips, в обоих costs CAGR >=5%,
Sharpe >=0.5, MDD <=25%, >=5 positive years из 8, worst year >=−15%, превышение
контроля по CAGR >=2 п.п., execution complete у всех arms/costs. Неудача = REJECT
или INVALID при execution failure; не ретюнить. PASS даёт лишь Stage 2 stress/
period-dependence и сравнение с V49, а не цель 20–50%, demo или live. Уже виденную
2018–2025 историю нельзя называть независимым holdout.

Outputs вне Git: source raw/metadata/calendar/releases/manifest, затем targets,
orders, positions, cash ledgers, counts, annual returns, costs, drawdown, assessments
и manifest в новом versioned run. Код/config/tests/protocol byte seal до full source
и outcomes. Нельзя перезапускать canonical outputs. 2026, credentials, broader
AlgoPack scope, main archive service и Windows collectors не затрагиваются.
