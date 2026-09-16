# V100 — второй уровень проверки V99, до новых стресс-результатов

Предыдущий goal turn — PROGRESS: V99 завершён и стал первым Stage1-кандидатом.
Цель остаётся относительно предсказуемые20–50% годовых. V100 не новая стратегия
и не новый элемент счётчика32гипотез: это проверка единственного прошедшего кандидата.

## Что уже известно

V99 дал6.86%/6.82%CAGR,просадку22%,пять положительных лет из восьми, но отрицательные
2024/2025. Геометрическая годовая доходность2018–2021~12.98%,2022–2025~1%.
Поэтому проверка сохранения исходного5%компонентного порога на каждом четырёхлетнем
отрезке уже ожидаемо не пройдена. Этот критерий записан ПОСЛЕ знакомства с baseline;
нельзя объявлять его неувиденной OOS-проверкой или новым неожиданным провалом.
Новые результаты latency/stress-cost и monthlydependence сV49ещё не рассчитаны.

## Фиксированный пакет

Базовую стратегию, source corpus,3monthlookback,monthlyfirstrelease,0.9gross,
40dayTTL,3dayfill expiry и daily integer ledger не менять. Базовые четыре расчёта
не перезапускать: брать canonical ledgers и проверять их cash/cost/metric/source identities.
Новых portfolio ledgers ровно12:

| Сценарий | Дополнительная задержка доступности | Издержки | Варианты |
| --- | --- | --- | --- |
| cost_stress | 0 дней | 4 ticks / 2× fee | primary + control |
| delay1 | 1 календарный день | base + double | primary + control |
| delay7 | 7 календарных дней | base + double + stress(4ticks/2×fee) | primary + control |

До seal synthetic test показал, что прежний ledger принимает только1/2/4ticks и
1×/2×fee. Первоначально предложенный3ticks/3×fee заменён штатным4ticks/2×fee stress;
это pre-outcome compatibility decision, без изменения ledger или чтения новых PnL.

Задержка — дополнительные24часа/7×24часов к доступности КАЖДОГО monthlymessage
и baseline. Originalrelease/observation dates не менять. Сообщение о недопуске тоже
приходит с задержкой; предыдущий state может оставаться известным только до исходного
TTL. Это не пересмотр цифр и не скрытый выбор более удачного дня. Задержки могут
откладывать не только вход, но и выход; risk carry не исключать из результата.
Для каждого сценария применяются неизменённые Stage1 gates и полный pairedcontrol.

## Время, зависимости и решение

Для всех arms/costs показать все5перекрывающихся четырёхлетних отрезков2018–2021
...2022–2025 и все8leave-one-year-out геометрических годовых результатов. Они
считаются из соответствующего пути: не сброс капитала/размера на границе года,
не стратегия, умеющая пропускать плохой год. Известный2018снулём не удалять.

Для baselinebase/double сравнить60месячных доходностей2021–2025 с соответствующей
V49combinedNAV. НуженDecember2020anchor, ни интерполяции, ни нулевого заполнения.
Показать корреляцию, все месяцы с убыткомV49, средний результат и число положительных
месяцевV99 в них. Это ex-post описание, не торговый switch и не разрешение смешать
стратегии/выбрать веса. V49 включает модельный cash yield и другой riskbudget, а
полеexact_futures_nav дублируетcombinedNAV; не использовать его как pure trading.

ConditionalStage2PASS требует всех исходных Stage1gates во всех новых стрессах и
не менее исходных5%годовых в КАЖДОМ четырёхлетнем baselineblock при обоих costs.
Последний критерий уже известен как слабое место; новые стресс-результаты сохранять
полностью независимо от его исхода. Executionfailure => INVALID_STAGE2_EXECUTION,
любая экономическая слабость => REJECT_STAGE2_ROBUSTNESS. Возможный PASS только
кандидат кStage3проверке источников/исполнения, не live/демо/достижениецели.

32гипотезы уже проверялись на переиспользуемой истории; этот пакет не даёт поправленной
на все испытания статистической уверенности. Временные отрезки пересекаются, результат
post-selection,не independent holdout и не прогноз вероятности заработка.

## Проверки и границы

Config/code/tests/этотprotocol SHAдо новых стрессов/корреляций. V99source/run manifest
и V49manifest/ledger SHA/bytes фиксированы. V49date-only preflightдо NAV:1272строки,
2020-12-30..2025-12-30. TransitiveV99/V64closure и существующие recentmarket declarations.
Каждый новый и baselineledger: source<=decision<fill, cash continuity, daily cash
identity, order/ledgercostagreement, performance/annual/count replay, <=2025границы.

Никаких новыхHTTP/sourcecollectors/моделей/движков/2026marketoutcomes/брокера/покупок/
credentials/Windowscollectors. MainAlgoPack не менять, broader scope не расширять.
OriginalH41receipt/revisionchain и exactbrokerPIT всё ещё не доказаны; временной
сдвиг этого не исправляет. При отрицательном итоге закрыть V99 как непрошедший
Stage2, не подбирать sign/window/asset/size/control и не повышать плечо.

До seal:9новых/85combinedsynthetictestsPASS7.80s,Ruffclean. Проверены clock-only
delay/nextopen, полный stress roster, все временные блоки, monthlyalignment/null,
отказ при2026/пропуске/невалидномNAV и строгий cash/costreplay с обнаружением
подменённого startingcash. Стресс-экономика и корреляции ещё не выполнялись.
