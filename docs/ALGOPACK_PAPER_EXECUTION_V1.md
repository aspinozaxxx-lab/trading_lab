# AlgoPack fixed paper execution V1

2026-09-07. Pre-outcome правила первой пары price-only/price+flow. Новая экономическая
проверка ещё не запускалась; F=null. [Training hypothesis](ALGOPACK_PAPER_TRAINING_SPEC_V1.md)
не меняется: прогноз следующего60min interval. Числа ниже выбраны до новых outcomes,
не оптимизированы по доходности и не являются брокерским тарифом/гарантией исполнения.

## Сделка и капитал

Два независимых виртуальных счёта по1млн RUB: это масштаб бумажного опыта, не заявленный
капитал пользователя. Каждый10min forecast сохраняется, но по одному asset/arm может
быть только одна открытая позиция. Нет суммирования шести перекрывающихся ставок,
пирамидинга, смены направления внутри позиции или переноса между контрактами.
Long/short определяется знаком прогноза; entry=E+10min, exit=E+70min. Outlier
abs(log forecast)>0,25 отклоняется, а не обрезается до удобного значения.

Basis для размера — min(current marked equity,1млн). На новый asset выделяется максимум
25%basis по условному номиналу и10%basis по начальной марже, также не больше свободной
маржи. Количество целое, без скрытого дробного фьючерса. Дополнительно не больше10%
видимого объёма лучшей стороны котировки. Номинал price×STEPPRICE/MINSTEP; LOTVOLUME
повторно не умножается. Portfolio runner ещё обязан обеспечить aggregate reservations,
актуальную marked equity/free margin, no duplicate pending intents и блокировку новых
входов при unresolved позиции. Сам pure core не хранит счёт и не доказывает эти условия.

Плановый выход только по времени, без подбора stop/take thresholds. Это первая fixed
execution model для проверки информационной добавки потока, не обещание ограниченной
просадки. Риск гэпа/короткой позиции/неисполненного выхода сохраняется.

## Издержки и допуск сигнала

Expected move на контракт: mid×abs(expm1(prediction))×STEPPRICE/MINSTEP.
Estimated roundtrip cost: полный текущий spread в RUB +2 adverse ticks +2×(exchange
BUYSELLFEE + broker scenario3RUB). Требуется expected move строго больше2×estimated cost.
Broker3RUB/contract/side — явно условный сценарий; пользовательский тариф ещё неизвестен.
Missing exchange fee запрещает вход; известный0fee не считается missing.

В моделируемом FOK исполнении покупка по ask+1tick, продажа по bid−1tick. Количество
зафиксировано до будущей entry-котировки: падение доступной глубины даёт no-fill,
а не пересчёт размера задним числом. На entry повторно проверяются nominal/margin limits.
FOK/10%depth — предположение симуляции; видимая ликвидность не гарантирует фактическое
исполнение. Результат всегда conditional paper, execution_admitted=false.

Два cost scenarios применяются к ОДНИМ и тем же сделкам:1× и2× суммы фактического
моделируемого crossing/slippage и fee. Сценарий2× не выбирает иной набор сигналов.
Gross mid, friction, fee и оба net сохраняются раздельно. Конверсия STEPPRICE/MINSTEP
должна совпасть на entry/exit; изменение даёт unresolved, не произвольный RUB PnL.
Налоги, реальный брокерский тариф и реальные fills пока не подтверждены: такие net
нельзя называть подтверждённым доходом пользователя после всех расходов.

## Причинное исполнение и оставшийся source gap

Forecast должен быть durable и фактически прочитан до создания intent; intent должен
быть durable строго до entry. Fill использует отдельный запрос, начатый не раньше
соответствующей границы entry/exit и intent publication. Никакого исполнения по уже
увиденному future bar open. Окно fill — первые30сек после границы; старше5сек quote
и старше30сек contract terms отклоняются. Quote date должна быть verified, exact SECID
сохраняется; expiry day, crossed/off-tick quotes не допускаются.

План требует известную к decision непрерывную официальную session, содержащую entry
и exit+30sec. Crossing clearing/session gap не допускается. Runtime обязан обновлять
calendar/source admission; dataclass Session не является доказательством происхождения.

Сверены [official realtime field descriptions](https://moexalgo.github.io/docs/description/realtime/)
и [official session calendar](https://moexalgo.github.io/docs/api/calendar-iss-calendars-futures-session/).
Book UPDATETIME содержит время без даты, SEQNUM документирован как opaque identity;
existing market-core exchange_date_verified=false нельзя просто переключить в true.
Marketdata описывает SYSTIME/TRADEDATE и BBO/depth: это кандидат отдельного датированного
source adapter, но соответствие полей и account entitlement ещё не проверены actual
request. Не читать его до complete activation/F. Quote date/session proof остаются
обязанностью нового reader, не выводятся из synthetic tests.

Если entry нет — явная причина отказа, без сделки. Если exit нет — unresolved позиция
остаётся в портфеле и блокирует новые входы. Её нельзя исключить из equity, считать
закрытой по старой цене или занулить return. Durable state machine, mark-to-market и
handling recovery ещё не реализованы этим pure module.

## Готовность

Pure make_intent/simulate_fill/close_trade и28synthetic tests реализованы. Нет CLI,
таймера, HTTP, портфельного ledger или executable evaluation. До новых цен необходимо
добавить dated quote/session source, ledger/evaluation/runtime и единый byte seal.
Следующий шаг — эти реальные недостающие части, не переобучение или повторный source audit.
