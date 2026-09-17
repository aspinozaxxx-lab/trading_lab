# Резервные источники после V99: bounded discovery, не economic tests

## Текущий статус 17 сентября 08:37 МСК — V112 закрыт; exporter FX review

[V112 result](V112_RUBLE_FUNDING_PRESSURE_RESULT.md): primary+0.6078%/+0.5789%,
22trips,3positiveyears/8; оба controls critical2, formal INVALID.42portfolio,
0activeStage2/3. Source/run audits и backups PASS; не улучшать старое правило.
V112 действительно добавил joint funding quantity/price, не повторял V18/V71.

Следующий bounded review — **фактические чистые продажи валюты крупнейшими
экспортёрами**. V64 — календарный proxy ожидаемых продаж перед налогами, V19 —
государственные Minfin FX операции, V107 — current account, не конвертация валюты.
Поиск `exporter/экспортер/экспортёр/foreign.exchange.sales` в configs/docs нашёл
только V64/V78 explanations, не отдельный готовый actual-exporter-flow screen.
Это не доказательство alpha/независимости; направление, нормализация и rule не выбраны.

Пока сделан **только official web search**, без открытия PDF, загрузки корпуса или
извлечения графиков. Найдены CBR monthly Financial Market Risk Reviews:

- [April2025](https://www.cbr.ru/Collection/Collection/File/55867/ORFR_2025-4.pdf):
  snippet содержит отдельный ratio net FX sales/FX export proceeds и прямо говорит
  об ежемесячных пересмотрах из-за уточнения зарегистрированных внешнеторговых контрактов.
- [July2025](https://www.cbr.ru/Collection/Collection/File/57148/ORFR_2025-7.pdf):
  snippet указывает cohort29exporters, источник — опрос банков, данные ЦБ/MOEX.
  Monthly net sale volume и ratio к export proceeds относятся к разным reference
  months. Нельзя считать report month датой доступности всех cells.
- [May2025](https://cbr.ru/Collection/Collection/File/55957/ORFR_2025-5.pdf) подтверждает
  предупреждение о revisions ratio. Search snippets также показали числовые source
  cells2023–2025 и исторический market narrative: они уже видены, не unseen.

Search-rendered chart labels не проверенные числа для модели. Полные PDF/страницы,
original release dates, cohort continuity и metadata ряда пока не прочитаны.
Новый source pack/config/seal/targets/backtest не создавались. Следующий шаг — один
небольшой dated source/definition sample, при работе с PDF читать соответствующий
skill и проверять визуальный контекст. Не строить extraction framework до feasibility.
Если cohort/clock/coverage не позволяют честный короткий screen, отказ без PnL.
Никаких2026market outcomes, broader AlgoPack economic admission, paid/broker/live.

## Исторический статус 17 сентября 07:58 МСК — V111 закрыт; CBR liquidity review

[V111 REJECT_STAGE1](V111_CREDIT_RISK_APPETITE_RESULT.md): CAGR −2.8632%/−2.0091%,
34 trips = 11 episodes + 23 rolls; все 4 execution-complete, но прибыли нет.
41 portfolio / 0 active Stage2/3. EBP rule не перенастраивать, исходный failed
capture manifest сохранён; audit и локальные source/run backups PASS.

Следующий небольшой review — **ликвидность российского банковского сектора**.
Предварительный `rg` по configs/docs/src не нашёл отдельного structural liquidity
family; это не доказательство независимости или alpha. Не превращать провалившуюся
H41 reserve-balance идею в ту же zero-rule с другим названием источника.

Прочитан [FAQ Банка России](https://www.cbr.ru/oper_br/o_dkp/liquidity/):
структурный дефицит/профицит описывает позицию баланса центрального банка и способ
управления денежным рынком, а не сам по себе здоровье экономики/банков или сигнал
покупки акций. Возможные причины включают наличность, бюджетные операции и активы.
Экономический trading mechanism, актив, знак и горизонт **ещё не выбраны**.

Прочитаны примечания [таблицы CBR, bounded query 2025](https://www.cbr.ru/hd_base/bliquidity/?UniDbQuery.From=01.10.2025&UniDbQuery.Posted=True&UniDbQuery.To=30.12.2025):
до November2023 аналитический headline был без учёта корсчетов; далее учитывается
сальдо корсчетов и усредняемых обязательных резервов (УОР). Нельзя склеить эти
headlines как единую неизменную величину. До окончания регулирования УОР прогнозный;
после фактической публикации баланс пересчитывается с начала периода усреднения.
Дата строки — не доказательство первоначального available_at, текущая таблица —
не original vintage. Ряд без корсчетов опубликован отдельно, но его historical
continuity, original availability и revision policy пока не установлены.

Web tool не открыл query 1–3Nov2023 (non-retryable safe-open error), HTTP collector
не запускался. Примечания затем прочитаны из другого уже найденного 2025 query,
не обхода запрета поставщика. Search/find показали отдельные macro cells Oct2025
и 2026: они не используются для выбора сигнала и не являются unseen. Рыночные
prices/returns/labels/targets/PnL2026 не открывались. Полного numeric corpus,
нового config/seal/targets/backtest пока нет; FAQ/таблица не сохранены как source pack.

Следующий bounded шаг: проверить единое определение выбранного ряда, публикацию,
revisions и права для короткого research screen <=2025. Если mechanism или dating
не позволяют содержательный дешёвый тест, короткий отказ без нового framework.
Main AlgoPack отдельно; broader economic scope не расширен, paid/broker/demo/live
не разрешаются этой записью, V107/TIC/FRED-original-report branches не перезапускать.

## Исторический статус 17 сентября 07:29 МСК — V110 закрыт; EBP bounded review

[V110 result](V110_BANK_CREDIT_SQUEEZE_RESULT.md): primary−3.9315%/−4.4744%,
MDD50.16%/51.38%,47trips =5episodes+42rolls; basecontrolINVALID.40portfolio,
0activeStage2/3. Currentvintage clock, not originalPIT. No sign/asset/lag/control
retune. Source attempts retained; originalPDF/HTML andFRED paused. Mainarchive отдельно.

Следующий небольшой review: public **excess bond premium (EBP)** — corporate credit
spread component not attributed to expected default risk. Это новая компонента
market risk appetite, не SLOOS survey или V109 repo quantity. Связь с уже изученным
STLFSI/V27 возможна; независимость/alpha не предполагаются. `rg` по docs/configs/src
до этой записи не нашёл отдельного EBP/Gilchrist/Zakrajsek family.

Прочитана только [официальная note,6Oct2016](https://www.federalreserve.gov/econres/notes/feds-notes/updating-the-recession-risk-and-the-excess-bond-premium-20161006.html):
EBP — исследовательский продукт, не официальный статистический release. Плановое
обновление после10am четвёртого businessday не гарантирует actual availability;
возможны blackout/delay. **Вся история может пересматриваться ежемесячно** из-за
balance-sheet revisions и изменения состава bond panel. В2018 документирована
исправленная публикация с ранее отсутствовавшими месяцами. Это нельзя исправить
произвольным publication lag или назвать original PIT.

Note прямо ссылается на permanent `https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv`.
В этом turn CSV не скачивался/не открывался; нового корпуса, config, направления,
актива или экономического результата нет. Следующий bounded шаг: rights/metadata
одного direct file, даты и схема до числовых значений; проверить, что выбран именно
EBP, не ex-post recession probability/label. 2026 observations исключить до values.
Не брать underlying proprietary corporate securities без отдельного разрешения.
Если full-history estimation/rights/availability не позволяют честный короткий
conditional screen, source refusal; не строить reconstruction framework.
До отдельного freeze никакой экономической проверки или обещания20–50%.

## Исторический статус 17 сентября 06:37 МСК — V109 закрыт; SLOOS bounded review

[V109REJECT_STAGE1](V109_PRIVATE_DELEVERAGING_RESULT.md): CAGR+0.5629%/+0.4379%,
MDD26.49%/26.51%,25trips.39portfolio/0activeStage2/3; цель20–50не достигнута.
Private repo rule не перенастраивать; V107/TIC paused. Main AlgoPack отдельно.

Следующий potential information set — bank lending conditions, не dealer repo
V109, H41 reserves V99 или manufacturingV101. Preliminary rg по docs/configs/src
не нашёл SLOOS/loan-officer/lending-standards family; это не доказательство alpha.
Идея для проверки: кредитные ограничения могут менять доступность оборотного
капитала и инвестиции. Public survey также отражает demand/macro expectations,
а передача к MOEX может отсутствовать. Актив, направление и rule пока не выбраны.

Прочитаны только official HTML overview/feed/research note и два narrative releases:

- [SLOOS overview](https://www.federalreserve.gov/data/sloos.htm) даёт ссылки на
  quarterly releases и дополнительные surveys; индекс имеет2020Septemberextra.
  Survey/month/observation-quarter не original publication timestamp.
- [Announcements](https://www.federalreserve.gov/feeds/sloos.html) документируют
  corrections2015/2017/2019 и historical revisions, а также изменение large-bank
  cutoff50bn→100bn в October2023 (published6Nov2023). Не смешивать размер банка
  с размером заёмщика. Current DDP/FRED series нельзя автоматически назвать PIT.
  Weighted aggregates добавлены4May2020, что не доказывает прежнюю доступность
  их back history. DDP retirement notice не повод покупать доступ или менять scope.
- [January2025](https://www.federalreserve.gov/data/sloos/sloos-202501.htm):
  описывает2024Q4, ответы до3Jan2025, LastUpdate3Feb2025. Net tightening — доля
  tightened минус eased, не уровень кредитной ставки/капитала. Standards и terms
  различаются. LastUpdate пока не подтверждён отдельным original-release evidence.
- [October2025](https://www.federalreserve.gov/data/sloos/sloos-202510.htm):
  описывает2025Q3, ответы до3Oct2025, LastUpdate3Nov2025. Narrative qualitative
  directions этих двух releases уже видены; не объявлять их полностью unseen.
  Числовые Table1/2, Chartdata, PDF/CSV/XML ещё не открывались.
- [Fed research,24May2024](https://www.federalreserve.gov/econres/notes/feds-notes/measuring-bank-credit-supply-shocks-using-the-senior-loan-officer-survey-20240524.html)
  отделяет supply shock от demand/macro/bank factors на bank-level regressions.
  Public net tightening не тот же очищенный CSI; не воспроизводить эту сложную
  microdata модель и не считать retrospective research series доступной раньше.

Следующий небольшой шаг — metadata-only dated-table inventory и rights/date/definition
проверка до полного numeric corpus. Использовать public aggregate, сохранять missing
как missing; нулевые пересмотренные observations не чинить самостоятельно. До любого
economic screen нужны отдельный config/seal, rule, source boundaries и execution
gates. При плохой coverage/невосстановимом dating — короткий source отказ вместо
нового parser framework. ПокаV110/config/targets/outcomes/sourcecapture не созданы.
Никаких purchases, confidential data, broaderAlgoPackscope,2026market или demo/live.

## Исторический статус 17 сентября 06:17 МСК — V109 готов к seal и screen

[V109](V109_PRIVATE_DELEVERAGING.md) выбрал именно nominal-Treasury uncleared
bilateral repo, не broad totals или capital capacity. Twelve bucket paths совпадают
в historical menus2022/2024; olderpre2022 и ill-described чужие totals не используются.
209weekly rows/12cells,207eligible, no missing; magnitudes не прочитаны. Conditional
publication10days, four-report joint borrowing/lending contraction → SIlong/cash.
113synthetictests/15futuresmetadatachecksPASS; source3roots/24files backupverified.
Next seal/commit/push, server tests и один economicrun. Пока38portfolio/0activeStage2/3.

## Исторический статус 17 сентября 05:49 МСК — V108 закрыт, dealer-financing review

[V108REJECT_STAGE1](V108_SUPPLY_CHAIN_PRESSURE_RESULT.md): primaryCAGR−1.5413%/
−1.7797%,15trips, новый Stage2candidateнеполучен.38portfolio/0activeStage2/3.
GSCPIнеперенастраивать, V107нечинить, mainAlgoPackпродолжает отдельно.

Следующий independent information set для bounded review — private dealer funding
и maturity transformation, не central-bank asset/liability proxyV99 и не CFTC
commercial hedgingV106. Potential mechanism: contraction/maturity mismatch of
secured intermediary funding может усиливать dollar funding pressure/risk repricing.
Связь сMOEXне доказана; актив/направление/окно/порог ещё не выбраны.
Repo gross volume не равен капиталу или свободной riskcapacity; broad stress naming
само по себе не новая гипотеза. Первый шаг — definitions и metadata, не новый engine.

Прочитаны только official HTML/API documentation shell и research notes:

- [NYFed primary-dealer statistics](https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics):
  weekly publication Thursdays около16:15 за предыдущую неделю; история сJan1998
  разбита по schemaeras. [API shell](https://markets.newyorkfed.org/static/docs/markets-api.html)
  linkedофициально, rendererневернул endpointdetails; seriesdefinitionsещёнескачаны.
- [FR2004 changes,2022](https://www.federalreserve.gov/econres/notes/feds-notes/insights-from-revised-form-fr2004-into-primary-dealer-securities-financing-and-mbs-activity-20220805.html):
  новый breakdown с5Jan2022 по venue/clearing/maturity. Borrowing/lending могут быть
  matched, netting освобождает balance-sheetcapacity, totalgrossнеизмеряетcapital.
  Поэтому нельзя без mappingсклеить одноимённыеseries илисделатьcapacityизvolume.
- [Repo-runs study,2017](https://www.federalreserve.gov/econres/notes/feds-notes/primary-dealers-behavior-during-the-2007-08-crisis-part-I-repo-runs-20170622.html):
  исследует confidential dealer-level2007–2009, не publicaggregatepredictorMOEX.
  Legal-entity scope не всяholdingcompany; securities-in/out включают разные types,
  их нельзя считать чистымcashrepoбезdefinitions. Использоватьнекакalphaproof.
- [Fails primer](https://www.newyorkfed.org/markets/pridealers_failsprimer.html):
  cumulativeoutstandingfails могут повторятьстарый fail и отражать chains/operational
  issues. Не считать их новыми defaults, netfundingloss илиdirectcapitalcapacity.

Поиск incidental вернул old release2022-01-06/observation2021-12-29 snippet со
значениямиfails; самиPDFнеоткрывались. Эти значения неfeatures и неосноваrulechoice.
Полный числовойcorpus/цены/PnL не читались,V109config/sealне создан. Оригинальные
releasevintages, точныеholidayoverrides, currentdefinitioncontinuity ещё не доказаны.
NYFedterms должны сопровождать любой sourcecapture; не publicredistribution,
confidentialdata, extra paidAPI илиscopeextension. Если publicseriesнепригодны,
короткийsourceотказ вместо reconstructeddealer-capitalframework.

## Исторический статус 17 сентября 05:37 МСК — GSCPI feasibility завершена

[Source note](GSCPI_SOURCE_FEASIBILITY_20260917.md):43eligible vintages/43ready pairs,
four boundedGET COMPLETE, no original-clock proof. Spreadsheet read-only workflow
сохранил raw и исключил protected cells до numeric read. [V108](V108_SUPPLY_CHAIN_PRESSURE.md)
фиксирует supply-constraint→BRlong/cash, не manufacturing-demand retune. 85tests и
15futuresmetadata checksPASS. Next seal/commit/push и один economicrun; source
numeric magnitudes/targets/PnL ещё не просмотрены. V107paused/noV3,archiveотдельно.

## Исторический статус 17 сентября 05:04 МСК — V107 paused; GSCPI metadata review

[V107](V107_CURRENT_ACCOUNT_SOURCE_PAUSED.md) дважды остановился на source parsing,
экономики нет. Не писать V3 и не обходить pause ручными строками. 37 portfolio /
0 active Stage2/3. TIPS real yield и inflation compensation уже закрыты V78;
поиск нового названия или ещё одного sign/window по ним не новый information set.

Поиск GSCPI / supply-chain-pressure по configs/docs/src до этой записи не нашёл
отдельного economic test. Возможная новая информация — ограничения поставок и
транспортировки, не G.17 manufacturing demand V101. Направление эффекта на MOEX
пока не выбрано: снижение input costs и изменение commodity-export revenues могут
действовать противоположно. Новый механизм не означает доказанную доходность.

[NY Fed launch, 18May2022](https://www.newyorkfed.org/newsevents/news/research/2022/20220518)
указывает первый public introduction January2022, регулярную публикацию с May2022
и время 10:00 ET в четвёртый business day месяца. История с 1997 ретроспективная,
не доступный тогда сигнал. Actual publication dates всё равно нужно подтвердить.
[Методология и revisions](https://libertystreeteconomics.newyorkfed.org/2022/03/global-supply-chain-pressure-index-march-2022-update/)
описывают demand adjustment, PCA/imputation и изменения прошлых оценок вплоть до
года назад. По current revised series нельзя восстановить original information set.

Прочитаны HTML, official frontend JS и descriptive JSON; CSV/XLSX не открывались.
Текущие macro snippets из поиска не используются как features, market outcomes не
читались. [Product page](https://www.newyorkfed.org/research/policy/gscpi) загружает
`/medialibrary/Research/Interactives/gscpi/js/main-es2015.js` (1409838 bytes).
В JS явно есть `revisions`, revision month labels и download routes:

- `/medialibrary/research/interactives/data/gscpi/gscpi_interactive_data.csv`
- `/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx`
- `/medialibrary/research/interactives/data/gscpi/gscpi.json` — descriptive metadata,
  10134 bytes, FAQ повторяет revision/PCA limitations.

JS observation не доказывает полноту historical vintage matrix или original clock.
Следующий маленький шаг — header/calendar-only inventory CSV и точный смысл колонок,
не чтение signal values или full economic preparation. Сохранить один bounded raw
только при допустимом scope/rights, hash/receipt и metadata; исключать release>=2026
до числового feature read. Если хранится лишь короткий current revision tail,
отклонить source для этого screen без собственного reconstructed-PCA framework.

[Terms](https://www.newyorkfed.org/privacy/termsofuse) разрешают personal/business
use с attribution и сохранением identifiers, но отдельно ограничивают third-party
content и публичные serial blog archives. Это не разрешение скачивать исходные
лицензируемые BDI/Harpex/PMI feeds. Для derived GSCPI дополнительно проверить
source-specific notices до corpus. Никаких purchases, писем или публичного архива.
CSV/XLSX metadata review требует соответствующего spreadsheet skill; в этом review
были только HTML/JS/JSON, skill лишь inspected, spreadsheet action ещё не было.

Пока V108/config/rule/targets/outcomes отсутствуют. Broad AlgoPack scope unanswered,
TIC/V107 paused, 2026 protected; основная загрузка продолжается отдельно.

## Предыдущий статус 17 сентября 04:16 МСК

Исторический статус 17 сентября 04:16 МСК:
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
