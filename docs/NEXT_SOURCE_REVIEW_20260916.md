# Резервные источники после V99: bounded discovery, не economic tests

Текущий статус 17 сентября 04:16 МСК:
[V106 завершён](V106_COMMERCIAL_HEDGING_PREMIUM_RESULT.md): primary +0.1664% /
−0.0319% CAGR, 10 trips, слишком слабая; controls execution-invalid, формальный
verdict INVALID_EXECUTION_NO_PROMOTION. Ни sign/window/asset retuning, ни control
repair-to-promote. 37 portfolio / 0 active Stage2/3. CFTC review ниже теперь история:
commercial rule уже проверено, total traders/spreading как risk-capacity proxy отвергнуты.

## Следующий bounded review — датированные публикации платёжного баланса ЦБ

Возможный новый information set — внешние торговые/доходные потоки, не Minfin FX
operations V19, survey forecasts V21/V105 или закрытый manufacturing channel.
Поиск экономических docs/configs/code не обнаружил отдельной balance-of-payments /
current-account family; это preliminary novelty check, не доказательство alpha.

Пока прочитаны только три официальных HTML releases; их linked quarterly commentary
PDF не открывались, новый full corpus/parser/service не создавался:

- [20 апреля 2023](https://cbr.ru/press/event/?id=14719): Q1 current-account surplus
  сократился вместе с trade balance; текст сравнивает экспорт/импорт с теми же
  кварталами прошлых лет. Нельзя принять это автоматически за QoQ surprise.
- [19 октября 2023](https://www.cbr.ru/press/event/?id=17141): Q3 surplus вырос
  относительно предыдущего квартала; названы экспорт, импорт и начисленные
  дивиденды нерезидентам. Это другой denominator сравнения, чем YoY.
- [30 января 2024](https://cbr.ru/press/event/?id=18378): текст о 2023 годе и
  сопоставлении с 2021/2022, не автоматически standalone Q4 release signal.

Следующий шаг — маленький dated-release inventory/coverage и проверка того, есть ли
сопоставимый отдельный квартальный показатель с проверяемой publication/revision
историей. До числового правила отдельно установить доступность, период, единицы,
rights и границы источника. Никакого V107/config/seal/targets/outcomes пока нет.
Не читать market outcomes 2026 и не принимать current revised series за original PIT.

Не смешивать cumulative со standalone-quarter, YoY с QoQ. Вычитание текущих revised
cumulative series не восстанавливает исходный monthly flow. Даже верно измеренный
current account не равен фактической продаже валюты на MOEX: financial account,
ограничения движения капитала и валюты расчётов требуют отдельного рассмотрения.
При слабой coverage/невосстановимой revision chain или необходимости большого нового
parser — зафиксировать source limitation и перейти дальше, не превращать review
в инфраструктурную ветку. Это agenda, не source admission или новый economic entrant.
Broad AlgoPack economic scope unanswered, TIC paused, archive работает отдельно.

## Предыдущий статус 17 сентября 03:45 МСК

Исторический статус17сентября03:45МСК:
[V105 REJECT_STAGE1](V105_SURVEY_DISPERSION_RESULT.md) завершён; GDPforecast IQR
contraction дал отрицательнуюдоходность в обоихcosts и не прошёлgates. V1URLidentity
failure сохранён,V2economicrulesнеизменны.36portfolio/0activeStage2/3. Не новый
surveychannel,quantile,sign/window retune; source review ниже — другое направление.

### CFTC producer hedging / risk capacity — исторический план, завершён V106

В уже сохранённом energy/metals source parser/schema есть producer_long/short,
managed_money_spreading, other_reportable_spreading и total_traders. Поиск точных
имён в экономических configs и futures_v*.py не нашёл их использования, кроме
source schemas; это предварительный novelty check, не доказанная независимость.
V58/V59 уже закрыли WTI managed-money net-flow/crowding, V87 — GOLDnet-flow→MIX/SI.
Не переименовывать эти сигналы и не менять их знак. Новые fieldvalues/coverage
числовойпригодности/targets/outcomes ещё не читались; V106config/seal нет.

[Acharya/Lochstoer/Ramadorai, NBER16875](https://www.nber.org/papers/w16875) связывают
издержки хеджирования с demand производителей и ограниченной способностью
спекулянтов принимать риск. Это rationale другого demand/capacity information set,
не доказательство tradableMOEXalpha и не разрешение считать числоtraders капиталом.
В качестве counterpoint [Gorton/Hayashi/Rouwenhorst, NBER13249](https://www.nber.org/papers/w13249)
отвергают существенную роль positions-based hedgingpressure в объяснении premia в
своей выборке. Пока прочитаны primary abstracts, не полныйpaper/PDF или новые данные.

Следующий шаг: коротко проверить измеримость demand/capacity существующими полями,
отличие от прежнего positioning, metadata-key coverage и pinnedpublication overrides.
Traders count не измеряет капитал, spreading не доказывает hedgingintent/capacity,
producer category может включать не только направление экономическогоhedge.
При слабой измеримости — отказ доeconomics, не новый большойparser/collector.
Если оправдано, один отдельный frozenrule/control/cost protocol перед values/targets.
Не использовать uniformreport+7days вместо известныхshutdown/correctionoverrides,
не ослаблять source current-vintage/admission/2026. BroadAlgoPackscopeunanswered,
TICpaused,archiveидёт отдельно. Это agenda, не проверенная гипотеза/новыйentrant.

## Предыдущий статус17сентября03:06МСК

Исторический статус17сентября03:06МСК:
[V103 REJECT_STAGE1](V103_ILLIQUIDITY_PREMIUM_RESULT.md) и
[V104 INVALID](V104_INVENTORY_COVER_PREMIUM_RESULT.md) уже завершены. Ни liquidity
premium, ни physical inventory-cover premium не дали кандидата.35portfolio/0active.
TICV102sourcepaused,не писать V4parser и не повторять прежние probes.

Следующий bounded review на готовых данных — **CBR macro-survey forecast dispersion**.
Catalog/code existing source содержит9statistics,включаяp10/p90; V21 использовал
только median revisions. Проверить metadata-only coverage и самостоятельный механизм
разногласий/неопределённости, без нового raw workbook parser. Новые statistic values,
market targets/outcomes ещё не читались; V105/config пока нет. Не добавлять каналы
или параметры в старый V21 по его результатам, не менять консервативную availability
или current-vintage limitations. При недостаточной новизне/coverage — отказ, не большая
подготовительная ветка. Broad AlgoPack scope по-прежнему unanswered.

Исторический статус17сентября02:05МСК: [V102 source paused](V102_TIC_SOURCE_PAUSED.md),
не complete feasibility и не economic result. Три последовательных format failures
сохранены, четвёртая версия в этом turn не создавалась;не автоматически продолжать
TIC parser в новой сессии.33portfolio/0activeStage2 unchanged,V102невычислялся.

Приоритет следующего шага — novelty review liquidity-risk compensation на existing
daily bundle. V66уже закрыл4volume/priceмеханизма; простой новыйfeature/порог не
независимаягипотеза. Сначала обосновать иной economic target/механику и proxy,иначе
отбросить. V103/config ещё нет;это agenda,не результат. BroadAlgoPackscopeunanswered.

TIC initial formats/calendar/privacy/source-use review сохранены в V102protocols.
Original monthly inventory,29unique release dates и canonicalUsingTICpage доступны
наserver. 2023breaksecuritiesнекасаетсяbankreportingпоannouncement;originalvintages
всё равно не доказаны. Никаких sourceeconomic admission/2026/credentials изменений.

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
