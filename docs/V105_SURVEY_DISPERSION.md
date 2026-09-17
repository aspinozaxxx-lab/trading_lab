# V105 — contraction of GDP forecast disagreement

Stage1, один новый information-set screen, research only. Протокол фиксируется до
новых numeric quartiles, states, targets и outcomes; уже просмотренная2021–2025
история не становится независимым holdout. V21 median-revision rule не меняется.

## Механизм и границы утверждения

Проверяем: сокращение разногласий о будущем росте экономики может снижать требуемую
компенсацию за этот риск и поддерживать оценку акций. Это наше предположение о знаке
медленного эффекта, не установленный вывод литературы. Сигнал может быть уже учтён
ценой задолго до разрешённого консервативного времени использования.
[Haase/Neuenkirch, CESifo10720](https://www.ifo.de/en/cesifo/publications/2023/working-paper/macroeconomic-expectations-and-state-dependent-factor-returns)
рассматривают forecast dispersion как отдельную информацию о risk premia и отмечают
зависимость эффекта, включая знак, от состояния экономики; это не репликация их VAR
или подтверждение российского индексного timing.
[Zarnowitz/Lambros](https://www.nber.org/papers/w1171) различают disagreement между
прогнозистами и субъективную uncertainty отдельного прогноза. Нельзя их отождествлять.

## Данные и novelty

Готовый CBR current-vintage source2021–2025: четыре artifact hashes и manifest
в `configs/v105_survey_dispersion_v1.json`, transitive futures bytes в V101/V64seal.
Metadata-only review:37survey months,36available before2026; GDP p25/p75 есть у всех36,
35пар с непосредственно предшествующим survey и тем же targetyear. Числовая
пригодность пока не проверялась. Raw workbook не парсить заново; новыйHTTP не нужен.
На сервер можно перенести пять уже сохранённых sourcefiles с проверкойSHA/nonoverwrite.

В отличие от V21, median/average не читаются как values. Используется ширина
распределения прогнозов ВВП, не направление их центральной оценки, новый channel
или sign flip старого signal. Никакой смеси с V49/V60/другими стратегиями.

`available_at` неизменно23:59:59МСК последнего дня следующего после survey месяца.
December2025rows доступны толькоJanuary2026: исключаются Arrowpredicate ДО загрузки
числовых values. Прогноз ВВП2026, сделанный и доступный2025, не является фактическим
рыночным исходом2026. Все рыночные цены/labels/returns2026 остаются запрещены.
Original historical vintages/receipt не доказаны; current workbook conditional
development admission не повышается. Redistribution не проверена, raw внеGit.

## Единственное правило

Current targetyear = surveyyear+1. `IQR = p75-p25`, percentagepoints. Сравнить с IQR
непосредственно предыдущего survey для ТОГО ЖЕ targetyear, в том числе прежним
year+2 при смене calendar year. Первый survey не имеет comparison. Missing/nonfinite/
invertedquartile -> newest state unready; не искать более ранний хороший predecessor.
ZeroIQR допустим; равенство или ростIQR -> cash. Если обаIQRvalid и current<previous,
longMIX0.9; иначеcash. Controlconstantlong0.9 на том же readiness/fillcalendar.
Оба направления вычисляются только после availability. Sourceidentifier URLfragment
survey=YYYY-MM создан для evidence/counts, это не отдельныйHTTP или originalvintage.

`source_date` = localconservativeavailabilitydate; survey_month и previous clocks
сохраняются отдельно. TTL70calendar days, decision→fillgap<=7. Causal EOD decision
V72 и следующий factualopen, нет samebarfill. Новейший unready release гасит старый
сигнал; terminalflat. Unavailable начало2021 остаётся в полном календаре какcash.

## Исполнение и отбор

Прежний V78/V64 integer daily ledger, initial1mRUB, signalgross.9/riskgross1.0,
marginbuffer2, participation1%, base1tick/1xfee и double2ticks/2xfee, cashinterest0.
Spec/fee/margin proxies не broker-exact. Halt/missing/carry/unresolved не удалять.
Нет fitting/train/calibration/seeds/normalization/search; purge не применим.

Stage2толькоесли allfour executioncomplete/critical0/unresolved0/terminalflat,
readyfraction>=.8, primary обаcosts CAGR>=5%, Sharpe>=.5, MDD<=25%, >=20trips,
>=3positiveyears из2021–2025, worstyear>=−15%, excessCAGRovercontrol>=2pp.
Точные gates сохранены в config и прежнем evaluator. ИначеREJECT_STAGE1, при
executionfailure INVALID_EXECUTION_NO_PROMOTION. 5%component gate не цель20–50%.
Control не продвигать после outcomes; no sign/quantile/horizon/asset/threshold/
weight/expiry/cost/period tuning. При провале новая информация/механизм, не V105v2.

## Проверки и отчёт

Synthetic tests: exactyear pairing, yearroll, clock, equal/zero/inverted/missing IQR,
immediate-predecessor missing mask, newer-source causality, median irrelevance,
protectedavailability Arrowfilter, delayednextopen/TTL/planmask/terminalflat,
flatpricecost-only ledger и tamper rejection. Доrun byte/schema/date-only preflight,
immutable code/config/tests/protocolseal, commit/push. Один serverrun безcredentials.

Сохранить source_states, обаtargets,4orders/positions/ledger, allmetrics/annual/costs,
coverage/trips/usedreleases и counterflags. Auditstates/targets/SHA/cash/annual/counts;
это не независимая реконструкция каждого riskcounter. Reports STATUS/EXPERIMENTS,
fullcanonical и backup внеGit. Roundtrips с rolls не35independentobservations.

Меняющийся состав участников, механическое сужение fixed-year горизонта, округление,
только35updatepairs и поздняяavailability ограничивают интерпретацию. Ни revised
history, ни developmentPASS не доказательство будущей прибыли. MainAlgoPackarchive
не прерывать; scopeнерасширять, TICpaused,V104closed, no live/demo/Windowscollectors.
