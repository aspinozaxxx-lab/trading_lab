# V78 — два канала американских облигационных ставок

Объявлено 2026-09-14 до приобретения рядов и чтения новых market outcomes.
Stage 1, research-only, цель 20–50% не изменена. Новая информация: реальные
долгосрочные ставки и инфляционная компенсация, не STLFSI/VIX governor, US claims,
российские опросы, OHLCV или перестройка старого торгового engine.

## Две гипотезы, один неизменный контроль

1. `real_discount`: снижение 10-летней реальной доходности за 20 наблюдений облегчает
   условия финансирования/дисконтирования: risk-on = -sign(DFII10[t]-DFII10[t-20]).
2. `inflation_compensation`: рост nominal-minus-real spread за тот же период может
   отражать спрос/инфляционный импульс, полезный экспортёрам сырья:
   risk-on = sign((DGS10-DFII10)[t]-(DGS10-DFII10)[t-20]).

Risk-on: BR +0.3, MIX +0.3, SI -0.3; risk-off разворачивает все три знака.
Нулевая разность — flat. Каждый кандидат сравнивается с constant risk-on при тех же
source/history/freshness masks. Контроль не является новым продвигаемым alpha.
Никакого fit, threshold/lag/window/asset/sign поиска. Оба исхода сохранить.
Breakeven включает liquidity/risk premia, не чистую ожидаемую инфляцию;
направление причинности и перенос на Россию — гипотезы, не установленный факт.

## Источники и clocks

Два официальных FRED CSV: DGS10 и DFII10, отдельные GET на
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>&cosd=2017-01-01&coed=2025-12-31`.
Raw outside Git, неизменяемые файлы/хэши/receipt clock; exact two-column schemas,
unique increasing ISO dates, ни одной строки >=2026. Максимум 256 KiB/response,
timeout 30 seconds, без credentials/redirects и без повторного запроса успешного raw.
Не открывать current series charts или неограниченный data download.

[H.15 about](https://www.federalreserve.gov/releases/h15/about.htm) описывает публикацию
по рабочим дням. [Официальные notices](https://www.federalreserve.gov/feeds/h15.html)
фиксируют 16:15 с октября 2016 и поздние Treasury corrections. Для условного screen
принять quote date +2 US federal business days, конец дня America/New_York, затем
MOEX EOD decision и строго следующий factual open. Это delay allowance, не доказанное
время каждой original release/FRED receipt. USFederalHolidayCalendar плюс закрытия
2019-01-14/2019-02-20. DST применять после построения локальной календарной даты.

Known Treasury exceptions из notices заранее консервативно фиксируются для ОБОИХ рядов:
2017-04-14 available не раньше 2017-05-18 EOD (две поздние коррекции);
2020-08-18 и 2020-08-19 не раньше 2020-08-26 EOD (неоднозначный observation/release date).
Двухдневный allowance покрывает указанные corrections для 2018-09-17,
2023-08-01 и 2023-09-12. Это не доказательство полноты всех historical revisions.
Current-vintage/original-release admission=false; положительный результат потребует
отдельной проверки vintages и исполнения. Данные 2026 остаются закрытыми.

Сопоставлять ряды по exact date. Обе missing quotes не являются новой публикацией,
строки остаются в raw. Частичный missing создаёт masked observation, не нулевую ставку.
Окно: текущая и 20 предыдущих observed dates, где есть хотя бы один ряд. Требовать
21 complete pairs, max adjacent gap 7 calendar days, total span <=40 days.
Нельзя перескакивать partial missing или заполнять его. Available_at для окна — MAX
времени доступности всех его компонентов, а не только последней quote date.
Late old-source windows не должны вытеснять уже известный более новый source date.
Freshness: source age at fill <=14 days, decision-to-fill <=7 days.

## Предварительный отсев и экономика

Сначала hashes/schema/date/missingness и source→decision→fill coverage, без MOEX prices
или PnL. При ready asset-date coverage <90% или <200 ready source dates в 2018–2025
не запускать экономику. Не менять gates после этой проверки.

Если проходит: все 2018–2025, initial cash 1 млн руб., готовый V72 daily target adapter /
V64 integer ledger / V68 summary, без изменения родителей. Gross signal <=0.9,
portfolio cap 1.0, margin reserve 2.0, cap 1% lagged volume, idle interest 0.
Costs: 1 tick +1x fee, 2 ticks +2x fee. Сохранить halts/carry/cancelled targets,
все годы и неизвестные исходы. Terminal flat и отсутствие critical/unresolved обязательны.
Полный observation/spec join до asset filtering; не повторять scope bug V71.

Gate для КАЖДОГО кандидата при обоих costs: CAGR>=5%, Sharpe>=0.5, MDD<=25%,
>=30 closed asset episodes, >=5/8 positive years, worst year>=-15%, CAGR excess
над контролем>=2 п.п. Все 4 arm/cost executions complete. Trade episodes не считаются
независимыми macro shocks. PASS лишь STAGE2_CANDIDATE, не достижение цели20–50%.

Code/config/source manifest seal и push до market outcome load. Price-free count
проверить ещё раз в runtime до market load. Не переименовывать NO_GO, не выбирать
лучший знак/период/вес после outcomes. Не возвращать старый paper и не менять collectors.
Поисковый запрос документации вернул также нерелевантные current-release snippets;
они не открывались отдельно и не использовались в дизайне/числах. Используются только
документация и явно ограниченный CSV диапазон, не результаты поиска с котировками.
