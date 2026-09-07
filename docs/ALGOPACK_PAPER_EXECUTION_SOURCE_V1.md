# Paper execution dated BBO/calendar source V1

2026-09-07. Новый source adapter, родители market/book/training/execution не изменяются.
Production activation/config/seal отсутствуют, F=null, actual source HTTP requests0.

## Что получает источник

Один exact paid RFUD/security response с двумя closed blocks: marketdata BBO/depth/
TRADEDATE/SYSTIME/UPDATETIME/SEQNUM и securities с уже фиксированными specs columns.
LAST/OPEN/PREVPRICE/SETTLEPRICE и иные outcome/history fields не запрашиваются.
Перед numeric interpretation проверяется date/clock projection: canonical TRADEDATE
равна current requested Moscow day, SYSTIME в ту же дату, UPDATETIME с этой датой
не позже SYSTIME/receipt и не раньше F. Несовпадение, null или datetime вместо
TRADEDATE date отклоняется. Документированный пример TRADEDATE неоднозначен, поэтому
не вводится молчаливый fallback или угадывание формата после numeric read.

Это дата записи vendor BBO, не независимое доказательство фактического fill. В новом
Quote поле exchange_date_verified означает согласованность ТРЁХ полей этого dated
record. Старый undated orderbook не меняется и не получает такое право. BIDDEPTH/
OFFERDEPTH используются как заявленная видимая глубина в conditional paper proxy;
реальная исполнимость и единицы фактического аккаунта ещё не проверены post-F запросом.
Execution всё равно проверяет5сек quote freshness,30сек specs freshness и сохраняет
execution_admitted=false. Missing/zero/crossed поля дают mask, не нулевой fill.

Calendar endpoint filtered from=till=current day, closed session_schedule и его types.
Поля расписания: дата/SECID/board/type, interval/update timestamps, settlement/clearing
markers. Unknown type отсутствующий в dictionary, future publication или неверный
interval отклоняют source. До3страниц, не более1000rows, обязательная empty terminal;
dictionary/day должны совпасть, duplicate rows запрещены.

В Session принимается единственный applicable period с точным title «Основная торговая
сессия» или «Дневная торговая сессия» из возвращённого type dictionary. Type code не
угадывается по подстроке. Другой title не считается regular; фактический список titles
аккаунта ещё не наблюдался. При overlapping/general/specific/unknown period — no session.
Clear/settlement marker обрезает конец известного интервала: после marker возобновление
не предполагается без отдельного известного regular period. Не угадывается длительность
клиринга. Это conservative coverage rule, не доказательство live trading status.

Источники описаний: [official realtime reference](https://moexalgo.github.io/docs/description/realtime/),
[official calendar reference](https://moexalgo.github.io/docs/description/calendar-iss/).
Calendar page прочитана напрямую с того же official host после отказа browser fetch.
Рыночный endpoint для этого не вызывался. Endpoint/calendar docs не доказывают entitlement.

## Transport, persistence и causal admission

Каждый fetch требует full activation и включение новых source/execution bytes в её
проверенный bundle. Затем post-F RequestWindow, exact route/identity/cursor; pinned CA,
10сек deadline/timeout,2MiB response cap, без redirects/retries/anonymous fallback.
Не принимается ambient session auth/trust_env. Token только из переданного runtime
параметра, env/credential tools модуль не читает. Error/body/secret reflection не выводятся.

Collector резервирует STARTED доHTTP, каждый validated raw response отдельно сохраняет
base64+SHA+receipt+normalized в immutable journal; partial failure сохраняется. Пакет
COMPLETE выдаётся после raw replay каждого response и проверки page closure. Consumer
повторно читает response records, проверяет hashes/chronology/cursors и полное совпадение
normalized с raw. Actual available_at — clock после consumer replay, не время vendor.
Quote/Terms/Session связаны с source journal SHA. COMPLETE не означает economic admission.

Нет CLI/timer, нет actual activation, нет установки F. Все actual requests только после
полного будущего runtime/evaluation/ledger seal. Parent F и закрытый старый2026 не ослабляются.
Локальные tests synthetic; Linux source→journal→observe→intent проверяется после push.

## Следующая работа

Durable portfolio state/reservations, mark-to-market, unresolved recovery и fixed
evaluation, затем combined runtime/config/seal/activation. Ни27synthetic tests, ни
официальный field reference не подтверждают20%/50% или фактическую доступность источника.
