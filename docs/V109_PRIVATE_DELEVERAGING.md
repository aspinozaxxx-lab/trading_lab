# V109 — сокращение частного обеспеченного посредничества

2026-09-17, Stage1, до числовых magnitudes/directions нового источника и PnL.
Предыдущий goal turn — PROGRESS: V108 завершён, отвергнут, проверен и сохранён.
Это новый information set, не перенастройка GSCPI, H.41 reserve balances V99
или CFTC commercial positioning V106. Цель устойчивых 20–50% остаётся прежней.

## Одно правило, один контроль

Заёмные средства и кредитование дилеров под nominal US Treasuries в uncleared
bilateral repo: general/specified collateral ×3 maturity buckets на каждой стороне.
Оба totals ниже собственных значений четыре weekly reports назад → SI long0.9;
иначе cash. Пять полных отчётов с положительными totals и одной schema era;
Decimal sums/comparisons. Control: постоянный SI long0.9 при той же готовности.
Нет fit, parameter search, выбора знака/актива/окна после результата или promotion control.

Сокращение частного посредничества может сопровождать дефицит долларового
финансирования. Но [исследование ФРС](https://www.federalreserve.gov/econres/notes/feds-notes/primary-dealers-behavior-during-the-2007-08-crisis-part-ii-intermediation-and-deleveraging-20170628.htm)
показывает, что matched-book может сокращаться без распродажи активов. Это работа
с confidential dealer-level2007–2009, не доказанный public aggregate predictor MOEX.
Client demand, venue substitution, quarter-end management и санкции/capital controls
могут полностью разрушить связь с USD/RUB. Не измеряем капитал, solvency или defaults.

## Источник и metadata-only discovery

Federal Reserve Bank of New York, [Primary Dealer Statistics](https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics),
[API](https://markets.newyorkfed.org/static/docs/markets-api.html),
[Terms of Use](https://www.newyorkfed.org/privacy/termsofuse). Private research с
attribution/notices, без confidential microdata, public redistribution или purchases.

Default dictionary содержит1539описаний только SBN2024, не всех historical eras.
Official JS ведёт к historical menu; найдены six schema eras, включая5Jan2022
и3Jul2024. Некоторые чужие total descriptions выглядят несогласованными и не
используются. Не склеиваем broad totals и не восстанавливаем капитальный framework.
У всех12выбранных ключей одинаковые menu paths/labels в SBN2022/SBN2024. Несмотря
на это, сравнения через break маскируются. До2022venue breakdown не подставляется.
Это соответствует [описанию изменения FR2004](https://www.federalreserve.gov/econres/notes/feds-notes/insights-from-revised-form-fr2004-into-primary-dealer-securities-financing-and-mbs-activity-20220805.html).

Root `source_evidence/dealer_metadata_20260917_v1`, три immutable subroots:

| Subroot | Captured GETs | Completed UTC | Manifest SHA256 |
| --- | ---: | --- | --- |
| capture | 6 | 02:55:57.723393 | 7e5cd3b435efa2c4cb372a2bb7f869239c87f99a36bc973b06da0cda2762eee9 |
| menu | 2 | 03:00:39.280300 | 997b12c7ff7168a782aa21a9bfa74661ebc509ae878475fba638b40e08f5dde2 |
| source | 1 | 03:05:34.589049 | 754b9c8e84b192a48d4a8382d3a29df6ed637c83387d9b5230078accad61c82a |

Bounded GETs, no redirects/retries/auth. Предварительные read-only HTML/JS/menu
просмотры не включены в эти captured request counts. Research units UID999 без
EnvironmentFile; main AlgoPack service не менялся. Original PIDs1952053/1968527/1985451,
invocations f479c3d3f6f64dd2afaa1cee9bdb97ba / c764e6bd52314b8ca89600b28ed8d495 /
c9c691553c354be5be330f383a473c56; running и successful journals наблюдались.
Три raw/script identities сохраняются в started.json; scripts входят в economic seal.

`source/financing.json`:129820bytes,SHA
`84d5c6bc8d4562bb50866730b90dc3fe0084233b1ac029d6afbf129db7dea658`.
Official frontend date-bounded request2022-01-05…2025-12-31/12keys;209Wednesday rows,
2508lexical numeric cells, no missing. Before seal только schema/dates/types/counts,
не величины, суммы, directions или новый PnL. Response current-vintage, не release archive.

Availability: конец observation-date+10calendar days NewYork, исходя из обычного
following-Thursday обновления и holiday allowance. Это явное **conditional** допущение,
не observed original release/receipt/revision chain. 207eligible reportsJan5,2022…
Dec17,2025; clocksJan16,2022…Dec28,2025 UTC. Dec24/31 values исключаются до inspection.
Готовность модели ниже207: initial4reports и4reportsпосле schema break маскируются;
zero aggregate тоже unready. Настоящие individual zeros допустимы. Missing cells не
заменяются нулём, entire missing weekly row/schema/duplicate/nonfinite/negative
amount вызывает fail closed. Никакой более старой good-state подстановки.

Local backups14+6+4files verified,21artifacthashes+3manifests. Archives outsideGit:
capture68170bytes/SHA66550ca817e728f68a127f103b021c6ca7fecbc1ef01df2706bb576e38e7da65;
menu434356bytes/SHA84991b4cb7f34ea12b2229ddd41845f7a60331139088939533eaaacb843fc961;
source14068bytes/SHA2a6a98e4f2bbab626f247dca213759487b7f7c23c4c00400f147749345717cd2.
Никаких source failures; один formatting warning исправлен до первого metadata запуска.

## Исполнение, критерии и ограничения

Полный2022–2025calendar, initial cash/masks не удаляются. Старый V72/V78/V64 EOD→
next factual open integer ledger, capital1mRUB, weight0.9, grosscap1, marginbuffer2,
participation1%, cashinterest0; costs1tick/1xfee и2ticks/2xfee. SourceTTL21days,
decision→fill<=7days, no2026market. Source начинается2022 по структуре данных, не
по выгодной доходности. Development история уже видена, не independent holdout.

Все4scenarios executioncomplete/critical0/unresolved0/terminalflat. Primary при
обоихcosts: CAGR>=5%, Sharpe>=0.5, MDD<=25%, trades>=20, >=3positiveyears/4,
worstyear>=−15%, meaningful excess>=2pp; readiness>=80%. Порог5% только для
компонента, не замена требуемым20–50%. Все outcomes/trades/rolls/years публикуются.
Stage2 только при заранее объявленном PASS; никаких post-outcome repairs-to-promote.

28new/113combined synthetic tests PASS3.27s, Ruffclean; real metadata/source identities
и15futures byte/schema/date checks PASS до numeric read. Следующий шаг immutable
seal + commit/push, server tests и один economic run/audit/backup. Без demo/live,
расширения AlgoPackeconomic scope, нового collector framework или model training.
