# V88 — точные expiry доступны; полный option→futures mapping ещё не построен

2026-09-15. Все10заранее объявленных запросов выполнены один раз: HTTP200 с первой
попытки, всего30885raw bytes. Это **source feasibility**, не экономический тест,
кандидатStage2 или подтверждённый источник дохода.

[Протокол](V88_OPTION_METADATA_PROBE.md), pre-request commit `95f4354`.
Seal: `c1529e0e6191f4290df97afc07f6baa01ede557126d1d1c3208d87e837525a50`.
Canonical: `/srv/trading_lab_data/source_evidence/v88_option_metadata_probe_v1`.
Manifest SHA: `10ff109b609658ebd0ff4ae4bb7e8f0f17e0d1b5a1afe521ea113699e25d9d7f`.
Completed2026-09-15T14:38:58.200513UTC.
Unit `trading-lab-v88-option-metadata-c1529e0e6191.service`, invocation при запуске
`802a2585f1304ac1b6d9b440c7929fba`, PID3093391. TerminalPID0/exit0/inactive/dead
подтверждён14:39:59UTC и journal; current transient show больше не хранит invocation.
Нельзя повторять canonical sample или считать его полным справочником108104опционов.

## Что установлено

Публичный [справочник ISS](https://iss.moex.com/iss/reference/193) вернул8/8точных
описаний SECID, включая `LSTDELDATE`. В raw schema title это прямо **«Дата экспирации»**,
типdate; `LSTTRADE` отдельно подписан как последний день обращения. Даты не выводились
из предположения о третьем четверге или совпадении с фьючерсной экспирацией.

| SECID | Дата экспирации | Тип по description | UNDERLYINGASSET |
| --- | --- | --- | --- |
| Si100000BC1 | 2021-03-18 | Маржируемый option | USD000UTSTOM |
| Si100.5CA5B | 2025-01-09 | Премиальный option_on_currency | USD000UTSTOM |
| RI100000BA1 | 2021-01-21 | Маржируемый option | RIH1 |
| RI100000BA5 | 2025-01-16 | Маржируемый option | RIH5 |
| BR100BB1 | 2021-02-23 | Маржируемый option | BRH1 |
| BR100BA5 | 2025-01-28 | Маржируемый option | BRG5 |
| MX100000BC1 | 2021-03-18 | Маржируемый option | MXH1 |
| MX145000BC5 | 2025-03-20 | Маржируемый option | MXH5 |

Особенно важно различие двух SI-контрактов, которые исходный weekly parser помещает
в один `logical_asset=SI`:

- Si100000BC1: NAME указывает опцион на фьючерсSi-3.21, LOTSIZE1,
  UNIT«в рублях за лот», STRIKE100000, маржируемый.
- Si100.5CA5B: недельный премиальный европейский валютный опцион, LOTSIZE100,
  UNIT«в рублях за1долларСША», STRIKE100.5, TYPEoption_on_currency.

Это разные payoff units и контрактные размеры. Два страйка не являются напрямую
сопоставимыми числами; контрактные OI нельзя без преобразования трактовать как один
объём хеджирования. При этом `UNDERLYINGASSET` у обоих равенUSD000UTSTOM: даже для
маржируемого Si это поле само по себе не идентифицирует ближайший underlying future.
В6других examples поле содержит фьючерсные коды, но полный join к нашему canonical
фьючерсному справочнику ещё не выполнен. Не подставлять текущий active future молча.

Результат выявляет ограничение интерпретации старых reported-subset OI features;
он не пересчитываетV39/V68, не доказывает численную ошибку всех старых PnL и не даёт
разрешения подбирать их новый фильтр по уже известным outcomes.

## Что означает календарь

Подписанный apim route отвечает JSON с11static columns, но без numericOPTION_SERIES_ID,
точногоSECID или отдельного underlying-security binding.

- from=till2021-01-08:0rows.
- from=till2025-01-03:1row, NG-1.25M030125XA, expiration_date2025-01-03;
  дляSI/RI/BR/MIX строк нет. Expiration time/type/weekend fields этой строкиNULL.

Это **не доказательство отсутствия торгуемых core4опционов на указанные даты**:
их существование подтверждено исходной историей и8descriptions. Такой date-range
calendar нельзя использовать как полный список активных опционов на дату. Наблюдения
согласуются с выборкой событий экспирации в диапазоне, но полная семантика фильтра
в этой проверке не доказана. Старый numeric-ID blocker volatility-curve join не снят.
Конечный вывод: description route пригоден для отдельного exact mapping source;
calendar sample сам по себе его не заменяет.

## Проверки и ограничения

- Source metadata identity:1327744rows,108104uniqueSECIDs,2021-01-08…2025-12-30.
  Читались толькоtradedate/logical_asset/secid/boardid, без величинOI, prices или PnL.
- Local32targetedtestsPASS,server15testsPASS,Ruffclean,7sealed dependencies verified.
- Независимая сверка10raw hashes/lengths, parser replays, request/record equality,
  HTTP/clocks и8description identity/date ranges прошла14:45:19.343085UTC.
- Все source dates находятся междуFRSTTRADE/LSTTRADE; все8expiry до2026.
- Credentials не передавались публичномуISS; дваapim requests использовали только
  существующееservice environment и pinnedCA. Redirects/новыепокупки отсутствуют.
- Current static descriptions не доказывают полную original publication/revision chain.
  Не делался вывод о dealer net gamma, экономической величине pinning или profitability.
- Signals, model fits, simulated/live trades:0; CAGR/Sharpe/MDD/PnL:null.
  Stage2/goal_verified/economic_admission:false. Не прибавлятьV88 кeconomic screens.

## Следующий конкретный шаг

1. До нового source-value/economic use зафиксировать отдельный metadata join protocol.
2. Сначала оценить число действительно нужныхSECIDs по **NULL-маске** OI исходного
   source, не читая величиныOI/страйков/цен и не выбирая успешные годы/контракты.
   Missing rows остаются в coverage denominator; наличие будущих labels не критерий.
3. Для необходимого корпуса получить точныеdescription fields с explicitexpiry,
   option type, units и underlying identity. Сохранять unmapped/conflicting записи;
   не распространять даты восьми примеров на все страйки без доказательства связи.
4. Если join даёт достаточное causal coverage, отдельно запечатать один дешёвый
   reported-OI pinning screen с control и1x/2xcosts на существующем futures ledger.
   Не строить новый trading engine и не считать OI наблюдаемой позицией дилеров.

В14:45UTC обаarchive units подтвержденыactive/running с прежнимиPID1663880/2522946
и invocation IDs. Их конфигурации, root, token, Windows tasks и расписания не менялись.
Новогоvolume census не было; последний полный замер находится вV87result.
Воронка остаётся25economic screens:21rejected+1incomplete+3invalid,0Stage2.
Цель относительно предсказуемых20–50%годовых пока не достигнута.
