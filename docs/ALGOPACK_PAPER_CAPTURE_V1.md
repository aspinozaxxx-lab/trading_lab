# AlgoPack activation + packet capture V1

2026-09-07. Соединение [market source](ALGOPACK_PAPER_MARKET_SOURCE_V1.md) с
[immutable journal](ALGOPACK_PAPER_JOURNAL_V1.md) и [inference](ALGOPACK_PAPER_INFERENCE_V1.md).
Actual activation/config/bundle ещё НЕ созданы, F=null, реальные HTTP requests0.

## Полный допуск до запроса

`algopack_paper_activation_v1.load_activation` требует pinned
`configs/algopack_paper_forward_v1.activation.json`, bundle `.seal.json`, config `.json`
и sidecar. Эти имена — интерфейс будущего runtime, не существующее разрешение.
Bundle обязан содержать capture/market/journal/inference/model/alignment, execution,
evaluation и runtime code, authorization, а также transitive training44 и witnessed
source7 closures без изменения родителей. Включение имени файла не является проверкой
качества экономической модели; её собственные tests/protocol всё равно обязательны.

Activation содержит exact model manifest SHA, paper-only scope, publication clock и F;
config future_start остаётся null, actual F берётся только из отдельной immutable activation.
F на Moscow midnight, строго после training/declared/publication clocks. Дополнительно
mtime/ctime ВСЕХ deployed файлов должны быть раньше F: старой декларации недостаточно,
если код/activation фактически скопированы позднее. Учитывать Linux clock/filesystem
assumptions, не менять frozen chmod/bytes после F. No live/broker authority.

`VerifiedActivation.request_ready()` повторяет checks перед КАЖДЫМ запросом и требует
actual now>=F. Metadata inspection с require_started=false не выдаёт request permission:
последующий request_ready всё равно WAIT до F. Source не использует придуманную F для
проверки подписки. Production registry отсутствует, поэтому сейчас positive admission невозможен.

## Полный пакет

`algopack_paper_capture_v1.capture_packet`:

1. Проверяет activation, резервирует immutable STARTED source event до HTTP.
2. Получает только closed RFUD/series metadata через неизменённый witnessed transport;
   выбирает ближайший из двух validated outright contracts каждого BR/MIX/RI/SI.
   Metadata selection не использует цены/объём; expiry day исключён.
3. Для каждого exact SECID получает current-day candles до пустой terminal page,
   затем orderbook/specs. Максимум22responses,120сек и spacing0,5сек, без retries.
4. Каждый валидированный response отдельно replay-ится и записывается в journal с
   исходными bytes (base64), SHA, normalized projection и request/response/validation clocks.
5. Перечитывает сохранённые ответы, проверяет hashes, exact URLs/date/identity/cursors,
   chronology, normalized==raw replay, выбранный plan и соответствие spec expiry.
6. Только после полного replay публикует COMPLETE packet с response references и aggregate.

При сбое остаются STARTED, все ранее сохранённые responses и короткий FAILED phase;
raw exception/headers/token не записываются. Нет COMPLETE packet и нет скрытого retry.
Пустой торговый день допустим как14responses без ценовых строк, не как нулевая цена.
COMPLETE означает structural source packet, не official-session/freshness/fill admission.
Vendor atomic snapshot по нескольким HTTP responses не доказан.

`observe_packet` повторно проверяет final journal event, каждую response reference и
полный aggregate replay; usable available_at — фактический clock ПОСЛЕ этих проверок.
`model_inputs` переносит этот clock в ContractPlan/PriceBar и возвращает journal source
reference для forecast writer. Exact internal contract ID включает asset/SECID/last-trade-date.
Дата свечи не становится временем доступности. Вложенные source normalized records
сохраняют available_at=null: последующая observed версия имеет отдельную common availability.

## Проверки и ещё необходимая работа

Synthetic registry tests подставляют fake parent hashes только внутри fixtures; source
integration использует fake HTTP и замоканный request_ready. Это НЕ actual permission
и НЕ тест прав аккаунта. Проверяются отсутствующая activation, неполная economic closure,
changed code, late deployment, pre-F request refusal, packet corruption/order/cursor,
empty-day coverage и source→model clock mapping. Linux integration проверяет full fake
capture→per-response journal→replay→COMPLETE→observe и сохранение partial failure.

Далее нужно соединить witnessed flow input с новым market packet, выполнить реальную
инференс-цепочку на synthetic end-to-end fixtures и реализовать fixed execution/evaluation
runtime. После этого — единый pre-outcome config/seal/activation, deployment до F и
автоматический post-F запуск на gpu-mlserver. Не создавать production registry раньше.
Брокер/тариф для комиссий запрошены у пользователя неблокирующим вопросом; ответ ещё
не получен. До него не выдавать assumed broker costs за подтверждённые реальные комиссии.
Доходность20%/50% всё ещё не подтверждена; actual forecasts/trades0, модели не переобучались.
