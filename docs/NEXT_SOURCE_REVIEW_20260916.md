# Резервные источники после V99: bounded discovery, не economic tests

Текущий статус17сентября: [V101 завершён INVALID](V101_MANUFACTURING_DEMAND_RESULT.md),
33portfolio/0activeStage2. TIC feasibility завершена; следующий шаг — один
[V102 bank-funding screen](V102_TIC_BANK_FUNDING.md),92GET+4reusedreleases,pre-outcome.
Original monthly inventory и4HTMLsamples сохранены,HTTP200;bankrow29formatsPASS.
UsingTICcanonicalpage архивирована,privateanalysisonly/no raw redistribution.
2023breaksecurities не касаетсяbankreporting по официальномуannouncement.
Monthlysection1исключаетAnnualSurveys2/3;indexJanuary2023typo подтверждён actual
January19,2024release. Старыйsystem-home-pageURL былHTMLredirect,неlicensetext.
Ни outcomesV102,ниStage2candidate пока нет;V101 не повторять/не ретюнить.

## Treasury TIC — первоначальный discovery record, заменён V102 protocol выше

Поиск по docs/configs/src не нашёл прежней TIC family. Возможный механизм для
исследования — трансграничный спрос на долларовые активы; это гипотеза, не доказанная
связь с будущим курсом SI/GOLD и не установленная независимость от прежних macrofamilies.
[Официальный указатель](https://home.treasury.gov/data/treasury-international-capital-tic-system/tic-press-releases-by-topic)
содержит датированные monthly releases, а[архив](https://home.treasury.gov/archives-of-tic-monthly-data-releases)
— месячные снимки данных. Пока прочитан HTML inventory и один HTML release, не ZIP/PDF
корпус или новая price history. Server access/праваполногоиспользования не проверены.

В[выпуске18Nov2025](https://home.treasury.gov/news/press-releases/sb0317) совместно
опубликованы August/September после shutdown. August в тексте уже пересмотрен;
original data вынесены в архив. Поэтому observation month и nominal archive label
не подходят как availability. Есть series break February2023 для строк1–21/30–32;
TIC не охватывает direct investment, custodial attribution ограничена. Все source
значения этой страницы просмотрены до какой-либо гипотезы; не market outcomes.

Первый следующий шаг: до3datedHTMLformats из разных лет, revision/clock/schema/
rights и небольшой serveraccess check. Не скачивать current revised series с2026.
Index label01/19/2023дляNovember2023 выглядит ошибочным — сверять сам release,
не автоматически исправлять год. Пригодность должна определяться до выбора
признака/актива/порога. Только затем отдельный pre-outcome protocol/seal и один
дешёвый economic screen на прежнемledger;V102config/run ещё нет. Если источнику
нужен большой новыйframework или доступ закрыт, сохранить вывод и перейти дальше.
Никаких покупок/писем/credentials/access-workaround, broaderAlgoPackscope не меняется.

## Исторический review после V99 (Census теперь blocked)

Проверены параллельно сбору H.4.1, без новых цен/доходностей или массовой загрузки.
При первоначальном review V99 прошёл Stage1 и получил приоритет для Stage2.
Обновление 2026-09-17: [V100 завершён и отклонил устойчивость V99](V100_V99_ROBUSTNESS_RESULT.md).
[Проверка Census завершилась source blocker](CENSUS_M3_FEASIBILITY_20260917.md):
первый server GET HTTP403Cloudflare, no retry, корпус отсутствует. Вместо ожидания
выбран отдельный [V101 G.17 manufacturing-demand screen](V101_MANUFACTURING_DEMAND.md).
Новый источник не даёт автоматического economic PASS; используется прежний ledger.

## ОПЕК — источник найден, массовый корпус не разрешён условиями

Найдены original dated HTML releases:
[18July2021](https://www.opec.org/pr-detail/209-18-jul-2021.html),
[2June2022](https://www.opec.org/pr-detail/127-02-jun-2022.html),
[5October2022](https://www.opec.org/pr-detail/73-05-oct-2022.html).
В них есть направление/размер изменения production plan и effective months.
Объявленный прирост не обязательно новая информация: часть планов подтверждается,
часть ускоряется. Нельзя превращать каждое повторение предыдущего плана в surprise.
Полный корпус/clock/revision chain и отличие обязательных квот от добровольных
сокращений не проверены. Старый V6GDELT oil_supply query уже включал OPEC; отдельного
source-bound production-plan change теста поиском docs/src/configs не найдено.

[Terms and Conditions](https://www.opec.org/terms-and-conditions.html), пункты6–9,
ограничивают shared electronic archive и коммерческое копирование; определение
commercial purpose включает исследование в надежде будущего заработка. Occasional
attributed internal/research references не равны разрешению на полный trading corpus.
Без отдельного достаточного основания не делать bulk download/server archive.
Не обходить условия через Wayback/перепечатки; ничего ОПЕК не скачано в server corpus,
не отправлены запросы на разрешение, не сделана покупка. Политика privacy — другой
документ, не лицензия. Относительные footerlinks на pr-detail сначала дали404;
нужные действующие root-level terms были прочитаны, не предположены.

## Census M3 — source blocked, не следующий незаблокированный пункт

Найден[официальный архив full manufacturing releases](https://www.census.gov/manufacturing/m3/historical_data/index.html)
и[архив advance durable-goods releases](https://www.census.gov/manufacturing/m3/adv/historical_data/index.html).
Идея для feasibility: новая информация о заказах/запасах и возможном спросе на сырьё,
не ещё одна комбинация нефтяных цен. Правило/актив/окно ещё не выбраны, Census config/
seal/run нет. V100 занят завершённым Stage2 V99; V101 выделен отдельной G.17 гипотезе.

На момент первоначальной записи был прочитан только HTML inventory. Обновление:
извлечённый текст трёх PDF просмотрен, визуальная проверка неполная, server corpus
не загружен из-за отказа доступа. Подробности и failed manifest — в новой feasibility note.
2026links/поисковые snippets не импортируются и не используются как признаки.
Месяц observation не release date: December2018advance search metadata указывает
публикациюFebruary2019. Late2025observations могут быть опубликованы уже2026 и не
допустимы для decision<=2025. На HTML index August/September2019fullreport ведут к
одному linkID: обязательно сверять идентичность документа, не полагаться на label.

При продолжении: bounded historical-format/publication/rights check, original vs
revised release distinctions и existing-family review до нового короткого протокола.
Не загружать текущий full-series bundle с2026 и не строить новый ledger. Пока это
источник для проверки, не утверждение причинности/прибыльности и не гипотеза в счётчике.
