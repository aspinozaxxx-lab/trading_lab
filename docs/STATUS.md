# Текущее состояние исследования

Обновлено: **2026-09-02**. Период разработки ограничен данными не позже
`2025-12-31`; данные 2026 для текущих V8–V38 гипотез защищены и не используются.

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
`1,2689/1,2478/1,2273`, MDD `17,3235%/17,4244%/16,7796%`, worst year
`+0,9087%/+0,4820%/−0,4482%`. Относительно V39 Sharpe улучшен на
`0,0174/0,0161/0,0083`, MDD — на `2,7087/2,7348/2,6553 п.п.`, worst year — во всех
сценариях; все CAGR выше 20%, primary имеет 5/5 positive years. Все пять presealed
gates true, verdict `GO_TO_FORWARD_PORTFOLIO_CONFIRMATION`.

Это сильнейший текущий вариант для цели «не менее 20% более предсказуемо», но не
доказательство live и не 50%: оба market-parent используют overlapping history, V39
adaptive, cash-carry не имеет historical bid/ask execution, idle-yield instrument не
верифицирован. Веса/50% RUONIA/DTE/signal после результата не менять. Следующий шаг —
forward-синхронизация V39, cash-carry quotes и фактической доходности разрешённого
cash instrument; live false.

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

### Fixed idle-fund pool — SEALED before values, implementation ready, 0/60 pairs

Чтобы не привязывать V41 к одному LQDT, до чтения котировок зафиксирован пул
`LQDT/SBMM/AKMM/TMON` с exact ISIN/ПДУ. Source SHA `37a3baeb...`, seal `ac299a7`.
Два среза 15:49/15:59 сохраняют BID/OFFER, лучшую/общую depth, lot/minstep,
settlement и clocks всех четырёх фондов; неполный фонд делает snapshot invalid.

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

Forward V39 V1 уже запечатан SHA `3677bcca...`, commit `ba9bbb1`; joint readiness
commit `24a41b6` raw-replay проверяет оба существующих source и не вычисляет signal/PnL.
Текущее состояние: option weekly levels `1/54`, V27 official CLOSE `0/253`, invalid
option/futures snapshots `0/0`; paper economics и CAGR reporting false. После обоих
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

Tasks `TradingLabV27ForwardExecution` (10:05 мск) и
`TradingLabV27ForwardDecision` (23:45 мск) имеют status `Ready`. Paper contract SHA
`d68f0595...`/commit `51acd4c` и fail-closed preflight `05a1f74` также опубликованы
до первого snapshot. В нём 252 return sessions требуют 253 common official CLOSE;
partial current week не считается завершённой. Сейчас 0/253 price warmup,
0/504 unseen evaluation. До завершения warmup PnL запрещён; до 504 evaluation sessions
никакая короткая annualization не является доказательством 20–50%. Полный порядок:
[FORWARD_V27_PROTOCOL.md](FORWARD_V27_PROTOCOL.md).

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

### P0 — forward-подтверждение V41 cash-carry sleeve

1. Не менять V41 80/20, 50% RUONIA, DTE 30–90, times, cashflow haircut или costs.
2. Проверять tasks `TradingLabForwardCashCarryDecision` (15:49) и
   `TradingLabForwardCashCarryFill` (15:59), затем paired readiness. Сейчас 0/60
   discovery, 0/20 calibration, 0/60 unseen evaluation.
3. Invalid/sleep snapshot не считать парой; не заменять missing BID/OFFER/clock нулём.
   Anonymous ISS не доказывает latency, size, queue или fill.
4. Параллельно получить byte-pinned broker fee/margin/order-log и конкретный
   cash/MMF/REPO instrument rule. Без них даже успешный quote-forward остаётся paper.
5. LQDT выбран как отдельный idle-only challenger, source SHA `15fb471a...`, seal
   `8ae3dc3`. Запустить tasks 15:49/15:59 и paired readiness; не считать его залогом,
   не читать iNAV без подтверждения лицензии и не строить PnL до 60 пар.
6. Канонический discovery count для V41 — joint depth admission `8183eb50...`, а не
   отдельные quote counts. Дата проходит только при 10 stock/futures depth gates,
   positive LQDT depth и same-stage skew `<=30s`.
7. Проверять `TradingLabForwardFundPoolDecision/Fill` и readiness фиксированного пула
   LQDT/SBMM/AKMM/TMON. До 60 пар не вычислять spread ranking, yield или PnL; состав
   пула после первого значения не менять.

### P0 — независимая forward-проверка V27

1. Не менять parent V27 SHA `7a9a44cf...`, horizons `21/63/126/252`, STLFSI4 `0`,
   key rate `20%`, 2x, RUONIA haircut `50%`, buffer/cost/capacity.
2. Каждый следующий сеанс проверить обе scheduled tasks и
   `v27_forward_validation_readiness`; invalid snapshot не считать в coverage.
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
2. Проверять task `TradingLabForwardMoexRms` и readiness; сейчас 0/60 discovery.
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
   pushed. Task `TradingLabForwardCnyRelativeValue` имеет status `Ready`, следующий
   запуск `2026-09-02 18:30`, затем Mon–Fri. Сейчас 0/40 discovery, 0/20 calibration,
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
