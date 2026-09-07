# AlgoPack future-paper market source V1 — parsers and bounded transport

2026-09-07. Продолжение [inference core](ALGOPACK_PAPER_INFERENCE_V1.md).
Реализованы request/parser и HTTP primitives. Это НЕ запущенный collector и НЕ полный
future admission. F=null, price requests0; нет CLI/timer/environment loading, actual
account entitlement не проверялся. [Разрешение](ALGOPACK_PAPER_AUTHORIZATION_20260907.md)
требует source/code/model/execution/evaluation seals до будущих prices/outcomes.

## Конкретное назначение

Новым моделям нужны завершённые10m свечи, а проверке прибыли — наблюдаемые котировки и
спецификации. Anonymous ISS candles с15мин задержкой не подменяют authorized apim
real-time; источник и timestamp нельзя заменить после того, как выяснится отсутствие
прогнозов. Нет новой гипотезы/переобучения, это необходимый data/execution adapter пары.

Официальные первоисточники:
[candles route](https://moexalgo.github.io/docs/api/get-futures-candles/),
[orderbook route](https://moexalgo.github.io/docs/api/get-futures-orderbook/),
[field reference](https://moexalgo.github.io/docs/description/realtime/).
Доступ конкретного аккаунта и наблюдаемую задержку подтвердит только post-F capture,
не наличие страницы API. Новые покупки/запросы до F не разрешены этим документом.

## Request scope

`algopack_paper_market_core_v1.RequestWindow` требует aware UTC-compatible clocks:
F строго после training completion и на московскую полночь; actual request>=F.
Причина midnight rule — запрос candles from/till=current local date захватывает весь
день. Частичная внутридневная F без доказанного server datetime-filter могла бы открыть
защищённые часы. F всё равно назначается только после ВСЕХ будущих seals/publication,
не выводится из сегодняшней даты и не берётся из synthetic fixtures.

URL генерируется для exact BR/MIX/RI/SI outright SECID, только HTTPS apim.moex.com,
RFUD, три endpoints: candles, orderbook и securities для specs. Closed `iss.only` и
columns whitelist; no marketdata/LAST/PREVPRICE extras. Candles interval10, from=till
текущий Moscow day, start0..144, limit500. Ни backfill до F, ни другой host/route/asset.

## Source interpretation

- Candles: begin/end сначала проверяются по ВСЕМ строкам, до numeric interpretation.
  Только текущий local day, >=F, <=receipt,10m begin grid, end в пределах interval,
  strict ordering/no duplicates. OHLC/volume numeric finite/nonnegative либо None;
  отсутствующие/некорректные OHLC и ещё не завершившийся interval остаются masks.
  Short page не означает автоматически completion: окончание candle pagination требует
  явную пустую страницу, максимум3страницы и144bars/day, без повторов между страницами.
  Future runner обязан контролировать actual start offsets и source identities каждого
  HTTP response; helper сам этого не делает и не доказывает vendor atomic snapshot.
- Orderbook: exact board/SECID/side, документированные20levels на сторону, unique
  side/price, finite nonnegative fields, opaque integer SEQNUM, canonical UPDATETIME.
  Empty/one-sided/missing/zero/locked/crossed/mixed-version books отмечаются явно.
  Geometry best bid/ask не является разрешённым fill. UPDATETIME не имеет даты;
  SEQNUM не декодируется самовольно как дата. exchange_date_verified=false и
  execution_admitted=false даже для согласованного положительного стакана.
- Specs: exact identity, expiry dates, LOTVOLUME/MINSTEP/STEPPRICE/INITIALMARGIN/BUYSELLFEE.
  Известная0fee отличается от None; missing, expiry day, nonpositive required spec
  остаются unresolved. Broker fee неизвестна и не подставляется0. Margin/stepprice
  snapshot не доказывает их применимость к будущему exit либо historical period.

Нормализованные записи содержат response_completed_at, но available_at=null.
Получение/парсинг не выдаются за durable source publication. Будущий publisher обязан
закончить все schema/hash/replay checks и атомарную запись, затем фиксировать actual
available_at, не раньше всех receipts/validation. До этого inference не допускается.

## Transport primitive

`algopack_paper_market_transport_v1.capture_response` вызывается только будущим runner,
который ПЕРЕД входом проверил полный activation seal. Сам helper не доказывает seals.
Он проверяет future request scope, credential shape и pinned application CA SHA;
не читает env/ключ самостоятельно. Timeout<=30s и общий monotonic deadline,2MiB cap,
redirects=false, exact response URL,0retries/no anonymous fallback. Token передаётся
только в Authorization. Bad status/size/clock/schema/reflected secret означают короткий
enumerated failure, без body/headers/raw exception. Между ответом и validation сохраняются
отдельные clocks; timestamp в начале общего будущего batch не является его available_at.

Успех helper: VALIDATED_NOT_PERSISTED, available_at=null, execution=false. Ничего на
диск не пишет и timer не включает. Capture persistence, locks, incomplete-attempt journal,
metadata discovery, full raw replay и per-capture commit ещё должны быть реализованы.
Collector только на gpu-mlserver; Windows допускает лишь code/synthetic tests.

## Проверки и следующая работа

70новых synthetic tests: window/routes, schema/time projection, incomplete candles,
pagination terminal, quote geometry, missing fees/specs, HTTP TLS/redirect/status/size,
pre-F no-request, secret/error suppression, clock discontinuity и CA byte tampering.
Первый тест oversized response имел слишком длинный autogenerated pytest ID; тестовый
стенд исправлен короткими explicit IDs, данные/экономический протокол не менялись.

Следующее: full sealed activation/capture runtime и durable forecast writer, затем
fixed source/calendar/freshness/execution/evaluation rules с costs1x/2x и полным учётом
sleep/unresolved. До готовности единого admission F=null; не вызывать transport с
придуманной F ради проверки доступа. Никаких historical AlgoPack PnL или real trades.
Текущий authoritative runtime/test status смотреть в STATUS, не повторять старое обучение.
