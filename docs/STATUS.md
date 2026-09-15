# Текущее состояние исследования

Обновлено: **2026-09-15**. Период разработки ограничен данными не позже
`2025-12-31`; данные 2026 для текущих V8–V38 гипотез защищены и не используются.

## V91 — metadata mapper готов; новый static sample check ещё не выполнен

[Протокол](V91_OPTION_CONTRACT_MAPPING.md): exact NAME + SERIES_NAME + dated futures
catalog, независимое согласование UNDERLYINGASSET, explicit expiry/strike definition
и exercise-to-future price equality. SI currency options исключаются, premium UNIT
не превращается в guessed strike multiplier. 59 новых / 126 combined local tests
PASS, Ruff clean. Это код для подготовки V90, не новый economic screen.
Четыре старых catalog независимо сверены с raw: 228 alias rows / 220 futures,
12 files / 255660 bytes, evidence SHA ca7fb707635608c186685f8463977e64df36f3014826e90df5102bb9d0a5505e.
Следом скопировать только этот tiny static subset на server, сверить code seal,
один новый binding check восьми saved V88 descriptions. Никаких повторных HTTP.
Полный V89 mapping ждёт terminal manifest; частичный BR prefix не economic universe.
OI magnitudes/market values/PnL для новой гипотезы не читались, Stage2=0, goal false.

Actual 16:08:58UTC все три download units active/running, прежние PID/invocations.
Main: 2872/26305 jobs, 34009646 rows, failed0/blocked0, 2013287133 stored bytes
completed jobs. FUTOI: 531/2192 days, 6637165 logical rows / 4340228 new-root rows,
237 unresolved ticker-days / 31 gap days, 85853057 new-root stored bytes.
V89: 5896/40820 exact descriptions, unavailable0, 23397538 raw bytes.
Final manifests отсутствуют. Services/token/Windows не менялись.
Новый du16:08:59UTC: data5000705958 + source_evidence197321491 =5198027449 bytes
(5.198GB), включая AlgoPack2280167368 + oldprocessed1456918554 =3737085922 (3.737GB).
Allocated total6048841728 (6.049GB); models/runs/tmp excluded, sequential snapshot.
Local2.720GB ниже — snapshot15:09:20UTC, не unique прибавка к server и не новый замер.

## V90 — правило/контроль и ledger bridge реализованы, пока synthetic-only

[Adapter/protocol status](V90_OPTION_STRIKE_CONVERGENCE_ADAPTER.md): новый reported-OI
pre-expiry convergence — основной вариант кбольшему OI двух соседнихстрайков,
контроль кближайшемустрайку.42новых synthetic tests и95total targeted local PASS,
Ruffclean; server3-file hashcheck и42/42synthetictestsPASS(2.64s).
Integration действительно выполняет2arms×2costs на старомintegerledger:
flat syntheticprice даёттолькорасходы, doubleхуже, terminalflat/no critical/unresolved.
Никаких реальных OI magnitudes/prices/targets/PnL дляV90нечиталось.
Config25b5d6266b9c968bb7adacf4261b5af0333d379cdb7f7b4853aeaa7e8e6f3429;
adapter31788d6a8c00f6bf1bd7e205c0cc1f7adb7fcb449bc894588a467bd79140cf74.
Это design snapshot, `economic_runner_enabled=false`, не full economic/input seal.
Нужен source-bound metadata mapper, не ручноеTrueдляготовности/совместимостиunits.
ПослеV89closure: одинmapping/coveragepass, полнаяфиксацияinput/code/gates, одинrun.
Покаwriterработает — следомподготовитьexactmetadatajoin наsyntheticdescriptions и
проверенныхдоговорныхидентификаторах; не читатьпервыеBRoutcomesилистроитьновыйledger.

Actual15:39:01UTC все3unitsrunning с прежнимиPID/invocations. V89PID3208549:
2908/40820exact descriptions,unavailable0,11048391rawbytes,finalmanifestabsent.
MainAlgoPackPID1663880:2678/26305jobs,32155488rows,33988pages,failed0/blocked0,
1906051342storedbytescompletedjobs. FUTOIV4PID2522946:479/2192days,6160127logicalrows,
3863190new-rootrows,222unresolvedticker-days/28gapdays,76786105storedbytes.
ОбаAlgoPackfinalmanifestsabsent,services/token/Windowsнеизменны. Новогополногоduнет:
4.902GBserverdata/source и2.720GBlocal ниже — snapshots15:08/15:09, не currentdedupsum.
Economic funnel остаётся25screens/0Stage2; цель20–50%неподтверждена.

## V89 — census COMPLETE, 40820 descriptions загружаются; server data/source 4.90GB

[Checkpoint](V89_OPTION_METADATA_SOURCE_STATUS.md): census завершён15:07:09UTC,
1327744rows/108104SECIDs,211024non-NULL OI rows; величины OI не читались.
40820нужных descriptions,67284all-NULL SECIDs сохранены в coverage.
Census manifest `e990fdc9d091d7a0abab7d3f3c329e14053e3771b96d934d2ccd4b171dfd26d1`.
Source unit `trading-lab-v89-option-metadata-1c71ebb0df2a.service` actual15:12:20UTC
active/running, PID3208549, invocation8a874553a92f4860bc235656c6e4e9b0.
297/40820exact descriptions, errors0,1118174new rawbytes; final manifest отсутствует.
No credentials/EnvironmentFile, restart=no; canonical/partial roots не перезапускать.
Pre-census commitcc4d737,25local/25server testsPASS;expandedlocal44PASS,Ruffclean,closure verified.
Первые5новых raw hash/length/HTTP/identity проверены, не full acquisition audit.
V89 не economic screen: no new OI magnitudes/market values/PnL,0 новых Stage2.

Actual15:08UTC оба AlgoPack units running, PID1663880/2522946: main2492/26305jobs,
30.197mrows,failed0/blocked0;FUTOI429/2192days,5.656mrows,222unresolvedticker-days,
28gapdays. Новые bytes: archive2.034GB + oldprocessedAlgoPack1.457GB =3.491GB.
Весь server data/source4.902GB (allocated5.657GB), уже включаяAlgoPack, безmodels/runs/tmp.
Local15:09:20UTC2.720GB/10841files отдельно; не складыватькопии какuniquehistory.
Всеroots/counters в checkpoint. Сервисы AlgoPack, токены и Windows не менялись.
Следом [reported-OI pre-expiry convergence](OPTION_PINNING_RESEARCH_NOTE_20260915.md):
малый synthetic adapter кготовомуdailyledger покаwriterработает; послеsourceclosure
одинmapping/coveragecheck и новыйeconomicseal. Не путатьdailyproxy с intraday expiry
и не выдавать ближайшийстрайк/общийOI за доказанныйdealerflow. Цельнеподтверждена.

### V89 pre-census checkpoint (preserved)

[Протокол](V89_OPTION_METADATA_SOURCE.md): из истории 2021–2025 читаются только
идентификаторы и NULL-маска OI, без его величин и рыночных цен. Все 108104 контракта
остаются в inventory; запросы описаний нужны каждому SECID с хотя бы одним non-NULL OI.
Восемь имеющихся V88 raw responses переиспользуются ссылками, без повторного HTTP.
Это подготовка нового expiry-pinning теста, не экономический результат или Stage2.
25 локальных synthetic/parent tests PASS, Ruff clean. Пять файлов и parent closure
зафиксированы до census/HTTP; seal
`1c71ebb0df2a69ce45b9dcf5ae00400fbf228f7a7feec9d26e68923b4ea19f5d`.
Pending server roots: `/srv/trading_lab_data/source_evidence/v89_option_metadata_census_v1`
и `/srv/trading_lab_data/source_evidence/v89_option_metadata_source_v1`.
Сначала один census, затем один public ISS writer с точным census SHA, без credentials.
Основные AlgoPack services не меняются. Число нужных описаний пока не измерено.
OI magnitudes, новые prices/returns/PnL не читались; economic/live/goal admission false.

## V88 — exact expiry доступен, смешанные SI contracts выявлены; PnL ещё не считался

[Результат](V88_OPTION_METADATA_PROBE_RESULT.md):10/10requests,HTTP200attempt1,
30885rawbytes;8exactSECIDdescriptions содержатLSTDELDATEсtitle«Датаэкспирации».
Но SI source смешивает marginedfutureoptions и premiumcurrencyoptions сразнымиunits/
lots;UNDERLYINGASSETуобоихUSD000UTSTOM,неexactfuture.6другихexamplesсодержатfuturescodes,
полногоjoinкнашемуcanonicalmarketещёнет. Calendar2021-01-08empty;2025-01-03однаNGexpiry,
неcompleteactiveoptionslist и неновыйnumericOPTION_SERIES_IDmapping.
Не заменятьmissingэкспирациитретьимчетвергом/activefuture и не повторятьV39/V68.
Source completed14:38:58.200513UTC,terminalPID0/exit0 observed14:39:59UTC.
Manifest10ff109b609658ebd0ff4ae4bb7e8f0f17e0d1b5a1afe521ea113699e25d9d7f;
canonical /srv/trading_lab_data/source_evidence/v88_option_metadata_probe_v1;
pre-request95f4354,seal c1529e0e6191f4290df97afc07f6baa01ede557126d1d1c3208d87e837525a50.
32local/15server testsPASS,Ruffclean;10raw/parser/record/clock +8identity/datechecksPASS
14:45:19UTC. Не rerunилиновыйколлектордлятехже8examples.
Следом:отдельныйmetadatajoinprotocol, оценкаNULL-maskнужныхOI-contracts безвеличин,
explicitexpiry/type/unit/underlyingcoverage, затемновыйfixedpinningeconomicseal.
V88неeconomic screen;воронка25=21rejected+1incomplete+3invalid,0Stage2;goalnotverified.
BothAlgoPackunitsactualrunning14:45UTC,PID1663880/2522946,unchanged;новогозамераbytesнет.

### V88 pre-request checkpoint (preserved)

[Протокол](V88_OPTION_METADATA_PROBE.md):8точныхexpiredSECID descriptions +2dated
calendar probes, толькоstaticmetadata. Проверка ранее отложенногоexpiry-pinning,
неeconomicrun и неV68retune. Source-date/schema/hash preflight подтвердил1327744rows,
108104uniqueoptions2021–2025; нетновыхOI/pricevalues. Нужныточныеexpiry/underlying/units.
32targetedtestsPASS,Ruffclean.7-file seal
c1529e0e6191f4290df97afc07f6baa01ede557126d1d1c3208d87e837525a50.
Pending serverroot /srv/trading_lab_data/source_evidence/v88_option_metadata_probe_v1.
До actualresponse не считатьcalendar entitlement/mapping доступным. Archive units
не меняются; no economic/Stage2 increment, goalnotverified.

## V87 — слабый GOLD positioning результат; архивы работают, общий server data/source4.67GB

[Результат](V87_GOLD_POSITIONING_RISK_RESULT.md): primarybase CAGR1.1282%,Sharpe0.1517,
MDD44.1600%;double0.9010%/0.1356/44.8684% с1criticalgrossrejection. Controlbase/double
CAGR−2.5197%/−2.5240%. Все4сценария сохранены;5/7positiveyears primary,161closed
asset episodes;0terminal/unresolved, но double execution incomplete. Wholebatch
INVALID_EXECUTION_NO_PROMOTION, не Stage2. Не менять размер/знак/lag/период ради rerun.
3542asset decisions/1771dates perarm,3324nonzero targets,348used releases,
feature/datecoverage94.3535%,364ready source dates;418GOLDreports,27timing overrides.
125localtargeted и отдельные65tests(overlap31),31servertestsPASS,Ruffclean;
21artifact/source/state/target +4metric/year/count/cash replaysPASS;
independent418clock/readiness/405Fractionchange checksPASS. Pre-outcome165e823.
Seal d1046052fd5e9de1451e7eaf5e209873e692ff9f032c7cc83b19522abb96d278;
metrics3d38bc7706bfb554586495040311169ba8d911266e9ee44b6a23941fe89f3c0b.
Canonical /srv/trading_lab_data/runs/v87_gold_positioning_risk_v1_d1046052fd5e;
terminalPID0/exit0 observed14:15:56UTC, independentauditcomplete14:17:10UTC.
25screensV65–V87=21rejected+1incomplete+3invalid,0Stage2; goal20–50%notverified.

Actual14:18UTC: new `data/algopack-archive`1808645667bytes≈1.81GB,allocated2.28GB.
Старая canonical AlgoPackcore4history отдельно1418832691bytes≈1.42GB; весь старый
`data/processed/algopack` сinventory/samples1.457GB на14:19. Два основных исторических
AlgoPack каталога вместе≈3.27GB. Исправление старой подписи: прежние1.67GBне включали
полнуюcore4history; НЕ прибавлять её кобщемуserverdata второйраз.
Serverdata4520667040 + source_evidence150734614 =4671401654bytes≈4.67GB,
allocated5.35GB; models/runs/tmp excluded. Local14:18snapshot10841files/2.72GB;
server/local не складыватькакuniquecorpus. Bothdownloadunitsactualactive/running,
PID1663880/2522946: main2171/26305jobs/26.694mrows,failed0/blocked0;
FUTOI344/2192days/4.830mrows,173unresolvedticker-days/21gapdays. Finalmanifestsнет.
Services/tokens/Windows не менялись, broadAlgoPackeconomic scope покаunanswered.

### V87 pre-outcome checkpoint (preserved)

[Протокол](V87_GOLD_POSITIONING_RISK.md): новый GOLD managed-money quarterly impulse
→ SI/MIX risk-demand basket, constant risk-off control, 2018warmup/2019–2025evaluation,
2costs, старый daily ledger. Никаких новых collectors, WTI numeric values или2026outcomes.
Source4hash/date/schema checks подтвердили418GOLD/418WTIreports2018–2025.
Новый adapter учитывает2018/19,2023,2025publication delays и GOLD2019-03-26correction
до2019-04-03EOD; старый uniform7day clock не является полным causal доказательством.
125targeted synthetic/parent tests PASS, Ruff clean. Отдельный12-file economic seal
d1046052fd5e9de1451e7eaf5e209873e692ff9f032c7cc83b19522abb96d278.
Canonical pending /srv/trading_lab_data/runs/v87_gold_positioning_risk_v1_d1046052fd5e.
Economic values/PnL ещё не читались, source revision chain notproved, goalfalse.
AlgoPack services неизменны; последний замер и actual runtime ниже вV86.

## V86 — STEO revisions INVALID_EXECUTION_NO_PROMOTION; архивы RUNNING

[Результат](V86_STEO_REVISIONS_RESULT.md): один2arms×2costs screen2018–2025,
primary CAGR−8,7839%/−9,2147%,Sharpe−0,1300/−0,1434,MDD81,1423%/82,4525%,
151closed episodes,4/8positiveyears. GrossVM тожеnegative. Primarybase execution
complete, но primarydouble/controlbase/controldouble имеют2/2/1criticalgrossrejects:
весь batchINVALID, не валидированная stressed прибыль. Не уменьшать размер/менятьзнак.
2024decisions/1980nonzero targets perarm,97,9249%featurecoverage,94ready releases;
October2022unknownnotice + dependentNovember masked, не исправлять ради rerun.
20hash/source-state-target +4metric/year/count/cash replaysPASS; independent97raw/
94revision/1245scalar/117duplicate checksPASS.86targeted+separate44tests (overlap)PASS.
Seal a8e5c82fdf2afd95c7bfb4dbccf43128b98e1c29e1a6891cca339d73b94c561e,
pre-outcome10f607a; metrics565e4bb0540db2f0d1ec528365ffc5f9ba3c9a2ea9ebb47bfe06c595e7ae53f9.
Canonical /srv/trading_lab_data/runs/v86_steo_revisions_v1_a8e5c82fdf2a, terminalPID0/exit0.
24screensV65–V86=21rejected+1incomplete+2invalid,0Stage2;goal20–50%notverified.

Actual13:47UTC AlgoPack1670849835apparent bytes/2094641152allocated bytes (~1,67/2,09GB).
Serverdata4380590905 + source_evidence150734614 =4531325519bytes (~4,53GB), inclarchive,
exclmodels/runs/tmp. Local last12:41snapshot2,72GB; не суммироватькакuniquecorpus.
BothdownloadsactualrunningPID1663880/2522946; main1963/26305jobs,24634122rows,
failed0/blocked0;FUTOI294/2192days,4261365rows,68unresolvedticker-days/6gapdays.
No final manifests; no restart/settings changes. Broader AlgoPack economic scope
unanswered; next research needs independent mechanism/information, not V86retune.

### V86 pre-outcome checkpoint (preserved)

[Economic protocol](V86_STEO_ECONOMIC_V1.md): same-next-quarter consumption-production
revision -> BR0.9,constantlong control,2018–2025,base/double fees,old daily ledger.
97source editions/89737568rawbytes/18notices; V4complete13:37:47.836166UTC,80raw reused.
Manifest0ec267b1fb866d3bee1148d3a5792813ffe31222b262e49846eae317922a8306;
V4source seal28a5dfb5f3fb75f55a73fc660148b58d309ae676d62a8c8dc2b23178c2666417.
Source root/safe references /srv/trading_lab_data/source_evidence/v86_steo_vintages_v4
и v3, оба сохранять. V1permission/V2malformedHTML/V3duplicate-code failures сохранены.
V4terminal PID0/exit0,14server testsPASS;86local source/economic/parent testsPASS.
Новые numeric forecast values/MOEX outcomes/PnL ещё не читались. Economic seal готовится;
правило/80editions+90%coverage gates зафиксированы до source values,originalPITfalse.
AlgoPack units не изменены; goal20–50%notverified. Не повторять source acquisition.

### Earlier V86 preparation checkpoint

[Протокол](V86_STEO_FORECAST_REVISIONS.md): BR по изменению forecast world demand-supply
для одного и того же next-calendar-quarter, а не V17 weekly actual changes.
97editions2017December–2025December, public EIA Excel archives, только3atab physical
series papr_world/patc_world. Source config/code подготовлены;8synthetic tests PASS.
Economic numeric values/outcomes ещё не читались. Original revision chain не считать
доказанной: notice/core modified clocks учитываются до отдельного economic seal.
Server acquisition/runtime/source manifest/economic config пока не созданы.
AlgoPack units не меняются; V85 broader economic scope остаётся unanswered.
Goal20–50%notverified; source feasibility не новый economic screen.

## V85 — EQOrderStats/HI2 source feasibility завершена, новый economic scope не подтверждён

[V85](V85_EQ_FLOW_FEASIBILITY.md): только metadata/keys/clocks, без numeric features/
prices/returns/fit/PnL. На12:50:15UTC EQOrderStats4269594rows/105nonempty days,
EQHI2135333rows/104days,EQTradeStats2587250rows/105days;2024только pilot15October,
остальное поздний2025. Ни один многолетний economic вывод из этого не следует.
Фиксированный30December:OrderStats49pages/48208rows/253tickers,HI22pages/1694rows/
154tickers;51raw/hash/date/key checks PASS,duplicates0. HI2time18:40daily, нельзя
использовать для того же утра. Same-day SYSTIME не доказывает original versions/timezone.
Три новых механизма-кандидата описаны, но не sealed/tested: отмены, replenishment,
prior-day concentration. Нет новогоengine/HTTP/data transfer/fit. Старое разрешение
было на один V79contest; один async вопрос о всех следующих preliminary AlgoPack
contests отправлен, ответа пока нет. Не подменять вопрос автоматическим продолжением,
не спрашивать его заново каждый turn и не запускать PnL до подтверждения scope.
Both archive units actualactive/running12:50UTC,PID1663880/2522946; unchanged.
Goal20–50%active/notverified;V85source feasibility не новый economic screen.

## V84 — SBER component ниже20%/cash, GAZP entry unresolved; архивы RUNNING

[Результат](V84_STOCK_PERPETUAL_BASIS_RESULT.md): выполнен один раз12:36:27.672148UTC.
SBER basis−44RUB; измеримый funding+basis-cost component APR base17,3176%/double17,1204%,
ниже cash-rate comparator21,7491%simple annual normalization. Это НЕ full pair PnL.
GAZPF2024-10-01 нет15:50entry candle;15:40decision есть. Другой бар не подставлять:
GAZP component=null,UNRESOLVED_ENDPOINT. Actual decisions/trades/fills0,proxy legs4/4и3/4;
full PnL/CAGR/Sharpe/MDD/annualreturns=null,5unknown pair groups each. Stage2/goal=false.
Cash comparator не investable income и не credit на margin. Pre-outcome push6357128;
server11V84tests PASS, independent11+16source/Decimal checks PASS. Вспомогательное
точное Decimal-vs-float equality исправлено на1e-12; maxdelta3e-17, canonical не менялся.
Metrics2cecd7147aafaa601f271a79cf14d1a0d65122f7f2fe8fde8c6c00745f65de5f.
Не повторять V84/подбирать другое время GAZP/уменьшать капитал. Следующая работа —
другой information set и дешёвый конкурс, не полный engine без показанного запаса.

[Протокол](V84_STOCK_PERPETUAL_BASIS.md): оба SBER/GAZP, fixed15:50next-bar endpoints
2024-10-01/2025-12-30, reserve30%, stock10/futures5bps per side и2xcosts.
Funding window entry-inclusive/exit-exclusive отличается от V81. Считается только
измеримый funding+basis-cost компонент и residual до20%APR/lagged RUONIA comparator;
пять unknown liability/execution groups не заполняются нулём, full pair PnL=null.
13-file seal5891f243865384d6d0436551e2da09af16c880b0af1fff69c7ec63314434c921.
Local75targeted tests PASS, после pre-seal empty-source уточнения11V84PASS; Ruff clean.
Canonical /srv/trading_lab_data/runs/v84_stock_perpetual_basis_v1;4public candle responses,
322rows/28825raw bytes, all200/attempt1. TerminalunitPID0/exit0 подтверждён12:37:17UTC.
Полный paired test этим коротким компонентным follow-up не объявляется выполненным.

По запросу пользователя объём файлов измерен отдельно от счётчиков загрузчика:
2026-09-15T12:41:05UTC AlgoPack archive apparent1375471252bytes (1,375GB),
allocated1706717184bytes (1,707GB), включая старый core4 78726995bytes.
Server market-data root4080174365bytes (4,080GB), включая этот архив.
Local D:/Projects/trading_lab_data/data:10841files/2719842747bytes (2,72GB),
reparse directories0. Server+local не складывать как уникальный corpus: дубли не
исключены. Models/runs/tmp не включены в market data. Actual units на12:41 running:
основнойPID1663880,1583jobs/20095301rows/21175pages,failed0/blocked0;
FUTOIPID2522946,185processed days/3073888logicalrows,9671resolved/47unresolved
ticker-days,3days_with_gaps. Оба final manifests отсутствуют. Архивные references не
посчитаны как новые bytes. Старый снимок12:09:1,228GBarchive/3,93GBserver сохранён
в pre-outcome commit6357128; рост загрузки фактический, downloader не менялся.

## V83 — обеспечение пока unresolved; FUTOI V4 RUNNING с явными source gaps

[V83](V83_STOCK_COLLATERAL_FEASIBILITY.md): mechanism exists, terms unresolved.
Пять исторических PDF БКС сохранены вне Git, SHA/релевантные страницы проверены.
Условия льготного РЕПО различаются в241001/250609; одинаковые цены двух частей
не доказывают нулевую комиссию. «Овернайт ГО» не освобождает обеспечение и не
подтверждает начисление RUONIA. Новых prices/dividends/rate series/PnL нет,
reserve30% и результаты V81/V82 не изменены. Брокерский вопрос пока unanswered.
Все экономические counts/Stage2 без изменений; цель20–50% не достигнута.

Actual checkpoint11:59:43.059880UTC: основной14-family unit active/running,
PID1663880,1348/26305jobs,17154756rows,18067pages,failed0/blocked0;
1024787666bytes completedjobs. [FUTOI V4 RUNNING](ALGOPACK_FUTOI_ARCHIVE_V4_RESULT.md),
unit trading-lab-algopack-futoi-archive-v4-f47d4cd22039.service,PID2522946,
invocation2e561d202042490d81ddc8aefa3cd543,start11:55:54.375041UTC.
131/2192processed days,7507ticker-days,7478matched/29unresolved,2328426intraday rows,
31489new-root rows,7524V2/V3pages reference-reused;651209new-root bytes completeddays.
Current2025-08-24,22/47tickers. Оба final manifest отсутствуют, free898792579072bytes.
processed days НЕ full coverage; новый terminal при gaps будет COMPLETE_WITH_SOURCE_GAPS.

V3 terminal failed/PID0/exit1 сохранён, не restart. Уточнение initial diagnosis:
status.current_ticker=AU означал последний УСПЕШНЫЙ тикер; следующий BM дал пустой
ответ2025-08-26. В pre-request V4protocol AU ошибочно назван причиной; отдельный
result содержит erratum, frozen bytes не менялись. Проблемный день теперь сохранён:
59pages/58ticker-days,47matched/11empty gaps,16312rows; independent59/59raw/hash/date/
final-point/coverage checks PASS. Day SHA00ae45dfb486cdd1dba9180afda02f5054cab2304dcc3e6ca8aad08feb91e44b.
Local93/server93tests PASS,Ruff clean; pre-request push1b44b19,
seal f47d4cd22039c56c5647a36087b4ee37fac96db8df62b87b6366d9a9ac7e947e.
V4+referencedV3+V2 сохранять вместе; core4 тоже не удалять. Windows mirror ещё нет.

## V82 — funding component на капитал с резервом ниже20%, full pair пока unresolved

[Результат](V82_STOCK_PERPETUAL_CAPITAL_RESULT.md), [протокол](V82_STOCK_PERPETUAL_CAPITAL.md):
оба SBERF/GAZPF, только уже известные V81
aggregates, reserve30% и stock10/futures5bps per side из прежнего stock-pair config,
base/double30/60bps. Это post-selection capital-capacity diagnostic, не full pair.
Один расчёт завершён11:12:44.357751UTC: funding-less-fee APR на капитал
base17,3890%/19,0247%,double17,2037%/18,8395%. Оба
FUNDING_ALONE_BELOW_TARGET_PAIR_UNRESOLVED, не full economic rejection пары.
Для20%APR только за счёт дохода30%-го резерва потребовалось бы double12,1172%/5,0289%
годовых самого резерва; это условие, НЕ credited cash или брокерская доступность.
Не уменьшать reserve/costs и не выбирать тикер по результату.
Local64tests(43new+21V81)/server43PASS,Ruff clean;46independent Decimal checks PASS.
Pre-derived-result1c9d9d9, nine-file seal
874998a9cce6f9c00ef544218d4622027bb03832dd19d5cab31e436231063bce.
Canonical /srv/trading_lab_data/runs/v82_stock_perpetual_capital_v1;
metrics8dafcb552bab1899fdc903f03d03c2b636e3dc97db80b469f16eb2807e87c46c.
Не повторять расчёт/replay. Source320sessions/319payments на тикер,455calendar days,
coverage100%,unknown funding0;decisions/fills0,семь unresolved pair-input groups каждый.
Полные portfolioPnL/CAGR/Sharpe/MDD/benchmark остаютсяnull; не заменять ими component APR.

Исторические DOC спецификации сохранены: MOEX26831 revision periods покрывают весь
2024-10…2025. Оригинальная ссылка26107 теперь возвращает HTML другого документа,
не PDF. Correct VM: short получает funding, но платит gross dividend adjustment;
gross stock dividends не второй источник прибыли. Record date nontrading -> previous
trading date, dividend revisions могут менять VM, forced conversion возможна.
Text/formulas extracted antiword; native Word page rendering unavailable. Exact3DOC
SHA/paths в config; текущие2026conversion fees не переносить на2024–2025.
Spot timestamp schema UTC index проверена без prices. CBR server file/schema/SHA есть,
rate values не читались. Новых price/dividend outcomes, transfer stock universe нет.
Optional broker/account question unanswered: нужен для actual collateral/fee доступности,
но это не blocker всех MOEX исследований. Crypto scope question также unanswered.
На11:14:18.760792UTC оба AlgoPack units actual active/running; PID1663880/1913099,
без restart. 14families1106/26305jobs,14000122rows/14747pages,837551970bytes completedjobs,
failed0/blocked0. FUTOI V3127/2192days,7275ticker-days/2259693rows,2221083new-root rows,
120V2pages reused,45895100new-root bytes; current2025-08-28,44/58tickers. Оба final
manifests отсутствуют; free899059843072bytes. Windows mirror новых архивов пока нет.

## V81 — два funding components прошли быстрый фильтр; требуется полный paired test

[Результат](V81_STOCK_PERPETUAL_FUNDING_RESULT.md), [протокол](V81_STOCK_PERPETUAL_FUNDING.md).
SBERF/GAZPF:320sessions/319payments каждый,2024-10-01…2025-12-30,455calendar days.
Все319учтённых выплат положительны;15/15positive months. Funding-credit7594,653/4196,656руб.
на100share nominal26685/13490руб. Simple APR22,8465%/24,9730%; после illustrative
double40bps hurdle22,5254%/24,6519%. Это нормировка ТОЛЬКО funding относительно начального
номинала, НЕ portfolio CAGR/PnL/доход на весь капитал. Margin cash, basis MTM, dividend
adjustment/actual dividends/tax и реальное исполнение пока не учтены. Decisions/fills0,
CAGR/Sharpe/MDD/portfolioPnL=null. Оба FUNDING_COMPONENT_CANDIDATE, но НЕ Stage2/live.
Пропусков320proxy sessions/payments0. Local49/server21tests PASS,Ruff clean;
8raw pages/640rows+2cashflow/unit/calendar/month/year replays PASS, no HTTP rerun.
Pre-value90b4db8, seal a9e4299e3a8846d6dba8d19588af18baaf63b7b2818e107e13b59b587e5ac89a;
canonical /srv/trading_lab_data/source_evidence/v81_stock_perpetual_funding_v1;
metrics6b90b9fb66a4b146156c28ed31ead1a7b6ff78cfd1d779ce12211f612fe68874.
Завершён10:31:41UTC, не повторять/не менять знак/тикеры/период/fee hurdle.

Следующий V82 обязан проверить ОБА полных hedged sleeves по отдельному seal до новых
price inputs. History metadata-only probe200/803bytes/0rows:OPEN/CLOSE/SETTLEPRICE/
SWAPRATE есть, dividend-adjustment field отсутствует. Нужен подтверждённый source для
поправки и фактических дивидендов; RMS projections не shareholder payments.
Exact existing SBER/GAZP stocks_10m_pre2026_v1 files и manifest пока отсутствуют на server;
references/hashes в configs/moex_stock_futures_cash_carry_source_v2.yaml. Локальные bytes/
SHA повторно совпали: SBER4776211/GAZP4714157/manifest15515bytes, цены не читались.
Это не external blocker: сверить timestamp/execution requirements и перенести только
нужную subset, если пригодна. Переноса ещё нет; не копировать весь universe.
Сравнить с cash benchmark за те же даты и доходностью всего капитала, не только номинала.
23V65–V80economic screens/0Stage2 остаются; V81 отдельно2funding-component tests,
0paired portfolio backtests. Цель20–50% НЕ достигнута.
Optional crypto scope question unanswered: crypto prices/data/PnL не запрашивались,
это не блокирует MOEX работу. Оба AlgoPack units в начале turn actual active/running,
PID1663880/1913099; не restart, counts в dated archive checkpoints.

## Последний screen — V80 GPR: REJECT_STAGE1; AlgoPack архивы RUNNING

[Результат](V80_GPR_RISK_RESULT.md), [протокол](V80_GPR_RISK.md): один Russia-news
risk-persistence signal, последний полный месяц против предыдущих12, joint BR/MIX/SI,
constant-stress control. Все2022–2025, unavailable начало сохранено, без fit/retune.
Price-free feasibility95,669291%,3048asset decisions/1016dates на arm,46ready releases;
132feature-unavailable/132stale overlapping flags,17source-unavailable,2901nonzero targets.
Один4arm/cost batch2,624094s: CAGR1×/2× −4,5783%/−4,7481%,Sharpe−0,4076/−0,4252,
MDD24,1416%/24,6752%,99/98closed asset episodes,1/4positive years;net−170512/−176386руб.
Control CAGR−6,6661%/−6,7348%; проигрыш меньший, но прибыли нет. Primary gross VM тоже
negative до10999/21521руб.costs. Все4execution complete,critical/unresolved0,terminalflat,
по1no-liquidity cancellation. Отсев по CAGR/Sharpe/годам;2× excess<2pp тоже не прошёл.
Local113/server113tests PASS,Ruff clean;19hash/rawDTA-commit-state-target/4metric-annual-
count-cash replays PASS. Pre-outcome6299f8b, economic seal
93b011ce775e9ea3af36674a2a143084e3f0616f68107e9d19ea06835d70d489;
canonical /srv/trading_lab_data/runs/v80_gpr_risk_v1_93b011ce775e;
metrics7fe5d6c09f252ee779601ecd2970bb6e0f308d6507e6272d820a5535c980e391.
V65–V80:23economic screens=21rejected+1incomplete+1invalid,0Stage2. Цель20–50% не достигнута.
Не повторять/переворачивать/настраивать этот GPR signal и не спасать его большой моделью.

[GPR source V2](V80_GPR_VINTAGES_SOURCE_V2.md) COMPLETE:46versions202203…202512,
34298157raw bytes,562undated records сохранены;46raw/hash/commit/calendar replays PASS.
Final manifest ed716b9021067ec24be87e7a6b3707c82a12d9b93e567cbc14b415942c6c6338;
root /srv/trading_lab_data/source_evidence/v80_gpr_vintages_2022_2025_v2.
Source full unit trading-lab-v80-gpr-source-full-v2-c9231bee65bf.service завершён0exit,
pre-sourceb2756e8. Oldest Git content, не сегодняшний overwritten edition; commit clock
только proxy, не witnessed public push. V1 undated-row failure/root сохранён, не restart.

На2026-09-15T10:01:30.915889UTC оба AlgoPack service actual active/running:
[14families](ALGOPACK_ARCHIVE_V1_STATUS.md) PID1663880,688/26305completed jobs,
9002346rows/9450pages,538526594bytes,failed0/blocked0;
[FUTOI V3](ALGOPACK_FUTOI_ARCHIVE_STATUS.md) PID1913099,60/2192complete days,
3452ticker-days/1080054intraday rows,1041444new-root rows,120V2pages reused,
21431384new-root bytes; current2025-11-03,42/65tickers. Оба final manifests ещё отсутствуют.
Totals только completed jobs/days, не полный disk usage. Free899502817280bytes.
V3+referenced V2+core4 хранить вместе; полного Windows mirror новых архивов пока нет.
Архивирование source-only, не новый income PASS. Protected2026/paper/timers/подписка не менялись.

## Последний конкурс — V79 R1: 3REJECT_STAGE1; расширенный архив RUNNING

[FUTOI V3 действительно RUNNING](ALGOPACK_FUTOI_ARCHIVE_STATUS.md), PID1913099,
unit trading-lab-algopack-futoi-archive-v3-721f2418b0dc.service. На09:00:00UTC:
4/2192complete calendar days,147ticker-days/48876intraday rows; current2025-12-29,
43/64tickers. Все3pilot days/150raw pages+global-final proofs audited PASS;
120V2pages reference-reused, не скачаны/скопированы заново. V1/V2 failed сохранены,
не запускать: неправильно требовали pair или last-per-group вместо final common point.
V3seal721f2418b0dcbfb65a76e45af387b4c7da9964276ba67e81db500dd45400c69b,
pre-request6601bb3, local103/server103tests PASS. Final manifest ещё нет.
Core4 exact78,726,995byte copy server-side,5SHA+5872coverage/proof keys verified.
API13columns с trade_session_date; old12columns не заменяют расширенные ответы.
Logical FUTOI archive состоит из V3+referenced V2+core4 roots; V3-only backup неполон.

Актуальное поручение2026-09-15: [разрешены conditional AlgoPack screen и архив](
ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md). Пользователь снял scope blocker
и поручил сохранить полезную историю до expiry подписки. Старые записи blocked ниже
исторические, цель active. [V79 R1 завершён](V79_ALGOPACK_FAST_SCREEN_RESULT.md):
pressure/absorption/depth change, source2020–2025, same four assets и готовые feature/label
таблицы, без fit. Mean60min gross0,2909/0,2932/−0,2257bps; net1×−9,7091/−9,7068/−10,2257,
net2×−19,7091/−19,7068/−20,2257bps. Selected15943/4716/21922,
unknown41/18/61; завершённые15902/4698/21861. Control net1×−10,1909bps.
Все6лет net negative у каждого arm, Stage2=0. Это conditional event-screen, не portfolio;
CAGR/Sharpe/MDD=null. Цель20–50% не достигнута. V65–V79:22screens=20rejected+
1incomplete(V73)+1invalid(V74). Пустой V79 V1 INVALID_SOURCE_STATUS_MAPPING отдельно:
не считать0eligible экономическим провалом; canonical сохранён, R1 только исправил
READY_ARCHIVE_ASSUMPTION в отдельном conditional consumer без изменения сигналов/costs.
R1 canonical /srv/trading_lab_data/runs/v79_algopack_fast_screen_r1_da9d02c55cce;
seal da9d02c55cce324e25a3731936419e2663ea664b9853a74da862dec3a1ac7bd6;
metrics81ca9e5b56b0bb3dd29437c5c35325a6f69d63f62148fe49ce59dcd7fa8ac21a.
Local20/server20tests и82094event source-arithmetic/nonoverlap/year/cost audit PASS.

[Архивный service работает](ALGOPACK_ARCHIVE_V1_STATUS.md):14EQ/FO/FXfamilies,
26305planned day/dataset jobs. На08:59:25UTC сохранены338jobs/4772919rows/4980pages,
failed0; systemctl active/running, PID1663880. First-day14/14raw audit PASS.
Root /srv/trading_lab_data/data/algopack-archive/algopack_archive_v1_5b7c66fa0e04;
unit trading-lab-algopack-archive-v1-5b7c66fa0e04.service. Полнота НЕ установлена,
работа продолжится без Windows окон; после terminal проверить final manifest/coverage.
Старые source/model flags,2026, paper, подписка/автопродление и существующие timers не менялись.

## Предыдущий economic batch — V78: оба REJECT_STAGE1

[Протокол](V78_TREASURY_CHANNELS.md), [результат](V78_TREASURY_CHANNELS_RESULT.md):
два новых Treasury information channels, real-discount и inflation-compensation,
20-observation changes, BR/MIX/SI по0.3, constant risk-on controls, full2018–2025.
Raw DGS10/DFII10 по2347rows/98missing, только2017–2025; current-vintage conditional.
Сначала clock-only feasibility:100%/6072asset decisions,1996ready source dates,
feature-unavailable/stale0. Затем один economic batch10.739700s,8arm/cost executions.
Real CAGR1×/2× −8.3438%/−9.0121%, Sharpe−0.6494/−0.7064,
MDD62.4708%/63.8287%,523/523episodes,4/8positive years; net−501457/−529771руб.
Compensation CAGR1.0018%/−2.1002%, Sharpe0.1409/−0.0778,
MDD31.5756%/38.1346%,685/657episodes,5/8 и4/8positive years; net82892/−155976руб.
Control CAGR0.2046%/0.1222%, одинаковый в двух cases. Все8execution complete,
critical/unresolved0,terminalflat; halts/carry/cancellations сохранены. Ни один Stage2.
Local70/server27tests PASS; audit35hashes/8metric-annual-count-cash/raw-state-target PASS.
Pre-source push8e1df10/pre-outcome seal81bee94, canonical
`/srv/trading_lab_data/runs/v78_treasury_channels_v1_8be2ac519e78`.
Seal8be2ac519e78183c51838d5a93d9ea068fe8b902c0dd59678c40b0c48607ce2e;
metrics2edb4e9c1aea7e391a3ebfeafe160fd4eb19b5b65e39e08ace610633698dc5b8.
V65–V78:19economic screens=17rejected+1incomplete+1invalid,0Stage2.
V75/V77 source-only отдельно. Не retune V78/не спасать новым engine/fit.
Цель20–50% не достигнута; protected2026/paper/collectors не менялись.

## Предварительный отсев — V77: SOURCE_FEASIBILITY_REJECTED, без цен

[Результат](V77_INDEX_MEMBERSHIP_RESULT.md): проверен официальный date-specific IMOEX
ticker route, 3 HTTP200. Два среза2018-01-03/2025-12-30: по45tickers, intersection28,
union62. All-period metadata127tickers, 29first-observation candidates в2018–2025,
18дат; по годам2/1/6/3/0/5/7/5. Это не29доказанных security inclusion events:
aliases/redomiciliation/исходная publication history ещё не подтверждены.
Для заранее определённого post-FIRST-inclusion drift minimum30 не достигнут.
Ready30stock manifest покрывает только ENPG из29; 28не покрыты, цены не читались.
Не делать PnL только по ENPG/не понижать gate/не добавлять re-entries ради количества.
Canonical source roots и hashes в отчёте; 2manifest/3raw metadata replay PASS.
Pre-source pushes91a18f3/5c32398; raw immutable outside Git, без нового collector/model/
engine. News sample остаётся paused, publication-time blocker не снят.
Economic runs0, trades/CAGR/Sharpe/MDD=null. V65–V76:17economic screens/0Stage2
без изменения; V75/V77 source-only отдельно. Цель20–50% не достигнута.
Следующий шаг — другой доступный information set/механизм и дешёвый screen,
с предварительным price-free clock/count feasibility, не расширение этой выборки.

## Предыдущий economic screen — V76: REJECT_STAGE1

[V76](V76_INITIAL_CLAIMS_CYCLE.md): новое US labor information set, ICNSA522weeks
2016–2025,4week average против52weeks-earlier. Risk-on BR/MIX long, SI short по0.3,
рост claims разворачивает joint basket. Constant risk-on control, full2018–2025,
два costs, готовые targets/ledger, без model/new collector. Current-vintage conditional
source, original-release/causal admission=false; Saturday observation не publication.
[Результат](V76_INITIAL_CLAIMS_CYCLE_RESULT.md): CAGR1×/2× −5,6847%/−6,0728%,
Sharpe−0,4551/−0,5040, MDD41,5803%/42,4253%,1067/1053closed asset episodes,
3/8positive years. Gross VM−280214/−213792руб., net−373486/−393791на1млн.
Control CAGR−1,6809%/−3,1851%,1105/1065episodes; primary не превосходит контроль.
Все4execution complete, critical/unresolved0,terminalflat; по3no-liquidity cancellations.
6072asset decisions/2024dates на arm,4804nonzero/417releases,17source-unavailable.
Source-ready79,3972%<90%:1251stale asset-dates/417dates, все source-age>14days,
decision-gap>7days0. Это следствие frozen lag/freshness, не missing CSV.
Не считать частые закрытия/reentry независимыми labor shocks и не удлинять TTL после PnL.
Pre-outcome pushf4fb8c1; один economic run5,503150s, local73/server21tests PASS.
Audit18hashes/4metric-count-cash/rawCSV-state-target replays PASS; все8лет сохранены.
Canonical `/srv/trading_lab_data/runs/v76_initial_claims_cycle_v1_fd9332b3e121`.
Seal fd9332b3e121a6afd11d1ef958014a1db21cc38c5ad0441771dd7e6eddfcb3a0;
metrics e611b2d33d0f32e4366af755732fe8446f46be7e09e69c6e2b17922c4a3bfce4.
V65–V76:17economic screens=15rejected+1incomplete+1invalid,0Stage2; V75 source-only отдельно.
Цель20–50% не достигнута. Нужен иной механизм; protected2026/paper/collectors не менялись.

## V75 — source-only dividend drift отсечён до цен

[Feasibility](V75_RMS_DIVIDEND_DRIFT_FEASIBILITY.md): matched CF revisions при том же
непустом будущем payment-date set дали только5changes (0/4/1 по2023/24/25),27stocks,
170global snapshots/10817rows. Новые/исчезнувшие даты не заменены zero, sign/lag не tune.
Недостаточно для30event screen; stock prices/PnL/перенос datasets не запускались.
Это SOURCE_FEASIBILITY_REJECTED, не новый economic backtest. V65–V74 остаются16/0Stage2.

## Предыдущий screen — V74: INVALID_EXECUTION_NO_PROMOTION

[V74](V74_BAKER_RIG_SUPPLY.md): новое physical upstream investment information set,
US oil-directed active rigs → BR, не EIA V17 inventories/refinery или CFTC retune.
Fixed13-release change, opposite direction, constant-long control, gross1, full2018–2025,
два costs, готовые V72 targets/V64 ledger. Source XLSX2013…Aug2025,169309rows/661dates.
11 ambiguous duplicate weeks2013 masked,13 optional County blanks сохранены; no dedup.
[Результат](V74_BAKER_RIG_SUPPLY_RESULT.md): все4 execution_complete=false,
critical2/gross_limit_counter2, atomic rejects0, все записанные order legs filled.
По2 capacity cancellations2022-03-01/02,1halt/carry, unresolved0, terminal flat.
Не называть counter двумя отклонёнными сделками и не снимать execution gate задним числом.
Только forensic raw: primary CAGR1×/2× −7,9384%/−8,9712%, Sharpe−0,0516/−0,0854,
MDD86,0480%/86,9237%,118episodes,3/8positive years; gross VM уже отрицателен.
Control raw CAGR+0,1416%/−0,8294%,93episodes. Это НЕ validated strategy returns.
2024daily decisions/arm, primary1922nonzero/396releases, control1946/401;
source ready96,1957%, полный2025 сохранён. Original vintages/causal admission=false.
Pre-outcome pushd405dff, один economic run3,678092s; local73/server21tests PASS.
Audit18child hashes/4metric-count-cash/raw-workbook-state-target replays PASS;
reproducibility PASS не снимает execution failure. Ни retune, ни simulation rerun.
Canonical `/srv/trading_lab_data/runs/v74_baker_rig_supply_v1_0e2c21e3964f`.
Seal0e2c21e3964f316b9c5c1fa98e6a09c5b3802e8779a0db48684eb092da37fd97;
metricsf6ceff245a47431406419adcd3830fdcb900e277cfb844148543545ca3edf6b7.
V65–V74:16screened=14rejected+1incomplete+1invalid/0Stage2. Не строить engine для V74.
Цель20–50% не достигнута; нужен иной механизм. Protected2026/paper/collectors неизменны.

## Предыдущий screen — V73: INCOMPLETE_NO_PROMOTION

[V73](V73_SBER_SHARE_CLASS_PAIR.md): same-issuer ordinary/preferred SBER/SBERP pair
через12общих сроков фьючерсов,2023–2025. Выбор пары до цен, weekly MAD deviation,
next-session entry/five-session exit,5/10bps per side, static short-common control.
[Результат](V73_SBER_SHARE_CLASS_PAIR_RESULT.md):157weekly decisions,16selected,
12complete/4unresolved (75%coverage); по годам4/4/4complete,0/1/3unresolved.
На полной части primary mean net1×/2× −0,020497%/−0,120785% на событие относительно
суммы начальных quoted notionals, median−0,005145%/−0,104427%,positive50%/25%.
Grossmean+0,079791% меньше base costs0,100288%; control mean−0,143289%/−0,243577%.
Все3года при double отрицательны; minimum30events не достигнут. Primary лучше контроля,
но нет положительного/устойчивого эффекта. Portfolio CAGR/Sharpe/MDD=null: не годовать
event means и не выбрасывать4неизвестных исхода. Whole16 return неизвестен.
One-contract1% participation проходит0/12complete: candle volume не доказательство BBO.
Local35/server16tests PASS,Ruff/diff PASS; audit4hashes/source-candidate-endpoint-metrics PASS.
Pre-outcome push2e2c71d; один run1,105801s после preflight, отдельный read-only replay.
Canonical `/srv/trading_lab_data/runs/v73_sber_share_class_pair_v1_74a9f44d7669`.
Seal74a9f44d76699acd04bc821b40b340d6611afbada5741003d3c4d06de54dd501;
metrics4a9101bf828e851fd794353c42824b2a63f8423a27cab3ec4a8deebc8bdaf4ff.
V65–V73:15screened=14rejected+1incomplete/0Stage2. V73 не retune/не строить новый ledger.
Цель20–50% не достигнута; нужен иной механизм. Protected2026/paper/collectors неизменны.

## Предыдущий screen — V72: REJECT_STAGE1

Новая информация: явные заявления ЦБ о будущих повышениях/снижениях ставки, не уже
проверенные числовые levels/governors V27 или прогноз бюджета V71. [Source protocol](
CBR_POLICY_RELEASES_SOURCE_V1.md) собирает все релизы отдельной категории2018–2025;
принятые решения в headline использованы контролем. Никакого fit или нового сервиса.
Source V1 после push72df00b остановился на29-м article:2022-07-22 footer00:00:00,
catalog13:30. V1raw сохранён, processed/PnL отсутствуют. [V2 correction](
CBR_POLICY_RELEASES_SOURCE_V2.md), push e0c5fad:68релизов2018–2025,77raw responses,
40date-only footers; end-of-day availability неизменна. Raw/normalization audit77/68 PASS.
Manifest83a89218c16785d961632c4a715e8f26d0fda0e0299e39ac98257f2621d75b70.
[Economic V72](V72_CBR_POLICY_GUIDANCE.md): fixed lexical next-action direction против
headline-only, MIX/SI по0.5nominal, TTL14days,2018–2025,1×/2×costs, старый ledger.
[Результат](V72_CBR_POLICY_GUIDANCE_RESULT.md): CAGR1×/2× −3,3803%/−3,4961%,
Sharpe−0,5653/−0,5838, MDD31,5134%/31,6906%;90закрытых эпизодов,3/8 и2/8прибыльных лет.
Control CAGR−5,1005%/−5,2541%,88эпизодов,1/8положительный год. Primary gross уже
отрицателен: net−240222/−247466руб. на исходный1млн за2018–2025; Stage2=0.
68/68readable releases,42directional/26flat;4048asset decisions,788nonzero targets,
42использованных релиза. Все4complete,critical/unresolved0,terminalflat; в controls
по1no-liquidity cancellation сохранены. Pre-outcome push dddfd09, единственный run2,972204s.
Canonical `/srv/trading_lab_data/runs/v72_cbr_policy_guidance_v1_8d7b732d7a47`.
Seal8d7b732d7a475a573dc7e7b459b80149c82b645682c792892598045a2b5c90da;
metrics e56de06182944470cd99d1a40d8d59fe14e6d287b511777e355fbdd823c6c3fd.
Local53/server22tests PASS; audit17hashes/state-target/4metrics-annual-count-cash PASS.
V65–V72:14rejected/0Stage2. Не tune-ить словарь/знак/TTL/активы/плечо; нужен иной механизм.
Цель20–50% не достигнута. Source не доказательство original historical versions.
Проверенные обходные направления не повторять: term/calendar уже закрыты; premium
options без quotes/spec identity blocked, volatility-curve catalog V2 показывает0/6
eligible archives по прежнему gate. Index sample и старый paper bootstrap не запускались.

## Предыдущий screen — V71: REJECT_STAGE1

[V71](V71_CBR_LIQUIDITY_SURPRISE.md): новая information hypothesis — ошибка недельного
прогноза government-account liquidity относительно matching realized contribution,
после завершения всего периода → направление SI. Контроль actual-only, одинаковая
доступность; не повтор/инверсия V18 forecast или V19 Minfin FX persistence.
Методика ЦБ: среднее накопленных дневных вкладов, не недельная сумма. Только полные
обычные Wed–Tue недели, без imputation; missing/irregular явно masked. 2021–2025,
gross1 target, готовый futures ledger, два costs, без fit/нового collector.
[Результат](V71_CBR_LIQUIDITY_SURPRISE_RESULT.md): CAGR1×/2× −8,1877%/−8,1629%,
Sharpe−0,3619/−0,3608, MDD41,8831%/41,7189%;121 закрытый эпизод,1/5 прибыльных лет.
Контроль CAGR−20,6766%/−20,8825%. Primary лучше контроля, но теряет капитал уже до
затрат; всего net−346819/−345938руб. на исходный1млн за пять лет. Stage2=0.
214/254 ready periods (84,2520%),1271 decisions,1056 nonzero targets; все4 executions
complete, critical/unresolved0, terminal flat. Один factual halt/carry и один cancelled
target no-open в каждом scenario сохранены, maximum close gross primary1,0757/1,0804.
V1 push `f6cffe8` остановился до portfolio ledger: SI observations против full specs;
только inputs/states. [R1](V71_SCOPE_REPAIR_R1.md), pre-simulation push `8f447cb`,
исправил только specs scope, сохранив parent bytes/signals/economics/gates.
R1 canonical `/srv/trading_lab_data/runs/v71_cbr_liquidity_surprise_r1_e9ac4c0832cd`.
Seal `e9ac4c0832cdb9e999745816a459b0081a79260ddeac2bcc8f42e504b5c4526b`;
metrics `d4749f1aefeec4e40f386f29cccfff0c7274907925f388e28d57946c179857f4`.
Единственный economic run2,122537s; local40/server27tests PASS, Ruff/diff PASS.
Audit17hashes/source states/4metrics-count-cash PASS; inherited inputs/states byte-identical.
V65–V71:13 rejected/0Stage2. Не менять знак/агрегацию/окна V71; нужен иной механизм.
Цель20–50% не достигнута. Protected2026/paper/collectors не менялись.

## Предыдущий screen — V70 завершён после accounting R1: REJECT_STAGE1

[V70](V70_OFZ_RELATIVE_CURVE.md): OFZ relative value — top-3 positive leave-one-out
yield-curve residuals против top-3 close-to-curve controls. SU262, 2–7 лет, monthly
first factual decision / strictly prior source, 2021–2025, 10/20 bps, готовый coupon
ledger без старой V52 selection или V49 blend. Не аукционный сигнал V67.
[Результат](V70_OFZ_RELATIVE_CURVE_RESULT.md): CAGR 1×/2× 4,4929%/3,0249%, Sharpe
0,5811/0,4055, MDD19,2397%/19,8828%; 103 закрытых эпизода, прибыльны3/5 и2/5 лет.
Контроль CAGR3,6400%/2,0872%; excess всего0,8530/0,9378 процентного пункта.
2025 принёс22,6206%/20,8011%, но это не устойчивые20% за весь2021–2025.
REJECT_STAGE1: CAGR, excess, число прибыльных лет; double costs также Sharpe.
60 месяцев/56 selected, 56 rebalances, 1271/1271 marks, 0 remaining unresolved во всех4.
Первый run после push `de7a2f8`, 2,824659s, первоначально INVALID_INCOMPLETE_ACCOUNTING
из-за11 sourcewide missing principal record dates; его metrics с null сохранены.
[R1](V70_ACCOUNTING_RECONCILIATION_R1.md), после pre-performance push `068df83`, доказал
44/44 zero entitlements и независимо сверил все credits. Исходные signal/trades/positions/
raw NAV/costs/gates неизменны; strategy simulations rerun0. Six exact documentary sources,
5 never-held и6 exact-record-date zero holdings в каждом scenario; не выдуманные выплаты.
R1 canonical `/srv/trading_lab_data/runs/v70_ofz_relative_curve_r1_60b09b6b2121`.
Seal `60b09b6b212163b31c934c7b6b814ee400603a3c0456d1e94e2a7b6e959280ac`;
metrics `b18acbc2cc427f23fc720c7908ff1a06bb772829f55744ca663bb8f57ece64f0`.
13new+15parent+2encoding local30 PASS; server13 PASS; Ruff/diff PASS.
R1 evaluation0,252720s; audit20parent+6new hashes/6documents/44proofs/4metric-credit replays PASS.
V65–V70:12 отсеянных гипотез,0 Stage2; R1 не новая гипотеза. Цель20–50% не достигнута.
Далее иной механизм/information set, не настройка V70/старых families. Protected2026
prices/returns/labels/PnL, paper bootstrap и collectors schedules не менялись.

## Предыдущий screen — V69 завершён: REJECT_STAGE1

[V69](V69_FUTURES_CHAIN_INTEREST.md): monthly direction по 63-session growth суммарного
reported futures-chain OI, BR/MIX/RI/SI, 2018–2025, constant-long контроль, два costs.
Не старые active-contract OI features V7/V8, не participant crowding и не option V68.
Все присутствующие OI cells должны быть известны; NULL маскирует весь daily total.
Месячное решение из строго prior source, новый invalid месяц не наследует старый сигнал.
[Результат](V69_FUTURES_CHAIN_INTEREST_RESULT.md): CAGR 1×/2× −5,5559%/−5,9359%,
Sharpe −0,5639/−0,6115, MDD 44,0979%/45,2677%; 200/198 закрытых эпизодов,
прибыльны 3/8 и 2/8 лет. Gross PnL отрицателен до затрат; контроль CAGR +2,7772%/+2,2152%.
309/384 месячных asset decisions готовы; все 4 executions complete, critical/unresolved 0,
terminal flat. REJECT_STAGE1: нет доходности/устойчивости и проигрыш контролю; 0 Stage2.
18 новых synthetic +11 shared-helper regression +2 encoding PASS; server 18 PASS до
единственного economic run 5,4935s. Audit 17/17 hashes, 4/4 metric/count/clock replays
и monthly schedule PASS. Pre-outcome push `0c8b0eb`, seal `ba001c39c1fa02e790d7837380b60c0327e99e1d051d8402b9b7c96554e860f1`.
Canonical `/srv/trading_lab_data/runs/v69_futures_chain_interest_v1_ba001c39c1fa`.
V65–V69: 11 отсеянных гипотез, 0 кандидатов Stage2. Знак/горизонт/пул/расписание не менять;
нужен другой содержательный механизм. Старый paper bootstrap остаётся отключённым
по последней проверке; новых collectors или fit нет.

## Работа возобновлена — 2026-09-13, V68 завершён: REJECT_STAGE1

Пользователь явно ответил «продолжай» после уточнения о паузе. Сохранённый checkpoint
[2026-09-08](PAUSE_20260908.md) остаётся историей; исследовательская пауза снята.
Новый [V68](V68_REPORTED_OPTION_FLOW.md): reported option VOLUME относительно OI,
самостоятельное направление фьючерсов против OI-only контроля, 4 актива/2 costs,
готовый ledger, без fit/нового collector. [Результат](V68_REPORTED_OPTION_FLOW_RESULT.md):
CAGR +1,7801%/+0,4407%, Sharpe0,2139/0,0943, MDD30,7118%/31,2457% при1×/2× costs;
414/408 закрытых эпизодов, положительны2/5 лет. Контроль CAGR −3,4787%/−4,0018%.
REJECT_STAGE1: доходность/Sharpe/просадка/число положительных лет не проходят gates.
Все4 ledger complete/terminal flat, critical0/unresolved0. Ready948/1044 source states;
missing volume/OI не объявляются нулём и полные market totals не доказаны.
Local11+2 encoding tests PASS, server11PASS (cwd-only pytest teardown retry), audit17/17
hashes и4/4 metric/count/clock replay. Единственный run4,7084s после push `018b008`.
Canonical `/srv/trading_lab_data/runs/v68_reported_option_flow_v1_ab09fc1343f0`.
V65/V66/V67/V68:10 отсеянных гипотез,0 кандидатов Stage2. Правило/знак/окно/пул не менять.
Expiry pinning не запускался: exact expiry в существующем source не подтверждён.
Paper bootstrap остаётся отключённым по последней проверке 2026-09-08; старый запуск
с F=September9 не включать автоматически и пропущенные prospective окна не backfill-ить.
Серверные source collectors оставлены работать; их schedules здесь не менялись.

## Предыдущий screen — V67 завершён, REJECT_STAGE1

[V67](V67_OFZ_AUCTION_CONCESSION.md): одна новая гипотеза на уже собранных 283 primary
OFZ-PD результатах и дневной истории облигаций. Покупка после публикации, оценка через
5 сессий, два ближайших по дюрации не размещённых в тот же день контроля, 10/20 bps
на сторону. Не V20 агрегированный cross-asset score и не V52 monthly carry.
Сначала clean-price event study: CAGR/Sharpe/MDD портфеля null, купоны/НКД/капитал
не объявляются учтёнными. [Результат](V67_OFZ_AUCTION_RESULT.md): 283 исходных события,
234 выбранных до будущих цен, 232 полных эпизода / 157 публикационных дней.
Среднее пятисессионное изменение чистой цены −0,0588%; после 1×/2× затрат
−0,2588%/−0,4588%. Превосходство над контролем +0,1126% не делает покупку прибыльной.
При удвоенных затратах все пять годовых средних отрицательны; REJECT_STAGE1.
Local 6 synthetic + 2 encoding tests, server 6 tests PASS; inputs 12/12, hashes 5/5,
232 исходных ценовых расчёта и 157 средних сверены. Pushed `4d7bbe2` до единственного run.
Canonical `/srv/trading_lab_data/runs/v67_ofz_auction_concession_v1_bd3c7ee1c1d2`.
За три новых проверки V65/V66/V67 — 9 отсеянных гипотез, 0 кандидатов Stage2.
Окно/знак/контроль V67 не менять; portfolio CAGR из event means не выводить.

## Предыдущий конкурс — V66 R1 завершён, 4 отсева / 0 кандидатов

[Протокол V66](V66_FAST_VOLUME_CONTEST.md): четыре механизма на завершённом дневном
OHLCV, каждый против того же ценового правила без объёмного фильтра. Три фиксированных
актива BR/RI/SI совместно, равные предельные веса 0,3, пять неттируемых дневных долей.
Те же разрешённые три периода и готовый учёт; 48 прогонов, без fit/нового источника.
[Результат](V66_FAST_VOLUME_RESULT.md): все 48 сценариев имеют полное исполнение,
все четыре гипотезы REJECT_STAGE1. В недавнем периоде CAGR 1×/2×: разворот −0,006/−0,029%,
продолжение −0,787/−0,888%, ложный пробой −0,100/−0,110%, сжатие −0,027/−0,029%.
Последние три отрицательны даже до затрат; у разворота валовые 5235 руб. меньше затрат
7521 руб. за весь 2018–2025. На уровень 2 ничего не переводить, правила не перенастраивать.
Полный R1 run после push `b3507f6`: 26,79 секунды расчёта, 45/45 входных проверок,
173/173 хеша артефактов и 48/48 повторных расчётов метрик. Server 13 tests PASS.
Canonical `/srv/trading_lab_data/runs/v66_fast_volume_contest_v1_9cf51b328e26`.
R1 seal `9cf51b328e26f8192121950593476762008a37d8d84a3591d60a2a294cc27f7c`.
Первая попытка `..._307db9d6583e` сохранена: отчётная ошибка nullable ID до записи PnL;
[R1](V66_COUNTING_REPAIR_R1.md) исправил только счётчик, не экономику.
В двух новых пакетах V65/V66 — 8 гипотез и 0 кандидатов Stage2. Цель 20–50% не достигнута.

## Предыдущий быстрый конкурс — V65, все четыре гипотезы отсеяны

Пользователь2026-09-08 потребовал приоритет быстрого экономического отсева и уровни
проверки. Принята [воронка](HYPOTHESIS_FUNNEL.md): быстрый конкурс → устойчивость →
исполнение → демо. V65 использует готовые разрешённые input manifests/ledger V64, но
не его налоговую стратегию или результаты. 4 гипотезы × 2 arms × 3 eras × 2 costs, без fit/нового
источника. [Результат V65](V65_FAST_CONTEST_RESULT.md): единственный run завершён,
все 4 гипотезы REJECT_STAGE1, кандидатов Stage2 — 0. 48 прогонов: 43 complete,
5 invalid execution. Recent CAGR 1×/2×: RI 1,46/1,38%; oil weekly −7,54/−10,74%;
FX 1,93/1,15%; post-roll recent invalid (не считать прибыльным).
45/45 input checks, 170/170 artifact identities. Commit `1c2d707` pushed до run;
8 server tests PASS. Старый 2026 защищён, цель не достигнута.

## Отложено по приоритету пользователя — индексный source sample

Подготовлен [fixed source sample](MOEX_INDEX_NEWS_SAMPLE_V1.md), но НЕ ЗАПУЩЕН:
9заранее известных публикаций/максимум18anonymous ISS requests, сначала date-only
admission, затем article fragment. Это проверка формата/revision evidence, не экономическая
выборка.32synthetic tests PASS, local commit5d39d27; server sample и raw audit не выполнялись.
Full catalogue пока явно disabled; никаких prices/labels/PnL или повторного обучения.
Позднее по просьбе пользователя работа поставлена на паузу, AlgoPack bootstrap отменён;
см. [точку продолжения](PAUSE_20260908.md). Source sample не запускать автоматически.

## Paper-контур — запуск отменён на время паузы

Фактическая проверка после отключения 2026-09-08 около 11:03 UTC: bootstrap timer
`disabled/inactive/dead`, NextElapse/LastTrigger пусты; bootstrap service `inactive`,
MainPID=0, start timestamp пуст; exact paper instance `not-found/inactive`, MainPID=0.
Не включать старый timer без проверки правил prospective возобновления. Ниже сохранена
история подготовки до отмены; её прежние команды запуска не являются текущей очередью.

[Bootstrap до паузы](ALGOPACK_PAPER_BOOTSTRAP_20260909.md): c760e2b pushed/deployed, syntax and
local/server2tests PASS. Exact operational units installed; ONLY timer enabled/started.
Actual timer active/waiting, next September9 00:01MSK, no prior trigger; bootstrap
inactive/dead/start timestamp empty. At F+1m: UID999check→once-only init→non-overwriting
sealed template install/compare→exact service start. Existing root skips auto init.
No actual forecasts/trades yet. Former due-time observation is cancelled by the pause.

Read-only operational preflight September8 09:22UTC: installed bootstrap bytes match,
NTP synchronized,904GiB free, UID999 parent write/search and Python execute checks exit0.
Paper base is still absent, expected before once-only init; no start/model/HTTP request.
Witnessed-flow last12:13MSK invocation success/exit0, not a new raw-data audit. Details
are in the bootstrap note. This is historical pre-pause evidence, not current startup
authorization. Current state and resumption constraints are in the pause checkpoint.

### Предшествующий этап — future activation published, waiting for boundary

[Publication evidence](ALGOPACK_PAPER_ACTIVATION_PUBLICATION_20260908.md):100files
matched server, full paper suite598PASS/1explicit-root skip59.43s UID999.
BundleSHA `adbce32835959587eac3b0c0653ea3b6e5d2e32c8248a5bc3a0d88202304ec85`,
activationSHA `f51c02902825f61ba74cfbbcdd719d7233bc1839f1a152d9289e35e9ea3624e0`.
Pushed/deployed d9a9fe2/5bc0690. Actual pre-F verifier PASS; request_ready correctly
WAIT_FUTURE_BOUNDARY. **F=2026-09-08T21:00:00UTC = September9 00:00Moscow**.
No initialization/service start/timer yet. After F: actual V2check, once-only initialize,
exact service install/start before09:00calendar window; inspect prospective source results.
Sealed bytes/permissions must not change after F. Income remains unverified.

### Предшествующий этап — prospective config fixed

[Forward protocol](ALGOPACK_PAPER_FORWARD_PROTOCOL_V1.md) and production-named config
created without activation/seal/F. Config SHA256
`be0a3263cd555cdca6a4f99dfeaf7f37f481549ce74af7daf38056d513b4774b`.
Pushed/deployed f4ee4f9 exact4files; local config3+encoding2 PASS, Ruff/diff PASS;
server config/activation/runtime23PASS1.38s UID999. Fixed existing model identities,
execution/evaluation constants and unverified fee assumption; no tuning/retraining.
Implementation snapshot is descriptive, not parameter overrides. Далее complete
transitive bundle seal and genuinely future activation publication. No HTTP/model IO.

### Предшествующий этап — actual benign service sandbox verified

[Systemd sandbox result](ALGOPACK_PAPER_SYSTEMD_SANDBOX_RESULT.md): pushed dbf2bfc,
transient synthetic service copied production sandbox/cleanup properties, no secrets.
UID999 import succeeded; outside write denied, inside0600, same parent/child cgroup.
SIGTERM-resistant child killed and both processes absent after15.085s; expected timeout
state reset for exact synthetic unit. Server1PASS15.68s. Production unit/activation absent.
Далее complete pre-F closure/publication prerequisites. F=null, no income admission.

### Предшествующий этап — source-to-execution integration

[Execution path measurement](ALGOPACK_PAPER_EXECUTION_PATH_RESULT.md): raw synthetic
HTTP→actual source replay/pool/due/bridge→two-arm entry/exit→anchored recovery,6events,
no duplicate fills. Pushed/deployed511d348; server UID9991PASS2.21s, related65PASS7.40s.
Measured entry0.642s/exit0.613s; fake process/HTTP/signal, not complete production SLA.
F=null. Далее benign-child service sandbox/cleanup and full pre-F activation preparation.

### Предшествующий этап — measured readiness overhead

[Actual readiness traversal](ALGOPACK_PAPER_READINESS_COST.md): isolated2099 activation,
89real code/config/doc dependencies, unchanged recursive runtime.ready and full verifier.
Pushed/deployed3c6bb03; Linux UID9991PASS0.69s. Three calls0.107874/0.103964/0.104133s,
each39full activation reloads; subsequent synthetic dependency mutation rejected.
Not total tick latency/SLA; no production activation/model/market IO. F=null.
Далее full-component synthetic timing and service sandbox verification; do not weaken
integrity checks merely because duplicate traversal exists.

### Предшествующий этап — server service preparation

[Paper service](ALGOPACK_PAPER_SERVICE.md): explicit activation-SHA instance, runtime V2
check-before-serve, whole-cgroup cleanup, private instance write scope, no automatic
restart/init/boot admission. Offline reporting handoff documented. Local service3 and
encoding2 tests PASS. Pushed ad371f3, exact3files deployed to repository only;
systemd-analyze verify PASS on server255, service+runtime14tests PASS1.37s UID999,
all3SHA match. Template not installed in systemd or started, activation absent, F=null.
Далее integrated timing/sandbox checks and complete pre-F activation.

### Предшествующий этап — integrated asynchronous runtime V2

[Runtime V2](ALGOPACK_PAPER_RUNTIME_V2.md): due→preparation poll→slot step, canonical
dispatch/restart guard, safe maintenance and child shutdown. Config explicitly selects
V2; legacy CLI refuses different selected runtime before credentials.11tests added,
local V2+startup4PASS/9Linux skips. Pushed/deployeda4f49f3:77/77related Linux tests UID999
PASS12.09s,4SHA match, parents verified, encoding2/Ruff PASS; legacy retained.
[Server result](ALGOPACK_PAPER_RUNTIME_V2_RESULT.md). F=null.
Далее broader integration/local overhead verification, service cleanup/report cadence
and complete pre-F activation. Tests do not establish provider SLA or income.

### Предшествующий этап — stepwise async slot admission

[Async slot V1](ALGOPACK_PAPER_ASYNC_SLOT_V1.md): intake→background session/union quotes→
current-position MARK→two-arm decisions one asset/tick. Shared mark/entry reference,
no main-thread HTTP; failed/late/uncertain attempts retained.9tests(local1PASS/8Linux
skips); pushed/deployed4493bc9:53/53related Linux tests UID999 PASS14.36s,3SHA match,
parents verified, encoding2/Ruff PASS. [Server result](ALGOPACK_PAPER_ASYNC_SLOT_V1_RESULT.md).
F=null. Далее integrated async runtime and full
original interference/restart tests; legacy runtime still unadmitted.

### Предшествующий этап — preparation completion intake V1

[Preparation intake V1](ALGOPACK_PAPER_PREPARATION_INTAKE_V1.md): supervisor/child/forecast
identity and durable chronology, actual-time consumption, once-only intake, no late
forecast read. Pushed/deployed65dcb43:67/67related Linux tests UID999 PASS13.74s;
local1PASS/8Linux skips, encoding2/Ruff PASS,3SHA match, parents verified.
[Server result](ALGOPACK_PAPER_PREPARATION_INTAKE_V1_RESULT.md). F=null.
Далее async slot calendar/marks/intent state machine, runtime integration and original
interference/deadline/restart retest. Legacy runtime remains unadmitted.

### Предшествующий этап — asynchronous due executor V1

[Async due executor V1](ALGOPACK_PAPER_ASYNC_DUE_V1.md): dedicated4quote-worker pool
connected to single anchored execution owner, exits first/shared arms, actual deadlines,
fresh later retries, expired exit risk retained. Pushed/deployeda2c1b68:52/52related Linux
tests UID999 PASS10.21s; local2PASS/7Linux skips, encoding2/Ruff PASS,3SHA match, parents
verified. [Server result](ALGOPACK_PAPER_ASYNC_DUE_V1_RESULT.md).
Not runtime-integrated, F=null. Далее async slot admission/runtime,
full timing/restart matrix and final activation. Legacy synchronous runtime not admitted.

### Предшествующий этап — bounded execution-source worker pool

[Execution worker pool V1](ALGOPACK_PAPER_EXECUTION_WORKER_V1.md): max4isolated source
children/no hidden queue, per-job deadlines, immutable references and raw identity/time
replay before consumption. Pushed/deployed034e7d4:56/56related Linux tests UID999
PASS3.46s; local1PASS/9Linux skips, encoding2/Ruff PASS,3SHA match, parents verified.
[Server result](ALGOPACK_PAPER_EXECUTION_WORKER_V1_RESULT.md). Not yet
runtime-integrated; original blocking defects remain. F=null. Далее async executor with
exit-priority capacity, single ledger owner and actual-time consumption/restart tests.

### Предшествующий этап — isolated preparation worker V1

[Preparation worker V1](ALGOPACK_PAPER_PREPARATION_WORKER_V1.md): source/model-only child,
own HTTP session, immutable references, one-child non-waiting supervisor with deadline
terminate/kill. Not yet integrated: original runtime interference defect remains.
Pushed/deployedc8d3851:47/47related Linux tests UID999 PASS15.22s, including9worker tests
and benign real child lifecycle.3SHA match, parents verified, encoding2/Ruff PASS.
[Server result](ALGOPACK_PAPER_PREPARATION_WORKER_V1_RESULT.md). F=null. Далее async executor integration,
remaining blocking execution-source work and actual scheduler interference retest.

### Предшествующий этап — scheduler interference characterization

[Scheduler interference](ALGOPACK_PAPER_SCHEDULER_INTERFERENCE_V1.md): synchronous slot
can block next pump beyond existing30s exit window; late-start120s/40s synthetic cases
model delays60s/39s even with immediate reopen. Pushed/deployedd1f3776:23/23related
Linux tests UID999 PASS2.13s, including4cases;2SHA match, encoding2/Ruff PASS.
[Reproduction result](ALGOPACK_PAPER_SCHEDULER_INTERFERENCE_V1_RESULT.md).
PASS confirms the readiness defect, not production SLA or economic evidence.
Next separate bounded source/model work from execution owner (or prove cooperative
nonblocking bounds); do not loosen fill freshness/deadlines. F=null.

### Предшествующий этап — due-pump shared quote latency fix

[Shared quote latency fix](ALGOPACK_PAPER_DUE_PUMP_LATENCY_FIX_20260908.md): arm-first
ordering aged shared quotes across other asset HTTP calls.2synthetic regressions failed
old code; grouped same contract/due/type contiguously, both PASS. Local4PASS/6Linux skips.
Pushed/deployed7947d2e:71/71related Linux tests UID999 PASS6.96s; encoding2/Ruff PASS,
3SHA match, parent seals verified. Old pump retained; current SHA b26a2768… must be
pinned pre-F. [Server result](ALGOPACK_PAPER_DUE_PUMP_LATENCY_FIX_RESULT.md).
Still no production SLA:4serial10s requests can exceed30s, slot blocking also to check.
F=null. Далее timing/interference verification and complete activation/service setup.

### Предшествующий этап — immutable report store/CLI V1

[Report store/CLI V1](ALGOPACK_PAPER_REPORT_STORE_V1.md): immutable canonical report,
source/activation/ledger scope, explicit failed/unresolved attempts. Offline CLI obtains
runtime lifetime lock before account recovery, no HTTP/token/service stop. Local2PASS/
6Linux skips; pushed/deployeda199992:100/100related Linux tests UID999 PASS9.86s,
encoding2/Ruff PASS,3SHA match, parent seals verified.
[Server result](ALGOPACK_PAPER_REPORT_STORE_V1_RESULT.md). F=null. Далее latency verification, final
activation/service configuration and safe reporting cadence, not new model training.

### Предшествующий этап — runtime calendar integration

[Runtime calendar integration](ALGOPACK_PAPER_RUNTIME_CALENDAR_V1.md): dedicated calendar
component, fixed morning canonical work, pump-first, no retry/backfill after restart.
Unactivated runtime updated; local4PASS/13Linux skips across runtime/startup/calendar.
Pushed/deployedcff39e5 + test-only6988394:81/81related Linux tests UID999 PASS4.73s.
Initial2FAIL were backward synthetic clock fixture, corrected before final PASS.
3SHA match, parent seals verified; old runtime retained, current runtime SHA79a1e87d…
must be pinned in future activation. [Server result](ALGOPACK_PAPER_RUNTIME_CALENDAR_V1_RESULT.md).
F=null. Далее report persistence/CLI, latency и complete pre-F activation/service.

### Предшествующий этап — calendar-bound report V1

[Calendar-bound report V1](ALGOPACK_PAPER_CALENDAR_REPORT_V1.md): expected days/digest
только из calendar policy; unresolved blocks evaluation before economic reads.
Full ledger replay rejects excluded-day activity/carried risk, including flat roundtrip.
Pushed/deployed99762b7:111/111related Linux synthetic tests UID999 PASS16.46s;
local1PASS/8Linux skips, encoding2/Ruff PASS,3SHA match, parent seals verified.
[Server result](ALGOPACK_PAPER_CALENDAR_REPORT_V1_RESULT.md). F=null, no economic run.
Далее runtime calendar scheduling, report persistence/CLI, latency и complete activation.

### Предшествующий этап — calendar policy V1

[Calendar policy V1](ALGOPACK_PAPER_CALENDAR_POLICY_V1.md): canonical weekday attempt
09:00–09:05Moscow, no fallback/revision replacement; complete F-to-end decision ledger.
Missing/late/unknown calendar blocks expected_days for entire period. Closed/weekend
exclusions retained for required economic ledger check. Pushed/deployedf908f0c:
124/124related Linux tests UID999 PASS5.28s; local3PASS/8Linux skips, encoding2/Ruff PASS,
3SHA match, parent seals verified. [Server result](ALGOPACK_PAPER_CALENDAR_POLICY_V1_RESULT.md).
F=null, no actual source request. Далее report wrapper with
excluded-day ledger checks, runtime scheduling, persistence/CLI, latency and activation.

### Предшествующий этап — calendar source V1

[Calendar source V1](ALGOPACK_PAPER_CALENDAR_SOURCE_V1.md): current-day activation-gated
HTTP adapter + immutable per-response journal + full raw/durable observation replay.
Pushed/deployedc864a38:113/113related Linux synthetic tests UID999 PASS4.43s;
local10PASS/4Linux skips, encoding2/Ruff PASS,3SHA match, parent seals verified.
[Server result](ALGOPACK_PAPER_CALENDAR_SOURCE_V1_RESULT.md). No actual API request/service,
F=null. Далее sealed version-selection/amendment policy и report calendar binding,
затем persistence/CLI, latency, complete activation. Не перезапускать обучение.

### Предшествующий этап — calendar core V1

[Calendar core V1](ALGOPACK_PAPER_CALENDAR_CORE_V1.md): реализованы closed URL/schema,
raw pagination/chronology/complete-date replay и revision digest,21synthetic tests.
Pushed/deployed297d088:74/74related Linux synthetic tests UID999 PASS3.03s;
local core+evaluation38PASS, encoding2/Ruff PASS,3SHA match, parent seals verified.
[Server result](ALGOPACK_PAPER_CALENDAR_CORE_V1_RESULT.md).
Это pure primitives, не HTTP/journal/official admission.
Следом durable calendar capture и version-selection policy,
затем report binding/persistence, latency и полный pre-F seal. F=null.

### Предшествующий этап — official calendar source discovery

[Calendar discovery 2026-09-08](ALGOPACK_PAPER_CALENDAR_DISCOVERY_20260908.md): найден
официальный futures off_days API, отличающий calendar date от session date, с null
для неизвестного статуса. Подтверждена ревизия расписания MOEX от04.09; static weekday
list/поздний календарь не доказывают исходный denominator. Это документация, не
реализованный adapter/seal: calendar_source_verified=false, F=null. API с ключом,
цены и economic run не запускались. Следом versioned calendar receipts и заранее
фиксированное правило выбора/изменений, затем report persistence/CLI и activation.

### Предшествующий этап — combined economic report V1

[Combined report V1](ALGOPACK_PAPER_REPORT_V1.md): forecast/execution audits + exact
ledger-prefix snapshot/coverage/count verification before frozen evaluation.
Pushed/deployed2b61650:418/418related Linux tests UID999 PASS, включая9report;
local1+encoding2PASS/8Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_REPORT_V1_RESULT.md). F=null;
calendar_source_verified=false, not economic admission.
Следом official expected-calendar provenance binding, report persistence/CLI, latency,
complete pre-F config/seal и service setup. No actual market/economic run.

### Предшествующий этап — исправление startup lock ordering

[Runtime startup fix](ALGOPACK_PAPER_RUNTIME_STARTUP_LOCK_FIX_20260908.md): подтверждена
гонка construct-before-lock (2regression FAIL на прежнем коде); exclusive lifetime lock
перенесён до полного replay портфеля. Pushed/deployed09777ff:409/409related Linux tests
UID999 PASS; local3+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_RUNTIME_STARTUP_LOCK_FIX_RESULT.md). Old runtime retained;
F=null, production activation отсутствует; стратегии unchanged.
Следом combined economic audit/evaluation report wiring, calendar/latency и full seal.

### Предшествующий этап — numerical forecast/source replay V1

[Forecast audit V1](ALGOPACK_PAPER_FORECAST_AUDIT_V1.md): raw packet/flow replay,
original availability reconstruction, fixed-model numeric recomputation and full
candidate equality. Pushed/deployed7c0da8f:407/407related Linux tests UID999 PASS,
включая7forecast-audit; local1+encoding2PASS/6Linux skips, Ruff PASS.3SHA match,
parents44/7 unchanged. [Server result](ALGOPACK_PAPER_FORECAST_AUDIT_V1_RESULT.md). F=null.
Следом combined economic audit/evaluation report wiring, official calendar/latency
checks, complete pre-F config/seal and server service activation. No actual economic run.

### Предшествующий этап — offline execution-binding replay V1

[Execution audit V1](ALGOPACK_PAPER_EXECUTION_AUDIT_V1.md): source evidence→intent/fill/
mark recomputation→full ledger parity. Pushed/deployed e01a84b:400/400related Linux
tests UID999 PASS, включая10audit; local2+encoding2PASS/8Linux skips, Ruff PASS.
3SHA match, parents44/7 unchanged. [Server result](ALGOPACK_PAPER_EXECUTION_AUDIT_V1_RESULT.md). F=null.
Numerical forecast not recomputed yet; PASS does not grant economic admission.
Следом independent forecast/feature replay и evaluation/report wiring, official
calendar/latency checks, complete pre-F config/seal и service setup.

### Предшествующий этап — unified runtime scheduler/CLI V1

[Runtime V1](ALGOPACK_PAPER_RUNTIME_V1.md): pump first, persisted flow selection→slot,
daily scheduler, lifetime serving lock, explicit check/init/serve, no automatic reset.
Pushed/deployed a1b4cd7:390/390related Linux tests UID999 PASS, включая7runtime;
local1+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_RUNTIME_V1_RESULT.md). Deployed CLI --check REFUSED
без activation; F=null, --serve/--initialize не запускались, service не включён.
Следом offline economic source/forecast/Fill replay и evaluation/report wiring, official
calendar evidence/latency checks, full pre-F config/seal и server service setup.
Runtime code is not activated paper run; no actual market requests/trades in this work.

### Предшествующий этап — fixed as-of flow selection V1

[Flow selection V1](ALGOPACK_PAPER_FLOW_SELECTION_V1.md): latest completed current-day
metadata, no value ranking/fallback, full selected replay and immutable import reuse.
Pushed/deployed43adb25:383/383related Linux tests UID999 PASS, включая9selection;
local8+encoding2PASS/1Linux skip, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_FLOW_SELECTION_V1_RESULT.md). F=null; activation нет.
Следом unified runtime scheduler/CLI with persisted selection, offline economic audit/
evaluation wiring и full pre-F publication. No actual source selection/run executed.

### Предшествующий этап — due-position pump V1

[Due pump V1](ALGOPACK_PAPER_DUE_PUMP_V1.md): prioritized due exits/entries, shared
same-contract source, actual deadline cancellation/unresolved, durable outcomes.
Pushed/deployed01e964b:374/374related Linux tests UID999 PASS, включая8due-pump;
local2+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_DUE_PUMP_V1_RESULT.md). F=null; activation нет.
Следом fixed as-of witnessed-flow selection и unified runtime scheduler, offline
economic evidence/evaluation wiring и full pre-F publication. No actual economic run.

### Предшествующий этап — single-attempt slot runner V1

[Slot runner V1](ALGOPACK_PAPER_SLOT_RUNNER_V1.md): capture→predict→actual consumption
→marks→fixed8reserve decisions, durable attempts/phase failures/no retry of reserved slot.
Pushed/deployed506ad84:366/366related Linux tests UID999 PASS, включая7slot-runner;
local1+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_SLOT_RUNNER_V1_RESULT.md). F=null; activation нет.
Следом due-entry/exit pump, as-of witnessed-flow selection и unified runtime scheduler,
offline raw/economic audit/evaluation wiring до full seal. No actual forecasts/trades.

### Предшествующий этап — ledger-derived daily snapshot V1

[Daily snapshot V1](ALGOPACK_PAPER_DAILY_SNAPSHOT_V1.md): fixed18:20window, coverage+
anchored ledger counts+actual MTM, immutable report; late publication not evaluable.
Pushed/deployed0215cd2:359/359related Linux tests UID999 PASS, включая7daily;
local1+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_DAILY_SNAPSHOT_V1_RESULT.md). F=null, activation нет.
Следом runtime consumption/failure evidence, offline raw/economic replay и evaluation
wiring, затем scheduler/full seal. Full daily replay latency пока не long-run SLA.

### Предшествующий этап — fixed-slot publication coverage V1

[Coverage V1](ALGOPACK_PAPER_COVERAGE_V1.md): fixed42×4 denominator, timely publication
replay, missing/partial/late failures, independent arms и immutable daily report.
Pushed/deployed0d5bc62:352/352related Linux tests UID999 PASS, включая8coverage;
local2+encoding2PASS/6Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_COVERAGE_V1_RESULT.md). F=null; activation нет.
Следом scheduled ledger-derived daily snapshots, runtime consumption/failure evidence
и offline raw/economic replay, затем scheduler/full seal. Publication ≠ execution.

### Предшествующий этап — source-bound mark refresh V1

[Mark refresh V1](ALGOPACK_PAPER_MARK_REFRESH_V1.md): source replay всех открытых
позиций → anchored MARK → actual post-commit liquidation valuation. Missing/corrupt
source заменяет old mark на None, unresolved exit сохраняется. Pushed/deployed c9093ab:
344/344related Linux tests UID999 PASS, включая8mark-refresh; local1+encoding2PASS/
7Linux skips, Ruff PASS.3SHA match, parents44/7 unchanged.
[Server result](ALGOPACK_PAPER_MARK_REFRESH_V1_RESULT.md). F=null; activation отсутствует.
Следом durable decision coverage, ledger-derived daily snapshots/offline evidence
replay и scheduler до полного seal. Оперативная MTM ещё не daily evaluation snapshot.

### Предшествующий этап — source-to-ledger execution bridge V1

[Execution bridge V1](ALGOPACK_PAPER_EXECUTION_BRIDGE_V1.md): consume/replay source refs
→ fixed intent/fill → anchored RESERVE/ENTRY/EXIT; missed entry CANCEL, missed exit
UNRESOLVED без повторных событий. Pushed/deployed b1fa29c:336/336related Linux tests
UID999 PASS, включая8bridge; local1+encoding2PASS/7Linux skips, Ruff PASS.3SHA match,
parents44/7 unchanged. [Server result](ALGOPACK_PAPER_EXECUTION_BRIDGE_V1_RESULT.md).
F=null, actual activation отсутствует. Следом MTM refresh, durable decision coverage,
ledger-derived daily snapshots/offline evidence replay и scheduler до полного seal.

### Предшествующий этап — portfolio command/anchor V1

[Portfolio anchors V1](ALGOPACK_PAPER_PORTFOLIO_ANCHOR_V1.md): отдельный control journal,
prior commands/sequential anchors и восстановление одного committed события без
повторного исполнения. Missing genesis/history не становится новым капиталом.
Pushed/deployed core2e81686/test266d269:328/328related Linux tests UID999 PASS,
включая13anchor; local1+encoding2PASS/12Linux skips, Ruff PASS.3SHA match,
training44/witnessed7 unchanged. [Server result](ALGOPACK_PAPER_PORTFOLIO_ANCHOR_V1_RESULT.md).
F=null; production activation отсутствует. Следом evidence-bound runtime, missed-exit
policy, daily ledger snapshot producer и scheduler; source-economic proof ещё не готов.

### Предшествующий этап — bounded-read portfolio session V1

[Portfolio session V1](ALGOPACK_PAPER_PORTFOLIO_SESSION_V1.md): startup full replay,
hot append с tail check/общим lock, cache invalidation при конфликте/uncertain write.
Pushed/deployed799c935:315/315related Linux tests отUID999 PASS, включая8session.
Local1+encoding2PASS/7Linux skips, Ruff PASS.3SHA match, training44/witnessed7 unchanged.
На том же synthetic501event journal old append0,1356сек, hot median10writes0,0401сек;
restart parity PASS. [Server result](ALGOPACK_PAPER_PORTFOLIO_SESSION_V1_RESULT.md).
Экономика unchanged; F=null, actual market requests/trades0. Не считать benchmark SLA.
Следом integrated runtime/evidence/anchors, recovery и scheduled daily snapshots.

### Предшествующий этап — fixed daily evaluation V1

[Evaluation V1](ALGOPACK_PAPER_EVALUATION_V1.md): полный calendar denominator, daily
snapshots18:20Moscow, missing/unresolved masks, independent arms/costs, total return/
daily MDD/годовые returns. CAGR/Sharpe только252sessions+365days, без promotion.
Pushed/deployede014b7a:307/307related Linux tests отUID999 PASS, включая17evaluation;
local17+encoding2PASS, Ruff PASS.3deployed SHA match; training44/witnessed7 unchanged.
[Server result](ALGOPACK_PAPER_EVALUATION_V1_RESULT.md). F=null, actual economic results0.
Следом integrated source-evidence runtime/daily snapshot builder, recovery/anchors и
fixed stability/forecast evaluation. Pure metrics не доказывают переданный ledger SHA.

### Предшествующий этап — portfolio state/replay V1

[Portfolio V1](ALGOPACK_PAPER_PORTFOLIO_V1.md): aggregate reservations, independent arms,
liquidation MTM1×/2×, unknown equity masks, immutable sequence/restart и external-tail
check реализованы. Pushed/deployed3f4767d:290/290related Linux tests отUID999 PASS,
включая13portfolio. Local11+encoding2PASS/2Linux skips, Ruff PASS.3deployed SHA match;
training44/witnessed7 parents unchanged. [Server result](ALGOPACK_PAPER_PORTFOLIO_V1_RESULT.md).
F=null; actual requests/forecasts/trades0. Нужны evidence-bound runtime event builder,
missed-exit recovery policy, evaluation и scheduler до complete activation.
Не выдавать ledger consistency за реальное исполнение и не удалять unresolved риск.
Текущий append replay-ит весь journal: до длинного run нужен verified incremental
runtime state/anchor или measurement latency; synthetic13 не доказывают scalable runtime.

### Предшествующий этап — dated BBO/calendar execution source V1

[Execution source V1](ALGOPACK_PAPER_EXECUTION_SOURCE_V1.md): joint dated BBO/specs,
calendar terminal pagination/clearing masks, bounded activation-gated transport,
per-response journal и replay→Quote/Terms/Session. Pushed/deployed5f86c8f:277/277related
Linux tests отUID999 PASS, включая27source tests. Local25+encoding2PASS/2Linux skips,
Ruff PASS.3deployed hashes match, training44/witnessed7 parents unchanged.
[Server result](ALGOPACK_PAPER_EXECUTION_SOURCE_V1_RESULT.md). F=null;
actual requests/forecasts/trades0, production activation отсутствует/verifier REFUSED.
Реальные calendar titles/schema/entitlement ещё не наблюдались; не угадывать их.
Следом portfolio ledger/evaluation/runtime, не новый source-only audit или обучение.

### Предшествующий этап — fixed paper execution core V1

[Execution V1](ALGOPACK_PAPER_EXECUTION_V1.md): fixed intent/sizing/cost buffer,
causal quote-fill window и conditional1×/2× costs реализованы;28local synthetic tests PASS.
Тариф broker3RUB условный, не подтверждённый. F=null; actual prices/forecasts/trades0.
Следом dated BBO/session source, durable portfolio ledger/evaluation/runtime и full
pre-F activation. Existing book exchange_date_verified=false нельзя вручную повысить.
Pushed/deployed0377697:250/250related Linux tests PASS отUID999, включая28execution;
local28+encoding2PASS, Ruff PASS.3deployed hashes match; training44/witnessed7 unchanged.
[Server result](ALGOPACK_PAPER_EXECUTION_V1_RESULT.md). Activation/config/seal отсутствуют,
verifier REFUSED доHTTP. Это conditional simulation primitives, не economic run/ledger.

### Предшествующий этап — witnessed flow → forecast bridge V1

[Predictor V1](ALGOPACK_PAPER_PREDICTOR_V1.md): source replay/journal/actual receipt
mapping и paired inference→durable publication соединены. Новый модуль требует себя
в activation closure; production registry отсутствует, F=null. Pushed/deployede83a045:
11/11new integration tests и222/222related tests PASS отUID999. Local1+encoding2PASS/
10Linux skips; Ruff PASS. Все3deployed hashes match; training44/witnessed7 closures PASS.
[Подробности проверки](ALGOPACK_PAPER_PREDICTOR_V1_RESULT.md). Actual market requests/
forecasts/trades0: synthetic prices, fake model bytes, no production activation.
Следом fixed execution/evaluation/runtime и его единый pre-F seal. Forecast wiring уже
соединён; не повторять обучение или source-only audit как отдельное исследование.

### Предшествующий этап — activation verifier + full packet capture V1

[Capture V1](ALGOPACK_PAPER_CAPTURE_V1.md) соединяет market source с immutable journal,
полным raw replay и source→model clock mapping. Activation verifier требует будущие
execution/evaluation/runtime files и transitive parents; registry/config пока отсутствуют,
F=null. Pushed/deployed43c4cd9; Linux211/211 related tests PASS, отдельно21/21 activation/
capture tests отUID999 PASS. Local18PASS/3Linux integration skips. Все5deployed SHA
совпали с local; training44/witnessed7 parent files unchanged. [Server result](ALGOPACK_PAPER_CAPTURE_V1_RESULT.md).
Missing production
activation реально проверена от service user: REFUSED до HTTP. Проверки только synthetic.
Actual HTTP/forecasts/trades0, новых ключей/config activation/timers не создавалось.
Неблокирующе запрошены broker/tariff для комиссии; пока ответ не получен, его не выдумывать.
Следующий шаг: witnessed flow→journal→inference bridge и synthetic end-to-end forecast,
затем fixed execution/evaluation/runtime и единая activation до начала нового периода.
Не повторять завершённые тесты/обучение как новый эксперимент. Новая доходность не измерена.

### Предшествующий этап — immutable paper journal V1

[Journal V1](ALGOPACK_PAPER_JOURNAL_V1.md) реализован: exclusive per-slot events,
fsync/readback/hashes, failure preservation, actual observation clock, source-reference
validation и late-consumption masks. Pushed/deployedfdb8b42; Linux180/180 related tests
PASS, отдельно все33journal tests отUID999 PASS, включая19durability cases.
Local14pure+encoding2PASS/19Linux-onlyskips.3deployed hashes match; parent training
closure44/44 PASS. Core SHA `d5fc58bdbfa1f25be5cee9234b473bf185fa0462889ac12b0aa0c239af3e21a7`,
tests `c67c4ebafcea50f88b5b60b764141a48e9a57e882fc2fad579f6597055042530`.
F=null, actual source/forecast writes0; испытания только synthetic temporary events.
Следом full source capture/replay + input assembler + fixed execution/evaluation activation.
Готовые primitives не повторять как отдельные исследования; соединить их в рабочий runtime.

### Предшествующий этап — market source core/transport V1

[Market source primitives](ALGOPACK_PAPER_MARKET_SOURCE_V1.md) реализованы:
bounded apim candles/book/specs routes, post-F Moscow-midnight request rule,
whole-table timestamp-before-numeric candle guard, explicit empty terminal pagination,
book/spec masks и bounded TLS transport без retries/redirects/body leaks.
70новых synthetic tests; related local149/149 +encoding, Ruff PASS. Pushed/deployed197c9e0,
Linux147/147 PASS. Все5deployed file hashes совпали с local; parent training closure44/44
и public application CA hash PASS отUID999, HTTP requests0. Core SHA
`6a83db1d6a3523b8028032c539baf1e41f9fae167f0cc407ed8b561dfa630cc5`, transport
`c7d9207a279e892ae51831ed1b11fd577bc55c52fb91c9ad6ce20ee2704449a8`.
Далее full activation/capture/writer/execution/evaluation runtime, не повторение parser tests.
НЕТ collector CLI/timer/actual requests: F=null, prices_read=false для нового источника.
VALIDATED_NOT_PERSISTED/available_at=null не позволяет использовать ответ для inference.

### Предшествующий этап — future inference core V1, ещё без real forecasts

[Inference core V1](ALGOPACK_PAPER_INFERENCE_V1.md) реализован: exact model hashes,
last-as-of source versions, отдельная baseline/full eligibility, no target API,
post-calculation deadline и явный COMPUTED_NOT_PERSISTED/execution=false.
New20synthetic tests, local89/89 с related model/alignment/runner+encoding, Ruff PASS.
Pushed/deployed `79e4795`; Linux87/87 PASS. Model-only reader от UID999 проверил обе
реальные pinned модели/schema20/40→4 без новых prices/labels; training closure44/44 PASS.
Deployed core SHA `173a7cb71cab47c7820d78f5ac2c5bd1ebdec626d55517e1924ce541c3bce788`,
tests `e55d6188369267d30550dc62e0a929f2ae43bef60ec717a1bb199b50df4c3794`,
doc `28378a040c9077060d4d40ef683b4375482c80be0f5ac8ff461ca693a517df89`; local/server match.
Следующий шаг — новый future source, durable forecast writer и fixed execution/evaluation
seal. F=null; actual forecasts0. Не повторять model training/decoder-only test как новый опыт.
Official docs подтверждают authorized apim real-time candles/orderbook в отличие от
15min anonymous candles; actual account entitlements ещё не проверены price request.
Witnessed FO collector работает: timeractive/waiting,last17:53UTC,next18:03UTC,
последний service terminal success/0. Новые local tasks/collectors не создавались.

### Предшествующий этап — paired training V1 TRAINED_NOT_EVALUATED

[Первое AlgoPack обучение завершено](ALGOPACK_PAPER_TRAINING_V1_RESULT.md): две fixed Ridge
20price/40price+flow features на одинаковых56996joint rows2020–2025, из63588candidate rows.
Started17:44:46.513872UTC, completed17:46:26.964097UTC, server service success/0, no network.
Seal44files `bb95784a169fd4c163c5df4ada231404321ea6e8bf5b8271425e0c869b7ebca2`,
canonical `/srv/trading_lab_data/runs/algopack-paper-training/algopack_paper_training_v1_bb95784a169f`.
Manifest SHA `028b2cead7111868ef345987e696be2d70aadd8bbaa0a8233ff676dd38fd7527`.
Pre-run pushed bfc7860; Linux105/105 target tests, расширенные250/250; local249pass/3skip.
Independent artifact/scaler/mask/Ridge-equation/provenance audit PASS, all9 artifact hashes PASS.
Actual <=2025 prices/labels теперь читались только для authorized training; forecasts/trades=0,
CAGR/Sharpe/MDD=N/A. Canonical/sealed code не повторять/не tune-ить. Цель20%/50% не достигнута.

Inference adapter теперь реализован; следующий bounded шаг — новый price/source/
execution/evaluation protocol и durable forecast writer. F пока=null;
до всех новых seals старые2026 prices/labels закрыты. Подробнее — result note выше.

### Предшествующий этап — price inputs COMPLETE

Новый полный price root `/srv/trading_lab_data/data/algopack-paper-price-inputs-v1`
проверен:662files/79219007bytes,1699545source rows; timestamps/contract/aggregate gates
и independent exact membership/all-file hashes PASS от trading-lab. Assembly manifest
220048bytes SHA `635f33d3da3d82a3328121f251486a79c123e478da7c1fd1de8b01999f184b7c`,
created2026-09-07T17:17:59.585523UTC. Root0750/UID999. Цены/labels/fit не читались.
V2 map correction:6044eligible rows/1518dates, four missing prior-date rows masked;
local77passed/1skip, Linux76/76. [Подробности и failure history](ALGOPACK_PAPER_INPUTS_V1.md).

Зафиксированная [paired training specification](ALGOPACK_PAPER_TRAINING_SPEC_V1.md):
20price vs40price+flow features, два fixed Ridge alpha10, одинаковые2020–2025 training
rows, separate labels/provenance; минимум5000joint rows. Executable config/code/
input seal и первый server training теперь COMPLETE. Никакого
ретроспективного AlgoPack CAGR. Сборку root/metadata preparation повторять нельзя.

### Основание и предшествующая реализация

Пользователь2026-09-07 явно разрешил предложенный эксперимент: [точный scope](ALGOPACK_PAPER_AUTHORIZATION_20260907.md).
AUTHORIZATION gate снят; повторно согласие не спрашивать. Training только на архиве
2020–2025 с оговоркой current-vintage; evaluation только после будущей границы F,
следующей за code/config/model seals. Старый2026 закрыт, live/broker orders запрещены.
Следующий шаг — обоснованный time/schema mapping и изолированный feature/label adapter,
затем executable protocol и input closure до обучения на gpu-mlserver.

[Alignment V1](ALGOPACK_PAPER_ALIGNMENT_V1.md) реализован:local38 + encoding2 PASS,
server38/38 PASS после commit/push `3f5f397`, Ruff PASS. Есть
отдельные online receipt / current-vintage training selectors, five flow/depth features
и независимые60m labels без future-target inference filtering. Official SDK трактует
tradetime как конец5m interval; Moscow mapping пока явное paper assumption, не гарантия
full session semantics. Код ещё не economic-sealed; реальные labels/fit не запускались.
Training OHLCV bundle найден на сервере в `data/v62-legacy-source-v1/data/processed/futures_v7_10m/`:
top и4asset manifest hashes совпадают; transitive input admission ещё предстоит.
Следующий конкретный шаг — manifest-bound loader и joint price/flow paired model protocol,
затем server training после seal. Не повторять permission review или завершённые quality runs.

### Подготовка price inputs

Новый [input loader V1](ALGOPACK_PAPER_INPUTS_V1.md) подготовлен отдельно:
transitive raw/Parquet hashes, protected time-only gates перед prices, causal active map
с сохранением ineligible rows. Local30passed/1 Windows skip/Ruff PASS;
Linux31inputs +38alignment PASS. Real preflight обнаружил missing raw219 и1empty Parquet
в старой V62 copy: они перенесены из originals в новый отдельный server root
`/srv/trading_lab_data/data/algopack-paper-price-inputs-v1`, старый не изменён.
Intraday tree нового root прошёл checks; active map V1 остановился на4nontradable
2018-01-03 rows с missing prior dates. Новый V2 сохраняет их masked, effective-date и
protected gates прежние. V2/Linux tests и завершение metadata admission уже выполнены,
итог/canonical в начале STATUS; повторно копировать данные нельзя. Цены/labels не читались.

### Историческая запись admission review

[Admission review V1](ALGOPACK_TRAIN_TODAY_ADMISSION_REVIEW_V1.md) завершён2026-09-07:
полученный сегодня архив потенциально пригоден как учебный материал, но это отдельная
гипотеза переноса final-vintage в online, не historical causal admission. Правила требуют
доступности training features к historical decision; market outcomes>=2026 запрещены.
Оба ограничения действуют. Новые labels/цены не читались, fit/predictions/PnL не запускались.

Нужен явный выбор: допустить отдельный paper-only эксперимент с current-vintage архивом
2020–2025 для обучения и новым будущим периодом цен/результатов строго после code/model
seal, без открытия прежнего2026 и без retrospective AlgoPack CAGR. Согласия пока нет.
Даже после согласия остаются gates timezone/bucket completion, row-level calendar,
exact execution и полный protocol seal. Review выявил, что V32 learning eligibility
читает future label path/target presence: готовую learning frame не переносить в online.
Не подменять ожидание решения пользователя повторными source audits/новыми timers.
Предыдущий turn дал progress через publication evidence; этот завершил admission review.
Это конкретный объединённый future-paper вариант, не готовый run и не сброс blocker audit.

## Предшествующий результат — AlgoPack publication metadata COMPLETE

[Publication metadata V1](ALGOPACK_FO_PUBLICATION_METADATA_V1.md) завершён один раз:
full source replay PASS, six-column projection2067949rows, independent report/hash/
group/count check PASS. Local389passed/4 Windows skips, Linux391/391, pre-run47b2c5e.
87,1761%rows имеют SYSTIME на более позднюю дату, чем tradedate; весь label2020–2023
позднее опубликован. Минимум SYSTIME2024-04-11, максимум2026-03-16;1056TSrows имеют
publication>=2026 (704label2023 +352label2025). Protected2026 market outcomes не читались.
Same-day TS132953/1007214, OB132238/1060735 не означают полной intraday causal admission.
Canonical `/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_publication_metadata_v1_b07f52140345`;
manifest `1bff6855218cceba6d815d137047458a089f3deec184f9325a99d3f2ed6afeda`.
Handle57424 terminal success/exit0,2min2.625s,created12:37:53UTC. Не повторять этот audit.

Назначенный здесь training-today design review уже выполнен, итог и оставшийся выбор
вверху. Это не ретроспективный backtest и не разрешение читать2026 outcomes; старые
source/model flags не изменены. Пока не читать новые labels и не fit-ить модель.

### Предшествующее уточнение поставщика

2026-09-07 около12:22UTC через открытую почту найден и прочитан ответ
`algopack@moex.com` на исходный запрос. [Сводка и точные ограничения](ALGOPACK_VENDOR_REPLY_20260907.md).
Подтверждены личное использование и SYSTIME как время публикации. Уточнения о
том, обновляется ли timestamp при исправлении исторической версии, нет.
FO OrderStats полный продукт только ожидается поставщиком до конца года; не считать
доступным сейчас. Письмо не является model/live admission. Новых сообщений не отправлено.
Следующий безопасный source шаг: отдельно sealed metadata-only audit исторического
SYSTIME (без prices/labels/PnL) на уже собранных inputs. Ни canonical history, ни
cohort quality повторно не запускать. User exploratory exception всё ещё не подтверждён.

Новый [publication metadata V1](ALGOPACK_FO_PUBLICATION_METADATA_V1.md) sealed до
анализа SYSTIME:34-file closure `b07f521403456484656a1de2b62801665d1449cd941aa781af0d5f8c9f7b5db5`;
новые tests31/31 до run. План выполнен, actual result/canonical/SHA приведены вверху.
Только6metadata fields после полного parent replay; новый run запрещён.

## AlgoPack witnessed quality COMPLETE, два scheduled PASS

Второй scheduled capture12:13UTC подтверждён:
`20260907T121300596553Z_881ff271b008`, 4913rows/16pages,
manifest `8e4c7721b54dc6fb8ca61b5affc0da89edc326ba3ccec8d2bdd00256827df807`.
Новый [witnessed quality](ALGOPACK_FO_WITNESSED_QUALITY_V1.md) завершён один раз,
pre-run commit/push3078c31, local358passed/4 Windows skips, Linux360/360.
Три full source replays PASS + independent version-index/hash/receipt check PASS.
4913unique keys/14659version observations/9746reobservations; new keys4865/16/32.
Feature/SYSTIME/metadata revisions0, dropped/reappeared/missing/alias0 на этом cohort.
Shared TS/OB2329/2337/2353, OB-only207, TS-only0. Negative spread_l1/l10=19/3 в
каждом снимке, сохранены как unresolved для feature/execution semantics, не как
отрицательные trading costs. Не суммировать повторные source rows как unique samples.
Canonical `/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_witnessed_quality_v1_64cc5d369fd0`;
manifest `4b9cc6fe93d902e42c0fb817faec40c8fb3f3e523b46c86772afed6a3d2babd5`.
Run terminal success12:14:26UTC,1.420s. Timer active/waiting next12:23UTC;
incomplete captures0. Не повторять quality cohort; prediction/historical/live=false.

### Хронология запуска witnessed source

Новый [witnessed source](ALGOPACK_FO_WITNESSED_V1.md) подготовлен отдельно от frozen
истории и старых collectors: current RFUD/series discovery, 8 exact SECIDs,
TS/OB full cursor, immutable raw/normalized/receipt snapshots, full replay.
Окно D−2..D+14 относится к vendor date labels, не к доступу к будущим наблюдениям.
Closure `67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26` (7files).
Pre-request commit/push `7cd5371`; local341passed/4 Windows skips, Linux343/343.
Manual capture 2026-09-07 11:56:59.545856–11:57:12.184771 UTC: 4865 rows/16pages,
2329 TradeStats +2536 OBStats, 8 current SECIDs. Полный replay внутри collector PASS;
отдельный PrivateNetwork audit также PASS. Canonical:
`/srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1/20260907T115659545856Z_b813c3346d94`.
Manifest SHA `d0e031f1e03599aa72cb0d9d1d84a78742e373bb574195918693363cd596d740`.
Новый `trading-lab-algopack-fo-witnessed-v1.timer` enabled/active/waiting,
каждые10min в :03/:13/:23/:33/:43/:53 UTC. На11:58:41UTC LastTrigger ещё пустой;
первые два scheduled captures назначены12:03/12:13UTC.
Первый scheduled capture уже подтверждён: `20260907T120300520961Z_f925ca4d538a`,
12:03:00.520961–12:03:16.667562UTC, 4881rows/16pages (TS2337/OB2544).
Manifest SHA `de98c9d66227585abc9148f22b07c3086fadf853857079ccc8e6fd0bd2bedba4`;
встроенный replay и отдельный PrivateNetwork audit PASS. Manual manifest неизменён,
incomplete attempts0. Timer active/waiting, LastTrigger12:03UTC, next12:13UTC.
Этот ранний checkpoint superseded подтверждённым вторым capture и quality вверху.
Существующие15timers не изменялись (всего теперь16), локальные tasks не включались.
Historical/model/live flags=false; source PASS не доказывает прибыль или PIT историю.

Новый [witnessed quality V1](ALGOPACK_FO_WITNESSED_QUALITY_V1.md) sealed до анализа:
три фиксированных captures до12:14UTC, separate unique/repeated/revised versions,
полный parent replay и immutable receipt index. Closure
`64cc5d369fd0e49efff57dddbfbd2657679e1abcd7453fc59f53d38b4a70c40e`; pre-run local17/17.
План выполнен: PrivateNetwork source-only report завершён, canonical/SHA вверху.
Это не historical model admission; повторный run запрещён.

## AlgoPack history и quality V1 COMPLETE

Позднее 2026-09-07 пользователь сообщил о покупке подписки и передал API key с явным
разрешением начать работу. Прежнее откладывание покупки больше не определяет очередь.
Ключ установлен через hidden SSH stdin только в `/etc/trading-lab/collector.env`,
`root:trading-lab 0640`; значение не помещено в Git, argv, raw или journal.
Оба исторических FO route дали authenticated HTTP 200 и ожидаемую metadata-схему.
V1 прошёл все 16 страниц TradeStats (15 023 строки), но остановился на первой OBStats:
19 из 1 000 строк имеют отсутствующий asset_code. Полный OBStats cursor заявляет
65 550 строк; это ещё не завершённая выгрузка. Canonical V1 не опубликован.
Отдельная V2 сохраняет null/empty asset_code с mask/count без вывода алиаса;
остальные schema/date/SECID/cursor guards остаются строгими. V1 не изменяется.
TLS/hostname проверяются с закреплённым MOEX CA только для AlgoPack service;
system trust и остальные collectors не менялись. См. source protocol для hashes.

V2 завершён один раз: 15 023 TradeStats / 65 550 OBStats, 82 страницы, audit 11/11.
Missing asset_code: TradeStats 0, OBStats 1 218; сохранены без подстановки.
Canonical external directory:
`/srv/trading_lab_data/data/processed/algopack/moex_algopack_fo_historical_inventory_v2_1da8655bf03d`.
Manifest SHA `89896f3a1647db6a7d1c794cc98745dec48123a4dbe6355baccfac2d8894f242`.
Для SiZ4/RIZ4/BRX4/MXZ4 по 163 TradeStats и 174 OBStats; все 163 ключа TradeStats
присутствуют в OBStats. Aliases Si/RTS/BR/MIX. 11 OB-only ранних bucket не заполнять
нулём. Pre-request commit `31bfc79`, local 73/73, server V2 28/28.

Flow/depth sample V1 завершён один раз после commit `09ac39f`: 652 TradeStats +
696 OBStats = 1 348 строк, 8 страниц, exact parent coverage PASS, audit 11/11.
Canonical `/srv/trading_lab_data/data/processed/algopack/moex_algopack_fo_flow_depth_sample_v1_49502b17c35a`;
manifest SHA `6a14b3f9c724725375e99363e2ed26ae247b9e52e6bb1d4a9523e7ac11749502`.
Local targeted 110/110, server sample 37/37. В каждом контракте spread_l1/l10 имеют
два null (09:55 и 10:00); один из них в совместном TS/OB ключе. Остальные selected
numeric fields без null на этом sample. Missing остаются mask, не 0 и не guessed fill.
Source technical PASS не даёт historical/PnL/live admission; SYSTIME unresolved.

Следующий шаг — отдельный resumable historical source protocol 2020–2025 с contract
ranges из pinned active map (147 SECID, 294 dataset jobs до cursor), полный raw audit
и coverage/missingness. Только затем отдельный экономический протокол новой информации.
Sample source frozen; не менять его после чтения и не запускать повторно.
Новый [history protocol](ALGOPACK_FO_HISTORY_V1.md): deterministic contract ranges,
resumable per-page provenance и full replay. Pre-request code/config closure
`c5fb0b96b12d77f5c01b1625b0b9b7ab582ed82d09117dc6217d577de33751d1` verified;
local targeted210 passed/1 Windows symlink skip, Linux case обязателен до сети.
Pre-request commit/push `84a1661`; Linux tests101/101 (включая symlink case),
runtime preflight от trading-lab PASS: 21 closure file, parent audit11/11, plan294jobs.
Plan SHA `30a6f1729f5a0213f06595cf60309fef820bd75088ecb4240ab6ded13591c01f`.

Batch завершён один раз: `success/exit0`, 25min57s, 294 jobs /2067949 rows /2198pages,
committed retries0. Unit `trading-lab-algopack-fo-history-v1-c5fb0b96b12d.service`,
invocation `4168e5c2f6f741d0a3324715fb933c9d`, handle36051 завершён. Collector выполнил
полный raw replay перед atomic publication. Canonical:
`/srv/trading_lab_data/data/processed/algopack/moex_algopack_fo_history_v1_c5fb0b96b12d`;
manifest SHA `f50fa60a6986070d45f6a69555076df1f5748d09b70407131591740e77425fb4`.
Source date admission=false: расхождения active-map dates сохранены, не исправлены.
Это успешный технический сбор, не полное календарное покрытие и не доказательство alpha.

Новый [metadata quality V1](ALGOPACK_FO_HISTORY_QUALITY_V1.md) запечатан до своего run:
closure `b57b9b226d63842dd0a3c09bafcd98746bcd48f383324f53e0b1bb4558f260ba` (28files),
config `8a6a356e4aac9c2b4643b7c7a1110a6047b6257d8d01b2918aeb560450d7c59e`.
План: отдельный full source audit, затем five-column metadata projection /exactTS-OB
alignment /counts по годам. Local187passed/3 Windows symlink skips, Ruff/closurePASS;
новые Linux cases проверены: server188/188, без skips. Pre-run commit/push `597da59`.
Quality завершён один раз: unit `trading-lab-algopack-fo-quality-v1-b57b9b226d63.service`,
handle12148 terminal success/exit0, 51.280s; invocation `1ccbf24f36ae4fdc953c58fa81157c03`.
PrivateNetwork=yes, no env/key; отдельный full raw replay PASS и metadata projection.
Canonical `/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_history_quality_v1_b57b9b226d63`;
manifest SHA `26342273cc79f4d168486651ba6a2369bece2a12465c7dac2e7ba3eef3fe558a`,
quality SHA `51b296bccb9c369baf54481fe6e726cfc5431a2ebd012fa24981df4b7c055a6a`.
TradeStats1007214/OBStats1060735; shared keys1000331, TS-only6883, OB-only60404.
Duplicate/off-grid/empty/alias issues0; source date admission=false (TS36missing/86extra,
OB8missing/116extra contract-dates). Null L1/L10 spread11143/13035, negative124/9.
Особенно важно: OBStats включает weekend SI keys без SI trades. Наличие стакана не
доказывает торгуемую сессию. Таблицы по годам/активам — в quality protocol/report.
Историю не перезапускать/не переписывать; audit берёт её exact manifest SHA.
Цель доходности не достигнута; real trading/брокер не подключаются.
Описание: [ALGOPACK_HISTORICAL_SOURCE.md](ALGOPACK_HISTORICAL_SOURCE.md).

Индексная ветка дала проверку API/архива и незапечатанный prototype с synthetic tests,
но source collection не запускался. Сохраняется как следующий независимый кандидат;
не запускать prototype до review и seal. Старые server collectors не менялись.

## Предыдущий завершённый эксперимент — V64 NO_GO

2026-09-07 пользователь отложил покупку и поручил исследовать другие гипотезы.
То откладывание покупки superseded более поздним сообщением пользователя выше;
новые покупки/смена тарифа/автопродление не разрешены.
Уже отправленное письмо не отзывать и не дублировать; ответ может быть рассмотрен позже.

V64 — фиксированный short SI перед номинальным налоговым сроком против окна на
14 дней раньше — завершён один раз на `gpu-mlserver`. Все 18 ledgers complete/flat,
но гипотеза не прошла заранее заданный screen. Это проверка календарной proxy,
не утверждение об отсутствии любого налогового эффекта и не повтор V19/V49.

| Era | CAGR primary / doubled / stress | CAGR control primary | MDD primary | Round trips |
| --- | ---: | ---: | ---: | ---: |
| 2008–2011 | 2,82% / 2,43% / 2,29% | −1,12% | 9,30% | 37 |
| 2012–2017 | 2,03% / 1,66% / 1,55% | 0,53% | 19,27% | 70 |
| 2018–2025 | −0,16% / −0,23% / −0,31% | 0,58% | 25,11% | 96 |

В ранних eras только 2/4 и 2/6 положительных годовых сегментов, ниже gate 60%.
В recent primary/stress отрицательны и хуже контроля. Итого 203 round trips primary;
20%/50% gates false, независимого holdout/live admission нет. Не подбирать окно/знак.

До economics: commit/push `238a0ed`, local targeted tests 42/42 (V64 17/17), server
synthetic 17/17 и metadata preflight 45/45. После run — read-only audit 156/156.
Seal SHA `b60a02b4ba1d5ea3dedcc0f82e5090cc82fea40cc1c7864f851a97b0ee39bbff`;
canonical `/srv/trading_lab_data/runs/v64_si_tax_calendar_v1_b60a02b4ba1d/`, metrics
SHA `e6b1372dcfe59dde395bb418f20f6391435ce54df488250a904c03384540f277`.
Фактические границы, годы, costs и ограничения — [V64_TAX_CALENDAR.md](V64_TAX_CALENDAR.md).

Следующая новая механика: объявленные включения в биржевой индекс и предполагаемый
спрос индексных фондов до даты пересмотра. Source-only проверка нашла шесть официальных
публикаций для трёх событий 2023–2025; это не шесть независимых наблюдений и не полный
исторический корпус. Подтверждены проблемы повторных публикаций и листов ожидания.
До экономического seal/теста нужен датированный versioned corpus и PIT instrument map.
Конкретный следующий шаг: [MOEX_INDEX_REBALANCE_SOURCE.md](MOEX_INDEX_REBALANCE_SOURCE.md).

## История до покупки AlgoPack — проверка PROMO и временное откладывание

2026-09-07 пользователь предложил рассмотреть подписку за 610 ₽, если она полезна.
В открытой карточке [AlgoPack](https://data.moex.com/products/algopack) проверен тариф
`PROMO`, период «на месяц», цена `610 ₽`. Указаны API/Python, Super Candles, FUTOI,
HI2, Mega Alerts, онлайн стаканы/свечи/сделки и машиночитаемый календарь.
Для Super Candles заявлены пятиминутные агрегаты и история с 2020 года; это не
только визуализация. Прежние ссылки на 600 ₽ не являются актуальной ценой этой карточки.

Рекомендация — ограниченный месячный пилот нового flow/book источника, не обещание
доходности. Фактическое покрытие FO TradeStats/OBStats, publication/revision semantics
и применимые права на хранение/личное ML нужно проверить. Кнопка оформления привела
к экрану входа DataShop; авторизация передана пользователю, никаких данных в поля входа
не вводилось. Финальная сумма checkout, продление и платная оферта ещё не проверены.
Условная готовность пользователя не считается акцептом договора, годовым бюджетом
или разрешением на автопродление. На том этапе покупки, нового аккаунта и API key не было.
Письмо MOEX уже отправлено, повторять его не нужно. Подробности и следующий шаг —
[DATA_ACCESS_REQUESTS.md](DATA_ACCESS_REQUESTS.md).

## Запрос тестового доступа MOEX — SENT, ожидается ответ поставщика

2026-09-07 пользователь явно разрешил подготовленный запрос тестового доступа и условий.
Прежний блокер отсутствия разрешения снят; не спрашивать повторно об общей готовности
обратиться в MOEX. Покупки/автопродление, акцепт договоров и live account не выполнялись.

Пользователь открыл Яндекс Почту в подключённом Chrome. Из текущего почтового аккаунта
отправлено одно письмо на `algopack@moex.com`, тема
«Тестовый доступ AlgoPack FO TradeStats/OBStats для личного исследования».
После отправки найдено именно это письмо в папке «Отправленные» с верными адресатом
и темой; интерфейс показывает `01:00`. Это подтверждение отправки почтовым сервисом,
не подтверждение доставки/прочтения MOEX или выдачи доступа.

Запрошены FO TradeStats/OBStats, личное автоматическое исследование, история 2020–2025,
sample 2024-10-15, publication/revision semantics и наличие FO OrderStats. В письме
явно указано не подключать платную подписку или автопродление. Вложений и копий нет;
приватные данные проекта, модели и результаты не отправлялись. Контактные данные
отправителя, account UID и посторонняя переписка в Git не сохраняются.

Первоначальная официальная веб-форма не отправлялась и закрыта после успешной отправки
письма. CAPTCHA не решалась, пользовательское соглашение формы не принималось. Блокер
контактных данных снят; не просить ФИО/e-mail повторно и не дублировать письмо.
Текущий статус `SENT_EMAIL_PROVIDER_CONFIRMED_AWAITING_VENDOR_REPLY`. Следующий шаг —
ответ именно по этому запросу, проверка условий/доступа, затем отдельный source seal.
Код, экономические протоколы, серверные collectors и canonical runs не менялись.
Подробности и исходный черновик — [DATA_ACCESS_REQUESTS.md](DATA_ACCESS_REQUESTS.md).

## История ожидания после V63 — 2026-09-06

Автопоиск требует ожидания пользователя/внешних данных. Один и тот же блокер
подтверждён в трёх последовательных goal turns: разрешения на внешний запрос нет,
credentials не появились, новая опционная история ещё не прошла discovery gate.
На третьей проверке metadata по-прежнему показывают 168 manifests только за три
source dates; даже верхняя граница возможных полных сессий 3 меньше требуемых 20.
Последний полный readiness подтвердил 2/20. Это не новая финансовая проверка и не
основание повторять закрытые семьи. Цель 20%/50% не достигнута и не снижена.

Условия возобновления: явное разрешение на подготовленный ограниченный запрос MOEX,
пригодные данные/права от пользователя либо достаточный новый forward период.
Токен сам по себе не заменяет права на использование. Server timers остаются
включёнными; пауза автоматического исследования не останавливает сбор данных.

2026-09-06 выполнена bounded source feasibility, не новый economic experiment.
В server `moex-microstructure-v1` только один target-free FUTOI snapshot: четыре
запроса, восемь строк, source audit 11/11; TradeStats/OBStats там не собирались.
AlgoPack/Interfax credentials отсутствуют. Корпоративные условия AlgoPack относятся
к юрлицам, поэтому нельзя объявлять корпоративную стоимость обязательной для личного
исследования. Наличие персонального API и старой ссылки на демо также не доказывает
доступ к нужной истории или права на наш ML workflow.

Подготовлен, но не отправлен запрос MOEX на ограниченный тест истории агрессивных
сделок и стакана, точные условия персонального использования и sample day. Нужна
отдельная авторизация пользователя на внешний запрос; покупок, регистрации,
акцепта условий, нового обучения и live trading не было. Подробности, доказательства
и черновик: [DATA_ACCESS_REQUESTS.md](DATA_ACCESS_REQUESTS.md).

15 server timers по-прежнему запланированы; failed collector units нет. В failed
research units сохранился старый preflight V62 с legacy-path PermissionError;
его не перезапускали и не сбрасывали. Канонический завершённый V62 не менялся.
Не повторять эту проверку при неизменных credentials/разрешениях как новый прогресс.
До ответа работают прежние frozen forward протоколы и их gates, без protected PnL.
Изменена только документация; encoding + V63 + source synthetic/seal tests 22/22,
`git diff --check` clean. Экономические configs, код и canonical artifacts не менялись.

### Независимая бесплатная ветка: verified wait, 2026-09-06 19:00 UTC

Разрешения на внешний запрос пока нет. Read-only проверка уже работающего option V2
source на сервере подтвердила `168` eligible snapshots, `0` invalid и `2/20` полных
discovery-сессий. 2026-09-03 и 2026-09-04 имеют по `83` снимка, span около `826` минут,
maximum gap около `16` минут; 2026-09-02 остаётся неполной сессией и не засчитывается.
Calibration `0/20`, unseen evaluation `0/60`, economic protocol admission `false`.

Все `168` parent manifests сопоставлены с `168` quality identities по hashes; нет
unpaired/mismatch. Свежий replay последнего quality report
`quality_snapshot_20260904T205500334111Z_b26c35c6` — `9/9`. Это не повторный полный
quality replay всех 168 reports: полный source replay выполнен readiness, quality
replay повторён только для последнего report, у остальных сверены связи и hashes.

`trading-lab-option-surface.timer` фактически `active/waiting`, следующий запуск
`2026-09-07 10:09 MSK`; последний service завершён `success/0` в `2026-09-04 23:55`.
Новый capture/restart не выполнялся, protected market values пользователю/агенту не
выводились, features/labels/PnL не вычислялись. Результат — проверенное ожидание данных,
не новая прибыль и не основание ослабить 20-session gate. Для ускорения основного
поиска остаётся нужен ответ пользователя на ограниченный запрос MOEX. Экономический
дизайн опционной ветки разрешён только после 20 полных discovery-сессий.

## V63 frozen profit attribution — COMPLETED, SAME RETURN DRIVER

Пользователь одобрил изменение порядка поиска: [RESEARCH_PROCESS.md](RESEARCH_PROCESS.md).
Выполнена accounting attribution V41/V49/V60 с V39 и cash-carry parent, без нового
обучения, изменения targets/fills/weights или просмотра protected 2026 outcomes.

До новых attribution values проверены input hashes/schemas/dates и формулы исходного кода.
`exact_futures_nav` у V49/V60 уже содержит collateral income и дублирует combined NAV;
он не является отдельной pure-futures equity curve. V63 использует сохранённые annual
futures summaries и order costs; не повторяет canonical executions.

V41/cash canonical originals остаются локально вне Git; восемь точных файлов скопированы
в новый server root `/srv/trading_lab_data/data/v63-profit-attribution-inputs-v1/`.
Transfer SHA `9dce79e6...`; старые run directories не менялись.
Seal/push/deploy `35ed00c`, config SHA `983b1a17...`, code SHA `73357a01...` предшествовали
одному завершённому server run. Canonical
`/srv/trading_lab_data/runs/v63_frozen_profit_attribution_v1_983b1a17/`, metrics SHA
`8b8a7532...`, identity SHA `c230a436...`; repeat read-only audit 183/183.

Главный вывод: у V49 primary net futures profit 4 518 093 ₽, modeled idle income
604 339 ₽ из общей прибыли 5 122 432 ₽ на стартовый 1 млн за пять лет. Значит, дело
не только в процентах. Но monthly correlation V49/V60 0,99337, V39/V41 0,99915:
лидеры в значительной мере повторяют один return driver. 2022 дал 51,73% net log growth
V49, а в 2025 его trading net −548 769 ₽ был частично компенсирован +334 009 ₽ процентов.

Cash sleeve действительно отличается по динамике (corr с V49 −0,17439), но его
primary CAGR всего 8,3450%; 59,28% всей прибыли sleeve — модельные проценты. В V41
cash с его процентами дал лишь 4,65% совокупной прибыли. Новая смесь тех же родителей
не является обоснованным следующим экспериментом. Цель 20%/50% не подтверждена.

V63 synthetic/seal tests 15/15 локально/на сервере; related + encoding bundle 30/30,
scoped Ruff clean. Первый service-user preflight остановился на root-owned V60 manifest
до NAV analysis; завершённый diagnostic выполнен bounded root process без изменения
прав старых артефактов. Детальный разбор, все costs/years/counts и ограничения:
[V63_PROFIT_ATTRIBUTION.md](V63_PROFIT_ATTRIBUTION.md).

## V62 opening regime — CANONICAL ECONOMIC NO-GO

Parent opening hypothesis `e1c1ab6`, config SHA `21b31830...`, was sealed but never
executed. The interrupted uncommitted implementation was rejected during code review:
current evening-bar existence and future target/exit volume affected morning eligibility
or sizing. No V62 market prices or outcomes had been loaded.

Separate pre-outcome admission V2 SHA `748d8e58...` preserves the parent strategy and
fixes these causal defects. Morning candidates never receive labels or inspect the
current evening. At a roll both gap endpoints use the same currently planned contract.
Candidate and label schemas are separate; outer and inner training use chronological
two-session purges. Entry requests use completed observations; exit capacity is applied
only on each actual exit attempt, with the original 12:20 deadline.

V2 запечатан/pushed commit `8ae2f77` до первого price-bearing run. Первый service attempt
от `trading-lab` завершился на чтении top manifest с `PermissionError`, до market load
и до создания output directory. Commit `f0012e5` добавил перенос только declared inputs:
444 файла / 58 304 850 bytes скопированы побайтно в
`/srv/trading_lab_data/data/v62-legacy-source-v1/`. Старые архивы и права на их родительские
каталоги не менялись. Повторный metadata-only preflight от service user подтвердил 218
market artifacts / 1 699 545 rows, 2 025 sessions, 8 064 causal plan rows, protected rows 0.

Единственный economic run завершён на сервере с `ExecMainStatus=0`:
`/srv/trading_lab_data/runs/v62_opening_regime_v2_748d8e58/`.
Metrics SHA `6814d37dafde68c96618431ce7b169848d521938d6625774df527aa3ec7ca1f3`,
identity SHA `e6cb807ef9617d33f2a577525221d6deea6157c6043e91bb536cbc27650092fa`.
Независимый audit в соседнем каталоге `_audit_v1` прошёл 157/157 checks, включая SHA,
нефильтрованный inference universe, accounting conservation и replay CAGR/Sharpe/MDD.

Всего 7 259 causal candidates; OOS 2021–2025 — 5 609 прогнозов на каждый из четырёх arms.
MLP: 728 направленных решений, 320 завершённых сделок, 11 no-fill, unresolved 0 во всех
трёх сценариях. Все primary/doubled/stress MLP ledgers прошли полный горизонт.

| MLP scenario | CAGR | Sharpe | Daily MDD | Intraday marked MDD |
|---|---:|---:|---:|---:|
| Primary | −0,6508% | −0,2324 | 10,3535% | 10,7399% |
| Doubled costs | −1,5941% | −0,5889 | 11,7059% | 12,1549% |
| Stress | −2,5343% | −0,9275 | 13,1151% | 13,4843% |

Primary годы: 2021 `−1,8797%`, 2022 `−4,3516%`, 2023 `+0,6117%`, 2024 `+1,4487%`,
2025 `+1,0468%`. Итог капитала 1 000 000 → 967 952,19 RUB; fees + slippage 42 945,09
RUB. Арифметический gross PnL тех же фактических размеров всего +10 897,28 RUB: издержки
превысили выявленный эффект. Это decomposition ledger, не отдельный zero-cost backtest.

Logistic baseline также complete и отрицательный: primary CAGR `−0,9591%`, 508 trades.
Fixed fade/continuation arms остановились на незакрытом BR `2025-02-25`; их partial
metrics не являются full-period CAGR. Их неполнота не отменяет самостоятельного
экономического провала полной MLP. Все численные 20%/50% цели V62 не достигнуты.

V62 закрыт: не менять thresholds, часы, направление, assets, costs или horizon на этой
истории, не выбирать post-hoc SI/short-only и не исправлять fixed arms ради promotion.
Лучшие прежние V41/V49/V60 остаются без нового независимого подтверждения. Следующий
шаг — новая экономическая информация/механизм, либо продолжение frozen forward discovery;
ещё одна перестановка price-only intraday features не обоснована.

Проверки: V62 synthetic 13/13 локально и на сервере; full suite 1 344 passed, 7 skipped,
две прежние V8 external-path failures. Scoped Ruff clean; полный Ruff содержит 58 старых
V8/V9 замечаний. Новые модели и все market/run artifacts находятся вне Git.

## Official MOEX futures calendar — SOURCE READY, V49 READINESS V3

Прямой documented ISS route `iss.moex.com/iss/calendars/futures` без авторизации
возвращает HTML, но публичная страница торгового календаря MOEX server-side содержит
структурированный `__NEXT_DATA__.offDays.futures`. Source-only transport был запечатан
до первого сохранённого ответа: config SHA `8380d1a0...`, admission SHA `9dc8ef1f...`,
implementation `c4a07428...`; commits `b6b39c4/d829d81` были pushed до collection.

Первый server snapshot
`snapshot_calendar_20260902T225345007058Z` содержит только даты/status/reason: `485`
дат `2026-09-03..2027-12-31`, из них `474` trading, `11` non-trading, unknown `0`.
Raw HTML `524 574` bytes сохранён gzip; source replay `18/18`, manifest/audit SHA
`19a2858e.../35a0283b...`. Readiness знает следующие шесть торговых сессий, invalid `0`,
поэтому operational blocker пятисессионного hard fallback снят для решений после
`2026-09-02T22:53:45Z`. Более ранние решения этот snapshot не ремонтирует.

Timer `trading-lab-futures-calendar.timer` работает на `gpu-mlserver` ежедневно в
`00:20` МСК; всего активны `15` server timers, локальных PowerShell tasks нет.
V49 calendar admission SHA `6b81c07c...`, readiness V3 implementation `6950ac24...`,
deploy `218d7aa`; server tests `21/21`. Текущий V49 state: calendar `1 valid/0 invalid`,
option/CLOSE `1/54 + 1/253`, execution/FRED/CBR `0/1/0`, causal join `0`. Calendar
является дополнительным AND-condition и не может обойти warmup: signal/return/target/
order/position/PnL не вычислялись, CAGR запрещён, live false.

## Historical MOEX Type B options — STRUCTURE VALID, ECONOMICS NOT TESTED

Официальный бесплатный Type B sample `OrderLog20241001_B.7z` загружен только на
`gpu-mlserver`; архив SHA `afccc160...`. Canonical source V3 содержит `6 561 395`
option tick events (`5 569 089` updates, `975 553` explicit quote clears, `16 753`
trades) и exact deal-ID overlap `16 753/16 753`; audit `10/10`. Бесплатный официальный
каталог проверен `2026-09-03`: других Type B дней в нём нет, полная история платная.

Core4 BBO V2 устранил same-timestamp look-ahead: trade видит только состояние конца
предыдущего distinct timestamp. Получено `957 259` BBO states и `13 670` trade contexts;
`13 607` имеют prior two-sided quote, locked/crossed `0`; audit `12/12`. Structural
defined-risk admission на заранее заданных 99 grid timestamps нашёл `9/72/403/1465`
adjacent-strike debit vertical opportunities при freshness `1/5/15/60s`; audit `12/12`.

Отдельный execution-diagnostic был sealed commit `82af580` до depth/friction values,
config SHA `cd32510e...`, implementation `771db67`. Canonical audit `11/11`; manifest/
audit SHA `5ed6ef18.../86a28f55...`. При freshness 15s медианная displayed entry/exit
capacity равна `3/3` контракта, median four-side crossing friction `16,6%` ширины
страйков; лишь `44/403` observations имеют friction `<=5%`, `129/403` — capacity обеих
сторон `>=5`, `35/403` — `>=10`. При 5s median capacity `5/5`, friction `16,8%`, и
только `11/72` имеют friction `<=5%`.

Вывод: market-order вертикали структурно возможны, но BBO crossing дорог; один день не
даёт expected return и запрещено превращать увиденные `5%/15s` в strategy thresholds.
Limit-order гипотеза потребует queue/latency source. Подробности и audit paths:
[MOEX_TYPE_B_OPTION_SOURCE.md](MOEX_TYPE_B_OPTION_SOURCE.md). Live trading false.

## Intraday MOEX option surface V2 — SOURCE-ONLY COLLECTION ACTIVE

V1 intraday admission SHA `b325dc26...` завершён без полной сессии: накоплено пять
eligible поздних snapshots, complete sessions `0/20`. Его снимки не переносятся в V2.
Новый source V2 запечатан до первого V2 value: config SHA `f9a06462...`, implementation
SHA `74d015a6...`, eligibility boundary `2026-09-02T21:25:00Z`. Admission V2 SHA
`fb598938...` запечатан отдельно до первого снимка.

V2 сохраняет исходные `UPDATETIME`, `TIME`, `SEQNUM`, `QUANTITY`, `OICHANGE` и margin
поля `PREVOPENPOSITION/IMNP/IMP/IMBUY/IMTIME`, которые V1 отбрасывал. Это позволяет
впоследствии проверять staleness и causal identity точнее. Public ISS depth/queue поля
оказались пустыми и не включены: V2 не доказывает очередь, задержку доставки или fill.

Authoritative `trading-lab-option-surface.timer` на `gpu-mlserver` пишет V2 Mon–Fri
10:09–22:59 МСК каждые 10 минут плюс 23:09/19/29/39/55. Отдельный
`trading-lab-option-surface-eod.timer` в 23:57 пишет ровно один V1 snapshot для frozen
V39/V49 forward-readiness. Локальные Windows tasks выключены. Readiness V2 требует для
одной complete session не менее 30 valid срезов, span `>=300` минут и max gap `<=25`
минут. До 20 complete discovery sessions запрещены features, labels, returns и PnL;
далее заранее разделены 20 calibration и 60 unseen sessions.

Будущий sealed economic protocol сравнит full-surface neural timing, price-only
ablation, fixed skew/term rule и always-abstain. Только defined-risk конструкции;
исполнение по наблюдаемому OFFER на входе и BID на выходе, naked short запрещён. Это
сбор нового причинного источника, а не заявление о найденной доходности.

Первый V2 tick создал `snapshot_20260902T212518751694Z`; source audit `22/22`,
readiness eligible/preboundary/invalid `1/0/0`, complete sessions `0/20`. Поздно начатая
сессия корректно не считается полной и не открывает economic seal; service result
success. Canonical V2 root:
`/srv/trading_lab_data/data/forward/moex-options-surface-v2-timestamps-margin`.

До просмотра clock/BBO/margin quality был запечатан отдельный source-diagnostic SHA
`b26c35c6...`, seal commit `6c41de3`; implementation `a3be7ba`. Первый immutable report
`quality_snapshot_20260902T212518751694Z_b26c35c6` прошёл replay `9/9`, quality/identity/
audit SHA `c110b722.../ef413dd5.../31138bf9...`. Из `2 280` contracts двусторонняя
положительная котировка была у `527`, соседних двусторонних пар — `486`; crossed/locked
`0/0`, все три margin fields положительны у всех rows. Но ночной срез старый: median
`market_update` lag `188,95` минуты, `0` rows в пределах 15 минут, `1 000` в пределах
60 минут, `1 280` старше часа. Это не дисквалифицирует дневной поток, но запрещает
выдавать наличие BID/OFFER за свежую исполнимую котировку. Dispatcher теперь запускает
тот же sealed quality report после каждого V2 capture; economics по-прежнему отсутствует.

## V60/V61 V49 shadow-equity governor — DEVELOPMENT GO, ROBUSTNESS NO-GO

V60 config SHA `40145868...`, seal/deploy commit `f132dd8`, implementation SHA
`4a3e38e5...`. До outcome был зафиксирован ровно один causal rule: frozen V39 targets
масштабируются `2.00x`, только когда latest strictly-prior always-on V49 primary shadow
NAV не ниже своей trailing 126-session mean; иначе и во время warmup используется
`1.00x`. Ни signal direction/zero, ни costs, exact integer execution, gross `4x`, margin
buffer `2x` или participation `1%` не менялись; parameter search отсутствовал.

Canonical run `v60_v49_equity_trend_governor_v1_20260902T193821Z_40145868` прошёл все
presealed development gates:

- primary/doubled/stress/execution-stress CAGR
  `39.9382%/38.8445%/38.4998%/38.4998%`;
- Sharpe `1.2435/1.2218/1.2111/1.2111`, MDD
  `22.0244%/22.0686%/22.2845%/22.2845%`;
- primary worst year `−2.1717%`; risk-on/risk-off/warmup dates `197/105/32`;
- против V49 MDD улучшен на `0.9477–2.3773 п.п.`, но CAGR ниже на
  `1.8843–4.1324 п.п.`;
- deterministic artifact/metric/gate replay полностью true. Manifest/metrics/audit SHA
  `5741a93d.../836041a7.../5de120c7...`.

V61 был отдельно запечатан до resampling: config SHA `321fff16...`, implementation/
deploy commit `ce5220d`, 300 000 circular-block paths, blocks `5/21/63/126`, rolling
`252/504`, leave-one-year-out и более строгий joint gate CAGR `>=20%` + MDD `<=25%`.
Canonical `v61_v60_robustness_20260902T194742Z_321fff16` дал
`INTERNAL_ROBUSTNESS_DOES_NOT_SUPPORT_20`; все пять minimum-20 conditions false:

- worst stress joint frequency `52.188% < 75%`, q05 CAGR `8.9513% < 20%`;
- доли stress rolling CAGR `>=20%`: `57.2968%` на 252d и `58.3875%` на 504d;
- leave-2022-out stress CAGR `18.7995% < 20%` — результат всё ещё заметно зависит от
  2022 года;
- audit полностью true; manifest/metrics/identity SHA
  `bb122360.../7915e08a.../beb718b0...`.

Итог: V60 — лучший новый risk-adjusted historical challenger, но исходную задачу
предсказуемых `>=20%` он не доказал. Не менять 126-session window, multipliers или
gates по этому outcome. Допустимы frozen forward V49/V60 и новая экономически иная
family/source; live false.

## V57/V58 official CFTC WTI positioning → BR — SOURCE AUDITED, V58 NO-GO

V57 source config SHA `22878af6...`, implementation commit `3d66bf4`, code SHA
`cdaa6389...`. Все schema/name corrections были ограничены официальными заголовками и
точными identity: CFTC сохранила код `067651`, но в 2022 переименовала основной рынок
из `CRUDE OIL, LIGHT SWEET` в `WTI-PHYSICAL`. Экономика V58 была запечатана до BR
outcome и не менялась. Immutable source содержит `836` строк — по `418` WTI и Gold,
`2018-01-02…2025-12-30`; replay имеет все `15/15` checks true. Manifest/positions/raw/
audit SHA `e0151b2b.../d155bf55.../3defacb9.../500413b2...`.

V58 config SHA `637eb6c4...`, seal commit `d1974ca`, implementation commit `831e359`,
code SHA `d89d7842...`. Единственный candidate использовал изменение WTI managed-money
net/OI против значения 13 допущенных reports назад; положительное изменение означало
long BR, отрицательное — short, без threshold. Решения weekly, CFTC delay не меньше
7 календарных дней, maximum age 14 дней; BR risk `20d log-vol / 30% target / 2x cap`,
factual next OPEN, exact rolls, 1% participation и costs `1/1`, `2/2`, `4/2`.

Canonical run
`runs/v58_cftc_wti_positioning_br_v1_20260902T184645Z_637eb6c4/`:

- `261` evaluation weekly decisions, `46` roll-only decisions и `303` nonzero targets;
- candidate primary/doubled/stress CAGR `−28.2451%/−28.7082%/−30.3806%`, Sharpe
  `−0.7333/−0.7531/−0.8285`, MDD `87.13%/87.24%/88.07%`;
- primary потерял `80.97%`, имел только `1/5` positive years; gross edge отрицателен,
  execution candidate complete, critical/unresolved `0/0`;
- frozen price-only 63-session baseline показал indicative CAGR `17.94%`, но его
  ledger invalid после unresolved expired-contract marks, поэтому это не admissible
  решение и не подтверждение 20%;
- V58 verdict `NO_GO`; server replay имеет все `28/28` checks true. Manifest/metrics/
  audit SHA `94a7b8f4.../44b9a22f.../43ac0263...`.

Не переворачивать sign и не менять 13-report lag/risk/cap на 2021–2025. Следующий
допустимый тест — отдельно запечатанная contrarian/crowding гипотеза на независимом
pre-2018 периоде с заново собранным official CFTC source; только после такого
подтверждения можно вернуться к combined-period проверке. Live trading запрещён.

## V59/V59R2 pre-2018 CFTC crowding — INVALID EXECUTION, NO USEFUL EDGE

Pre-2018 source config SHA `1d8fb69b...`, implementation `0dfed56b...`; official
CFTC bundle содержит `626` строк (`313` WTI + `313` Gold),
`2012-01-03…2017-12-26`, raw replay `15/15` true. Manifest/positions/raw/audit SHA
`8ea54168.../c8641234.../c93a4c15.../c0cbf0af...`.

V59 inverse/crowding sign был запечатан до source join; parent SHA `cf597ddc...`.
Первый run invalid: atomic roll с нулевой capacity оставил expired `BRF3`. R1
`a79613a3...` включил существующий `cancel_and_clip`, R2 `4ca4f1ad...` добавил
risk-first cash exit только на roll-only decisions; sign/lag/risk/costs не менялись.
Canonical diagnostic R2
`v59r2_cftc_wti_crowding_br_pre2018_v1_20260902T190953Z_4ca4f1ad` всё ещё invalid:
`1754` critical missing-contract marks после weekly+roll collision. До блокировки
indicative primary/doubled/stress CAGR лишь `0.7174%/0.6124%/0.5768%`, поэтому новая
execution-подгонка не оправдана. Replay `8/8` true; manifest/metrics/audit SHA
`964e3481.../33c8d40a.../658e0577...`. Семью CFTC закрыть; live trading запрещён.

## V52R2 OFZ carry/roll-down — NO-GO, 1.92–4.51% CAGR

V52 был запечатан до первого чтения market values: config SHA `ee995ff4...`, commit
`2b25672`, implementation `a7752bd0...`. Первый server run остановился до output на
валидном пустом trade-frame. R1 SHA `491e53c3...` исправил только empty artifact
schema; его audited result доказал `0` selected rows/сделок, потому что MOEX history
использует legacy `CURRENCYID=SUR`, а протокол буквально требовал `RUB`.

R2 semantic-only correction SHA `8a2e97e2...`, commit `87340af`, сохранила
`FACEUNIT=RUB` и все duration/liquidity/top-3/weights/execution/cost/gates, заменив
только source identity `RUB -> SUR`. Canonical server run
`runs/v52r2_ofz_carry_roll_down_20260902T172306Z_8a2e97e2/`, external replay
`all_true=true`, manifest/metrics/audit SHA
`116734b7.../14fce225.../b4a99d11...`.

- `60` monthly decisions, `171` selected rows, `56` completed rebalances,
  `687` scenario trades и `11 088` position rows; один unresolved rebalance;
- standalone CAGR `4.5140% / 3.6422% / 1.9194%` при `10/20/40` bps, Sharpe
  `0.555/0.457/0.262`, MDD `22.92%/23.78%/25.69%`;
- primary `4/5` positive years, doubled `3/5`, stress `2/5`; `11` conservative
  unresolved schedule cashflows в каждом scenario;
- fixed fully-funded `85% V49 + 15% OFZ` CAGR
  `39.4530%/38.7578%/36.2516%/36.2516%`, MDD `22.43–24.15%`;
- обязательные standalone return/Sharpe/MDD/cashflow gates провалены, 50% false,
  verdict `NO_GO`.

OFZ sleeve немного снижает часть drawdown, но существенно разбавляет V49 и не является
новым сильным return engine. Не менять maturity `2–7`, liquidity `10m`, top-3,
monthly rebalance, `85/15` или costs по этому outcome. Допустим новый principled target
на OFZ curve state только после отдельного seal; live trading запрещён.

## Official MOEX OFZ source — AUDITED

Source V1 SHA `c43f7366...`/implementation `11aa44c7...` был sealed после schema
probe, но остановился без output: board-wide ISS игнорировал `from/till` и вернул
текущую дату 2026. R1 SHA `bdd7b19b...` исправил только explicit daily transport и
прошёл всю history in-memory, затем fail-closed на namespaced bondization cursor.
R2 SHA `227b1641...`, implementation commit `7ae803b`, SHA `70f6e58c...` заменил
только schedule pagination на global `start`; economic fields не менялись.

Canonical external source
`data/processed/ofz/moex-ofz-history-bondization-2021-2025-v1/`:

- `70 896` TQOB `SU*` rows, `1 271` dates, `83` securities;
- `67 249` rows с positive trades/value/close;
- `676` coupon, `32` amortization, `0` offer events;
- history/bondization SHA `f045482b.../d69be407...`;
- manifest/audit SHA `102b4add.../809eef13...`, raw replay `all_true=true`;
- return/label/signal/target/order/position/PnL отсутствуют, market rows 2026+ `0`.

Source остаётся неизменяемой основой. Первый economic test завершён V52R2 `NO_GO`;
повторный carry/roll-down parameter search на 2021–2025 запрещён. Подробности — в
`docs/MOEX_OFZ_SOURCE.md`. Live trading запрещён.

## V53R1 OFZ curve governor — NO-GO, 25.96–28.59% CAGR

V53 config SHA `838ee791...`, implementation commit `c428a76`, SHA `a9cdfc4d...`
запечатал один sign-only state до curve/V49 join: liquid SU262 `2–4y` против `5–7y`,
inverted factor `1.25`, normal `0.75`, missing `0`. Первый output имел exact state и
ledger replay, но audit false из-за `numpy.bool_ -> "True"`. R1 SHA `61c18f55...`,
commit `870ae4a`, corrected engine `94897e75...` изменил только builtin-bool cast.

Canonical run `runs/v53r1_ofz_curve_v49_governor_20260902T173750Z_61c18f55/`:

- states inverted/normal/missing `20/37/3`, valid months `57/60`, V49 coverage `96.93%`;
- primary/doubled/stress CAGR `28.5942%/28.0275%/25.9556%`;
- Sharpe `1.078/1.053/1.011`, MDD `25.49%/26.08%/27.09%`;
- primary и all-scenario CAGR/Sharpe gates false, 50% false; verdict `NO_GO`;
- external replay `all_true=true`; manifest/metrics/audit SHA
  `796c4aba.../97468194.../0f1190c9...`.

Governor уничтожил значительную часть frozen V49 edge и не улучшил predictability.
Не инвертировать sign, не менять buckets/liquidity и factors `1.25/0.75` на этой
истории. Следующий independent mechanism — собственная торговая доходность RGBI/OFZ
futures, не ещё один governor V49.

## V54 official RGBI futures source — AUDITED, NO PNL YET

Source config SHA `fe49459e...`, implementation commit `5249e68`, SHA `c9f8a3b6...`
был sealed после identity/date/schema-only probe и до market values. Canonical external
bundle `data/processed/info_radar/moex-rgbi-futures-daily-2022-2025-v1/`:

- exact 15 quarterly series `RBM2…RBZ5`, `1 607` daily rows, 24 raw responses;
- `1 402` positive-activity и `1 402` complete OPEN/CLOSE rows;
- series/daily/raw SHA `6dce9f16.../f993a6b0.../ce762a9e...`;
- manifest/audit SHA `60dbb74c.../c054b4e8...`, raw replay `all_true=true`;
- curve/basis/return/label/signal/trade/PnL отсутствуют, 2026+ rows `0`.

`RGBIF` начался только `2025-12-23` и исключён; archived calendar spreads и stopped
O2/O4/O6 также не смешивались с quarterly RGBI. Market values пока не использовать
для выбора horizon/direction/roll/risk. Следующий V55 должен быть sealed первым.

## V55 RGBI causal trend — NO-GO, stress negative

Config SHA `6f27813b...`, implementation commit `4990c45`, SHA `67e30353...`;
canonical server run
`runs/v55_rgbi_futures_causal_trend_v1_20260902T175313Z_6f27813b/`.
До outcomes был запечатан единственный normalized candidate: `63` momentum,
`20` volatility, target `25%`, cap `3x`, deterministic 10-day roll, next OPEN и
`5/10/20` bps.

- `886` signal, `885` candidate, `762` executed sessions; unresolved `123` (`13.90%`);
- primary/doubled/stress CAGR `11.0337%/6.9488%/−0.8009%`;
- Sharpe `0.525/0.397/0.140`, MDD `33.73%/36.24%/41.00%`;
- profitable years `2/4`; stress worst year `−21.24%`;
- return/Sharpe/MDD/worst-year/coverage gates false, verdict `NO_GO`;
- external artifact replay `all_true=true`; manifest/metrics/audit SHA
  `7feade35.../dd64fe35.../42af2681...`.

Trend не даёт требуемые 20% и exact specs replay не оправдан. Не менять `63/20/25%/3x`,
roll, direction или costs на этой истории. Следующий механизм — отдельная RVI
volatility-risk-premium corridor, а не соседний RGBI horizon.

## V56 outright RVI short corridor — INVALID AND ECONOMICALLY NEGATIVE

Config SHA `bc1c3f2b...` был отдельно запечатан/pushed commit `85bc27e` до market
values; implementation commit `e9e8ce1`, SHA `ba196276...`. Единственный кандидат:
short front RVI после completed `30 <= close < 45`, factual next OPEN, TP `<=24`,
distant stop `>=45`, 20-session maximum, expiry buffer `5`, `1%` stop-risk, `1x`
gross cap и costs `0.10/0.20/0.40` points per side. V45 curve thresholds не
использовались. Canonical server run:
`runs/v56_rvi_outlier_short_corridor_v1_20260902T181304Z_bc1c3f2b/`.

- `326` signal sessions, `58` non-overlap candidates, `27` complete trades;
  `22` rejects, `2` unresolved entries и `21` unresolved daily marks;
- exits: `5` distant stops, `17` expiry buffers, `5` maximum holding, `0` TP;
- complete-subset primary/doubled/stress CAGR
  `-0.2575%/-0.3435%/-0.5163%`, Sharpe `-0.262/-0.349/-0.519`;
- primary gross/net PnL `-8,481/-12,689 RUB`, profit factor `0.731`, `2/5`
  positive years; stress net `-25,313 RUB`;
- sealed verdict `INVALID_UNRESOLVED_EXECUTION_OR_MARKS`; every economic return,
  Sharpe, stability and profit-factor gate also fails on the fully marked subset;
- independent server replay `all_true=true`; manifest/metrics/audit SHA
  `f19f49df.../1375e535.../f244faa1...`.

Даже идеальный repair пропусков не меняет отрицательный gross edge уже доказанных
сделок. Не менять `30/24/45`, holding, DTE, sizing, direction или costs по этому
outcome и не создавать V56.1. Следующая работа должна использовать новый return
mechanism; historical defined-risk option premium требует отдельного исполнимого
bid/offer source, а не THEOR_PRICE или OI.

## V51 robustness audit V42R2 — STABILITY PORTFOLIO ALSO FAILS INTERNAL 20%

V51 config SHA `2a1e467b...`, implementation commit `5a00d74`, implementation SHA
`3e38079b...`; canonical server-only run
`runs/v51_v42r2_robustness_20260902T161549Z_2a1e467b/`. До resampling были
обязательны все девять frozen V42R2 market-cost curves; выбор fund/cost scenario,
веса `80/20`, V39 economics и execution запрещены. Выполнено `900 000` fixed-seed
circular moving-block paths, blocks `5/21/63/126`, rolling `252/504` и пять
leave-one-year-out исключений. Ни prices/targets/positions, ни данные 2026 не читались.

Хотя observed CAGR всех девяти сценариев остаётся `24.0969–25.4527%`, строгий verdict
`INTERNAL_ROBUSTNESS_DOES_NOT_SUPPORT_20`; провалены все пять gates:

- worst joint `CAGR >=20%` и `MDD <=30%` frequency `61.244% < 75%`;
- worst bootstrap q05 CAGR `7.7086% < 20%`;
- worst rolling 252-session fraction CAGR `>=20%`: `52.3017% < 65%`;
- worst rolling 504-session fraction: `38.7516% < 75%`;
- worst leave-one-year-out CAGR `15.7917% < 20%` при исключении 2022;
- aspirational 50% false; worst median bootstrap CAGR `23.3705%`, worst joint 50/30
  frequency лишь `1.276%`.

Artifact replay `all_true=true`; metrics/manifest/identity SHA
`2c3eabb4.../8385fd60.../8f899e9a...`. Deflated-Sharpe probability worst stress при
250 trials `43.84%`. Вывод сильнее V50: 20% cash-carry allocation снижает MDD, но не
создаёт независимый return engine и не устраняет зависимость от выдающегося 2022.
Увеличивать carry weight по этому outcome или выбирать лучший fund запрещено. Для
реального продвижения нужен новый uncorrelated causal mechanism с собственной
доходностью, а затем frozen forward portfolio; live trading запрещён.

## V50R1 robustness audit V49 — 20% INTERNAL SUPPORT NOT CONFIRMED

V50 был заранее запечатан SHA `0e626e17...`, но остановился в preflight без output и
до любого resampling: канонические V49 metrics использовали `365.25` дней в году, а
заимствованный verifier V27 — `365.2425`. Единственная R1-поправка запечатана до
результата SHA `5a5b36ca...`, implementation commit `0714967`, wrapper SHA
`b35bd178...`; bootstrap clock, `300 000` paths, seeds, blocks `5/21/63/126`, rolling
windows и gates не менялись. Canonical server-only run:
`runs/v50_v49_robustness_20260902T155610Z_5a5b36ca/`.

Verdict `INTERNAL_ROBUSTNESS_DOES_NOT_SUPPORT_20`:

- observed primary/doubled/stress CAGR точно воспроизведён как
  `43.6833% / 42.9769% / 40.3841%`;
- worst stress block joint frequency `CAGR >=20%` и `MDD <=40%` — `81.668%`, gate
  `75%` пройден;
- worst stress bootstrap CAGR q05 — только `10.4537%`, gate `20%` провален;
- stress rolling 252/504-session доля окон с CAGR `>=20%` —
  `60.1371% / 59.4278%` при gates `65% / 75%`, оба провалены;
- leave-one-year-out stress минимум `21.4171%` (исключён 2022), gate `20%` пройден;
- aspirational 50% support false; worst joint `CAGR >=50%`, `MDD <=40%` — `28.604%`.

External artifact replay дал `all_true=true`; metrics/manifest/identity SHA
`3b60978b.../a5002f6d.../46c9a0e1...`. Это same-history post-selection diagnostic, не
forward probability. Он показывает временную концентрацию edge: повышение V49 scale
не превращает его в относительно предсказуемые `20%`. V49/V50 не повторять, block/
window/gates не выбирать по результату и не создавать соседний leverage variant.
Главный путь остаётся post-seal forward V49/V48/V27 плюс экономически новая family на
новых causal источниках; live trading запрещён.

## V49 exact double-risk — BEST EXACT CAGR, strict NO-GO at 45% primary gate

V49 config SHA `37b4fcb0...`, seal `ad22fb4`, implementation commit `540741a`,
implementation SHA `1ddb838a...`; canonical
`runs/v49_v39_double_risk_exact_execution_v1_20260902T122406Z_37b4fcb0/`.
Единственный заранее зафиксированный режим ровно удваивает frozen V39 mapped targets:
scale `2.00x`, gross cap `4.00`, margin buffer `2.00`, participation `1%`, carry `0`.
Ни scale sweep, ни выбор режима после результата не выполнялись. Расчёт выполнен ровно
один раз на `gpu-mlserver` из commit `540741a`; все даты строго раньше 2026.

Результат — лучший exact integer/capacity/margin historical CAGR, но строгий `NO_GO`:

- primary/doubled/stress/execution-stress CAGR
  `43.6833% / 42.9769% / 40.3841% / 40.3841%`;
- Sharpe `1.306 / 1.277 / 1.248 / 1.248`;
- MDD `22.9721% / 23.5018% / 24.6617% / 24.6617%`;
- worst year `-3.3889% / -3.5929% / -3.7918% / -3.7918%`, primary `4/5`
  positive years;
- maximum participation `0.5904%`, zero clips, margin rejects, critical failures и
  unresolved halts; primary/doubled/stress total costs
  `124 334 / 244 135 / 343 432` RUB.

Провален ровно один обязательный gate: primary CAGR `43.6833% < 45%`; отдельный 50%
stretch gate также false. Все scenario CAGR остаются выше `40%`, а gates Sharpe/MDD/
worst-year/execution прошли. Внешний replay-аудит — `all_true=true`; manifest/metrics/
audit SHA `b806e811.../eb24680a.../60a88ce6...`.

Это post-V48 adaptive same-history sensitivity, а не независимое подтверждение и не
обещание доходности. Не запускать V49 повторно и не перебирать `2.01x`, `2.1x`, caps,
margin buffer или gates по уже увиденному результату. Допустим только заранее
запечатанный paper/forward arm на будущих post-seal наблюдениях; live trading false.
Forward V1 теперь запечатан SHA `520bd3d4...`, boundary
`2026-09-02T12:30:04Z`, implementation/deploy commit `a6cd0af`. Первый server
readiness: option `0/54`, CLOSE `0/253`, execution/FRED/CBR `0/0/0`; один preseal
option snapshot и два preseal components исключены, invalid `0`, PnL/CAGR false.
Отдельный исполняемый paper-arm seal V1 создан до следующего server snapshot: config
SHA `56822e1e...`, boundary `2026-09-02T19:16:00Z`. Он повторно фиксирует ровно один
arm `2.00x/4.00/2.00/1%`, V39 signs/zeros и exact BID/OFFER execution; все пять
eligible counts на границе равны нулю. Это устраняет двусмысленность старой очереди:
новый arm уже запечатан, повторно обнулять boundary нельзя. Exact commit `8f7176b`
запушен и развернут на `gpu-mlserver`; server tests `5 passed`, paper readiness снова
подтвердил `0/54 + 0/253`, execution/FRED/CBR `0/0/0`, exclusions `1 + 2`, invalid `0`.

FRED transport V2 admission SHA `62ca9450...` и successor deploy `8cee8cd` не сдвигают
эту границу. Текущий paper-arm readiness V2: option/CLOSE `1/54 + 1/253`, post-seal
execution/FRED/CBR `0/1/0`, excluded preseal option/components `1/2`, invalid `0`,
causal join `0`; PnL/CAGR всё ещё запрещены.

## V48 exact frontier — FORWARD BASELINE, 38.46–39.86% CAGR

V48 SHA `3b7ae0e4...`, seal `5c7e9e0`, implementation `ba414cc`; canonical
`runs/v48_v47_exact_integer_execution_v1_20260902T102529Z_3b7ae0e4/`. Он заново
проигрывает scaled frozen V39 targets через integer contracts, factual next OPEN,
1% lagged-volume capacity, atomic rolls, exact costs и doubled margin reserve.

Frontier `1.50x` прошёл все presealed exact gates:

- primary/doubled/stress/delayed CAGR
  `39.8604% / 39.0021% / 38.4612% / 38.4612%`;
- Sharpe `1.300 / 1.279 / 1.266 / 1.266`;
- MDD `23.9696% / 23.6966% / 23.9102% / 23.9102%`;
- worst year `-2.9305% / -3.1054% / -3.5999% / -3.5999%`, `4/5` positive years;
- max participation `0.4374%`, zero clips, liquidity/roll cancels, margin rejects,
  critical failures и unresolved halts.

Это новый исторический lead и первый вариант, близкий к 50%, который сохранил более
`38%` CAGR даже после exact integer/capacity/margin/cost replay. Stability mode тоже
сильный (`29.39–30.57%`, Sharpe `1.29–1.33`, MDD менее `19%`), но строгий `NO_GO`:
primary имеет только `4/5` positive years из-за `2025 -0.1492%`, поэтому режимы не
выбирались после результата.

V48 всё ещё не live GO: это масштабирование известного same-history winner, public
OHLC/spec proxy, а не broker fills или independent forward. Forward protocol V1 уже
запечатан до первого V27 snapshot: SHA `1fbc8c10...`, единственный режим `frontier`,
scale `1.50`, gross cap `3.00`, margin buffer `2.00`, participation `1%`, carry `0`.
Source mapping correction SHA `019f970e...` перевёл readiness на независимые V27
components без изменения режима. FRED V2 admission SHA `62ca9450...` и readiness V4
теперь дают: option levels `1/54`, official CLOSE `1/253`, execution dates `1`, CBR
`1`, FRED anonymous-v1/v2/authenticated `0/1/0`, invalid `0`, causal join `0`;
signals/returns/PnL и annualization запрещены.
Scale, cap, buffer, execution marks и gates по 2021–2025 больше не менять; см.
`docs/FORWARD_V48_FRONTIER_PROTOCOL.md`.

V39/V27 readiness также восстановлен после fail-closed identity alert. До первого V27
snapshot был запечатан transport-only compatibility SHA `ae70f0d4...`: он разрешает
только exact collector implementation `7a6f5732...` с тремя повторами того же запроса
и исправленной Protocol-signature. Economics, endpoints, normalization, schema и
availability не менялись; cache/backfill запрещены. Atomic V2 действительно остался
`0`, потому что persistent FRED disconnect отклонял весь snapshot. До первого decision
или PnL запечатан component protocol SHA `242d2684...`: MOEX, FRED и CBR теперь имеют
собственные immutable timestamps. Первый execution component (`25` rows) и CBR
component (`550` rows) прошли raw replay без единого failed check; на этом этапе FRED
был явно missing и не мог задним числом ремонтировать прошлое решение.

Официальный host `api.stlouisfed.org` доступен, но требует ключ. Старый anonymous
fredgraph зависал только с прежним research User-Agent; transport-only probe того же
URL с browser-compatible headers прошёл. До первого ответа запечатаны source SHA
`8a26480d...` и admission SHA `62ca9450...`; implementation `5cf38c92...` не меняет
series/query/parser/availability. Wrapper использует API только при валидном
`FRED_API_KEY`, иначе anonymous header V2; после failure fallback запрещён.
Первый 57-row V2 snapshot прошёл `15/15`, manifest/audit SHA
`e1d7b83c.../5d34f36f...`. Сейчас key configured `false`, anonymous-v1/v2/authenticated
snapshots `0/1/0`.

Forward collection перенесён на `gpu-mlserver`: commit `bd1f63c` добавил
cross-platform dispatcher и 13 native systemd timers, серверные каталоги
`/opt/trading_lab` и `/srv/trading_lab_data`, отдельного пользователя `trading-lab` и
защищённый environment file вне Git. Все прежние данные (`311` files, `2 616 600`
bytes) перенесены без изменения общего byte count. Первый автоматический server cycle
`2026-09-02 14:59/15:09` дважды подряд создал cross-market и broad-carry snapshots;
все четыре завершились `Result=success`, `ExecMainStatus=0` и прошли raw replay
`all_true=true`. Server forward root содержит `331` file после второго цикла.

После этого все `16` локальных Windows tasks `TradingLab*` отключены (`13` active
выключены, `3` уже были disabled). Definitions не удалены и остаются только аварийным
fallback; одновременно с server timers включать их запрещено. Подробности —
`docs/SERVER_COLLECTORS.md`.

## V47 normalized risk ladder — NEW HISTORICAL FRONTIER, exact execution unproved

V47 SHA `0b3524f4...`, seal `a20d16e`, implementation `234a23e`; canonical
`runs/v47_v39_margin_feasible_risk_ladder_v1_20260902T101210Z_0b3524f4/`. Он
масштабирует только market PnL frozen V39, не умножая его исходный collateral income,
и отдельно начисляет half-RUONIA на свободный cash. Два режима запечатаны заранее и
не выбираются после результата.

- Stability (`1.10x` market + `20%` carry): CAGR
  `34.6195%/34.0527%/32.5127%/32.5103%`, Sharpe `1.344–1.276`, MDD `21.11–21.86%`;
  primary `5/5` positive years, stress worst year около `-0.054%`.
- Frontier (`1.50x` market, no carry): CAGR
  `43.8458%/43.0582%/41.7016%/41.7016%`, Sharpe `1.259–1.212`, MDD `28.01–28.95%`,
  worst year не ниже `-3.632%`.

Оба режима прошли presealed same-history gates и это ближайший корректный результат к
целевым 50%. Но V47 остаётся normalized proxy: exact integer contracts, 1% capacity и
двойной initial-margin buffer исходного ledger ещё не replayed. Поэтому следующий шаг
V48 — exact execution audit; до него это не execution-feasible и не live GO.

## V46 full-V39 + margin-headroom carry overlay — NO-GO

V46 проверил способ не разбавлять V39 до 80%, а использовать фиксированные 20%
свободного cash headroom как self-financing carry overlay. Config SHA `b18ed5bc...`,
seal `ed18e79`, implementation `775e0ce`; canonical
`runs/v46_v39_margin_headroom_carry_overlay_v1_20260902T100211Z_b18ed5bc/`.
В расчёт добавляется только carry сверх вытесненного half-RUONIA baseline. Strictly
prior margin разрешал overlay `1 271/1 272` sessions; максимум был `50.89%` против
запечатанного порога `70%`.

Primary CAGR достиг `28.8896%`, Sharpe `1.2594`, worst year `+0.0094%`, то есть
получено `5/5` positive years без сокращения V39. Doubled CAGR `28.4171%`. Но
zero-cashflow/delayed-fill stress дали лишь `27.7870%/27.7863%`, ухудшили V39 CAGR,
Sharpe, MDD и worst year. Строгий verdict `NO_GO`; долю, baseline и headroom threshold
после результата не менять. Это близкий к 29% primary кандидат, но не более надёжный
all-stress вариант, поэтому V41 остаётся stability lead и live trading запрещён.

## V45 RVI calendar corridor — NO-GO

Новый независимый volatility source успешно собран и raw-replay audited: protocol
SHA `bb4aec1d...`, seal `fce9705`, implementation `14c93c1`; `84` RVI monthly series,
`4 372` daily rows, `2 382` строк с positive activity и OPEN/CLOSE, `85` raw responses,
audit `14/14 true`. Bundle остаётся вне Git в
`moex-rvi-futures-daily-2019-2025-v1`; outcomes в source отсутствуют.

V45 SHA `2207f549...`, seal `afc7152`, implementation `161db45`, mechanical no-outcome
repair `4065b75`; canonical
`runs/v45_rvi_calendar_corridor_20260902T095257Z_2207f549/`. Presealed adjacent-curve
corridor дал `99` signals, `29` complete trades, `0` unresolved exits: `19` TP,
`8` expiry exits, `2` distant stops. Primary/doubled/stress CAGR
`0.2123% / 0.0597% / -0.2481%`, Sharpe `0.6043 / 0.2008 / -0.9704`, MDD
`0.4735% / 0.7083% / 1.3407%`. Primary profit factor `2.6472`, но только `2/5`
positive years, `0` trades in 2022 и отрицательный stress total.

Verdict `NO_GO`: edge слишком редок и мал для цели, stress costs его уничтожают.
Corridor/window/direction/DTE/capacity/cost/sizing на этой истории больше не менять.
V41 остаётся lead; live trading по-прежнему запрещён.

## V44 breadth governor — NO-GO; V41 remains lead

V44 проверил независимую защитную гипотезу: prior-close breadth всего fixed
30-stock universe должен был заранее переводить V41 из `80/20` в `40/60` при доле
положительного 63-session momentum ниже `1/3`. Protocol SHA `0343758a...`, seal
`ca16574`, implementation `a4a4b19`, timestamp-index repair `bca9e86`; canonical run
`v44_v41_stock_breadth_governor_v1_20260902T092313Z_0343758a`.

На `1 435` valid states получилось `425` risk-off sessions и `58` transitions.
Primary/doubled/stress CAGR `19.0388% / 18.1239% / 16.1276%`, Sharpe
`1.3146 / 1.2566 / 1.1372`, MDD `16.9736% / 17.1447% / 16.6651%`, worst year
`+2.8874% / +1.7434% / -1.3993%`. Защита улучшила часть primary/doubled stability,
но не прошла обязательный 20% return gate ни в одном cost scenario и ухудшила stress
Sharpe/worst year. Verdict `NO_GO`; повторная настройка lookback/threshold/scale/sign
по этой истории запрещена. V41 остаётся историческим lead, но не live-разрешением.

## RUONIA/RUSFAR spread source — COMPLETE, market economically sleeping

Официальный same-expiry futures route RUONIA (`RR`) против RUSFAR (`MF`) прошёл
source-only аудит. Protocol SHA `0e7db967...`, seal `8296184`, implementation
`7f2e25d`; external bundle `moex-ruonia-rusfar-futures-daily-2019-2025-v1` содержит
`79` exact-expiry pairs, `36 737` rows и `444` raw responses. Replay audit `14/14 true`;
manifest/pairs/daily/raw/audit SHA
`e5d3dad1.../e17b702b.../261ce00e.../b1d6e35f.../0f7c68d6...`.

Экономический тест не запускается: positive trade-activity rows всего `1 523` у
RUONIA и `636` у RUSFAR, после 2022 года RUONIA leg полностью без таких наблюдений,
а `34 592 / 36 737` строк не имеют OPEN/CLOSE. Settlement-only PnL не доказывает
двухногое исполнение. Статус `SOURCE_COMPLETE_ECONOMIC_SLEEP_NO_TRADES`, не PnL
`NO_GO`; live trading запрещён.

## V43 broad carry challenger — 20% GATE PASSED, V41 REMAINS LEAD

Broad carry idle-RUONIA V1 сохранил ровно 29 unit-corrected сделок. Canonical
`runs/stock_futures_cash_carry_broad_idle_ruonia_v1_20260902T083317Z_e5d91172/`;
metrics/manifest/ledger/audit `aca91c52.../9fa21e58.../d04539a4.../4fbad76d...`.
Equal-sleeves CAGR primary/doubled/zero/delayed
`7,1376%/7,0879%/6,2483%/6,2452%`, active-cap
`8,4986%/8,3599%/5,9489%/5,9406%`; все годы положительны, MDD не выше
`0,3572%/1,0305%`. Это стабильный cash sleeve, но отдельно он не достигает 20%.

V43 SHA `e816f05f...`, seal `8c9f1a8`, implementation `01f0ea4` заранее зафиксировал
тот же 80/20 no-rebalance вес, оба broad views и четыре stress. Canonical
`runs/v43_v39_broad_carry_ruonia_stability_v1_20260902T084341Z_e816f05f/`;
metrics/manifest/ledger/audit `abdaab13.../3b47e1ad.../f0464c1b.../de9367a3...`, audit
`8/8 true`.

Equal-sleeves CAGR `25,4371%/25,0231%/24,5837%/24,5834%`, active-cap
`25,5853%/25,1630%/24,5522%/24,5514%` для primary/doubled/zero-cashflow/
delayed-fill. Оба views проходят все presealed gates против V39 и имеют 5/5 positive
primary years. Но ни один не доминирует V41: active-cap прибавляет лишь
`0,0171/0,0177 п.п.` CAGR в primary/doubled и теряет `0,0665 п.п.` в stress; MDD
совпадает с V41 до показанной точности. Поэтому V41 остаётся lead, V43 — отдельный
forward breadth challenger. Выбирать view по этому результату, менять вес или делать
live promotion запрещено.

## Новый лучший stability candidate: V41 V39 + cash-carry + idle RUONIA — GO TO FORWARD

Cash-carry V2 SHA `a4c03aaa...`, seal `3265bd8` добавил только доход на свободный
капитал: ровно 15 frozen trades V1 не изменялись; asset-sleeve с позицией от entry до
exit включительно получает 0%, неактивный — 50% latest causally available RUONIA,
actual/365. Canonical
`runs/stock_futures_cash_carry_idle_ruonia_v2_20260902T041838Z_a4c03aaa/`; metrics
`2ddc7ba4...`, manifest `018044c6...`, audit `22a17cd...`, ledger `69310021...`.
Mean eligible capital `87,10%`, missing rate dates `0`. Primary/doubled/zero-cashflow
CAGR `8,3450%/8,2022%/6,5768%`, Sharpe `6,085/6,180/12,678`, MDD
`0,5610%/0,5626%/0,5762%`; все годы положительны. Verdict
`CASH_SLEEVE_FORWARD_CANDIDATE`, но historical broker instrument, реально платящий
50% RUONIA с мгновенной ликвидностью, ещё не доказан.

V41 SHA `45418128...`, seal `67a1eef` наследует без изменения presealed V40R1 вес
80% V39 / 20% cash-carry, no rebalance; заменён только zero-yield cash parent на
frozen V2. Canonical
`runs/v41_v39_cash_carry_ruonia_stability_v1_20260902T042117Z_45418128/`; metrics
`000ae99b...`, manifest `586e1b2d...`, audit `7dfc4696...`, ledger `38bdd2ce...`.

Primary/doubled/stress CAGR `25,5683%/25,1454%/24,6187%`, Sharpe
`1,2685/1,2482/1,2273`, MDD `17,3235%/17,4244%/16,7796%`, worst year
`+0,9087%/+0,4820%/−0,4482%`. Относительно V39 Sharpe улучшен на
`0,0170/0,0164/0,0083`, MDD — на `2,7087/2,7348/2,6553 п.п.`, worst year — во всех
сценариях; все CAGR выше 20%, primary имеет 5/5 positive years. Все пять presealed
gates true, verdict `GO_TO_FORWARD_PORTFOLIO_CONFIRMATION`.

До exact V48 это был сильнейший stability-вариант для цели «не менее 20% более
предсказуемо», но не доказательство live и не 50%: оба market-parent используют
overlapping history, V39
adaptive, cash-carry не имеет historical bid/ask execution, idle-yield instrument не
верифицирован. Веса/50% RUONIA/DTE/signal после результата не менять. Следующий шаг —
forward-синхронизация V39, cash-carry quotes и фактической доходности разрешённого
cash instrument; live false.

### V42R2 real idle-fund cost stress — ROBUST ABOVE 20%, same-history only

После V41 запечатан только cost diagnostic, без изменения сигналов, сделок и 80/20.
R1 был сохранён invalid: initial fund purchase входил в turnover, но не применялся к
NAV. R2 SHA `02a61505...`, seal `ab9b44a` исправил только момент списания начальных
5/10 bps; economic parameters и parent inputs не менялись. Canonical
`runs/v42r2_v41_idle_fund_cost_stress_v1_20260902T052406Z_02a61505/`; metrics
`39f55595...`, manifest `66a86c5f...`, audit `f93ca87b...`, ledger `312d07e4...`.

Три заранее заданных idle-cost stress пересечены с primary/doubled/stress market:

- LQDT max TER `0,29364%` + 13% tax proxy + 5 bps one-way: CAGR
  `25,4527%/25,0290%/24,5090%`;
- TMON max `1,199%` + tax proxy + 10 bps: `25,3549%/24,9306%/24,4162%`;
- zero idle yield + 10 bps switching: `25,0185%/24,5917%/24,0969%`.

Все 9 CAGR выше 20%, все MDD `16,8030–17,5249%` лучше соответствующего V39. Значит,
условный бесплатный idle-yield не является причиной прохождения 20% gate. Но это
post-result same-history robustness: он не выбирает фонд, не подтверждает execution и
не повышает V41 до live. Verdict `ROBUST_TO_DECLARED_IDLE_COST_STRESSES`.

Проверка реализации: scoped ruff clean, 13 related tests passed. Полный suite через
`.venv`: `1128 passed, 7 skipped`; два прежних V8 context failures остались только
из-за отсутствующего external `data/processed/futures_v8/manifest_8c26216529a9b73b.json`.
Новых regression failures нет. Repo-wide ruff всё ещё видит 58 legacy V8/V9/style
нарушений вне V42; они не исправлялись в этом эксперименте.

### Cross-market V3 — COMPLETE CORE SOURCE, discovery active

Cross V2 завершён как source-design dead end: все десять immutable срезов
`10:29..11:59` имели ровно `34/35`, потому что anonymous CETS ISS возвращал для
`CNYRUB_TOM` clocks/last, но не BID/OFFER. Это не zero quote и не основание скрывать
пропуск.

V3 SHA `f680f8bb...`, seal `aab247a`, implementation `e204316` был зафиксирован после
ограниченного source-availability probe, но до первого persisted V3 snapshot. Он
сохраняет `CNYRUB_TOM` как optional unresolved и добавляет exact `CNYRUBF` как core
currency state; 30 акций, SI/RI/BR/MIX, четыре фонда, schedule и запрет outcomes не
меняются. Первый immutable `11:59` snapshot имеет `40` rows, `35/35` complete core,
`5` raw responses, manifest/normalized/raw/audit SHA
`0cef4c96.../a722ebd6.../240d30b8.../a159eea1...`, replay audit `18/18 true`.
Readiness audit на `12:29`: `4/4` complete snapshots, `0` invalid, `0/20` sessions;
annualization/PnL запрещены.

Task `TradingLabForwardCrossMarketBBO10mV3` включён с `12:09`, V2 cross task
отключён, broad V2 продолжает работать. Public ISS всё ещё примерно на 15 минут
задержан и не даёт depth, поэтому V3 решает completeness, но не realtime/queue/fill.

### Delayed-BBO V2 — SEALED, source limitation recorded

V1 установил фактическое ограничение anonymous ISS: BBO задержан примерно на 15 минут,
а best depth не выдаётся. До следующей quote запечатаны source-only corrections:
cross SHA `d4d8910c...`, broad SHA `cb753e01...`, seal `b152720`; implementation
`7b7b031`. V2 требует BBO/clocks/identity/units, но явно оставляет depth, realtime,
size, queue и fill unresolved. Universe, schedule, requests и будущая экономика V1 не
изменены.

Первые ручные immutable snapshots в 10:29 прошли replay `16/16`. Cross имеет 34/35
quote-complete core rows (`CNYRUB_TOM` missing), status `invalid_core_quotes`, raw/
normalized SHA `f9c94550.../c7c1037d...`. Broad имеет 30/30, status
`complete_30_pair_quotes`, raw/pairs SHA `cd6f4104.../bbb450ea...`. Scheduled repeat
10:39 завершился кодом 0 для обоих: cross снова 34/35, broad снова 30/30, audits all
true. Readiness: cross `0` complete snapshots, broad `2`, complete sessions `0/20`.

V1 tasks отключены. V2 tasks
`TradingLabForwardCrossMarketBBO10mV2` и
`TradingLabForwardBroadStockFuturesCarry10mV2` включены Mon–Fri, `10:09..18:39`,
каждые 10 минут. Воспроизводимая регистрация находится в
`scripts/register_forward_delayed_bbo_v2_tasks.ps1`. Это delayed source discovery,
не realtime timing, не execution evidence и не найденная прибыль.

### Forward cross-market BBO V1 — FIRST SNAPSHOT AUDITED, depth unavailable, task paused

Открыт новый forward-only путь вместо дальнейшего same-history leverage tuning.
Config SHA `80d5202d...`, seal `95ca5b3` зафиксировал до первого значения 30 TQBR
акций, ближайшие metadata-only SI/RI/BR/MIX, `CNYRUB_TOM` и context
`LQDT/SBMM/AKMM/TMON`. Implementation `33b002c` делает четыре bulk ISS-запроса на
снимок и сохраняет BBO, лучшую/общую depth, number of orders, cumulative activity/OI,
exchange clocks и actual retrieval. Returns/labels/signals/trades/PnL отсутствуют.
До первого значения официальный pagination contract был учтён commit `97806f8`:
каждый bulk request получает server-side `securities=...` exact sealed universe, поэтому
тикеры за первой страницей не теряются и число запросов остаётся четыре.
До первого значения также исправлено только имя optional activity field: официальный
ISS использует `VOLTODAY`, а не `VOLUME`; commit `97603a1`, economics/universe/schedule
не менялись.

Срезы назначены каждые 10 минут `10:09..18:39` МСК. Core требует все 30 акций, четыре
фьючерса и CNY с положительными non-locked BID/OFFER и best depth; context fund может
быть invalid отдельно. Readiness сейчас `0` snapshots и `0/20` source-discovery
sessions; нужно минимум 30 complete core snapshots в день. Затем только после нового
economic seal: 20 calibration и 60 unseen sessions. Это инфраструктура для continuous
neural timing, all-market correlations и нового volatile-corridor теста, не найденная
прибыль и не live promotion. AlgoPack token отсутствует, поэтому order/cancel flow пока
не собирается. Task `TradingLabForwardCrossMarketBBO10m` проверен через Scheduler XML:
Mon–Fri, `10:09`, repeat `PT10M`, duration `PT8H31M`, state `Ready`, first run
`2026-09-02 10:09:00` МСК.

Scoped Ruff clean, source/replay/readiness tests `6/6`. Полная регрессия после добавления
источника: `1134 passed, 7 skipped`; два прежних V8 context failures — тот же missing
external `data/processed/futures_v8/manifest_8c26216529a9b73b.json`. Подробности:
[FORWARD_CROSS_MARKET_BBO_PROTOCOL.md](FORWARD_CROSS_MARKET_BBO_PROTOCOL.md).

Первый scheduled snapshot `2026-09-02 10:09` сохранён immutable: 39 rows, 4 raw
responses, raw SHA `12313e19...`, normalized SHA `c3206543...`, audit `15/15 true`.
Он честно `invalid_core`: anonymous ISS вернул positive two-sided BBO для `38/39`,
но `BIDDEPTH/OFFERDEPTH` пусты у всех 39; aggregate equity depth присутствует у 34,
aggregate futures depth отсутствует. `CNYRUB_TOM` в этом срезе не имел two-sided BBO.
`UPDATETIME` отстаёт от retrieval/SYSTIME примерно на 15 минут, поэтому anonymous
source не годится для realtime 10m timing. Task V1 disabled в `10:12`, snapshot не
переписывать. Следующий допустимый V2 должен считать BBO completeness отдельно,
оставлять depth unresolved и не называться realtime без AlgoPack/broker entitlement.

### Broad 30-stock futures cash-carry V1 — FIRST SNAPSHOT AUDITED, depth unavailable

Metadata-only probe без quotes/PnL подтвердил matching active RFUD futures для всех
`30/30` акций фиксированного V35 universe. Все выбранные 30–120 DTE контракты имеют
RFUD board, `TYPE=futures`; `LOTVOLUME` меняется от 1 до 10 000 акций. Exact mapping,
исключение perpetual `GAZPF/SBERF`, selection и units запечатаны SHA `5cd396e0...`,
seal `228edb8` до первой котировки.

Collector `5266903` делает series + filtered TQBR + filtered RFUD, проверяет integer
`futures LOTVOLUME / spot LOTSIZE`, сохраняет 30 синхронных BID/OFFER/depth/spec/clock
пар и не вычисляет basis/yield/rank/signal/PnL. Tests/replay `5/5`. Readiness/task
`4d1cf7a`; `TradingLabForwardBroadStockFuturesCarry10m` проверен: Mon–Fri, `10:09`,
`PT10M` на `PT8H31M`, state `Ready`, first run `2026-09-02 10:09` МСК.

Полная регрессия после обоих новых source paths в штатном `.venv`:
`1139 passed, 7 skipped`; остаются только два прежних V8 context failures из-за
отсутствующего external `data/processed/futures_v8/manifest_8c26216529a9b73b.json`.

Нужно 20 sessions минимум по 30 complete snapshots, затем новый economic seal, 20
calibration и 60 unseen sessions. Это прямой путь увеличить частоту стабильного
fully-funded sleeve с 5 до 30 активов, но metadata coverage ещё не прибыль и не live.
[FORWARD_BROAD_STOCK_FUTURES_CARRY_PROTOCOL.md](FORWARD_BROAD_STOCK_FUTURES_CARRY_PROTOCOL.md).

Первый scheduled snapshot `2026-09-02 10:09` сохранил 30/30 exact pairs и три raw
responses; raw SHA `487fc1c5...`, pairs SHA `4d831ef4...`, audit `15/15 true`.
Все 30 spot/futures pairs имеют two-sided BBO, exact units и clocks, но V1 status
`invalid_pairs`: best depth отсутствует у обеих ног, aggregate depth есть для 30 spot
и отсутствует для 30 futures. Это entitlement limitation, не parser/schema failure.
Task V1 disabled в `10:12`; отдельный V2 может копить delayed executable-side quotes,
но размер/queue/fill останутся unresolved до broker/AlgoPack evidence.

### Дополнительный source screen — funding curve ограничена лицензией, calendar breadth узкий

Официальная методология подтверждает рублёвую кривую RUSFAR на сроках overnight,
1W, 2W, 1M и 3M, но страница индикатора прямо требует договор для использования
значений с целью извлечения прибыли. Поэтому anonymous RUSFAR values не добавляются
в торговый dataset. Бесплатный причинный funding baseline остаётся latest available
CBR RUONIA; для исполнимого hurdle дополнительно нужны broker cash/REPO terms.

Metadata-only RFUD probe без quotes обнаружил две или более одновременно активные
квартальные серии только у `5/30` fixed stocks: `GAZP`, `LKOH`, `ROSN`, `SBER`,
`SBERP`. У остальных 25 сейчас доступна только одна подходящая серия. Значит broad
single-stock calendar-spread family не масштабируется на весь universe и пока остаётся
узким forward challenger; создавать фиктивные дальние контракты или считать outright
BBO атомарным multileg fill запрещено.

### Broad historical cash-carry source — COMPLETE, 2.13M CANDLES AUDITED

Metadata-only `show_expired=1` preflight по exact `underlying_asset` нашёл `339`
outright-контрактов 2023–2025 для `29/30` fixed stocks: по 12 серий у большинства,
10 у `BSPB/CBOM`, 7 у `TATNP`, 0 у `ENPG`. Calendar spreads и perpetuals исключаются
закрытым SECID/name rule; исторические `asset_code` сохраняются, включая переход
`PLZL -> PLZLM`. Ни candle, basis, return, signal, trade, PnL во время preflight не
читались.

Source config SHA `6bc8f4a2...`, seal `6726883`; collector/test commit `1b169f7`.
Collector жёстко ограничивает candles датой `<2026-01-01`, проверяет description
`TYPE=futures`, RFUD board, exact asset code и положительный integer `LOTSIZE`, хранит
все raw series/description/candle pages и делает replay audit. Targeted tests `2/2`,
scoped Ruff clean. Collection завершён после первых operational forward-срезов, чтобы
не мешать задачам 10:05/10:09. Допустим ровно один новый economic protocol: frozen V1
threshold/DTE/time/haircut/costs, меняется только breadth. Это новая проверка
возможности поднять частоту и диверсификацию, не найденная прибыль.
Полная регрессия после source implementation: `1141 passed, 7 skipped`; два прежних
V8 context failures остаются только из-за отсутствующего external manifest, новых
failures нет.

Canonical external bundle завершён в 10:35 и независимо replay-аудирован: 339 specs,
`2,132,435` 10m candles, 4,800 raw responses; specs/candles/raw SHA
`94104d5c.../0f254379.../624460af...`, audit `14/14 true`. Coverage 29/30; ENPG
остаётся missing. Следующий шаг уже не collection: preseal и один economic breadth
test с exact per-contract `lot_size_shares`, frozen 15:40/15:50, 30–90 DTE, exit 5
DTE, haircut 50%, hurdle `max(20%, RUONIA+4%)` и теми же costs.

Economic breadth protocol уже запечатан до чтения broad outcomes: SHA
`0279da39...`. Он сохраняет все перечисленные V1 правила и меняет только universe и
exact `lot_size_shares`; ENPG missing, CBOM/RUAL имеют explicit zero cashflow mapping.
Обязательны primary/doubled/zero-cashflow/one-bar-delayed scenarios и два заранее
заданных portfolio view: 1/29 equal sleeves и 10% active concentration cap. Следующее
действие — implementation/tests, затем один canonical run без настройки по результату.

Canonical V1 `...T080545Z_0279da39` технически прошёл внутренний audit и дал 45 trades,
но внешняя unit-validity проверка обнаружила structural mismatch, поэтому verdict
переопределён как `INVALID_HISTORICAL_UNIT_IDENTITY`, а не экономический `NO_GO`.
Back-adjusted TQBR и исторические futures/RMS имеют разные share basis у 27 контрактов:
TRNFP 5, GMKN 6, PLZL 9, VTBR 7. Например, старые PLZL имеют price ratio около 100
при description LOTSIZE 10; pre-consolidation VTBR — ratio около 20 при LOTSIZE
100000. Все V1 metrics (`0.59%` primary equal-sleeve CAGR и отрицательные stresses)
запрещено использовать для выбора активов или нового threshold.

Официальные MOEX notices подтверждают corporate actions: TRNFP split 1:100 с
21.02.2024, GMKN 1:100 с 08.04.2024, PLZL 1:10 в марте 2025 и VTBR consolidation
5000:1 в июле 2024. Source correction SHA `2416baf3...` фиксирует восемь notice URLs,
dates/factors и exact 27 pre-action contracts до corrected replay. Сначала собрать и
byte-pin raw notices, затем sealed R1 может изменить только unit basis, не universe,
signal, time, DTE, hurdle, costs или portfolio views.

Correction source завершён: 4 events, 27 affected contracts, 8 raw HTML; events/
affected/raw SHA `ce06df7.../32939c5f.../272e9700...`, replay audit `15/15 true`.
Economic R1 уже запечатан SHA `c2aa6752...` до corrected outcomes. Он наследует parent
implementation/config по exact hashes и меняет только adjusted spot units плюс
per-share RMS basis до effective corporate-action dates. Price-unit gate заранее
требует 338 контрактов с median normalized ratio `0.75..1.35` и один explicit missing.

R1 canonical `runs/stock_futures_cash_carry_broad_r1_20260902T082721Z_c2aa6752/`
прошёл 12/12 audit и unit gate: 338 valid ratios `0.919..1.066`, один explicit missing
`CMU3`. 11,711 decisions, 29 trades; primary wins 29/29, zero/delayed 24/29. Equal
sleeves primary/doubled/zero/delayed CAGR
`1.8412%/1.7614%/0.4166%/0.4118%`, Sharpe `1.912/1.867/1.124/1.116`, MDD
`0.3866–0.5127%`; active-cap CAGR `5.3132%/5.0841%/1.1634%/1.1500%`, Sharpe
`1.914/1.869/1.061/1.053`, MDD `1.0596–1.5641%`. Все 3 года положительны во всех
сценариях. Verdict `FORWARD_CANDIDATE`, но standalone ниже 20% и execution не доказан.

Следующий overlay уже sealed до результата: SHA `e5d91172...`. Он сохраняет exact 29
trades и оба views, добавляя только унаследованные из V41 50% causal RUONIA на
неактивный капитал; entry/exit day ineligible, active-cap использует conservative
max(current, previous exposure). Никакой сигнал/weight/threshold не меняется.

### Forward cash-carry quotes — SEALED, automation ready, 0/60 pairs

Source V1 SHA `b25fe86c...`, seal `a193e0d` зафиксирован до первого post-seal BID/OFFER.
Collector сохраняет только official series/description и текущие TQBR/RFUD BID/OFFER
для пяти frozen пар в 15:49/15:59 МСК. Контракт выбирается metadata-only по exact
`LSTTRADE` 30–90 дней, `LOTSIZE=100`; no contract = explicit sleep, неполная/locked
quote = invalid всего snapshot. Raw canonical JSON replay exact, backfill до
`2026-09-02` и derived basis/signal/trade/PnL запрещены.

Модули `moex_forward_stock_futures_cash_carry_source` и
`forward_stock_futures_cash_carry_readiness`, wrappers и Windows tasks готовы.
Implementation `a8f0139`, exact-second scheduler correction `766c6f8`; tasks
`TradingLabForwardCashCarryDecision` и `TradingLabForwardCashCarryFill` имеют status
`Ready`, ближайшие запуски `2026-09-02 15:49:00/15:59:00` МСК.
Readiness: `0/60` complete decision/fill discovery pairs, затем 20 calibration и 60
unseen evaluation; fill retrieval обязан быть позже decision. До 60 пар новая
экономика/PnL запрещены, до окончания unseen evaluation запрещена annualization.
Подробности: [FORWARD_STOCK_FUTURES_CASH_CARRY_PROTOCOL.md](FORWARD_STOCK_FUTURES_CASH_CARRY_PROTOCOL.md).

### Forward LQDT idle cash — SEALED, tasks READY, 0/60 pairs

Проверен конкретный механизм вместо условных 50% RUONIA. LQDT (`RU000A1014L8`, ПДУ
№3915) — торгуемый на TQBR БПИФ денежного рынка; официальная цель — доход через РЕПО
с ЦК. Однако сообщение MOEX/NCC с 15 июля 2026 не включает LQDT в расширенный список
обеспечения. Поэтому допустимая гипотеза совпадает с V41: LQDT только в неактивном
sleeve и ноль паёв во время stock-futures позиции, без двойного использования капитала.

Source SHA `15fb471a...`, seal `8ae3dc3` предшествует official quote values. Два
forward-only TQBR snapshot 15:49/15:59 сохраняют BID/OFFER, lot/minstep, settlement и
clocks; iNAV LQDTM не собирается из-за нерешённых условий коммерческого использования
индексных данных. Readiness 0/60 + 20 calibration + 60 unseen; paper yield/PnL пока
запрещён. Implementation `d03a8b7`; tasks `TradingLabForwardLqdtDecision/Fill` имеют
status `Ready` и exact next run `2026-09-02 15:49:00/15:59:00` МСК.
[FORWARD_LQDT_IDLE_CASH_PROTOCOL.md](FORWARD_LQDT_IDLE_CASH_PROTOCOL.md).

### V41 joint depth admission — SEALED, 0/60 joint dates

Перед первым snapshot выяснено, что raw ISS обоих collectors уже содержит
`BIDDEPTH/OFFERDEPTH`, хотя processed V1 хранит только quotes. Поэтому источники не
перезапускаются. Отдельный source-quality gate SHA `8183eb50...`, seal `293165b`
требует на каждом stage: все 5 spot/futures pairs, глубину для минимум 100 акций и
1 контракта в обе стороны, положительную LQDT depth и retrieval skew между collectors
не более 30 секунд. Fill каждого parent строго позже decision.

Joint readiness сейчас `0/60`; затем 20 calibration и 60 unseen. Gate не вычисляет
basis/yield/return/signal/trade/PnL и не решает LQDT allocation capacity, broker queue,
fees, margin или settlement. Это предотвращает накопление 60 дней формально полных,
но фактически неисполнимых котировок.

### Fixed idle-fund pool — SEALED, tasks READY, 0/60 pairs

Чтобы не привязывать V41 к одному LQDT, до чтения котировок зафиксирован пул
`LQDT/SBMM/AKMM/TMON` с exact ISIN/ПДУ. Source SHA `37a3baeb...`, seal `ac299a7`.
Два среза 15:49/15:59 сохраняют BID/OFFER, лучшую/общую depth, lot/minstep,
settlement и clocks всех четырёх фондов; неполный фонд делает snapshot invalid.
Implementation `3c2f1eb`; tasks `TradingLabForwardFundPoolDecision/Fill` зарегистрированы
и имеют status `Ready`, ближайшие запуски `2026-09-02 15:49:00/15:59:00` МСК.

До 60 полных пар нельзя ранжировать фонды. После discovery правило выбора сначала
запечатывается, затем получает 20 calibration и 60 unseen пар. В экономику обязательно
войдут покупка по OFFER, продажа по BID, комиссия, налог, settlement и полная ликвидация
перед активной cash-carry позицией. Live false; залоговая пригодность не предполагается.
[FORWARD_MONEY_MARKET_FUND_POOL_PROTOCOL.md](FORWARD_MONEY_MARKET_FUND_POOL_PROTOCOL.md).

## V40R1 stability blend 80% V39 + 20% cash-carry — risk reduced, strict NO-GO

Единственный weight `80/20`, отсутствие rebalancing и scenario mapping были запечатаны
до combined equity. Первый V40 SHA `125c4740...` fail-closed остановился в parent
preflight: ledger ошибочно объявлен 781 rows вместо factual 793; combined metrics не
считались. R1 SHA `05ce1266...`, seal `eddd16f` изменил только row count. После
успешной записи первый output `...T041223Z...` завершил процесс ошибкой печати Unicode
`Δ` в CP1251; report-only ASCII correction `b445f33` не менял числа. Canonical:
`runs/v40r1_v39_cash_carry_stability_v1_20260902T041248Z_05ce1266/`; metrics
`8812dffb...`, manifest `9460e514...`, audit `572221d6...`, ledger `9bd3ebdc...`.

Primary/doubled/stress CAGR `25,0336%/24,6070%/24,1113%`, Sharpe
`1,2392/1,2188/1,1993`, MDD `17,4210%/17,5226%/16,8766%`. Относительно V39 MDD
улучшена на `2,6111/2,6366/2,5583 п.п.`, worst year — на
`0,7425/0,7509/0,4224 п.п.`; primary стал положительным во все пять лет, включая
2025 `+0,2264%` вместо `−0,5162%`. Все stress CAGR остаются выше 20%.

Strict verdict `NO_GO`, потому что заранее обязательный Sharpe gate ухудшился на
`0,0122/0,0129/0,0196`; остальные три gates true. Это не повод подбирать вес после
результата. Frozen 80/20 можно считать отдельной более консервативной historical
альтернативой V39, но только новый forward период может решить, воспроизводится ли
снижение drawdown. Live false, результат same-history adaptive.

## Новый стабильный sleeve: covered stock–futures cash-and-carry V1 — NO-GO standalone

После провала несинхронного dividend-spread направления запечатан принципиально иной
контрактный механизм: купить 100 акций и одновременно продать один deliverable futures
того же эмитента. Source V2 SHA `ffef4524...` сохранил 61 контракт, 16 589 daily rows
и 4 625 PIT cashflow observations. Публичный старый dividend endpoint MOEX оказался
ошибочным, актуальный CCI вернул `X-MicexPassport-Marker: denied`; paid values не
читались. Source V3 SHA `d6e751e7...` был pushed до intraday values и собрал 485 141
официальную 10m свечу, 61 description с `LOTSIZE=100` и 1 058 raw responses. Canonical
source `data/processed/info_radar/moex-stock-futures-cash-carry-intraday-2023-2025-v3/`;
manifest `c9ca6aa8...`, candles `0f16e6e9...`, raw `dbe9b156...`; replay exact.

Economic SHA `aa35b0d8...`, seal `0416fb4` precedes basis/signals/PnL. Fixed rule:
15:40 Moscow close decision, exact synchronized 15:50 next-open fill, nearest 30–90 DTE,
exit at 5 DTE, fully funded long 100 shares/short one futures, 30% futures capital
reserve, 50% haircut PIT RMS cashflow, admission `max(20%, RUONIA+4%)`, costs
spot/futures 10/5 bps per side and doubled 20/10. No parameter fitting.

Canonical `runs/stock_futures_cash_carry_intraday_v1_20260902T040404Z_aa35b0d8/`;
metrics `e9eee0c3...`, manifest `9025f572...`, audit `e2216343...`. Из 2 262 решений
получено 15 signals/trades; все 15 primary прибыльны, 14/15 прибыльны даже при zero
cashflow + doubled costs. Primary/doubled/zero-cashflow CAGR
`5,1921%/4,9605%/2,3388%`, Sharpe `2,9436/2,9062/3,6012`, MDD
`0,6399%/0,6416%/0,6551%`. Годы: 2023 `0%`, 2024 `+5,5773%`, 2025 `+10,2042%`.
Full RMS proxy upper bound CAGR `7,8141%`.

Verdict `NO_GO` как самостоятельная 20% стратегия: trades `15 < 20`, CAGR ниже цели,
RMS не доказывает фактическую выплату, а candles не доказывают bid/ask execution.
Однако это первый отдельный механизм с высоким Sharpe и почти нулевым drawdown;
сохранять как frozen stabilizing sleeve. Threshold/DTE/time/haircut/costs на этой истории
не менять. Следующий допустимый тест — заранее sealed портфель frozen V39 + этот sleeve
или новый forward collector с bid/ask и broker margin, не оптимизация cash-carry V1.

## Последний результат: V38 official MOEX MR1 governor — NO-GO

Новый point-in-time архив официальных риск-параметров MOEX был запечатан как source
V4 SHA `83bcabed...` до чтения `MR1`: 4 647 raw responses, 189 682 `limits` states,
88 639 `staticparams` states и 10 817 unique cashflow events. Canonical source
`data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/`; manifest
`e88360d3...`, audit `013c6e23...`, raw ZIP `d2b8d5e4...`; независимый replay дал
11/11 true. V1–V3 корректно остановились без output на обнаруженных temporal/key
особенностях архива и не являются источниками.

V38 config SHA `3f9288e3...`/seal `dd5d118` и implementation `832f12c` были pushed до
чтения MR1/PnL. Frozen V27 дополнялся единственным asset-specific правилом: на weekly
decision latest causally available official `MR1` сравнивался с предыдущим weekly
state; exact positive change переводил только соответствующий SI/RI/BR/MIX target в
cash, missing/stale также cash. Zero boundary, seven-day age, V27 signal/governors,
2x, RUONIA, execution и costs не подбирались.

Canonical `runs/v38_moex_margin_risk_governor_20260902T020147Z_3f9288e3/`; metrics
SHA `32b457ab...`, identity `f5c76687...`, 26/26 artifacts exact и независимый metric
replay 15/15 true. В OOS было 23 increase states и 18 сокращённых ненулевых targets.
Primary/doubled/stress CAGR `24,5261%/23,9458%/23,5132%`; primary Sharpe `1,0868`,
MDD `20,2538%`, worst year `−0,5832%`. Все CAGR выше 20%, primary MDD и worst year
лучше V27, но Sharpe хуже на `0,1251`, doubled MDD хуже на `0,1088 п.п.`, stress —
на `0,7363 п.п.`. Verdict `NO_GO`: same-history MR1 threshold/duration/level, MR2/MR3,
global switch и inversion больше не тестировать. Источник остаётся полезен для forward
execution/margin admission и экономически иной dividend/defined-risk option family.

## Новый historical source: public MOEX option EOD pilot V2 — SOURCE COMPLETE

После subscriber-only monthly ZIP найден официальный public ISS endpoint exact-date
history для рынка options. Source V2 SHA `685fb7e9...` и seal `cecda6f` были pushed до
чтения значений января 2021; collector commit `affed25`. Canonical
`data/processed/options/moex-core4-options-pilot-2021-01-v2/`: 124 asset-date запроса,
1 133 raw pages, 105 318 rows, 6 956 SECID, даты `2021-01-04..2021-01-29`; SI/RI/BR/MIX
`58 742/18 956/17 010/10 610`. Manifest `0211e452...`, processed `9a37fb55...`, raw ZIP
`76474c32...`, audit `6f069c60...`; повторный raw replay 9/9 true.

Это качественный источник settlement/contract states, но ещё не источник честной
опционной доходности: `THEOR_PRICE` отсутствует во всех строках, `CLOSE` есть только в
7 868, positive volume/trades — в 7 887 (около 7,5%), historical bid/ask отсутствуют.
Нельзя считать settlement/theoretical value ценой исполнения. До official exact
expiry/spec mapping и licensed Type B/A bid/ask/order history historical option PnL не
запечатывать. Практический путь — продолжать forward option collector: readiness 1/60,
invalid 0; затем 20 calibration и 40 unseen evaluation.

## Последний результат: V39 weekly option-OI tail governor — GO TO FORWARD

Пилот расширен в отдельный target-free weekly source V3, запечатанный commits
`9a51a3c`/`f6327c7` до non-pilot values. Canonical
`data/processed/options/moex-core4-options-weekly-2021-2025-v3/`: 261 exact frozen-V27
decision dates × 4 assets, 1 044 jobs, 13 802 raw pages, 1 327 744 rows и 108 104 SECID.
Manifest `0453f05c...`, audit `e09534ff...`, Parquet `fdd67cd9...`, raw ZIP
`c1308810...`; независимый replay 11/11. Во всех 1 044 asset-week группах положительны
и call, и put OI; source не содержит returns/targets/predictions/PnL.

V39 SHA `3b5d3074...`, seal commit `700ff9a` и implementation commits
`b9e5114`/`f184834` pushed до первого успешного join с V27/PnL. Единственное
правило: latest source date строго раньше weekly decision; изменение aggregate put-share
сравнивается с 10/90 квантилями только 52 предыдущих изменений того же asset. Long
гасится лишь выше q90, short — лишь ниже q10; warmup проходит parent без изменений,
missing/stale после warmup гасит asset. Опционы не торгуются, V27 execution/costs/2x
не меняются.

Canonical `runs/v39_option_oi_tail_governor_20260902T025023Z_3b5d3074/`; metrics
`52993f82...`, identity `fe60f262...`; 17/17 artifact identities и независимый replay
primary/doubled/stress metrics, rolling q10/q90, scale и target rules полностью true.
Из 1 044 OOS asset-weeks получены 97 put-tail и 101 call-tail state, 44 ненулевых target
сокращены. Primary/doubled/stress CAGR `28,6849%/28,2235%/27,8287%`, Sharpe
`1,2515/1,2317/1,2189`, MDD `20,0322%/20,1593%/19,4348%`; worst year
`−0,5162%/−0,9560%/−1,4607%`. Все scenario CAGR выше 20%; относительно V27 улучшены
CAGR, Sharpe, MDD и worst year во всех требуемых сравнениях. Verdict
`GO_TO_NEW_FORWARD_CONFIRMATION`, live false: это adaptive same-history evidence, не
независимое доказательство и не обещание 50%. Window/quantiles/signs/assets/scale больше
не менять; добавить V39 к forward paper validation как заранее замороженный challenger.

Forward V39 V1 уже запечатан SHA `3677bcca...`, commit `ba9bbb1`; старый atomic
readiness сохранён для exact replay. Component successor V2 принимает admission
`62ca9450...`, raw-replay проверяет V27 components и не вычисляет signal/PnL. Текущее
состояние: option weekly levels `1/54`, V27 official CLOSE `1/253`, execution/FRED/CBR
`1/1/1`, causal join `0`, invalid option/component snapshots `0/0`; paper economics и
CAGR reporting false. После обоих
warmup потребуются 504 sessions/104 weeks/two full years. Полный контракт:
[FORWARD_V39_PROTOCOL.md](FORWARD_V39_PROTOCOL.md).

## Dividend-adjusted single-stock spreads — NO-GO

RMS cashflow не покрывает SI/RI/BR/MIX, зато даёт 4 994 point-in-time anticipated
cashflow rows на 170 dates для GAZR/SBRF/ROSN/TATN/NOTK. Official series metadata
подтвердил 53 dated same-root calendar spreads `2023-03-17..2025-12-19`; все 53 exact
archive codes присутствуют в public MOEX spread archive. Price/Bid/Ask/PnL до seal не
читались.

Source-only config SHA `ad9a3008...`, seal commit `3e8dd71`; adapter commits
`be2e4d3..92aed3d`. Canonical source
`data/processed/info_radar/moex-dividend-calendar-spreads-2023-2025-v1/` имеет 53
спреда, 3 513 ISS rows, 3 556 archive rows и 222 exact raw responses. Manifest
`a8c1b0b0...`, raw `439a514a...`; полный series/board/history/HTML/CSV replay true.

Economic V1 SHA `52a8ce06...`, seal `adf36d5`, implementation `7fba805` и
empty-ledger audit correction `f62fdbd` были pushed до успешного output. Единственное
правило: strictly prior RMS cashflow между expirations задаёт opposite fair shift;
вход только на следующей bid/ask quote при остающемся положительном edge, затем
fair-target/2-edge stop/10 observations, дополнительные costs 2/4/8 points.
Canonical `runs/dividend_calendar_spread_v1_20260902T032624Z_52a8ce06/`; metrics
`18646592...`, manifest `37759b73...`, audit exact. Из 31 cashflow-change events не
осталось ни одного executable entry: следующая quote уже не давала положительный edge.
Verdict `NO_GO`. Same-history sign/lag/threshold/events/holding и same-day RMS закрыты;
следующий осмысленный dividend-source должен появляться **раньше** RMS/рынка, например
original-timestamp issuer/board disclosures, и проверяться только новым seal.

## Последний результат: V37 cross-market intraday breakout — NO-GO

V37 проверил принципиально иной target на frozen 30-stock 10m source: one-sided
трёхакционный Donchian continuation с breadth всех бумаг, fixed full/aggregate MLP
threshold `0,60`, next-open entry, trailing-profit corridor `0,6%/0,4%`, distant stop
`1,8%`, maximum 24 bars и costs `1x/2x/3,5x`. Config SHA `15c6d67c...`, seal
`f8dd07f`; implementation `b12876f` был pushed до target/PnL. Первый run остановился
до outcomes/output на timestamp-index decode; parser-only correction `6cd2c0a` была
pushed до возобновления.

Canonical `runs/v37_cross_market_breakout_20260902T011012Z_15c6d67c/`; metrics SHA
`4023a7ea...`, identity `ead762ab...`, audit `1279ea48...`, manifest `a000b2a3...`;
artifact replay полностью true. Получено 6 392 candidates, 6 355 с наблюдаемым path,
5 045 OOS signals ungated и 10 090 neural predictions. Full MLP оставил один signal,
но factual participation `1,994%` превысил 1%, поэтому trade `0`, unresolved `1`;
aggregate MLP оставил 0 signals.

Ungated primary/doubled/stress CAGR `−9,0797%/−23,2151%/−83,7847%`, primary Sharpe
`−1,2835`, MDD `35,5776%`, 751 trades, worst year `−17,4140%`. Long-only ungated
primary CAGR `−6,6135%`, Sharpe `−1,2434`, все четыре года неположительны. Required
participation отдельных candidates достигало `42,716%`; costs primary ungated
`360 741,67 ₽`. Verdict `NO_GO`: threshold/sign/exit/stop/leverage/ticker/year больше
не менять на этой истории. Price-only 10m continuation не является источником 20%.

## Главная активная проверка: V27 forward validation

Сильнейший development-кандидат V27 (`28,3752%` CAGR, Sharpe `1,2119`, MDD
`20,7138%`) имеет независимый forward V1 seal SHA `c1acf97b...`, commit `a79fd4c`.
До первого snapshot обнаружено, что current `LAST` не равен официальному дневному
`CLOSE`, который использует V12/V27. V1 source поэтому superseded без данных. Чистая
source-коррекция V2 SHA `f4a7d016...` запечатана commit `941e0b9` до просмотра
post-seal CLOSE; реализация commit `09e73c4`, SHA `f38a41f0...`, сохраняет отдельный
official history row каждого контракта и полностью replay-аудируется. Экономика и
параметры не изменены; backfill market data `2026-01-01..2026-09-01` запрещён.

Authoritative server execution timer остаётся 10:05 мск. Decision 23:45 оказался раньше
полной публикации official history и правильно завершился без output. Неизменный retry
в 00:45 создал 25-row market decision и прошёл полный replay. Operational schedule V2
SHA `48f16f2c...` фиксирует Tue–Sat 00:45/01:15/06:00: первый success сохраняется,
следующие attempts только аудитят и skip-ят ту же source date. Paper contract SHA
`d68f0595...`/commit `51acd4c` и fail-closed preflight `05a1f74` также опубликованы
до первого snapshot. В нём 252 return sessions требуют 253 common official CLOSE;
partial current week не считается завершённой. Сейчас 1/253 price warmup,
0/504 unseen evaluation. До завершения warmup PnL запрещён; до 504 evaluation sessions
никакая короткая annualization не является доказательством 20–50%. Полный порядок:
[FORWARD_V27_PROTOCOL.md](FORWARD_V27_PROTOCOL.md).

Первый atomic execution run `2026-09-02 10:05` и ручной retry не создали общий snapshot:
официальный FRED STLFSI4 endpoint трижды дал 30-second read timeout. Market/CBR bytes
не были частично опубликованы, cache/zero substitution запрещены. Это состояние
сохранено как корректный fail-closed результат superseded atomic V2.

Этот availability coupling исправлен новым source-storage boundary до первого decision:
component config SHA `242d2684...`, implementation `026fef9f...`, readiness
`d7b4d30a...`; V48 source-mapping correction SHA `019f970e...`. Scheduled wrapper
сначала сохраняет required MOEX component, затем независимо пытается CBR и FRED.
Фактически сохранены и replay-аудированы execution `1` (`25` rows), decision `1`
(`25` rows) и CBR `1` (`550` rows). Новый anonymous FRED transport V2 был запечатан
до ответа: source SHA `8a26480d...`, admission SHA `62ca9450...`, implementation
`5cf38c92...`. Он изменил только headers. Deploy `799656f` создал первый 57-row FRED
component; audit `15/15`, manifest/audit `e1d7b83c.../5d34f36f...`. Readiness V3:
4 valid, 0 invalid, FRED/CBR ready, warmup `1/253`. Любой join по-прежнему требует
macro `retrieved_at <= decision_at`; поэтому поздний первый FRED не ремонтирует прошлое
decision и causal join остаётся `0`.

Downstream commit `8cee8cd` добавил V48 readiness V4 и V49 forward/paper readiness V2;
`df8c57e` добавил V39 component readiness V2. Они принимают V2 protocol id и сохраняют
прежние boundaries, fixed multipliers и promotion gates. Signal/return/target/
prediction/PnL не вычислялись.

Отдельный operational blocker: hard fallback ролла требует official future-session
calendar MOEX. Endpoint найден, но без `MOEX_ALGOPACK_TOKEN` возвращает HTML. Generic
weekdays запрещены; отсутствие авторизации не мешает накоплению source, но блокирует
paper economics/promotion.

## Новый независимый источник: MOEX RMS cashflow/risk — ACTIVE, 0/60 discovery

Публичные official `staticparams`, `limits`, `cashflow` дают anticipated cashflows по
21 underlying и risk/margin parameters по 198 asset codes без price/return/PnL. Source
V1 SHA `fd0145eb...` был запечатан до values, но metadata probe обнаружил независимый
clock cashflow (`2026-08-26`) против risk tables (`2026-09-01`); V1 output не создан.
V2 correction SHA `48044ecf...`/commit `cc1bcd2` разрешает только раздельные clocks и
фиксирует `available_at >= actual retrieval`, не меняя экономическую гипотезу.

Collector commit `dcd9795`, automation/readiness `ff4d0d0`; synthetic raw replay
`4/4`. Task `TradingLabForwardMoexRms` имеет status `Ready`, Mon–Fri 23:35 мск. Первый
snapshot запрещён, пока risk source date меньше `2026-09-02`; сейчас 0/60 discovery,
после него 20 calibration и 60 unseen evaluation. Допустимые будущие families заранее
ограничены dividend fair value, margin-risk governor, cross-asset ranking и defined-risk
option regime; economic seal и PnL до discovery запрещены.

## Последний результат: V36-R1 multi-era online expert ensemble NO-GO

V36 проверила на одной причинной шкале `2008-10-08..2025-12-30` десять заранее
фиксированных экспертов: четыре trend horizon, multi-horizon trend, curve carry,
trend/carry confirmation, cross-asset relative trend, horizon consensus и cash.
Discounted exponential weights обновлялись только раз в неделю по уже завершившейся
предыдущей неделе; сравнения — static equal active experts и frozen three-sleeve.
Evaluation `2013..2025`, exact next-open integer execution, 1% participation и три
сценария costs; 2026 не читался.

Первый immutable V36
`runs/v36_online_expert_20260901T223514Z_cb391e44/` оказался технически невалиден:
derived pre-2018 execution заканчивался `2017-12-01`, хотя три Z7-контракта оставались
открыты. Это породило 6 161 missing contract rows и ложный нулевой PnL 2018–2025.
Каталог не изменён. R1 до исправленного PnL запечатал parent daily SHA `00a9a872...`,
ровно 42 официальные строки SI/RI/MIX за `2017-12-04..2017-12-21` и детерминированный
flat на factual expiry open `2017-12-21`; сигнал, eta/decay, риск, leverage и costs не
менялись. Config SHA `156f573c...`, runner SHA `7a1c18b9...`, seal `aea629f` pushed до
outcome; outcome-free tests `14/14`.

Canonical R1:
`runs/v36r1_online_expert_20260901T224722Z_156f573c/`; metrics SHA `9812a1fd...`,
identity SHA `c193c7cf...`, audit SHA `d97aaa82...`; independent audit 11/11. Все
ledgers complete, critical/unresolved `0`, 3 159/3 159 nonzero targets covered.
Online primary/doubled/stress CAGR `6,4262%/5,1407%/4,8394%`, primary Sharpe `0,3989`,
MDD `40,7292%`, positive years `7/13`, worst year `−25,937%`. Static equal primary
лучше: CAGR `8,1551%`, Sharpe `0,4566`, MDD `39,3230%`; frozen three-sleeve primary
`6,6055%/0,3949/48,7712%`.

Verdict `NO_GO`: online allocator не превзошёл статическую смесь и не поддерживает ни
20%, ни 50%. Веса запаздывают за режимами; новый способ смешивания тех же сигналов не
является новым edge. V36 horizons/signs/eta/decay/cash/risk/leverage/costs и boundary
repair не менять по этому outcome. Следующий исторический тест обязан добавлять
независимый механизм дохода или новый point-in-time источник; live trading запрещён.

Новый независимый source уже запущен: `moex_forward_option_surface_source` был
sealed/pushed `f9dba15` до persistence и сохранил первый public-delayed SI/RI/BR/MIX
snapshot `snapshot_20260901T230311250639Z`. В нём 2 062 контракта, 532 положительных
двусторонних quotes, полные settlement/underlying settlement и audit 17/17. Исторический
monthly ZIP оказался subscriber-only и не подменялся. До накопления последовательности
60 discovery + 20 calibration + 40 unseen evaluation опционный PnL запрещён; будущая
family — только defined-risk premium, без naked short.
Сбор больше не ручной: task `TradingLabForwardOptionSurface` зарегистрирован на Mon–Fri
23:55 UTC+3 с `StartWhenAvailable`, `IgnoreNew` и timeout 10 минут. Source-date probe
предотвращает повтор одной торговой даты. Независимый manual task run дал result `0` и
не увеличил snapshot count (`1`), то есть operational loop фактически проверен.
Read-only readiness monitor повторно проиграл raw responses и подтвердил `1` valid unique
date, `0` invalid, current phase `discovery`, remaining `59` до разрешения seal
экономического protocol. Повреждённый snapshot теперь не блокирует immutable replacement.

Параллельно открыта принципиально другая relative-value ветка: USD/RUB cash-and-carry.
Source config/code commits `bd7f138`/`a049b51` были pushed до market read. Canonical
`USD000UTSTOM` source содержит 2 027 unique dates `2018-01-03..2025-12-30`, 21 raw page,
51/51 replay checks; manifest `59f1d026...`, Parquet `e83f562f...`, audit `408cc22c...`.
OHLC полны, WAPRICE missing 398. Basis/PnL ещё не считались: следующий допустимый шаг —
отдельно sealed long-spot/short-SI protocol с next-session execution, costs, margin и
RUONIA opportunity cost. Это новый механизм дохода, но пока не результат.

Экономический V1 уже завершён и закрыт как `NO_GO`: canonical
`runs/fx_cash_carry_v1_20260901T233224Z_4b3ca33e/`, metrics `3f638a7b...`, replay
11/11. Development дал лишь одну сделку и CAGR `0,3471%` против RUONIA `7,2699%`;
evaluation — 0 сделок, CAGR `0%` против RUONIA `16,5405%`. 398 zero-price/zero-trade
spot rows начинаются после `2024-06-12`, поэтому USD/RUB cash-and-carry через MOEX
spot не является рабочей веткой для 2025. Threshold/date tuning запрещён; следующий
relative-value screen должен использовать реально продолжающий торговаться spot.

CNY screen завершил следующий шаг. Source commits `b217921`/`0149d4d` предшествовали
первому price build; canonical bundle имеет 2 027 `CNYRUB_TOM` rows и 3 636 rows всех
12 quarterly `CRH3..CRZ5`, 157/157 replay checks. Manifest `7b8c4a8d...`, spot
`f9132e51...`, futures `36c2af69...`, audit `ac371f8b...`; в 2025 spot имеет 254
positive-trade sessions и все четыре CR торгуются. Economic config/runner
`0fef4c6`/`f17e1f6` были pushed до outcomes. Canonical
`runs/cny_cash_carry_v1_20260901T234628Z_1b9406d9/` operationally complete, но
`NO_GO`: 0/8 development и 0/4 evaluation entries перекрыли RUONIA+2% на полном
spot/margin capital; evaluation CAGR `0%` против RUONIA `20,9377%`.

Капиталоэффективная futures/futures ветка также завершена. Source V2
`data/processed/fx_basis/moex-cny-perpetual-current-vintage-v2/` содержит 937
`CNYRUBF` sessions `2022-04-26..2025-12-30`, 784 nonmissing `SWAPRATE`; audit 33/33,
manifest `1664a012...`, Parquet `3b1ee181...`. Economic V1 был запечатан до ставок,
но оказался **невалиден по единицам**: funding умножался на lot 1 000, а price PnL,
notional и costs — нет. Его immutable run
`runs/cny_perpetual_quarterly_spread_v1_20260902T000440Z_5b2d6be7/` и абсурдный
numeric GO запрещено использовать как evidence.

Отдельный V2 unit correction SHA `6a0a7cbe...` и runner `48afc99` были pushed до
corrected PnL. Canonical
`runs/cny_perpetual_quarterly_spread_v2_20260902T000944Z_6a0a7cbe/`, metrics
`d1a23519...`, audit `c6d8cdd2...`; independent audit 15/15. Corrected point value,
notional, spread и commission равны quote cash × 1 000, funding остаётся
`SWAPRATE × 1 000`. Результат `NO_GO`: 0/8 development и 0/4 evaluation entries;
evaluation CAGR `0%` против RUONIA `20,9377%`. Лучший sealed entry CRH5 имел
расчётные `13,8903%` при causal RUONIA `20,85%`, поэтому hurdle не прошёл.
Threshold/date/direction и тот же zero-yield collateral больше не менять.

## Последний результат: V35 thirty-stock intraday residual basket NO-GO

V35 проверила принципиально иной механизм: после каждого второго завершённого
10-минутного бара синхронное состояние всех 30 акций определяет три наиболее
отрицательных residual-z для long и три наиболее положительных для short. Вход — на
следующем exact common open, выход через 60 минут, одновременно только одна
dollar-neutral корзина. Full MLP видит четыре 30-мерных блока и агрегаты; ablation MLP —
только агрегаты; fixed rule торгует каждый кандидат. Threshold `0,55/0,65/0,75`
выбирается исключительно на предшествующем календарном году под doubled costs.

До economic read source-only seal `95fad8a` создал физически изолированный bundle
`data/processed/stocks_10m_pre2026_v1/`: 30 Parquet, 4 527 436 rows,
`2018-01-03..2025-12-30`, manifest SHA `5a7a4873...`, audit 12/12. V35 config SHA
`257422c0ce2824e3a12252f1759e01fdee29c321f11190bd3b09d9a2b4984388`, core SHA
`f31e0b80...`, runner SHA `b7dce2d8...`. Seal `fac5625` был pushed до первого
economic calculation. Первая попытка остановилась до returns/labels/PnL и без output
на pandas-index representation `timestamp`; loader-only fix `df207d1` был tested и
pushed до повторного economic start, не меняя config/economics.

Единственный canonical run
`runs/v35_cross_sectional_intraday_20260901T220621Z_257422c0/`: metrics SHA
`8c9820cf...`, identity SHA `18b48fba...`, audit SHA `dbfb1305...`; audit 16/16.
96 005 common timestamps дали 11 297 candidates, 9 024 evaluation candidates и 18 048
neural predictions. Positive doubled-cost labels только 420. Все восемь annual
model-folds получили `sleep_insufficient_calibration`, поэтому обе MLP сделали ноль
сделок. Пороги после outcome не ослаблять.

Fixed rule исполнил 2 965 primary trades. Gross profit всего 29 706,79 RUB против
436 751,84 RUB trading costs и 10 833,56 RUB borrow; gross win rate `52,82%`, но net
win rate `14,77%`. Primary total `−41,7879%`, CAGR `−12,6519%`, Sharpe `−8,9863`,
MDD `41,7928%`; годы 2022/2023/2024/2025 = `−2,7500%/−9,7048%/−15,2270%/−21,8009%`.
Doubled CAGR `−38,1944%`, stress почти полная потеря. Fixed execution также выявил
867 primary capacity-unresolved: historical bar value недостаточен как доказательство
fill, short locate/lot history отсутствуют. Это усиливает live-запрет, но не меняет
экономический вывод: gross edge на исполненных primary trades был лишь `0,858 bp` в
среднем при 20 bp round trip. Verdict `NO_GO`; V35 sign/horizon/threshold/universe/
cost/leverage больше не tune-ить.

После добавления equity forward collector целевые source/V35/encoding tests `23/23`,
scoped Ruff clean. Полный suite штатной командой `python -m pytest`: `997 passed,
7 skipped, 2 failed`; оба failure — прежний sealed V8 anti-junction guard, который не
принимает внешний NTFS `data/`, новых failures нет. Standalone `pytest.exe` отдельно
не является штатным entry point: он не добавляет root в import path и останавливается
на трёх legacy collection imports.

Следующее независимое направление — forward equity microstructure: official MOEX
stock `tradestats/orderstats/obstats`, реальные spread/depth, aggressive flow и order
cancel imbalance, дополненные broker short-locate/borrow и lot-size records. До
накопления original-vintage snapshots новый neural PnL по этому направлению sleeping.

Public delayed futures source уже фактически проверен:
`data/forward/moex-microstructure-v1/snapshot_20260901T214719330521Z/`, source date
`2026-08-18`, 8 normalized FUTOI rows, audit 11/11. Он target-free, но задержка 15 дней
не позволяет использовать его для same-day timing; `MOEX_ALGOPACK_TOKEN` отсутствует.

## Последний результат: V34 relative-corridor barrier NO-GO

После закрытия absolute-return regression подготовлена отдельная family V34. Она
торгует только относительное отклонение RI–MIX: beta оценивается по 132 последним exact
returns, admission требует `|z| >= 1,5`, take-profit равен одной residual sigma на
шестибарном масштабе, distant stop в три раза дальше, maximum hold 12 баров. Target —
достигнут ли take-profit и положителен ли stress-net выход на следующем open. Это не
перенастройка знака или threshold V32/V33.

Full MLP `[24,12]` оценивает barrier probability по всем четырём рынкам и MOEX curve
context; сравнения заранее фиксированы как тот же market-only MLP и безмодельное fixed
corridor rule. Monthly expanding core, preceding-three-month calibration и one-day
purge могут выбрать только probability `0,55/0,65/0,75`. Не больше двух
неперекрывающихся сделок в день. RI и MIX открываются/закрываются атомарно; risk at stop
`0,75%`, pair gross `<=1,2`, asset `<=0,6`, signal/factual participation `0,25%/1%`,
exit имеет максимум шесть exact retry.

Config SHA `eece2650f3f049d29ae6e9ba3fe65f98393f368c6ab40c36740da0ab7c6c7c09`,
core SHA `f3e86c52b5199b2e6844326cb771cbef9a075c0420f71c74d8f7d8906908b8f6`, runner SHA
`e8ad78828ba89e535978c4db27434382c82ccac34da6181122e05c7e47f7bcfc`.
Metadata-only preflight 8/8 совпал с V32 source identities; V32–V34 scoped tests
`25/25`, full suite `976 passed, 7 skipped` плюс те же два известные V8 anti-junction
failures. Seal commit `12b48dc` был pushed и подтверждён remote до outcome.

Единственный canonical run
`runs/v34_relative_corridor_20260901T213656Z_eece2650/`: metrics SHA
`1db3bc1a92759e9e2940df5a93387b0d3556301ad18b9a58929400cad09b2ee3`, identity SHA
`687c13284403d358eca913a6d723893a6c7316de15f954c775fce185d2a202d3`; audit 62/62.
Получено 389 candidates на 156 event days, из них 323 в evaluation и 133 positive
barrier targets. Но все 52 model-fold records (`26 x 2`) получили
`sleep_insufficient_nested_history`: maximum calibration source days только 33 против
sealed minimum 40. Поэтому full и market-only MLP сделали ноль сделок; gates нельзя
ослаблять после outcome.

Fixed corridor полностью исполнил 118 pair trades / 472 legs, unresolved 0, costs
27 624,64 RUB. Total return `−2,9293%`, CAGR `−1,3634%`, Sharpe `−1,0445`, MDD
`4,5066%`; calendar `2022 +0,7919%`, `2023 −4,0636%`, `2024 +0,3874%`. Из 52 TP
все прибыльны, но 11 distant stops и 55 time exits дали отрицательный итог. Verdict
`NO_GO`, все 20%/50% claims false, live trading запрещён. V34 thresholds/horizon/gates
не менять на этой history; нужна новая mechanism/source family.

Следующий источник реализован как `moex_forward_microstructure_source`: immutable
one-shot FUTOI + subscribed futures `tradestats/obstats` с actual retrieval timestamp,
closed target-free schema и без сохранения bearer token. Public FUTOI задержан на 15
дней и не годится для intraday решения; настоящий новый timing experiment начнётся
только после ALGOPACK entitlement и накопления unseen real-time snapshots.

## Предыдущий результат: V33 full-horizon economic NO-GO

После отрицательной независимой проверки V31 открыта принципиально новая family, а не
ещё одна настройка старого weekly trend. V32 делает решение после каждого завершённого
10-минутного bucket, одновременно видит SI/RI/BR/MIX и 92 maturity-agnostic признака
официальных MOEX option coefficients. Target — следующие 60 минут open-to-open;
исполнение — на следующем exact common open, принудительный flat в 18:30 мск.

Config `configs/futures_v32_curve_regime_intraday.yaml` byte-sealed SHA
`c7da1d45bee19a7e386df1bd2cec6d5b4ac335ba64eb9f0118a3d8fa42743d54`; core SHA
`45bffa212eeb57ec2c6527acba033795553e6454186ca3f176913e27ad2cb305`, runner SHA
`9f70fa3c21dc3b0c525e92d1bc334debd78e4f4728ffc687d49b11c06181b53b`.
Outcome-free tests прошли `13/13`. Metadata-only preflight, не читавший OHLCV/return/
target/PnL, подтвердил 218 raw artifacts, 8 064 causal effective-date plans, 683 209
active bars, 169 644 exact common-four buckets, 686 curve events и 29 810 решений на
670 event days; все 10 checks true.
Полная регрессия проекта после V33: `970 passed, 7 skipped`; два старых V8 anti-junction tests
ожидаемо падают, потому что внешний `data/` намеренно resolve-ится за Git root. Это тот
же известный инфраструктурный конфликт, новых V32 failures нет.

Frozen comparison: full MLP ensemble `[32,16]` против того же market-only MLP и full
Ridge. Monthly expanding core + preceding-three-month calibration имеют one-day purge;
calibration может выбрать только один из заранее заданных stress-cost hurdles
`1,5/2,5/4,0`, без инверсии знака. Portfolio target 30% annual volatility, gross `<=1,6`,
asset `<=0,6`; integer next-open ledger проверяет 0,25% causal signal volume, 1% factual
capacity, 2x margin buffer и costs `1tick/1fee`, `2/2`, `4/2`.

V32 seal commit `936e3e0` был pushed до outcomes. Canonical run
`runs/v32_curve_regime_intraday_20260901T181223Z_c7da1d45/` имеет metrics SHA
`f4adf509...`; независимый audit проверил 47/47 artifact/check identities. Но все пять
ledger остановились слишком рано: full MLP/Ridge — `2022-04-26 11:00 UTC` на BR,
market-only — `2022-05-13 11:00 UTC` на MIX. В обоих случаях оставался ровно один
контракт, а factual bucket volume `79/97` дал `floor(1% * volume) = 0`. Причина одна —
`insufficient_exit_capacity`. Напечатанные partial-2022 CAGR/Sharpe не являются
экономическим evidence; V32 verdict `NO_GO`, full-horizon stability не проверена.

V33 — отдельная post-outcome adaptive execution correction. Она byte-pin-ит все три
V32 target artifacts по 98 168 rows и **не** меняет feature/model/seed/split/threshold/
sign/weight/risk/cost/gate. Единственная новая семантика: de-risk partial-fill и carry,
reversal close-first, затем open на остатке capacity; flat 18:30 повторяется максимум в
шести exact buckets. Это консервативно сохраняет mark-to-market незакрытой позиции.
Config SHA `615d7b8e...`, module SHA `3ad113cc...`; tests V32+V33+encoding `21/21`,
preflight 10/10 проверил parent audit, пять stop records, три target artifacts,
24 542 timestamps и 538 flat days. Seal commit `8c180e9` был pushed до outcomes.
Canonical run `runs/v33_curve_regime_liquidity_20260901T183357Z_615d7b8e/`, metrics SHA
`17d9602a...`, identity SHA `d0b5b436...`; audit 35/35 exact.

Execution repair сработал: full-MLP primary/doubled/stress дошли до `2024-05-21`,
unresolved 0; всего по пяти ledgers 7 824 filled legs, 10 partial fills и 21 zero-capacity
retry. Но экономика отрицательна: full-MLP primary total `−3,6783%`, CAGR `−1,7374%`,
Sharpe `−0,2471`, MDD `17,0343%`; doubled CAGR `−4,0113%`; stress total `−13,9154%`,
CAGR `−6,7677%`, Sharpe `−1,1212`, MDD `22,5476%`. Market-only primary тоже отрицателен:
CAGR `−2,8398%`. Full MLP торговал только в апреле–мае 2022: последующие 24 месяца
calibration gate оставил cash; calendar returns `2022 −3,6783%`, `2023 0%`, `2024 0%`.
Все 20%/50% gates false, verdict `NO_GO`, live trading запрещён.

OOS diagnosis закрывает направление absolute 60m return regression: full-MLP IC
`0,0622` в 2022 стал около `−0,005` в 2023–2024; у active 2022 predictions средний
signed gross всего `0,198 bp` против `8,981 bp` stress round-trip cost. Threshold/sign/
horizon этой family больше не tune-ить. Следующая новая гипотеза должна моделировать
execution-aware barrier outcome — вероятность take-profit в относительном corridor раньше
дальнего stop — и снижать turnover; original coefficient delivery vintage всё равно
требует отдельного forward collector/paper confirmation.

После провала V29 открыт новый, ещё не просмотренный рыночный период 2008–2011.
Metadata-only audit без daily endpoint нашёл ровно 81 официальный expired contract:
BR/MIX/RI/SI = 38/1/16/26, с FRSTTRADE/LSTDELDATE и единственным RFUD segment у каждого;
LSTTRADE отсутствует у 81/81 и сохраняется missing. Source-only protocol
`moex_pre2012_core_daily_source_v1` был sealed/pushed commit `49467bc` до первого daily
response: config SHA `92c7f324...`, wrapper SHA `55965d9c...`, parent SHA `7dd25e01...`.
V1 collection остановилась fail-closed без output на официальной identity-only строке
`RIM9_2009/2008-09-12`: все OHLC/WAP/settlement/activity/OI отсутствуют. Цены не
печатались, returns/PnL не считались. Узкая V2 correction сохраняет такую строку missing
с false market/execution flags, оставляет raw bytes, exact universe/dates/endpoints и
все остальные parser rules неизменными. V2 config SHA `74847dd3...`, module SHA
`acc547f5...` был pushed commit `617ce72`, затем collection и отдельный offline replay
успешно завершены. Immutable manifest SHA `e06fd978...`, daily SHA `1c5eee45...`, raw
SHA `e8a97876...`: 8 381 rows, 81 contracts, 224 requests, даты
`2008-01-09..2011-12-16`, все 41 audit checks true. Ровно две inert identities —
`RIM9_2009` и `SiU9_2009` на `2008-09-12`. До отдельного strategy seal запрещено читать
2008–2011 returns/PnL: этот кризисно-восстановительный отрезок сохраняется как будущий
честный holdout, а не период для подбора параметров.

До первого price-bearing derived build D1 был sealed/pushed commit `45e55af`: config SHA
`8f5737bc...`, module SHA `d0c22df7...`. Metadata-only calendar audit зафиксировал official-cycle admission
SI/RI/BR/MIX = 16/16/38/1 contracts и 8 011 source rows. Master — exact intersection
SI/RI/BR: 781 сессия `2008-10-08..2011-12-15`; MIX доступен только в последних 54,
поэтому первые 727 строк заранее определены как `asset_not_yet_available`, flat/masked,
без цен и backfill. D1 требует zero unresolved roll/exit, outcome columns запрещены.
D1 остановился до загрузки `daily.parquet` и без output: acquisition manifest имеет
правильный `protected_from=2026-01-01`, а loader ошибочно ожидал там derived ceiling
`2012-01-01`. Boundary-only D2 был sealed/pushed commit `fa61763`, затем построил
отдельный immutable output, но не принят: 25/27 deterministic checks true. Единственные
расхождения — Parquet bool против object для двух уже равных флагов и tuple против JSON
list для тех же month codes; market-value mismatch count равен нулю. D2 зафиксировал
3 124 panel rows, 6 627 contract/spec rows, source-only rolls SI/RI/BR/MIX = 11/11/36/0
и zero unresolved roll/exit. Persistence-only D3 был sealed/pushed commit `afaa278` до
нового build: config SHA `93b1d3fb...`, module SHA `438f2dd5...`. Canonical immutable
output успешно собран: manifest SHA `ff9b2771...`, panel SHA `390b1c8b...`; отдельный
replay дал 27/27 true, а дополнительное strict-dtype сравнение подтвердило exact все
четыре frames. Counts и market semantics не изменились; returns/PnL не вычислялись.

## Короткий ответ

На текущий момент **ни одна стратегия не доказала требуемые устойчивые 20% годовых**.
V30 выглядел сильным на открытом 2013–2017 development: primary/stress CAGR
`22,9090%/21,4113%`, Sharpe `1,1216/1,0634`, MDD `27,7870%/28,4707%`. Но отдельный
V31 seal `370b4d8` заморозил ту же формулу до первого чтения 2008–2011, и единственный
temporal run `runs/v31_pre2012_temporal_20260901T145938Z_6dcb6dab/` её опроверг.
Primary/stress CAGR `−6,7528%/−7,1594%`, Sharpe `−0,4630/−0,4958`, MDD
`26,9631%/27,3717%`, положительных календарных сегментов `0/3`. Baseline 1x тоже
отрицателен: CAGR `−5,1096%`. Исполнение полное, coverage 193/193, critical/unresolved
0, поэтому это экономический **NO-GO**, а не execution failure. Read-only audit:
artifacts 35/35 exact, checks 122/122, все шесть ledger metric replays exact; metrics
SHA `d6d12842...`, identity SHA `9e98428e...`. Gates 20% и 50% оба false; live trading
запрещён. V30/V31 больше не tune-ить и не повторять.

Дополнительный структурный вывод: строгий 252-session feature был finite в конце 2009 и
в 2011, но полностью sleeping в 2010 после missing observations. Это не разрешает
gap-imputation или shorter-window повтор на уже открытом holdout. Для новой family
gap-tolerant multi-scale features можно разрабатывать только на всей теперь открытой
history с nested walk-forward и подтверждать новым paper/forward периодом.

Предыдущий главный lead **V27** прошёл same-history gates, но его независимая проверка
не подтвердила экономику после исправления execution.
Он объединяет frozen V12/V25 trend, неизменный максимум 2x, консервативный доход RUONIA,
capacity-aware исполнение и новый binary cash governor: latest causally available
официальная ключевая ставка ЦБ `>=20%`. Все правила были committed/pushed до PnL.
Primary combined CAGR **28,3752%**, Sharpe **1,2119**, MDD **−20,7138%**; stress CAGR
**27,3643%**, MDD **−21,0511%**. Все sealed gates пройдены. Текущий общий статус:
**GO TO NEW UNSEEN VALIDATION, но NO-GO for live trading**.

Отдельный post-selection audit **V27-R1** был запечатан и pushed до чтения дневной
equity curve, затем выполнен ровно один раз.
Config SHA `a8d6ed420593aeb26e0bf537b402a6edba6b40ab7dd64d48947dc2a936ec8b10`
фиксирует circular block bootstrap по 5/21/63 сессии, 20 000 повторов на каждый из трёх
cost scenarios, rolling 252-session windows, leave-one-year-out и deflated-Sharpe
sensitivity. Все 49 checks true. В stress minimum bootstrap-frequency совместного
`CAGR >=20%` и `MDD <=30%` равна **65,70%**, а для `CAGR >=50%` — только **4,33%**;
5-й процентиль CAGR падает до **8,13%**. В rolling 252-session stress-окнах **87,95%**
положительны, но лишь **57,00%** достигают 20%, minimum CAGR **−17,32%**. Поэтому audit
поддерживает переход к unseen validation, но прямо отвергает трактовку V27 как уже
доказанного «предсказуемого 20% ежегодно» и не поддерживает цель 50%.

V26 был необходимым промежуточным прорывом: 2x V25 + RUONIA + `cancel_and_clip` дал
primary CAGR **24,1698%**, Sharpe **0,9764**, MDD **−33,5661%**, а stress CAGR
**23,0255%**. Он устранил 8 critical events V15, но strict MDD `<=30%` не прошёл;
verdict **NO-GO**. V27 не менял плечо или costs, а добавил один новый официальный
причинный режим риска и снизил MDD на **12,8523 п.п.**.

Decisive проверка **V28** выполнена один раз после push seal `4310bc3`. Canonical run
`runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/`, metrics SHA `73b614b8...`.
Результат плохой: primary combined CAGR **−2,4271%**, Sharpe **−0,2682**, MDD
**−17,6953%**; stress CAGR **−2,5950%**. Но execution одновременно invalid: пять
capacity-cancelled atomic rolls оставили expired old contracts; с `2014-05-19` BRK4
не имеет factual rows, что породило 5 129 critical failures и 1 251 rejected legs.
Поэтому V28 не поддерживает ни 20%, ни 50%, а его метрики нельзя считать валидным
полным тестом signal economics. Следующий отдельный V29 должен проверить risk-first
roll: full executable old-leg exit, independently capacity-clipped new entry/cash.

V29 был sealed/pushed commit `478a246`, затем выполнен ровно один раз. Исправление
полностью устранило execution trap: 639/639 coverage, 527 filled legs, 15 clips и ноль
roll cancellations/rejected/critical/unresolved. Но стабильной прибыли нет: primary
total `+24,8749%` за пять лет, CAGR лишь `4,6133%`, Sharpe `0,3191`, MDD `−47,3846%`;
stress CAGR `3,7117%`, MDD `−48,6822%`. Положителен только 2014 (`+90,9463%`), четыре
остальных года отрицательны. Verdict `FAIL_POST_V28_20`: V29 не поддерживает 20% или 50%,
не является independent confirmation и запрещён для live.

Следующее принципиально иное направление — exchange-listed календарные спреды, а не
ещё один threshold directional trend. Source-only V1 был запечатан до bulk collection:
config SHA `7268753933efb4c9633f3e314ebc1d67cf4a7d63e4290e0f3a0142bacce8048e`,
implementation SHA `db217488...`. Metadata preflight причинно связал все 110 RFUD
спредов SI/RI/BR/MIX с официальными кодами публичного архива без ручных aliases.
Обычный ISS probe дал шесть settlement rows и ноль reported trade rows, тогда как
официальный CSV того же спреда содержит 71 уникальную дату и фактические поля
Last/Bid/Ask/High/Low/Amount/Volume/Trades. Collector сохраняет ISS и public archive
раздельно, архивирует exact HTML/CSV bytes, сохраняет и помечает расхождения интервалов,
аварийно запрещает любую market-value дату `>=2026-01-01` и не считает returns/PnL.
Seal `293e54e` был pushed, затем V1 collection корректно остановился без output:
`SiZ5SiH6` вернул `ASSETCODE = NULL/empty string`, а V1 принимал только NULL.
Parser-only V2 сохранил V1 byte-identical и прошёл blank-код, но после push seal
`7c8d45a` collection снова остановился без output: у единственного `BRF1BRG1`
computed ISS interval пуст (`2021-01-01..2020-12-30`), хотя public archive содержит
допустимую 2021 строку. Metadata audit подтвердил exact count 1. Collection-only V3
оставляет official board dates неизменными, делает 0 ISS requests/rows только для этой
exact identity и обязан собрать её public archive; любой второй empty interval reject.
V3 config SHA `3d89c51fe674f3b55282aba808ad6f0336cae502956681203f02b0218022f19c`, module SHA
`3f344899...`; seal `ed16ca3` был pushed, затем V3 один раз успешно собрал immutable
bundle `data/processed/info_radar/moex-calendar-spreads-current-vintage-2021-2025-v3/`.
Manifest SHA `94d5fab4...`, raw SHA `ccaba170...`; все 47 checks true и независимый
`--audit-only` повторён. Получено 9 997 ISS settlement rows и 10 157 public-archive rows,
из них 8 887 с reported trades. Все 110 spread имеют archive rows, 109 — activity;
единственный inactive — non-adjacent `RIH2RIU2`. Ноль protected rows. Returns/PnL ещё
не считались. Source-derived protocol D1 уже зафиксирован до первого build: config SHA
`657fd42b472797028f5b0194c7b159ac1538ddab5caea8f9c416f0a403e34cd0`, implementation
SHA `d04f7d8f...`; seal commit `35ab387` был pushed до build. Он заранее выбирает только
regular-adjacent spreads с совпадающей
датой near expiry, reported activity, complete uncrossed EOD quote и минимальным
неотрицательным days-to-near по asset/date. Canonical immutable build содержит 8 281
candidate и 4 366 active rows; locked quotes сохранены flags, обе ноги соединены только
с causally prior spec proxy. Manifest SHA `b5e15c2e...`; build и отдельный replay дали
29/29 checks true. Это всё ещё source-only без returns/PnL. Отдельный economic EV1 уже
запечатан до outcomes: config SHA `e74dab97...`, implementation SHA `f8d0108e...`.
Он фиксирует 10 стратегий, primary volatile corridor с дальним stop, causal monthly
cross-asset MLP, equal-quantity long-far/short-near accounting, 1% capacity, gross 1,6x
и costs 1/2/4 ticks. Внутренняя evaluation — 2024–2025; best-of-ten не считается
подтверждением. Seal commit `ee7e311` был pushed, но V1 run остановился до output и до
любого напечатанного результата на пустой `net_pnl` schema одной strategy. V1 сохранён.
V2 меняет только empty-Series adapter: config SHA `e9865302...`, module SHA
`9d96dfe3...`; seal `e1a519d` был pushed, canonical manifest `facc159f...`, audits
37/37 и 29/29 true. Economic verdict `NO_GO_NO_EVALUATION_EXPOSURE`: 3 734 MLP
predictions превратились лишь в 13 plans 2021–2022 и ноль сделок 2024–2025. Primary
development дал `+0,3602%` на одной сделке, что статистически бесполезно. Причина
изолирована: abs-z сигналов достаточно, но EOD `quote_width <= 2 sigma` имел pass counts
16/19/0/0/0 по 2021–2025. Следующий V3 допустим только как post-outcome adaptive
source-semantics correction без изменения thresholds/ledger/costs/gates. V3 уже
зафиксирован: config SHA `c38a7356...`, module SHA `fb9b4e15...`. Он меняет только
signal price midpoint → factual reported Last и исключает closing EOD width из admission;
сам width остаётся MLP feature, strict-positive flag, two-leg 1% capacity, все десять
rules, risks/costs/gates неизменны. Seal `58ba05c` был pushed; canonical manifest
`a7de7e04...`, audits 37/37 и 29/29 true. Экспозиция восстановлена до 1 666 plans, но
primary evaluation `−0,2160%`, stress `−0,4818%`: `NO_GO`. Exploratory cross-sectional
extremes дал `+0,2074%` и 2/2 positive years, но stress `−0,3174%`, development
`−1,1892%`; это лишь слабый gross edge до costs.

Cost-aware V4 был sealed/pushed commit `a6929ce` до outcomes: config SHA `b7ddc0ac...`,
module SHA `17351808...`. Он выбрал post-selected `cross_sectional_extremes` и допустил
entry только при causal expected remaining move не меньше 2x полной stress round-trip
стоимости. Canonical manifest SHA `e9b4e301...`, metrics SHA `0b683ce0...`; все audit
checks true. Из 1 029 plans selected primary сохранил 38 evaluation trades и дал
`+0,3095%`, CAGR `+0,1528%`, Sharpe `0,3416`, оба года положительны. Но doubled costs
оставили только `+0,0675%` и 1/2 positive years, stress дал `−0,1664%`; development
`−1,2291%`, full `−0,9234%`. Verdict `NO_GO`: hurdle не прошёл CAGR, Sharpe и
stress gates. Same-history V5 tuning и увеличение плеча закрыты; следующий шаг — exact
historical multileg trades/order actions/specs либо новый unseen период.

Для этого следующего шага до первого licensed byte подготовлен source-only parser V1:
config SHA `464cce7a...`, module SHA `5e64ba6a...`. Он fail-closed различает market-wide
`multileg_deal`/`multileg_dict`, participant fills/order actions и `f04.ID_MULT` legs,
отбрасывает participant identifiers из processed schema и запрещает undated/2026+
packages до чтения содержимого. Synthetic end-to-end build/replay прошёл; canonical
output отсутствует, потому что лицензированного архива ещё нет. Сначала нужен January
2021 pilot только для schema/coverage preflight, затем полный 2021–2025 archive. Полные
требования и шаблон запроса — [MOEX_MULTILEG_DATA.md](MOEX_MULTILEG_DATA.md).

Новый source-only protocol V3 для официального MOEX EOD 2012–2017 подготовлен до
первого daily price response: config SHA
`0b86cda4d3bddf72831075a771c3e7f6568a0a4ba2f78c64b0254c980c902b08`,
implementation SHA `7dd25e01...`. V1 metadata preflight выявил lowercase-sensitive
finder; V2 после исправления обнаружил все 155 aliases, но остановился до daily history
на отсутствующем у старых descriptions `LSTTRADE`. Полный metadata-only audit показал:
FRSTTRADE/LSTDELDATE и один RFUD segment есть у 155/155, LSTTRADE есть у 91 и missing
у 64. V3 сохраняет missing, а обязательный LSTDELDATE использует как request end. Exact
set 155 contracts (BR/MIX/RI/SI = 71/24/24/36), dates, daily schema/cursor и raw archive
не менялись. V3 был pushed commit `38fc63a` до первого daily response и успешно собрал
immutable bundle: 30 059 rows `2012-01-03..2017-12-21`, 544 raw requests, manifest SHA
`e60d0bcacff17af0229d150552a70ac235e821c2d271970ea2567c212a5f3da6`. Exact replay
подтвердил 18 finder + 155 description/boards + 371 daily pages и все 30 059 raw rows.
Стратегия, returns и PnL ещё не рассчитывались; следующий этап — derived source panel/
spec proxy и отдельный V28 seal.

Derived-source D1 был pushed commit `ce22460` до единственного build. Byte/hash/temporal
аудит прошёл, но operational verdict — **непригоден**: в source есть старые serial-month
Si contracts, и nearest-expiry planner после трёх успешных roll получил 9
`carry_unfilled_roll`, затем 1 276 `carry_unfilled_exit`. Returns, signal и PnL не
считались. D1 сохранён immutable с manifest SHA `73ffe4c3...` как честный failed source
derivation. D2 с official-cycle filter был sealed/pushed commit `b858d54`, но его build
правильно остановился без output: SI дал 22, а не ошибочно ожидавшиеся 23 roll. Source-
only diagnosis показал единственный bounded gap: после factual exit `2016-12-09` нет
admitted 2017 SI observation до `2017-01-03`; planner остаётся flat пять сессий и
re-enters `2017-01-04`, не создавая return bridge. D3 подготовлен до build: config SHA
`d21dd650...`, implementation SHA `c04d8224...`. Он наследует D2 byte-identical, требует
exact action counts, 22/23/70/23 roll для SI/RI/BR/MIX, exact flat-gap dates и ноль
unfilled roll/exit. D3 был pushed commit `8877b75` до build и успешно опубликован:
manifest SHA `3ab20092dbe4fd8a58211d11db1b6dcd6a8335f98051146da76a0f3c0c82fa71`,
1 479 common sessions `2012-01-03..2017-12-01`, 5 916 panel rows, 28 797 contract/spec
rows, все exact action gates true, unresolved roll/exit = 0. Ни returns, ни PnL пока не
считались. Следующий этап — bounded STLFSI4/RUONIA/key-rate source и отдельный V28 seal.

Macro source S1 был pushed commit `9a5ff96`, но первый request трижды получил FRED read
timeout с research User-Agent; ни один response не сохранён и output не создан. S2
transport-only correction был pushed commit `5bec23f` и получил все три responses, но
fail-closed parser остановился до publication на старом RUONIA marker: из 1 478 rows
только 78 имеют explicit publication date, для 1 400 timing неизвестен. Market outcomes
не читались, S2 output отсутствует. S3 parser-only correction запечатан до collection:
config SHA `ae575962...`, implementation SHA `5f2e4e09...`; unknown publication и
`available_at` сохраняются missing, inference/zero-fill/collateral credit запрещены.
Seal был pushed commit `1f9c343`, затем S3 успешно опубликован и полностью replayed:
manifest SHA `949bc7bf...`, raw SHA `8109f157...`; 312 STLFSI4, 1 478 RUONIA и 1 065
key-rate rows, все SHA/schema/availability checks true. Следующий разрешённый шаг —
отдельный pre-outcome V28 seal.

V12 primary: total return **45,1114%**, CAGR **7,7318%**, Sharpe **0,7624**,
MDD **−14,1526%**; четыре из пяти лет положительны. При doubled costs total return
**40,8019%**, при stress — **41,7324%**. Это conservative research proxy, а не
broker-exact обещание прибыли.

V13 добавил строгий front/next carry confirmation и поднял historical total return до
**52,4579%** и CAGR до **8,8013%**, но Sharpe упал до **0,7081**, а MDD вырос до
**−20,6861%**. Поэтому V13 — агрессивный return-challenger с verdict **NO-GO** как
стабилизатор; V12 остаётся главным более устойчивым lead.

V14 проверил предыдущую сессию RVI как forward-volatility governor. MDD снизился до
**−9,3980%**, но CAGR упал до **4,6687%**, Sharpe — до **0,7342**. Verdict снова
**NO-GO**: риск стал меньше, но цель доходности отдалилась.

V15 впервые пробил целевую доходность: frozen V12 с 2x targets и консервативным доходом
на свободное обеспечение дал combined CAGR **21,3272%** (stress **20,4453%**). Но MDD
вырос до **−34,4823%**, 2025 дал **−15,2535%**, а остановка RI/MIX в марте 2022 создала
8 critical execution events. Поэтому V15 — важный capital-efficiency lead, но его
verdict **NO-GO**, метрики недействительны для promotion и live trading запрещён.

V16 после дополнительного source-аудита **INVALIDATED**. У 932 из 1 044 FUTOI states
официальный `systime`/`available_at` позже decision; все 2021–2024 states и часть 2025
были недоступны. Механические CAGR **22,0082%** и Sharpe **0,9678** нельзя считать
причинным результатом: join проверял только `source_date`, а не обязательное
`available_at <= decision_at`. Replay теперь аварийно запрещён кодом. V12 остаётся
единственным lead с GO только к новой unseen validation.

Официальный MOEX FUTOI daily-last — current-vintage archive, а не доказанный PIT history.
MOEX описывает `SYSTIME` как время публикации; для 10 456 из 11 744 строк оно отстаёт от
observation более чем на сутки, а для всей истории 2020–2024 равно 21.06.2025. Полный
5m downloader сохраняет actual retrieval и использует
`conservative_available_at = max(SYSTIME + buffer, retrieval_at)`, поэтому архив не
может участвовать в backtest 2021–2025. Bundle уже завершён: 2 015 624 строки,
1 007 812 paired points, manifest SHA `cc432d59...`; minimum conservative availability
`2026-08-31T22:43:34Z`. Подробности — в
[карте источников](INFORMATION_SOURCES.md).

Официальный EIA WPSR Table 1 bundle содержит 727 допустимых release vintages и 38 248
target-free строк `2012-01-05..2025-12-29`. Один stale issue `2019-07-03` изолирован,
71 межвыпусковая revision сохранена; его единственный sealed-тест уже завершён как V17.

V17 выполнил этот sealed test и получил **NO-GO**: total return **−33,1422%**,
CAGR **−7,7373%**, Sharpe **−0,1893**, MDD **−48,8033%**, только два положительных года.
Все 294 nonzero execution dependencies покрыты, 0 critical/unresolved, поэтому провал не
объясняется исполнением. Raw delayed EIA balance не является доходным сигналом; signs,
компоненты, lag и thresholds по этому результату не инвертировать и не подбирать.

V18 проверил новый release-keyed source family: 458 датированных недельных прогнозов
факторов банковской ликвидности ЦБ за `2017-01-10..2025-12-30`. Прямой знак будущего
government-account flow для SI дал **−41,9547%**, CAGR **−10,3092%**, Sharpe
**−0,5137**, MDD **−55,7292%** и только один положительный год. Все 257 nonzero
execution dependencies покрыты, 0 critical/unresolved. Verdict **NO-GO**; знак,
thresholds, lag и expiry по этому outcome не подбирать.

V19 проверил следующий независимый current-vintage source: 1 238 фактических дневных
факторов ЦБ `2021-01-11..2025-12-30`, включая 939 ненулевых операций Минфина с валютой.
Прямой persistence-знак для SI дал total return **−0,0316%**, CAGR **−0,0063%**,
Sharpe **0,0501**, MDD **−30,7614%** и два положительных года. Все 937 nonzero
execution dependencies покрыты, 0 critical/unresolved. Verdict **NO_GO**: сильный
**+33,97%** в 2025 не компенсирует убытки трёх лет и не разрешает post-outcome отбор
amount/change days, smoothing, lag или sign flip.

V20 проверил новый Minfin OFZ source family после pre-outcome seal. 283 successful
ОФЗ-ПД rows дали 166 prior-only scored auction days; demand-strength basket long RI/MIX и
short SI получил total return **−5,3468%**, CAGR **−1,0931%**, Sharpe **−0,6313%** и
MDD **−6,1937%**. Все 504 nonzero dependencies покрыты, 0 critical/unresolved. Verdict
**NO_GO**: низкая просадка при maximum gross 47% не превращает отрицательный expectation
в стабильный edge. Signs, extreme-score threshold, rank window, expiry и event kinds по
этому outcome не подбирать.

Новый target-free CBR macro-survey source собран без чтения market outcomes: 11 787
records, 37 survey months и 17 indicators. Processed SHA `a139ead8...`, manifest SHA
`faae8927...`; original historical vintages отсутствуют. Консервативный month+1-end
contract допускает до границы 2026 только 36 releases. Источник готов для одного
predeclared development test revisions ожиданий, но не для независимого подтверждения.

V21 был запечатан и pushed до outcome, затем выполнен ровно один раз. Direct next-year
median revisions дали механический total return **−3,1730%**, CAGR **−0,6429%**,
Sharpe **−0,0788**, MDD **−18,7868%** и 3/5 положительных лет. Coverage 200/202:
у RI/MIX на `2022-03-24` не было lagged volume, portfolio-atomic rebalance отклонён,
поэтому все ledger incomplete с двумя critical failures. Verdict **NO_GO**; знаки,
indicators, oil priority, thresholds, risk/expiry и blend по этому outcome не подбирать.

V22 проверил новый release-specific Business Climate Index после pre-outcome commit
`eb0891a`. Результат впервые после серии V17–V21 положителен во всех cost scenarios:
primary total **+13,3661%**, CAGR **2,5411%**, Sharpe **0,3569**, MDD **−8,8570%**.
Но положительны только 2023/2024, а 2024 дал почти всю прибыль; sealed CAGR/Sharpe/3-of-4
year gates не пройдены. Execution полностью доказан: 153/153 dependencies, 0 rejected,
critical и unresolved. Verdict **NO_GO**; BCI thresholds, components, exact decimals,
signs, risk/expiry и blend по этому outcome не подбирать.

Следующий независимый источник подготовлен без чтения рыночного outcome: 48
release-specific выпусков ЦБ по инфляционным ожиданиям и потребительским настроениям,
включая HTML/PDF/XLSX и 146 сохранённых официальных ответов. Processed SHA
`70711272...`, manifest SHA `b132a45e...`; все 48 HTML endpoints подтверждают XLSX после
округления. V23 запечатан SHA `2a8a35a8...`: единственный confirmation regime, cash rule,
risk, expiry и promotion gates были неизменяемы до outcome. Canonical run дал primary
**−5,3484%**, CAGR **−1,0935%**, Sharpe **−0,1589**, MDD **−13,6190%**; doubled/stress
тоже отрицательны. Verdict **NO_GO**, same-history tuning этой family закрыт.

Новая треугольная гипотеза RI/MIX/SI проверена двумя заранее зафиксированными execution
вариантами и закрыта как **NO-GO**. Оба запуска остановились fail-closed на фактической
ликвидности; все доступные до остановки метрики отрицательны.

## Сводка активных гипотез

| Направление | Главный development-результат 2021–2025 | Решение |
|---|---:|---|
| V30/V31 equal trend/carry/relative + final risk restoration | Dev CAGR 22,91%; unseen primary CAGR −6,75%, Sharpe −0,46, MDD −26,96%; 0/3 positive segments | Independent temporal **NO-GO**; family closed, не live |
| V29 risk-first roll, post-V28 2013–2017 | +24,87%, CAGR 4,61%, Sharpe 0,32, MDD −47,38%; execution complete | Execution fixed, economics unstable; **FAIL/NO-GO** |
| V27 V26 + CBR key-rate `>=20%` cash governor | +248,61%, CAGR 28,38%, Sharpe 1,21, MDD −20,71%; stress CAGR 27,36% | Все sealed gates пройдены; **GO к новой unseen validation, не live** |
| V26 2x V25 + causal RUONIA + capacity admission | +195,14%, CAGR 24,17%, Sharpe 0,98, MDD −33,57%; complete | Return/execution gates пройдены, MDD `>30%`; NO-GO |
| V12 core-four correlation trend | +45,11%, CAGR 7,73%, Sharpe 0,76, MDD −14,15% | GO к новой unseen validation; не live |
| V13 trend + carry confirmation | +52,46%, CAGR 8,80%, Sharpe 0,71, MDD −20,69% | Return выше, stability хуже; NO-GO как replacement |
| V14 prior-session RVI governor | +25,62%, CAGR 4,67%, Sharpe 0,73, MDD −9,40% | MDD лучше, edge слабее; NO-GO |
| V15 2x V12 + causal RUONIA | +162,87%, CAGR 21,33%, Sharpe 0,88, MDD −34,48%; 8 critical | CAGR gate пройден, stability/execution gates нет; NO-GO |
| V16 FUTOI crowding + capacity-aware 2x | Механически CAGR 22,01%, но 932/1 044 states были недоступны | **INVALID: FUTOI look-ahead**, метрики не использовать |
| V17 EIA physical balance for BR | −33,14%, CAGR −7,74%, Sharpe −0,19, MDD −48,80% | Полное исполнение, но сигнал убыточен; NO-GO |
| V18 CBR forward-liquidity direction for SI | −41,95%, CAGR −10,31%, Sharpe −0,51, MDD −55,73% | Полное исполнение, прямой знак убыточен; NO-GO |
| V19 CBR reported Minfin FX persistence | −0,03%, CAGR −0,006%, Sharpe 0,05, MDD −30,76% | Полное исполнение, но edge отсутствует; NO-GO |
| V20 Minfin OFZ-PD demand strength | −5,35%, CAGR −1,09%, Sharpe −0,63, MDD −6,19% | Полное исполнение, но сигнал убыточен; NO-GO |
| V21 CBR next-year macro revisions | −3,17%, CAGR −0,64%, Sharpe −0,08, MDD −18,79%; 2 critical | Signal отрицателен и execution incomplete; NO-GO |
| V22 CBR printed BCI regime | +13,37%, CAGR 2,54%, Sharpe 0,36, MDD −8,86%; complete | Положительный, но нестабильный и ниже gates; NO-GO |
| V23 CBR household confirmation | −5,35%, CAGR −1,09%, Sharpe −0,16, MDD −13,62%; ledger complete | Отрицателен во всех cost scenarios; NO-GO |
| V24 daily VIX/VIX3M governor | +38,89%, CAGR 6,79%, Sharpe 0,74, MDD −14,28%; complete | Прибыльный, но stability и costs хуже V12; NO-GO |
| V25 weekly STLFSI4 governor | +49,07%, CAGR 8,31%, Sharpe 0,82, MDD −14,23%; complete | Return/Sharpe лучше V12, MDD хуже на 0,074 п.п.; strict NO-GO |
| Structural futures breadth | RAM: CAGR 6,77%, Sharpe 0,78, MDD −15,13% | Продолжать только exact-execution проверку |
| Sparse key-rate events | 10 сделок, CAGR 0,99%, Sharpe 0,82, MDD −0,47% | Малый наблюдаемый lead, недостаточно масштаба |
| RI/MIX/SI triangular relative value | V10: 4 сделки, −2,58%; V11: 10 сделок, −0,68%; оба invalid после unresolved | Закрыт, NO-GO |
| Corridor hazard 0,8/2,8 ATR | 58 сделок, CAGR 0,46%, Sharpe 0,35 | Закрыт, NO-GO |
| Continuous 10m neural timing | 0 допущенных neural trades; breakout CAGR −53,71% | Закрыт, NO-GO |
| 30-stock market graph | IC −0,00639; CAGR −10,32%, Sharpe −1,40 | Закрыт, NO-GO |
| Long-only relative momentum | CAGR 1,29%, Sharpe 0,18, MDD −49,34% | Закрыт, NO-GO |

Полная история и точные external run paths находятся в
[реестре экспериментов](EXPERIMENTS.md).

## V27 extreme key-rate governor — все sealed gates пройдены

Protocol/config commit `aca0380` был pushed до первого PnL. Config SHA
`7a9a44cf7b09c7820a514b2706e332744a3b30ced8b7d3d4c8bdf7448a3194fe`
фиксирует ровно один круглый monetary boundary: latest key rate `>=20%` переводит
уже STLFSI4-governed portfolio в cash; `<20%` пропускает его. Missing/stale старше семи
дней также cash. Максимум 2x, RUONIA haircut 50%, buffer 10%, capacity и costs V26 не
изменены. Source-only states до PnL: all `418 = 309 pass / 68 STLFSI cash / 40 key-rate
cash / 1 missing`; OOS `261 = 197/24/40/0`.

Canonical run:
`runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/`; metrics SHA
`5fc1f271acf8f9df711006bca24e6bc40425bf097c21e989eb0296baeb0e7654`.

- 115/115 checks true; 27/27 declared artifacts прошли bytes/SHA/row audit;
- raw CBR SOAP 121 958 bytes, SHA `06da1497...`, exact replay всех 2 015 key-rate rows;
- 828/828 nonzero next-open dependencies; все orders filled, 0 critical/unresolved;
- primary combined return **+248,6127%**, CAGR **28,3752%**, Sharpe **1,2119**,
  MDD **−20,7138%**, costs **44 141,07 RUB**, collateral **366 595,47 RUB**;
- doubled: CAGR **27,6201%**, Sharpe **1,1918**, MDD **−20,9410%**;
- stress: CAGR **27,3643%**, Sharpe **1,1839**, MDD **−21,0511%**;
- primary годы: **+40,34%/+72,45%/+30,68%/+11,87%/−1,48%**;
- против V26: CAGR `+4,21 п.п.`, Sharpe `+0,2356`, MDD лучше на `12,85 п.п.`,
  worst year лучше на `10,79 п.п.`, costs ниже на 11 156,59 RUB;
- market artifacts заканчиваются `2025-12-30`; timestamps/targets/PnL 2026 отсутствуют.

Verdict **GO_TO_NEW_UNSEEN_VALIDATION** означает только переход к заранее запечатанному
forward/PIT или ранее не просмотренному рынку. V27 создан после просмотра V26 на тех же
2021–2025, поэтому не является независимым доказательством и live trading запрещён.
Нельзя менять 20% boundary, age, cash/partial scale или V26 economics по этому outcome.

## V26 capital efficiency — цель доходности пробита, MDD gate не пройден

Config SHA `2b08589013f3b3387002830cad7878ef0fffc5dc808b8165fc004e724abf4c1b`
и commit `3b9ce95` были pushed до market outcome; pre-PnL routing fix `5515321` лишь
перенёс 2x после допустимого base mapper, не читая PnL. Canonical run:
`runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/`; metrics SHA
`b4149969696e23a29a06b58085510d9f8c9f2bbf584ca0d2aaa883801493567d`.

- 99/99 checks true; 25/25 declared artifacts прошли audit;
- 1 016/1 016 dependencies, all filled orders, 0 critical/unresolved; шесть причинных
  no-open cancellations на фактических остановках заменили 8 critical events V15;
- primary/doubled/stress combined CAGR **24,17%/23,41%/23,03%**;
- Sharpe **0,976/0,956/0,946**, но MDD **33,57%/33,99%/33,97%**;
- единственный false promotion condition — all-scenario MDD `<=30%`.

Verdict остаётся `NO_GO`; снижать постоянное плечо после этого outcome нельзя. V26
сохраняется как exact parent V27 и как доказательство работоспособности capacity policy.

## V25 STLFSI4 weekly governor — сильнейший challenger, strict NO-GO

Source commit `cdfe674` и protocol commit `74c5461` были pushed до первого outcome.
Config SHA `dd8b60513de7261aa051c12bd5598fffd880c90c98489a5becac820b7597416b`
фиксирует official zero, following-Thursday availability, 14-day age, binary global
scale и OOS states `237 pass / 24 stress-cash / 0 missing`. Canonical run:
`runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/`; metrics SHA
`c2518d17b4e945ef921fa8dbaa8bd330645131acddd73fc01a45c44c0aacfa86`.

- 82/82 checks true; raw CSV exact replay; 20/20 run files прошли SHA/row audit;
- 1 016/1 016 dependencies, 438 primary filled legs, 0 rejected/critical/unresolved;
- primary/doubled/stress return **+49,07%/+47,18%/+46,86%**;
- primary CAGR **8,31%**, Sharpe **0,818**, MDD **−14,226%**, costs 13 835,17 RUB;
- годы: **+17,53%/+14,01%/+12,08%/+1,54%/−2,26%**;
- maximum participation **0,11287%**, no order-time gross/margin breach;
- market artifacts заканчиваются `2025-12-30`.

V25 улучшил V12 total return на 3,96 п.п., CAGR на 0,58 п.п., Sharpe на 0,0553 и worst
year на 0,37 п.п.; equity ни в одной ledger session не ниже V12. MDD gate, однако,
false: `14,2262% > 14,1526%`. Обе кривые имеют тот же peak/trough interval
`2024-11-26 → 2025-03-03`; V25 имеет более высокий trough в RUB, но также более высокий
peak, поэтому относительная просадка хуже на 0,0736 п.п. Verdict `NO_GO` менять нельзя.
Практический статус — приоритетный кандидат для новой forward/PIT validation, не live.

## V24 Cboe VIX/VIX3M daily governor — прибыльный, но хуже V12

V24 не меняет frozen V12 signal/risk/execution. Config SHA
`f81b5aaa666346fa049b550e5dfc92c24ecf6ef2790a2cb00fb83235f24c064c`
заранее зафиксировал daily binary global scale: causally available complete contango
`VIX/VIX3M < 1` пропускает V12, backwardation/flat/missing/stale переводит всё в cash.
Source/calendar-only counts `1785/167/72` all и `1170/53/47` OOS были sealed до PnL.
Pre-outcome commit `34023c1` pushed до canonical run
`runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/`; metrics SHA
`1da1b995fd432c938f62745abcc71f7e85af5a5d20735b9a98631a41d21d2f98`.

- 83/83 checks true; strict replay двух raw CSV точно восстановил processed source;
- 3 722/3 722 dependencies, primary 774 filled legs, 0 rejected/critical/unresolved;
- primary/doubled/stress return **+38,89%/+37,13%/+33,54%**;
- primary CAGR **6,79%**, Sharpe **0,739**, MDD **−14,28%**, costs **26 009,44 RUB**;
- годы: **+16,56%/+8,66%/+7,62%/+10,50%/−7,80%**;
- maximum participation **0,13643%**, maximum post-mark gross leverage **0,9443**;
- все 20 run files прошли bytes/SHA/row audit, market timestamps `<=2025-12-30`.

V24 прошёл CAGR, 4/5 years и положительные doubled/stress gates, но проиграл V12 по
Sharpe на `0,0231` и по MDD на `0,125 п.п.`. Сто cash sessions создали 67 episodes и
133 scale transitions; filled legs выросли с 429 до 774, costs — на 12 622,16 RUB.
Verdict `NO_GO`: не ретюнить ratio boundary, freshness, levels, smoothing, hysteresis,
partial scale или asset exceptions на 2021–2025.

## V23 CBR household confirmation — валидный отрицательный NO-GO

V23 использует новую household source family и не изменяет увиденные BCI outcomes V22.
Config SHA
`2a8a35a898eddae72694bce159282ced6f72230b537613ad224c0d2b6001f2ee` фиксирует:

- exact XLSX expected-inflation и consumer-sentiment sequential deltas;
- risk-on только при inflation down + sentiment up, risk-off только при обратной паре;
- mixed/zero = cash, long/short signs RI/MIX/SI неизменны, BR = zero;
- 48 releases, 1 warmup, 47 scored, 16/17/14 regimes и 99 nonzero directions;
- risk budget 1/3, prior 60d vol, target 20%, floor 10%, gross `<=1`, expiry 45 days;
- next factual open, portfolio-atomic execution и costs 1×/2×/stress;
- CAGR/Sharpe/MDD/year gates и запрет данных/метрик `>=2026-01-01`.

Source commit `3d18a03` уже pushed до protocol. Pre-outcome тесты прошли (`6 passed`),
включая полный replay 146 raw responses и synthetic expiry/collision. Реализация была
pushed commit `4ac40df` до outcome. Canonical run:
`runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/`, metrics SHA
`33614e391a547a636ed3ef1a2df44653d05669c24495aacb43f73125cbc9b839`.

- 92/92 checks true; 19/19 artifacts сверены по bytes/SHA/rows;
- 33 confirmations до collision; September/October 2022 оставили October;
- три confirmed states `2022-03..05` fail-closed остались cash из-за отсутствия causal
  prior-60-session volatility: mapped 29/32 distinct confirmed states после collision;
- сформированный ledger complete: 111/111 nonzero dependencies, 109 filled legs,
  0 rejected/critical/unresolved, maximum participation **0,03956%**;
- primary/doubled/stress return **−5,35%/−5,63%/−5,92%**;
- primary CAGR **−1,09%**, Sharpe **−0,159**, MDD **−13,62%**, costs **2 775,79 RUB**;
- годы: 2021 **0,00%**, 2022 **−3,77%**, 2023 **−2,42%**,
  2024 **−1,19%**, 2025 **+2,01%**; terminal position отсутствует.

Verdict `NO_GO`: return, CAGR, Sharpe, active-year и cost gates провалены. Нельзя
инвертировать signs, выбирать один household ряд, вводить thresholds, торговать mixed
states или подбирать risk/expiry/blend на том же outcome.

Новый независимый FRED/Cboe VIX/VIX3M source V2 собран без MOEX outcome: 2 087 grid rows,
2 011 complete pairs, 76 missing сохранены, 174 backwardation и 1 837 contango. Processed
SHA `6ffe7daa...`, manifest SHA `0aecc29fd...`; оба bounded raw CSV не содержат 2026 и
точно воспроизводят processed frame. V24 был запечатан config SHA `f81b5aaa...` и pushed
commit `34023c1` до единственного outcome. Daily contango governor сохранил прибыль:
total **+38,8855%**, CAGR **6,7910%**, Sharpe **0,7394**, MDD **−14,2777%**, все cost
scenarios положительны и execution complete. Но он оказался хуже frozen V12 и по Sharpe,
и по MDD, а costs выросли на 12,62 тыс. RUB. Verdict **NO_GO**; boundary, freshness,
binary scale и state mapping на этой истории больше не менять.

V25 с независимым weekly STLFSI4 оказался наиболее сильным challenger: total
**+49,0720%**, CAGR **8,3137%**, Sharpe **0,8177**, четыре положительных года и все cost
scenarios profitable при полном исполнении. Он улучшил V12 return/Sharpe/worst year и
ни в одной ledger session не имел equity ниже V12. Но MDD **−14,2262%** оказался на
**0,0736 п.п.** хуже строгой границы V12. Поэтому официальный verdict — **NO_GO** по
единственному MDD gate; результат перспективен только для новой forward/PIT validation,
а current-vintage STLFSI4 Version 4 не разрешает live claim.

## V22 CBR Business Climate Index — положительный, но слабый NO-GO

V22 использует новую official release-specific информацию и не меняет провалившиеся
V20/V21 families. Config SHA
`97b2aa74416eae4ebbce28d018a460f98ade4993cfb086487d28515976c18fbe` фиксирует:

- только знак sequential delta printed one-decimal composite BCI;
- improvement = long RI/MIX и short SI, decline = обратный знак, BR = zero;
- 44 releases, 1 warmup, 43 scored, 117 nonzero asset directions;
- risk budget 1/3 для SI/RI/MIX, prior 60d vol, target 20%, floor 10%, gross `<=1`;
- 45-day expiry, next factual open, portfolio-atomic execution и costs 1×/2×/stress;
- exact chart decimals, component selection, thresholds, training и blend запрещены.

Pre-outcome commit `eb0891a`; canonical run
`runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/`, metrics SHA
`10d7b0bf1b84d46b7cfe6fac784ba8e279bd22bd277fa76c2c8f51238f274214`.

- 43 mapped signal/expiry states, одна корректная October/November collision и 13 rolls;
- 224 target rows, 153/153 nonzero dependencies complete;
- primary/doubled/stress return **+13,37%/+12,88%/+11,96%**;
- primary CAGR **2,54%**, Sharpe **0,357**, MDD **−8,86%**, costs **4 873,13 RUB**;
- годы: 2021 **0,00%**, 2022 **−3,78%**, 2023 **+1,52%**,
  2024 **+20,84%**, 2025 **−3,96%**;
- все 91 checks true, все 17 declared artifacts повторно сверены, market outputs
  заканчиваются `2025-12-30`.

Verdict `NO_GO`: execution и costs выдержаны, но CAGR/Sharpe/positive-active-years нет.
После просмотра результата параметры менять нельзя; новый тест требует нового источника
или forward history.

## V21 CBR macro revisions — отрицательный и execution-incomplete результат

V21 был запечатан и pushed commit `5414251` до первого чтения market outcomes.

- config SHA:
  `5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc`;
- metrics SHA:
  `cfc704e757393760cabcddeb6f3d1614f43df8ee8523b46db0fccd0ac8b92c0e`;
- canonical run:
  `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/`;
- 11 787 source records дали 36 causal releases, 1 warmup и 35 scored releases;
  component counts: SI 34, RI 28, MIX 28 и BR 12 ненулевых revisions;
- 32 mapped source decisions, три skipped signals весны 2022 без полной prior volatility,
  34 roll decisions и 264 target rows;
- coverage **200/202**: RI и MIX на `2022-03-24` не имели lagged volume;
- каждый cost scenario имеет один `unknown_lagged_volume` atomic rejection,
  `critical_failure_count=2`, 0 unresolved и `execution_complete=false`;
- primary/doubled/stress mechanical return **−3,17%/−3,90%/−4,43%**;
- primary CAGR **−0,64%**, Sharpe **−0,079**, MDD **−18,79%**, costs
  **4 501,83 RUB**, maximum participation **0,06402%**;
- годы: 2021 **+1,68%**, 2022 **−1,27%**, 2023 **+0,79%**,
  2024 **+2,03%**, 2025 **−6,21%**;
- все 87 input/source/temporal/runtime checks true; все 17 declared run artifacts
  повторно сверены по bytes/SHA, цены/returns/targets/PnL 2026 не читались.

Verdict `NO_GO`: signal не проходит return gates даже механически, а incomplete
execution дополнительно запрещает promotion. Same-history sign/indicator/threshold/oil-
priority/risk/expiry tuning и blend с V12 закрыты.

Новый target-free CBR Business Climate Index source собран без market outcomes: 44
release-specific страницы и 44 PDF за `2022-05..2025-12`, processed SHA `b312f4e5...`,
manifest SHA `99ad128b...`. Сохранены сводный BCI, текущие оценки и ожидания; 90/90 raw
responses повторно прошли byte/SHA audit. Availability использует конец более поздней из
publication/last-update dates, а same-time collision оставляет более новый release month.
Sealed V22 direct-delta уже завершён положительным, но слабым `NO_GO`; источник остаётся
development-only и требует forward snapshots для независимого подтверждения.

## V20 Minfin OFZ demand strength — валидный отрицательный результат

V20 был запечатан и pushed commit `4e52378` до первого чтения RI/MIX/SI outcomes.

- config SHA:
  `788fadbd9c499483c560488a5a3d9d2e95f7e95496e5736ed4465eca889341ed`;
- metrics SHA:
  `cbfa0c8803e631697400813d3fb4ba8a2ba2eda00a38cc5114dd652472d33d78`;
- canonical run:
  `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/`;
- 283 successful ОФЗ-ПД rows агрегированы в 179 auction days: 13 causal warmup и
  166 scored; 82 positive, 76 negative и 8 zero scores;
- 29 expiry-to-zero states и 10 roll decisions; 504/504 nonzero execution dependencies
  complete;
- primary/doubled/stress total return **−5,35%/−5,49%/−5,44%**;
- primary CAGR **−1,09%**, Sharpe **−0,631**, MDD **−6,19%**, costs
  **1 409,28 RUB**, maximum participation **0,01358%**;
- годы: 2021 **−0,01%**, 2022 **−3,95%**, 2023 **−0,29%**,
  2024 **+0,78%**, 2025 **−1,93%**;
- все 86 input/temporal/runtime checks true; все три ledger complete,
  0 rejected/critical/unresolved.

Последняя source publication — `2025-12-24`; последняя mapped market session —
`2025-12-30`. Ни price/return/target/PnL 2026 не читались. Прямой prior-rank score
bid-to-cover плюс placed volume закрыт. Signs, extreme-score threshold, rank window,
expiry и event kinds нельзя выбирать по увиденному результату.

## V19 CBR Minfin FX persistence — валидный отрицательный результат

V19 был запечатан и pushed commit `0558e7e` до первого чтения SI outcomes.

- config SHA:
  `1340ffacae93b514fe4605262d8946a6a87cbc4619c1748b48ac45b9a9b19946`;
- metrics SHA:
  `dff0016e3501136714f66b3237dfb66f37449bde69c77ab489efdc777446b08d`;
- canonical run:
  `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/`;
- 1 235 mapped source decisions, одна same-session collision и два records без будущей
  active session; 937/937 nonzero execution dependencies complete;
- primary/doubled/stress total return **−0,03%/−0,24%/−0,57%**;
- primary CAGR **−0,006%**, Sharpe **0,050**, MDD **−30,76%**, costs
  **4 154,95 RUB**, maximum participation **0,01155%**;
- годы: 2021 **−4,65%**, 2022 **+3,49%**, 2023 **−20,13%**,
  2024 **−5,32%**, 2025 **+33,97%**;
- все три ledger complete, 0 rejected/critical/unresolved.

Последние source publications доходят до `2025-12-31`, но decisions, targets, positions
и PnL заканчиваются `2025-12-30`; outcomes 2026 не читались. Прямой persistence-знак
закрыт. Magnitude/change-day selection, smoothing, иной lag или инверсия после просмотра
результата запрещены как data mining.

## V18 CBR liquidity forecast — валидный отрицательный результат

V18 был запечатан и pushed commit `0c3fc80` до первого чтения SI outcomes.

- config SHA:
  `ee2d7fd77037eccf15237f827ed357e0b8608c96fae1f393e8a3478945b8b10a`;
- metrics SHA:
  `b67423433a03ebcd4cdebac5df33754e62be94b4719a430f1642596c357e9f28`;
- canonical run:
  `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/`;
- 240 OOS release decisions, 10 expiry-to-zero и 18 roll decisions; 257/257 nonzero
  execution dependencies complete;
- primary/doubled/stress total return **−41,95%/−44,59%/−44,49%**;
- primary costs **8 289,95 RUB**, maximum participation **0,01155%**;
- годы: 2021 **−1,77%**, 2022 **−46,94%**, 2023 **−9,47%**,
  2024 **−1,33%**, 2025 **+24,67%**;
- все три ledger complete, 0 rejected/critical/unresolved; один factual halt carried.

Последний forecast interval заканчивается в январе 2026, но market decisions, targets,
positions и PnL заканчиваются `2025-12-30`; защищённые outcomes 2026 не читались. Прямой
знак government-account forecast закрыт. Простая инверсия или отбор extreme weeks после
просмотра результата запрещены как data mining.

## V17 EIA physical balance — валидный отрицательный результат

V17 был запечатан и pushed commit `a8b8407` до первого чтения BR outcomes.

- config SHA:
  `1d8eee3f7aa99aff5798aeaf6a946d110cfa4e4b451b57580b1d9ef6cd17b37a`;
- metrics SHA:
  `fbd3b74e44ce91d484bb9e1594130ee2dd4d6589c0e50cabb34f3345b898f255`;
- canonical run: `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/`;
- 245 OOS release decisions и 49 roll decisions; 1 176 target rows, 294/294 nonzero
  execution dependencies complete;
- primary/doubled/stress total return **−33,14%/−39,97%/−42,68%**;
- primary costs **82 842,43 RUB**, maximum participation **0,1383%**;
- годы: 2021 **+7,80%**, 2022 **−31,73%**, 2023 **+59,58%**,
  2024 **−19,83%**, 2025 **−28,99%**;
- все три ledger complete, 0 rejected/critical/unresolved; один factual halt carried.

Source полезен как чистый PIT dataset, но именно raw-change delayed weekly direction
закрыт. Допустимое возвращение к EIA требует новой информации — прежде всего исторического
point-in-time analyst consensus для настоящего surprise — либо нового forward периода.

## V16 FUTOI governor — INVALID из-за недоказанной доступности

V16 был честно запечатан до PnL, но последующий более глубокий source-аудит обнаружил
нарушение общего PIT-контракта. Это делает run недействительным независимо от красивых
метрик или pre-outcome seal.

- config SHA:
  `d04617756a8226ecc2900a0f3f4036e5891903a65bb722608b276908d803c070`;
- metrics SHA:
  `8246e155843dad0928c1ae283b9023622fc19fe9ed11ca956753bfbe92c6d73f`;
- canonical run:
  `runs/v16_futoi_governor_20260831T220539Z_d0461775/`;
- 1 044 weekly asset states: только 112 имели recorded `available_at` не позже decision;
  932 были недоступны, включая все 832 states 2021–2024;
- первый допустимый state появляется только `2025-06-27`, последний недопустимый —
  `2025-06-20`; исторические строки 2020–2024 были republished 21.06.2025;
- 1 040/1 040 nonzero target dependencies, 730 filled legs, 0 rejected/critical/
  unresolved, шесть текущих attempts причинно отменены из-за отсутствия factual open;
- primary futures-only CAGR **20,1280%**; collateral **201 950,38 RUB**; combined CAGR
  **22,0082%**, Sharpe **0,9678**, MDD **−31,3402%**;
- doubled/stress combined CAGR **21,8474%/21,0971%**, оба complete и положительны;
- годы: 2021 **+39,1146%**, 2022 **+70,4325%**, 2023 **+15,2018%**,
  2024 **+9,0275%**, 2025 **−9,2234%**;
- все 23 artifact hashes и 19 parquet row counts совпали; 40 временных полей имеют
  максимум `2025-12-30`.

Числа выше сохранены только как forensic record. Их нельзя сравнивать с V12/V15 как
causal performance и нельзя использовать для выбора новой стратегии. Причина ошибки:
`build_futoi_governor` требовал `source_date < decision_date`, но не требовал
`available_at <= decision_at`; warmup 2020 также не был доказанно доступен к началу OOS.
Canonical directory и metrics SHA не изменяются, а текущий entry point V16 теперь
выбрасывает `RuntimeError` с причиной invalidation до чтения PnL.

## V15 capital efficiency — доходность найдена, устойчивость ещё нет

V15 был запечатан commit `f68226f`; отдельный fix `85b1074` только разрешил уже
объявленный 2x target в mapper/ledger и был отправлен до первого расчёта PnL.

- config SHA:
  `8cbcf30712684607e16cde27a9bca333e4740bd3bdb119646890d0b28d00a50d`;
- metrics SHA:
  `3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4`;
- primary futures-only CAGR **19,9802%**; collateral **142 698,54 RUB**; combined CAGR
  **21,3272%**, Sharpe **0,8826**, MDD **−34,4823%**;
- doubled/stress combined CAGR **20,5038%/20,4453%**, оба total return положительны;
- четыре из пяти лет положительны, но 2025 **−15,2535%**;
- 1 040/1 040 targets и 1 271/1 271 RUONIA intervals покрыты;
- 12 rejected legs и 8 critical events относятся к factual halt RI/MIX в марте 2022;
  unresolved на конце нет, но `execution_complete=false`.

Это первый прямой результат выше 20% CAGR, однако не решение задачи стабильного дохода:
25% MDD gate превышен почти на 9,5 п.п., а неполное исполнение запрещает считать метрики
promotion-valid. Не создавать V15.1 с подстройкой leverage/haircut/buffer по уже
увиденному результату.

## V14 RVI governor — risk control работает, доходность нет

V14 был запечатан commit `677c713` до PnL и выполнил один вариант без threshold search:

- config SHA:
  `9f680ebfcfcd6aae98a1e39eb44b9c51b59aa73067edc32e7a558399a8a29a53`;
- metrics SHA:
  `1a236f0698ab906532e5381d8ecbc5c7b896c742533ad9b1e95df1096c8aa3ea`;
- 259/261 OOS weekly decisions имели точный previous-session RVI, 219 downscaled;
- primary return **+25,62%** за пять лет, CAGR **4,67%**, Sharpe **0,734**,
  MDD **−9,40%**;
- doubled/stress return **+25,51%/+24,68%**;
- 1 040/1 040 nonzero targets покрыты, 0 rejected/critical/unresolved.

RVI снизил MDD V12 на 4,75 п.п., но не улучшил Sharpe и опустил CAGR ниже sealed 5%.
Не создавать V14.1 с новым порогом по уже увиденной истории.

## V13 carry confirmation — доход выше, устойчивость хуже

V13 был запечатан commit `2c51cef` до просмотра outcome. Он оставил V12 portfolio и
execution byte-identical, но допускал trend только при совпадении знака с одновременной
front/next кривой, доказанно известной на close решения.

- config SHA:
  `94841c0baa1f4c7e0f88302467dfde3bc8104b2e662382b9224bbaf9b75f07ef`;
- metrics SHA:
  `783b0a7ec9dd613df9b7f38c3070eb33ee980358a69ec4a11f4e411e079a6039`;
- 2 681 OOS confirmed и 1 363 observed-not-confirmed asset rows;
- 841/841 nonzero target dependencies полны; 431 primary filled legs, 0 rejected,
  0 critical и 0 unresolved;
- годы: 2021 **+21,48%**, 2022 **+20,08%**, 2023 **+5,19%**,
  2024 **+1,22%**, 2025 **−1,84%**;
- doubled/stress total return **+51,85%/+51,62%**.

По сравнению с V12 CAGR выше на 1,07 п.п. и worst year лучше на 0,79 п.п., но MDD хуже
на 6,53 п.п., Sharpe ниже на 0,054 и costs выше на 4 049,64 RUB. Это не улучшение
стабильности. Не создавать V13.1 с carry threshold/blend на уже просмотренной истории.

## V12 core-four correlation trend — новый исполнимый lead

V12 использует только BR/MIX/RI/SI, для которых уже существовал единый frozen
conservative spec proxy. После закрытия каждой недели он строит общий multi-horizon
trend score 21/63/126/252 сессий, затем учитывает 60-session covariance всех четырёх
рынков, target volatility 20%, gross `<= 1` и пять недельных turnover sleeves. Сигнал
исполняется только на следующем factual open; roll получает отдельное причинное решение.

- sealed protocol SHA:
  `0b1a79d5c09cf40330886ebfba84bb9a7a8a84973301d59627200050e61b3e53`;
- 261 weekly decisions, 53 дополнительных roll decisions, 1 256 полных target rows;
- 1 040 ненулевых targets, coverage **1 040/1 040**;
- 1 272 ledger sessions, 429 filled legs, 0 rejected legs, 0 critical failures,
  0 unresolved halts;
- primary costs **13 387,28 RUB**, maximum participation **0,1129%** при cap 1%,
  maximum gross leverage **0,9544**, maximum 2x modeled-margin ratio **0,4688**;
- primary годы: 2021 **+17,53%**, 2022 **+14,01%**, 2023 **+7,78%**,
  2024 **+3,19%**, 2025 **−2,63%**;
- terminal positions carried; отдельный one-way exit reserve **173,40 RUB** оставляет
  total return **45,0941%**.

Sealed gate полностью пройден, но результат adaptive: V5–V11 и широкий structural lead
уже были известны до V12. На этой же истории запрещено менять horizons, sleeves, universe,
vol target или costs. Historical exchange specs, broker fees, spread/queue и intraday
margin остаются приблизительными, поэтому live promotion запрещён.

## V10/V11 triangular relative value — почему закрыт

V10 фиксировал residual `log(RI) − log(MIX) + log(SI)`, prior-72 z-score, вход при
`|z| >= 2`, take-profit внутри `0,5σ`, дальний stop `4σ`, максимум 18 баров и три
integer-contract legs. Заполнение было намеренно неблагоприятным: buy по high, sell по
low следующего точного 10m bucket; gross `<= 0,9`, участие `<= 1%`.

- 169 071 общих баров, из них 109 143 OOS и 31 953 допустимых signal bars;
- 4 завершённые корзины, все убыточны; partial ordinary return **−2,5806%**,
  Sharpe **−0,6344**, costs **697,15 RUB**;
- первая unresolved заявка: `2022-03-29 08:00 UTC`, недостаточный entry-window volume;
- full-period CAGR/Sharpe недействительны: ledger остановлен, а не продолжен с
  игнорированием неудобной заявки.

V11 не менял alpha/пороги и проверил open следующего bucket с one-tick cost, sizing по
0,25% известного signal volume и фактическим cap 1%. Это adaptive same-period diagnostic,
не независимое подтверждение.

- 10 завершённых корзин: partial return **−0,6768%**, Sharpe **−0,9736**, profit factor
  **0,1189**, win rate **20%**, costs **1 899,99 RUB**;
- 12 exit-capacity retries; `2022-06-06 11:10 UTC` выход не вместился в шесть следующих
  bucket и стал unresolved;
- verdict снова `NO_GO_UNRESOLVED_EXECUTION`.

Не создавать V12, который меняет только z-threshold, holding period, stop или liquidity
cap на той же истории. Возвращаться к relative value имеет смысл лишь с новой информацией:
PIT spot/index basket, funding/dividends, calendar-spread legs или order-book execution.

## Structural: почему ещё нет GO

Канонический proxy использовал 22 candidate roots, в среднем 17,71 допустимых активов и
1 259 development-сессий. Три лидера:

| Strategy | CAGR 5 bps | Sharpe | MDD | CAGR 10 bps |
|---|---:|---:|---:|---:|
| `risk_adjusted_momentum` | 6,7745% | 0,7840 | −15,1293% | 5,3463% |
| `tsmom_multi` | 6,3111% | 0,7943 | −14,2108% | 4,7127% |
| `tsmom_6m` | 5,3410% | 0,8091 | −11,9518% | 4,1414% |

Robustness-аудит не даёт независимого подтверждения:

- PBO-style probability выбранного кандидата оказаться ниже медианы: **69,84%**;
- вероятность selected OOS Sharpe `<= 0`: **22,22%**;
- корреляция `tsmom_multi`/RAM: **0,9641**;
- семь silent-missing proxy sessions: `2024-06-17…2024-06-21` и
  `2025-11-27…2025-11-28`;
- сигнал использует official close, а proxy получает следующий close-to-close return,
  поэтому same-close предположение само по себе неисполнимо.

Sealed execution study имеет verdict `NO_GO`. Для RAM ordinary расчёт остановился после
308 из 1 259 сессий: первая unresolved дата `2022-03-18`, причина
`GBPU:GUH2:missing_settle_or_contract`. Historical specs/fees/IM отсутствуют для 21
эффективного root; полная registry есть только для BR/MIX/RTS/Si. Дневной `OPEN` не
доказывает spread, очередь, partial fills или intraday tradability.

## Очередь работ

### P0 — быстрый конкурс стратегий, затем только прошедшие кандидаты

V91 [source-bound metadata mapper готов](V91_OPTION_CONTRACT_MAPPING.md),
59 новых / 126 combined local tests PASS. Сейчас один server static sample binding
check на восьми saved V88 descriptions и tiny catalog subset; не повтор HTTP/probe.
После него результат сохранить отдельно и двигаться к полному V89 mapping после closure.
Не делать новый audit этого sample вместо следующего исследовательского шага.

V90 [pure target adapter и ledger bridge готовы](V90_OPTION_STRIKE_CONVERGENCE_ADAPTER.md),
42new/95total local synthetictestsPASS. Не повторятьsyntheticпроверкикакновыйeconomic
результат. ПокаV89acquisitionRUNNING, следующийboundedшаг — source-bound mapper для
staticdescriptions→exactfutureidentity/quoteunits, syntheticfixtures доactualmapping.
ПослеV89finalmanifest одинполныйmapping/coveragecheck, экономическийconfig/code/input
seal и один2arms×2costsrun. Sourcecalendar261×4groups долженбытьявнопроверен; empty/missing
release нельзяобойтистарымсигналом. Не ставитьготовностьmetadata/unitsручнымTrue.
V89census/probe/audit/writerнеповторять,partialrootнеперезаписывать,V88referencesсохранить.
SI premium/marginedнесмешивать; currentdescriptionнеoriginalPIT. Daily pre-expiry proxy
неintradayexpiry: V62simulatehardcoded10:10–12:20, напрямуюквечернемутестунеподходит.
Никакогоeconomic/Stage2incrementпоподготовке. Protected2026 и scopegatesостаются.

V87 [GOLD positioning risk](V87_GOLD_POSITIONING_RISK_RESULT.md) завершён и проверен:
baseCAGR1.13%/MDD44.16%,doublecriticalfailure, wholebatchINVALID. Не повторятьcanonical,
audit, source assembly или настраивать знак/активы/lag/TTL/размер по outcome. Нужен иной
economicmechanism/informationset, а не ещё одна версия GOLD/WTI/STEO того же правила.
AlgoPack downloading не остановлен; новый conditional economic scopeV85 покаunanswered.
Поправка volume scope вначалеSTATUS: новый archive1.81GB, не вся стараяAlgoPackhistory.

V86 STEO forecast revisions завершён: [результат](V86_STEO_REVISIONS_RESULT.md).
Основной вариант убыточен; весь конкурс INVALID_EXECUTION_NO_PROMOTION. Не повторять
97-file collection, арифметические audits или canonical run, не менять sign/quarter/
size/costs/years ради улучшения результата. Source V4 ссылается на V3 raw: сохранить
оба каталога вместе. Дубли papr_world и неизвестный notice date не скрывать.
В первую очередь — новый разрешённый механизм на уже имеющихся данных, не доработка
инфраструктуры ради V86. Если пользователь подтвердит broader AlgoPack scope, брать
описанные V85 механизмы отмены/пополнения заявок по отдельному заранее fixed contest;
без ответа эта ветка остаётся scope-gated, но скачивание не останавливается.

V85 EQOrderStats/HI2 [source feasibility](V85_EQ_FLOW_FEASIBILITY.md) уже завершена.
Не повторять census/51page sample как новый результат. Свежий scope question на
расширение narrow V79conditional exception отправлен один раз; пока unanswered.
До ответа не строить/запускать новый AlgoPack economic engine. После ответа — новый
фиксированный конкурс на конкретном snapshot, никакого ослабления2026/PIT/live.
Это branch-level scope gate, не вывод об отсутствии всех возможных MOEX стратегий.

V84 завершён: [результат](V84_STOCK_PERPETUAL_BASIS_RESULT.md). SBER measured component
ниже20%/cash, GAZP missing fixed entry. Не повторять расчёт/audit/выбирать другой час,
уменьшать reserve/costs или называть отсутствие component headroom полным доказательством
убыточности всех пар. Следующий дешёвый конкурс — другой information set/механизм.
Возможная source-only feasibility: ещё не использованные EQOrderStats/HI2, по реально
сохранённым manifests/date/schema, без price outcomes до нового fixed protocol/seal.
Не повторять rejected V79 FO flow/depth rules и не строить полный paired engine без
показанного экономического запаса. Очередь не блокируется ожиданием конца скачивания.
V83 collateral feasibility тоже завершена: [отчёт](V83_STOCK_COLLATERAL_FEASIBILITY.md).
Не повторять широкий обзор брокеров/PDF. Дивиденды/конвертация/cash VM/actual broker
execution остаются unknown, а не бесплатными или уже учтёнными в V84 liabilities.
FUTOI V3 terminal failed, не restart; V4 запущен для сохранения raw с явными gaps
и reference reuse V2/V3. Проверить actual runtime в начале STATUS и archive-status,
не считать старый RUNNING checkpoint ниже актуальным.

V82 capital diagnostic завершён: [результат](V82_STOCK_PERPETUAL_CAPITAL_RESULT.md).
Funding на капитал с reserve30% даёт double17,2037%/18,8395%APR, не20%.
НЕ повторять V81/V82 batch/audits или снижать reserve/costs по результату.
Это2component follow-ups, не full paired PnL. Последующий V84 не показал запаса SBER
от basis/cash comparison, GAZP endpoint unresolved. Полный paired execution/economics
требует новой обоснованной механики и fixed protocol, full capital/margin, dividend
adjustment/actual dividends/tax,conversion,1x/2xcosts. Нужные два spot files теперь
в отдельном server subset leaf V84; standard history всё ещё не имеет dividend-adjustment.
Новых paired outcomes до отдельного seal не читать.
Не выбирать только GAZPF по большему увиденному APR и не называть APR уже готовым CAGR.
V80 GPR REJECT_STAGE1; не повторять source/feasibility/PnL или менять sign/window/TTL/годы.
46GPR vintages сохранены; их полнота/commit proxy не означает PIT или доходность.

Разрешение2026-09-15 получено; прежний scope blocker снят, повторно не спрашивать.
V79 R1 уже проверил3conditional AlgoPack механизма: все REJECT_STAGE1, см. начало.
Не повторять training, V1 mapping failure или source quality audits как новый поиск.
Архивная загрузка14families действительно RUNNING: [handle/состояние/продолжение](
ALGOPACK_ARCHIVE_V1_STATUS.md). Довести её до terminal coverage audit, не запускать
второй writer при живом service. FUTOI V1/V2/V3 failed, не запускать снова;
[V4 supplement RUNNING](ALGOPACK_FUTOI_ARCHIVE_STATUS.md), reference reuse7524V2/V3pages,
problem-day59page raw/coverage audit PASS. Довести оба архива до terminal coverage audit;
полный продукт ещё не скопирован. V4 зависит от старых V2/V3roots, не удалять их.
Для следующей экономической идеи использовать содержательно новую информацию и
отдельный protocol/admission, не threshold/cost/horizon retune этих3правил.
Не превращать source download или negative event means в portfolio20–50% result.

1. V78 завершён: оба Treasury-channel candidates REJECT_STAGE1, metrics вверху.
   Clock coverage100% не дала доходности; не менять знак/lag/window/риск/годы,
   не выдавать controls за alpha и не усложнять модель для спасения этих вариантов.
   V65–V78:19economic screens=17rejected+1incomplete+1invalid,0Stage2.
   Нужен иной доступный information set/механизм и дешёвый economic screen.
   V77 first-index-observation source feasibility завершена до цен:29candidates<30,
   ready stock coverage1/29; подробности вверху. Не повторять census/не ослаблять gate,
   не добавлять re-entries/aliases радиN и не строить engine под единственный ENPG.
   Сначала без цен проверить число событий и coverage по source→decision→fill clocks;
   если gates недостижимы, не строить engine и не открывать outcomes ради такого screen.
   V75 dividend drift отсечён source-only по5comparables; matching/lag не ослаблять.
   Предыдущий [V74 rig-supply](V74_BAKER_RIG_SUPPLY_RESULT.md) invalid: все4execution gatesfalse,
   gross-limit counters2/arm/cost, без rejected orders; raw primary gross уже отрицателен.
   Не превращать воспроизводимость или forensic CAGR в valid result/Stage2.
   Canonical/SHA/все годы вверху. Выбрать другое независимое information set или механизм
   после сверки реестра и выполнить дешёвый economic screen на допустимой истории.
   Не повторять/перенастраивать календарь, OHLCV, покупку V67, сигналы V68/V69, curve V70
   и forecast-error V71, policy-text V72, share-class V73, rig-supply V74, claims-cycle V76; не менять
   агрегирование/словари/знаки/TTL после результата; не спасать V73/V74 новым потоком/engine;
   контролям не присваивать роль новых alpha после результата. Не строить новый учёт
   для провалившегося ценового эффекта и не выводить CAGR из event means.
2. Следовать [HYPOTHESIS_FUNNEL.md](HYPOTHESIS_FUNNEL.md): глубокая проверка только для
   Stage2 candidates, а не инфраструктура до первого экономического screen.
3. Пользователь возобновил исследования 2026-09-13; V68–V78 завершены, см. верх STATUS.
   Paper bootstrap был отключён при паузе; не включать старый запуск автоматически.
   Source sample индексных новостей пока не запускать вместо экономического screen.

### P0 — AlgoPack history/quality завершены; новая информация для проверки

1. Ключ уже установлен на сервере; не просить повторно, не печатать и не переносить
   в local/Git/командные аргументы. Никаких дополнительных покупок/изменений тарифа.
2. Inventory V2 завершён и audited 11/11, canonical path/SHA вверху. V1 failed staging
   сохранить; ни одну версию не перезапускать ради улучшения результата.
3. Flow/depth sample завершён, audit 11/11, exact parent coverage PASS. History тоже
   завершён: 294jobs/2067949rows, canonical SHA в начале STATUS. Не перезапускать.
   Отдельный full replay и metadata coverage/TS-OB alignment тоже завершены —
   [quality V1](ALGOPACK_FO_HISTORY_QUALITY_V1.md). Не повторять ради нового результата.
   Пропуски не заменять нулём, date admission=false не превращать в полный PASS.
4. [Witnessed FO source V1](ALGOPACK_FO_WITNESSED_V1.md) запечатан и deployed,
   manual capture/replay PASS, новый timer enabled. Начальный operational gate выполнен:
   два scheduled captures12:03/12:13UTC и fixed three-capture quality COMPLETE
   (canonical/SHA вверху). Не повторять их и не строить ещё одну короткую проверку
   тех же снимков. Источник продолжает сбор; model/execution gates не сняты.
   Никаких дополнительных manual captures вместо timer.
   Старый manual
   FUTOI/latest collector и dispatcher не включают этот stream; не утверждать,
   что установка ключа автоматически включила постоянный FO flow/depth timer.
   Никаких current SECID из2025 карты и protected2026 prices/labels/PnL.
5. Publication audit и [training-today review](ALGOPACK_TRAIN_TODAY_ADMISSION_REVIEW_V1.md)
   COMPLETE. Пользователь явно разрешил archive-training assumption и новый future-only
   paper период: [scope](ALGOPACK_PAPER_AUTHORIZATION_20260907.md). Ранее2026 не открывать.
   Alignment, price inputs и paired Ridge training уже COMPLETE/TRAINED_NOT_EVALUATED;
   canonical/SHA в разделе завершённого обучения выше. Не повторять assembly/fit.
   Полный100-file paper seal и activation опубликованы: F=2026-09-08T21:00UTC.
   [Bootstrap](ALGOPACK_PAPER_BOOTSTRAP_20260909.md) уже назначен на21:01UTC; до F не
   запускать initialize/serve и не читать production model/price outcomes.
   source/model/live flags старых версий не менять. Общий permission blocker снят.
6. После назначенного запуска проверить actual bootstrap Result/ExecMainStatus/start
   timestamp и paper main PID/cgroup, затем новое calendar window September9 09:00–09:05MSK.
   Existing/partial account и failed invocation сохранять; initialization не повторять
   вслепую. Дальше сравнивать frozen price-only vs price+flow/depth на совместном состоянии
   четырёх активов и новых10min decisions. Retrospective screen не выбран: historical
   PnL запрещён, а старый2026 до F защищён. Не подменять процессный exit0 или synthetic
   PASS доказательством source/execution admission, независимости сигнала или доходности.
7. [Протокол подключения и ограничения](ALGOPACK_HISTORICAL_SOURCE.md). Не считать
   приобретение источника или технический PASS доказательством минимальных 20%.

### Следующая независимая ветка — бесплатный corpus индексных объявлений

1. После завершения подготовки AlgoPack и замечания пользователя об опросе таймера
   возобновлена bounded source-only проверка: [9article sample](MOEX_INDEX_NEWS_SAMPLE_V1.md).
  32synthetic tests PASS; до seal/push/server run реального результата нет. Full catalogue
   disabled до sample/review; уже зафиксированный paper-контур не менять.
2. V64 завершён `NO_GO`, audit 156/156; canonical не повторять и не превращать его
   control в новую стратегию. Не подбирать окно/знак/размер/годы по этому исходу.
3. Следовать [MOEX_INDEX_REBALANCE_SOURCE.md](MOEX_INDEX_REBALANCE_SOURCE.md): сначала
   запечатать source-only протокол полного 2012–2025 корпуса объявлений IMOEX/RTS,
   с explicit missing periods, revision/dedup и current-vintage ограничением.
4. Без prices/returns собрать sample/parser на сервере, проверить publication/effective
   times, отличать подтверждённые включения от waitlist и временных исключений.
   Не строить новый engine или equity PnL на трёх удобных событиях из web search.
5. После source audit отдельно зафиксировать long-only event hypothesis, causal
   execution, control, costs и eras до первого economic load. Пригодность бесплатного
   источника и прибыльность ещё не установлены; закрытые семьи не переоткрывать.

### История доступа — AlgoPack / новый flow-depth источник после V63

1. Следовать [RESEARCH_PROCESS.md](RESEARCH_PROCESS.md), не снижая цель 20%/50%.
2. V63 завершён, 183/183 replay checks; не повторять diagnostic или parent runs.
3. Bounded source feasibility 2026-09-06 выполнена; собственная готовая история
   TradeStats/OBStats не установлена, credentials нет. Нужен разрешённый пользователем
   запрос тестового доступа MOEX по [DATA_ACCESS_REQUESTS.md](DATA_ACCESS_REQUESTS.md).
   Разрешение получено 2026-09-07; письмо отправлено через открытую пользователем
   Яндекс Почту и проверено в «Отправленных». Не дублировать. После вопроса о цене
   проверен AlgoPack PROMO: 610 ₽/месяц, API и Super Candles включены; оформление
   остановлено на входе DataShop. После этого пользователь отложил покупку: вход,
   платные условия, оформление и paid collector не являются активной очередью.
   Возврат к этому направлению — по новому поручению либо после получения доступа;
   уже отправленное письмо не отзывать и не дублировать.
   Не повторять inventory/поиск тех же условий без изменения доступа. После доступа:
   source-only seal и sample audit, затем отдельный sealed economic test и лишь после
   него обоснованное усложнение модели. Не покупать доступ без отдельного разрешения.
4. Не превращать хорошие годы, часы или корреляции V63 в новую настроенную стратегию.
   Не создавать очередную смесь/scale V41/V49/V60: monthly risk overlap теперь измерен.

### P0 — intraday option-surface discovery и defined-risk volatility family

1. V58/V59 CFTC закрыты, V60 прошёл development, V61 не подтвердил minimum 20%.
   Не менять их signs/windows/multipliers по уже увиденному outcome.
2. Держать активным server intraday timer option admission V2 SHA `fb598938...` и
   отдельный V1 EOD compatibility timer; каждый V2 eligible snapshot обязан быть
   post-boundary, пройти полный source replay и sealed quality diagnostic SHA
   `b26c35c6...`.
3. До 20 complete sessions не вычислять features, labels, returns или PnL. После gate
   один раз запечатать экономический protocol до чтения следующих outcomes.
4. Сравнить full-surface neural timing с price-only ablation, fixed skew/term rule и
   always-abstain; использовать только defined-risk конструкции, observed OFFER/BID,
   size/capacity и запрет naked short.
5. Historical MOEX Type B остаётся отдельным ускорителем, но покупка требует разрешения
   пользователя. Public delayed snapshot нельзя трактовать как доказательство queue/fill.

### P0 — post-seal paper arm V49 без повторного historical tuning

1. Forward config SHA `520bd3d4...` уже запечатан с eligibility boundary
   `2026-09-02T12:30:04Z`; source counts V49 начинаются с нуля. Не повторять canonical
   V49 и не проверять соседние scales/caps/buffers на 2021–2025. Historical verdict
   остаётся `NO_GO`, даже если разрыв до primary gate всего `1.3167` п.п.
   Первый server readiness подтвердил `0/54 + 0/253`, preseal exclusions `1 + 2`,
   invalid `0`; implementation и server deploy commit `a6cd0af`.
2. Выполнено до следующего server snapshot: отдельный paper config SHA `56822e1e...`,
   boundary `2026-09-02T19:16:00Z`, ровно один arm `2.00x`, gross cap `4.00`, margin
   buffer `2.00`, participation `1%`, V39 signs/zeros и exact execution без изменений.
   Все eligible counts при seal были нулевыми. Не создавать ещё одну границу и не
   backfill-ить уже собранные 2026 observations как unseen V49 outcome.
3. Использовать те же независимые component sources и warmup, что V48, но вести V49
   отдельно: V48 `1.50x` остаётся заранее выбранным baseline, V49 не заменяет его.
4. До полного warmup/evaluation не считать CAGR и не выбирать arm. Любой paper pass
   требует broker-exact IM/fees/fills и второго unseen периода; live trading запрещён.
5. V50R1 уже показал, что same-history stability floor `20%` не подтверждён: q05
   `10.4537%`, rolling gates false. Поэтому не компенсировать это новым плечом или
   выбором удачных historical windows; ждать frozen post-seal observations и развивать
   только новый causal source/mechanism с отдельным seal.

### P0 — forward-подтверждение V41 cash-carry sleeve

1. Не менять V41 80/20, 50% RUONIA, DTE 30–90, times, cashflow haircut или costs.
   V42R2 уже доказал только same-history устойчивость CAGR к fund TER/tax/switching;
   не использовать его для изменения веса или выбора фонда до forward discovery.
2. Проверять server timers `trading-lab-cash-carry-decision.timer` (15:49) и
   `trading-lab-cash-carry-fill.timer` (15:59), затем paired readiness. Сейчас 0/60
   discovery, 0/20 calibration, 0/60 unseen evaluation.
3. Invalid/sleep snapshot не считать парой; не заменять missing BID/OFFER/clock нулём.
   Anonymous ISS не доказывает latency, size, queue или fill.
4. Параллельно получить byte-pinned broker fee/margin/order-log и конкретный
   cash/MMF/REPO instrument rule. Без них даже успешный quote-forward остаётся paper.
   Exchange baseline уже уточнён: current MOEX stock-futures taker BaseFutFee
   `0,011385%` на сторону, но это не включает broker/NCC pass-through; frozen 5 bps
   assumption до broker document не снижать.
5. LQDT выбран как отдельный idle-only challenger, source SHA `15fb471a...`, seal
   `8ae3dc3`. Запустить tasks 15:49/15:59 и paired readiness; не считать его залогом,
   не читать iNAV без подтверждения лицензии и не строить PnL до 60 пар.
6. Канонический discovery count для V41 — joint depth admission `8183eb50...`, а не
   отдельные quote counts. Дата проходит только при 10 stock/futures depth gates,
   positive LQDT depth и same-stage skew `<=30s`.
7. Проверять server timers `trading-lab-fund-pool-decision/fill.timer` и readiness фиксированного пула
   LQDT/SBMM/AKMM/TMON. До 60 пар не вычислять spread ranking, yield или PnL; состав
   пула после первого значения не менять.
8. V51 уже проверил все девять V42R2 curves и провалил все internal-20 gates, включая
   leave-2022-out `15.7917%`. Не увеличивать cash-carry weight и не выбирать fund по
   этому outcome. Следующий historical mechanism допустим только с независимым return
   engine; V41 продолжать лишь как frozen forward baseline.

### P0 — независимая forward-проверка V27

1. Не менять parent V27 SHA `7a9a44cf...`, horizons `21/63/126/252`, STLFSI4 `0`,
   key rate `20%`, 2x, RUONIA haircut `50%`, buffer/cost/capacity.
2. Каждый следующий сеанс проверить server timers `trading-lab-v27-decision.timer` и
   `trading-lab-v27-execution.timer`, затем component readiness; invalid snapshot не
   считать в coverage.
3. Первые 253 common official CLOSE дают 252 return sessions и являются только warmup.
   Затем неизменяемый paper runner
   использует минимум 504 sessions; до этого не вычислять/публиковать V27 forward CAGR.
4. Получить broker-exact collateral/IM/fee/order-log правила параллельно; numeric GO без
   них остаётся paper-only и требует второго unseen confirmation.

### P0 — forward MOEX RMS и новые execution/cashflow hypotheses

1. Historical V4 source `83bcabed...`/manifest `e88360d3...` не перезаписывать;
   V1–V3 output не восстанавливать. V38 является canonical `NO_GO`, поэтому MR1
   threshold/age/persistence, MR2/MR3 substitution, global switch и sign inversion на
   2021–2025 запрещены.
2. Проверять server timer `trading-lab-moex-rms.timer` и readiness; сейчас 0/60 discovery.
   Snapshot обязан быть post-seal, raw-replayed и не содержать price/return/PnL.
3. MR1 использовать в будущем прежде всего как broker/exchange admission input:
   фактический margin reserve и capacity, а не как ещё один tuned alpha switch.
4. Historical dividend-spread V1 уже завершён `NO_GO`: 31 RMS events, 0 following-quote
   entries. Не повторять его после 60 discovery с изменённым lag/sign/threshold. Новый
   dividend alpha допускается только от original-timestamp board/issuer disclosure,
   которое объективно раньше RMS repricing.
5. Предпочтительный источник — authenticated Interfax e-disclosure JSON Gateway с
   event clock и correction chain; credentials отсутствуют, spend не разрешён. Exact
   условия, тарифы и acceptance checklist: `docs/DATA_ACCESS_REQUESTS.md`. До отдельного
   разрешения пользователя status `SLEEPING_NO_CREDENTIALS_NO_SPEND`.
6. Defined-risk option regime остаётся отдельной forward family: 20 calibration и 40
   unseen evaluation после discovery; naked option risk и historical 2026 backfill
   запрещены.

### P0 — доходный collateral и forward CNY relative value

1. V1 perpetual/quarterly numeric GO недействителен из-за ошибки contract units;
   использовать только corrected V2 `NO_GO` и не перезаписывать оба run.
2. Не ослаблять historical RUONIA hurdle и не выбирать контракты по уже просмотренным
   2023–2025 estimates. Новый test допустим только как отдельная экономика доходного
   collateral: byte-pinned broker/exchange rules, haircut, доступность вывода/залога,
   фактическая комиссия и margin calls.
3. Начать forward-only snapshot потока `CNYRUBF`/ближайших CR после отдельного seal;
   сохранять bid/ask, `SWAPRATE`, specs/IM и retrieval time. Historical 2026 backfill
   запрещён. Source SHA `1305af9d...`, collector `13371f2`, readiness `7abf796` уже
   pushed. Server timer `trading-lab-cny-relative-value.timer` запускается в 18:30
   Mon–Fri. Сейчас 0/40 discovery, 0/20 calibration,
   0/60 unseen evaluation; до заранее заданного paper периода PnL не считать.
4. Автоматический option-surface collector оставить активным: сейчас 1/60 discovery,
   затем 20 calibration и 40 unseen evaluation; naked short options запрещены.

### P0 — forward equity microstructure вместо повторной настройки V35

1. V35 canonical `NO_GO`; immutable run и source bundle не повторять. Не ослаблять
   probability `0,55/0,65/0,75`, не менять mean-reversion sign, 60-minute horizon,
   universe, leverage или costs на уже просмотренном 2020–2025 panel.
2. Реализовать target-free one-shot collector официальных MOEX equity
   `tradestats/orderstats/obstats`: только aggressive-flow, order-add/cancel imbalance,
   spread/depth и timestamps; raw bytes, `SYSTIME`, retrieval, entitlement и
   `available_at=max(SYSTIME+buffer,retrieval)` обязательны. Absolute price/return/
   target/PnL в feature snapshot не сохранять.
3. Получить ALGOPACK entitlement и запускать collector каждые пять минут на заранее
   фиксированном liquid universe. Public delayed data годятся лишь для pipeline test,
   не для same-day prediction.
4. Отдельно получить у брокера timestamped short-locate availability, borrow rate,
   historical/current lot size, commission и actual fills. Без locate нельзя считать
   short legs V35 исполнимыми; без order log нельзя доказывать fill по candle value.
5. До накопления заранее заданного forward периода не считать PnL. Затем sealed paper
   protocol должен сравнить flow/depth neural gate с price-only baseline при same
   next-open execution; реальный капитал запрещён. Полная последовательность и source
   gates записаны в [FORWARD_EQUITY_PROTOCOL.md](FORWARD_EQUITY_PROTOCOL.md).

### P0 — сохранить новый 2008–2011 holdout до просмотра outcomes

1. V1 seal `49467bc` не менять и не повторять: collection остановилась без output на
   exact NULL-placeholder `RIM9_2009/2008-09-12`. Commit/push parser-only V2 config SHA
   `74847dd3...`, module SHA `acc547f5...` выполнены commit `617ce72`.
2. V2 для 81 exact contract собран во внешний immutable каталог
   `data/processed/futures_pre2012/moex-core3-mix-daily-current-vintage-2008-2011-v2/`,
   manifest SHA `e06fd978...`; отдельный `--audit-only` дал 41/41 true. Collection не
   повторять и output не перезаписывать.
3. D1 seal `45e55af` и D2 seal `fa61763` не менять. D2 rejected output не повторять и
   не перезаписывать. D3 seal `afaa278` и canonical suffix `-v3` завершены: manifest
   SHA `ff9b2771...`, 27/27 replay checks и strict dtypes exact. Outcomes были открыты
   только один раз после V31 seal; source не менять. MIX до 2011 остаётся отсутствующим,
   gap/roll нельзя синтезировать.
4. Принципиально новый V30 target на уже просмотренном 2012–2017 завершён. D2 seal
   `aea34e4`, immutable run `v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a`,
   metrics SHA `e5aeb7d1...`; exact audit 33/33. Формулу, параметры риска и costs по
   этому периоду больше не менять; V30 не называть holdout и run не перезаписывать.
5. V31 sealed/pushed `370b4d8` до outcome read и выполнен ровно один раз. Immutable run
   `v31_pre2012_temporal_20260901T145938Z_6dcb6dab`, metrics SHA `d6d12842...`;
   audit 35/35 artifacts, 122/122 checks, 6/6 metric replays. Verdict
   `UNSEEN_TEMPORAL_NO_GO_20`; primary/stress CAGR `−6,75%/−7,16%`. Не повторять,
   не менять start/window/sign/asset/cost/leverage и не использовать для live.
6. Следующая family должна быть экономически иной и оцениваться по nested walk-forward
   на всей открытой 2008–2025 history; независимое подтверждение теперь возможно только
   в заранее запечатанном paper/forward периоде. Приоритет: причинные gap-tolerant
   multi-scale features, cross-market regimes и новые original-vintage/intraday sources.

### P0 — новый market-neutral source family

1. Canonical V3 public source и D1 derived panel завершены без перезаписи parents:
   manifests `94d5fab4...`/`b5e15c2e...`, audits полностью true. Не overwrite.
2. EV1 fail-closed без output; EV2 восстановил reporter, но имел нулевую evaluation
   exposure; EV3 восстановил 1 666 plans, но primary/stress отрицательны. EV4 cost hurdle
   дал только `+0,3095%` primary и `−0,1664%` stress; verdict `NO_GO`. Не создавать V5
   с новым threshold, leverage, asset/year filter или stop по тем же outcomes.
3. Source-only multileg parser V1 sealed SHA `464cce7a...` до licensed bytes. Сначала
   получить January 2021 pilot `multileg_deal` + `multileg_dict`; если доступен member
   archive, добавить `multilegf04`, `multilegordlog`, `f04.ID_MULT`. Pilot — только
   preflight, без PnL и canonical publication.
4. Письменно подтвердить у MOEX, входит ли multileg history в Type C и существует ли
   historical full-market multileg order log. Participant `multilegordlog_XXYY` не
   считать полной очередью; публичный Type A sample listed spreads не содержал.
5. Только после полного 2021–2025 source manifest отдельно запечатать новый execution
   replay. Historical specs, tick values, IM, exchange/clearing tariffs и broker fees
   должны быть point-in-time; результат остаётся adaptive и не разрешает live.

### P0 — независимо подтвердить V27, не подгоняя его

1. Заморозить byte-identical V27 целиком: V12 signal, V25 STLFSI4 zero/age, key-rate
   boundary `>=20%`/7-day age, максимум 2x, RUONIA haircut/buffer, universe, capacity и
   execution costs. Не выбирать partial scale или новый threshold по 2021–2025.
2. Новый unseen market period получен: official MOEX 2012–2017 source V3 содержит
   30 059 daily rows по 155 contracts; D3 причинно построил common calendar/roll/spec
   без synthetic gap return. Raw replay, hashes и границы проверены.
3. D1 выявил serial-contract failure; D2 остановился без output на неверном ожидании
   непрерывного SI roll; D3 с exact flat/sleep semantics успешно собран и проверен.
   S1 transport failed без output; S2 failed parse без output; S3 успешно собран и
   replayed. V28 завершён с отрицательным и execution-invalid outcome; не повторять.
   V29 risk-first correction выполнен один раз после pre-outcome push. Execution стал
   полным, но CAGR `3,71–4,61%`, MDD `47,38–48,68%` и только 1/5 positive years дают
   `FAIL_POST_V28_20`. V29 не повторять и не tune-ить на 2013–2017. Следующий PnL —
   только новая независимая информация/target family либо forward collection; historical
   specs/fees/IM всё ещё proxy, licensed MOEX/broker archive обязателен для live evidence.
4. Провести заранее запечатанный paper/shadow forward test без реального капитала;
   отдельно мониторить key-rate/STLFSI availability, отрицательные недели, drawdown,
   capacity cancels и деградацию trend edge.
5. Только после независимого подтверждения проектировать отдельный live-admission
   protocol с operational risk и аварийным отключением.
6. V27-R1 уже выполнен ровно один раз: 180 000 bootstrap paths, 3 063 rolling windows,
   49/49 checks. Его resampling frequency не называть вероятностью будущей прибыли и не
   менять V27 по результатам.

### P1 — новая информация для intraday timing и устойчивости

Официальная документация повторно проверена 2026-09-02: futures ALGOPACK даёт
5-минутные `tradestats/obstats` и заявляет Super Candles history с 2020 года, но FO
`orderstats` в futures REST menu не подтверждён. `Full_orders_log` за 21 000 RUB/month
— live FAST option, а не заявленный historical archive. До test token и письменных
non-display ML rights новый spend запрещён; готовый target-free collector остаётся
sleeping и должен запускаться только на `gpu-mlserver` после credentials.

1. Считать V16 `INVALID`: 932/1 044 FUTOI states нарушают `available_at <= decision_at`.
   Не использовать его return, diagnostics или thresholds для дальнейшего отбора.
2. Полный официальный FUTOI 5m уже сохранён как current-vintage/forward source:
   2 015 624 строки, 5 896 raw records, все hashes совпали. Для каждой строки есть
   official `SYSTIME`, actual retrieval и `conservative_available_at`; история 2021–2025
   при таком contract не backtest-admissible.
3. Для исторического continuous timing нужен лицензированный archival feed с original
   publication vintages либо собственный forward collector. Без него FUTOI-гипотеза
   sleeping, даже если анонимный endpoint технически возвращает данные.
4. EIA v2 source audit завершён, но sealed V17 raw-change composite убыточен и закрыт.
   Не инвертировать его signs и не сокращать lag; искать point-in-time consensus surprise
   либо принципиально другой независимый source family.
5. Новый CBR release-keyed liquidity-forecast bundle готов: 458 releases, 537 requests,
   12 недель без record, maximum release gap 16 дней, processed SHA `a8faab04...`.
   V18 direct SI test выполнен после pre-outcome push и дал `NO_GO`: CAGR −10,31%,
   Sharpe −0,51, MDD −55,73%. Не инвертировать знак и не перебирать строки/пороги;
   следующий тест должен использовать новую заранее обоснованную информацию.
6. RVI threshold/blend на 2021–2025 также запрещён sealed V14; совпадение с invalid V16
   drawdown остаётся только post-outcome наблюдением.
7. CBR daily-factors source собран: 1 238 admitted rows, processed SHA `88885d36...`,
   manifest SHA `f1701ec3...`. V19 выполнен после pre-outcome push и дал `NO_GO`:
   total return −0,03%, Sharpe 0,05, MDD −30,76%. Не выбирать magnitude/change days,
   smoothing, lag, blend или sign flip по увиденному результату.
8. Официальный Minfin OFZ source готов: 410 events, 364 primary results, 283 ОФЗ-ПД,
   processed SHA `a8c5c024...`, manifest SHA `c6fcf390...`; все карточки классифицированы
   и primary fields полны. Availability консервативно равна концу publication day.
9. V20 prior-only demand-strength test завершён `NO_GO`: total return −5,35%,
   Sharpe −0,63, MDD −6,19%, 504/504 dependencies complete. Не менять rank window,
   basket signs, expiry, threshold или включённые event kinds по этому outcome.
10. CBR macro-survey bundle готов: 11 787 records, 37 months, 17 indicators, processed
    SHA `a139ead8...`, manifest SHA `faae8927...`. V21 завершён `NO_GO`: mechanical
    total return −3,17%, Sharpe −0,08, MDD −18,79%, 200/202 coverage и 2 critical.
    Direct revisions family закрыт; не менять signs/indicators/oil priority/thresholds,
    risk/expiry или blend по этому outcome. December 2025 остаётся исключён.
11. CBR Business Climate Index bundle готов: 44 releases, 90 raw responses, processed
    SHA `b312f4e5...`, manifest SHA `99ad128b...`; 21 positive, 18 negative и 4 zero
    sequential changes. V22 direct regime завершён `NO_GO`: +13,37%, Sharpe 0,36,
    MDD −8,86%, complete execution. Не подбирать threshold/components/sign/risk/expiry;
    следующий PnL допускается только с новой независимой информацией или forward period.
12. CBR household inflation/sentiment bundle готов: 48 releases, 146 raw responses,
    processed SHA `70711272...`, manifest SHA `b132a45e...`; 16 risk-on, 17 risk-off и
    14 mixed source confirmations после warmup до collision handling. V23 завершён
    `NO_GO`: −5,35%, Sharpe −0,16, MDD −13,62%, downstream ledger complete, но 3
    confirmed states fail-closed не mapped. Same-history household tuning закрыт.
13. FRED/Cboe VIX/VIX3M V2 готов: 2 087 grid rows, 2 011 complete pairs, processed SHA
    `6ffe7daa...`, manifest SHA `0aecc29fd...`; 2 010 pairs causal до границы 2026,
    включая 174 backwardation. V24 был запечатан/pushed до outcome и завершён `NO_GO`:
    +38,89%, Sharpe 0,739, MDD −14,28%, complete execution, но оба stability gates хуже
    V12 и costs выше. Same-history VIX boundary/freshness/scaling tuning закрыт.
14. Source-only screen отверг NFCI/ANFCI: 0 above-zero OOS weeks означают тождественный
    V12. STLFSI4 bundle готов: 417 weekly rows, 416 causal до 2026, processed SHA
    `4937b686...`, manifest SHA `1a992f64...`, strict raw replay exact. V25 был sealed и
    pushed до outcome; +49,07%, Sharpe 0,818 и worst year лучше V12, execution complete,
    но MDD хуже на 0,0736 п.п., поэтому strict `NO_GO`. Следующий шаг — только новая
    forward/PIT validation; same-history STLFSI tuning закрыт.
15. V26 доказал capital efficiency: all-scenario CAGR `23,03–24,17%`, 0 critical, но
    MDD `33,57–33,99%`, strict `NO_GO`. V27 добавил raw-replayed official key-rate
    `>=20%` cash state и прошёл все gates: primary/stress CAGR `28,38%/27,36%`, MDD
    `20,71%/21,05%`, Sharpe `1,212/1,184`. Это adaptive same-history lead; следующий
    PnL допустим только в отдельной unseen/PIT validation, не через tuning V27.

### P2 — разблокировать широкий structural exact execution

1. Получить лицензированный point-in-time архив historical contract specifications,
   multipliers/ticks, exchange и broker fees, initial margin и settlement rules для 21
   фактически торгуемого root.
2. Разобрать `GBPU:GUH2` на `2022-03-18` и все rejected/partial roll cases без
   zero-imputation или ручного подглядывания в будущие данные.
3. Устранить либо честно исключить семь silent-missing sessions, сохранив причинность.
4. Без изменения сигналов повторно проверить только `tsmom_6m`, `tsmom_multi` и
   `risk_adjusted_momentum`.
5. Требовать 1 259/1 259 разрешённых сессий и положительный результат при 5/10/20 bps,
   delayed execution, integer contracts, capacity и gross cap.

### P3 — наблюдать sparse event lead

Не оптимизировать key-rate sleeve на десяти сделках. Его можно расширять только новой
историей или независимыми заранее объявленными event families. Сохранять отдельный
baseline: neural timing не улучшил входы и полностью abstained.

### P4 — корпоративная отчётность

Контур sleeping до появления корпуса с подтверждёнными правами, точным publication time,
revision chain и page evidence. Локальная LLM извлекает факты, но не видит рыночные labels.

## Что не продолжать без новой независимой идеи

- threshold-only `intraday_timing_v3`;
- повторный 30-stock attention/graph на том же target;
- новые варианты corridor на тех же OOS после просмотра результатов;
- новые пороги/стопы/ослабление capacity для RI/MIX/SI triangle на тех же OOS;
- long-only momentum overlays на той же таблице без независимого holdout;
- V27 key-rate threshold/age/partial-scale variants на 2021–2025;
- V8 PnL до authoritative admission certificate и полного источникового аудита.

## Канонические внешние артефакты

Пути ниже относительны к `D:\Projects\trading_lab_data`:

- `runs/futures_v9_structural/structural_c86d4852729d4c8a/results.json`
- `runs/futures_v9_structural_robustness/robustness_870183b62323f8bb/audit.json`
- `runs/futures_v9_structural_execution/execution_8a934dfae72c769c/results.json`
- `runs/event_alpha_v1/development_20260818T155959Z_91f61abe/report.md`
- `runs/futures-v9-corridor-development-v1/metrics.json`
- `runs/futures_v9_intraday_timing_v2_full_20260818T164623Z/report.md`
- `runs/futures_v9_event_timing_hybrid_development_20260818T170400Z_92e98a72/report.md`
- `runs/market_graph_v1_20260818T164732Z/metrics.json`
- `runs/market_graph_v2_long_only_20260819T074638Z/metrics.json`
- `runs/v10_triangular_20260831T171000Z_4ff5c4cb/metrics.json`
- `runs/v11_buffered_open_20260831T171200Z_584bf289/metrics.json`
- `runs/v12_core4_trend_20260831T182210Z_0b1a79d5/metrics.json`
- `runs/v13_trend_carry_20260831T190300Z_94841c0b/metrics.json`
- `runs/v14_rvi_governor_20260831T201919Z_9f680ebf/metrics.json`
- `runs/v15_levered_ruonia_20260831T205040Z_8cbcf307/metrics.json`
- `runs/v16_futoi_governor_20260831T220539Z_d0461775/metrics.json`
- `runs/v17_eia_supply_demand_20260831T234157Z_1d8eee3f/metrics.json`
- `runs/v18_cbr_liquidity_forecast_20260901T002046Z_ee2d7fd7/metrics.json`
- `runs/v19_cbr_minfin_fx_persistence_20260901T004717Z_1340ffac/metrics.json`
- `runs/v20_minfin_ofz_demand_strength_20260901T014359Z_788fadbd/metrics.json`
- `runs/v21_cbr_macro_revision_breadth_20260901T022038Z_5d97fd51/metrics.json`
- `runs/v22_cbr_business_climate_20260901T025910Z_97b2aa74/metrics.json`
- `runs/v23_cbr_household_confirmation_20260901T034927Z_2a8a35a8/metrics.json`
- `runs/v24_cboe_vix_governor_20260901T042913Z_f81b5aaa/metrics.json`
- `runs/v25_stlfsi_governor_20260901T045542Z_dd8b6051/metrics.json`
- `runs/v26_stlfsi_levered_ruonia_capacity_20260901T051200Z_2b085890/metrics.json`
- `runs/v27_key_rate_governor_20260901T052350Z_7a9a44cf/metrics.json`
- `runs/v28_pre2018_unseen_20260901T082728Z_4f9e6663/metrics.json`
- `runs/v29_risk_first_roll_20260901T085436Z_d92f8cf2/metrics.json`
- `runs/v49_v39_double_risk_exact_execution_v1_20260902T122406Z_37b4fcb0/metrics.json`
- `runs/v58_cftc_wti_positioning_br_v1_20260902T184645Z_637eb6c4/metrics.json`

При переносе или восстановлении данных сначала сверяй hashes из
[DATA_AND_INTEGRITY.md](DATA_AND_INTEGRITY.md), затем открывай артефакт.

## Состояние миграции репозитория

Канонические код и документация находятся в `D:\Projects\trading_lab`; canonical `data`,
`runs` и модели остаются вне Git в `D:\Projects\trading_lab_data`. Любая сохранившаяся
копия под `D:\Projects\Trading` является только recovery source, а не рабочим репозиторием.
Миграционная проверка начата 2026-08-31; полный suite повторён 2026-09-01:

- в старом source/config/test дереве не было old-only файлов: 274 файла совпали
  побайтово, 10 имеют ожидаемые migration-изменения в актуальной копии, 8 добавлены уже
  после переноса;
- все 1 403 файла `data` и 1 598 файлов `runs` совпали с external storage по
  относительному пути, размеру и SHA-256; отдельными оставались только `.venv` и кеши;
- восстановлены ошибочно исключённые общим `.gitignore` Python-пакеты
  `market_lab.data` и `market_lab.models`; root external paths теперь anchored как
  `/data`, `/runs`, `/models`, `/checkpoints`;
- полный CPU suite: **880 passed, 7 skipped, 2 failed**;
- два failure относятся только к sealed V8 `context_run`: его старый anti-symlink guard
  намеренно не принимает external NTFS junction. Старый byte-sealed код нельзя менять
  задним числом; нужен новый migration-compatible loader/code identity;
- migration/config/offline-CLI slice: **5 passed**; тестовый CLI теперь пишет только в
  pytest temp, а не в canonical external `runs`;
- Ruff для изменённых config/migration файлов: clean; полный legacy tree имеет 58
  существующих замечаний (27 `E501`, 27 `F401`, 2 `I001`, 2 `UP035`), которые нельзя
  массово auto-fix без проверки code seals;
- encoding tests проходят. Для неизменяемых identity-pinned V9–V11 файлов без BOM задан
  точный allowlist; новые незапечатанные text/code files обязаны иметь UTF-8 BOM.

Git-инвентарь содержит только код/config/tests/docs и маленькие fixtures: ни `data/`, ни
`runs/`, ни `models/`, ни checkpoints/Parquet/NPZ/PT в commit не входят.
