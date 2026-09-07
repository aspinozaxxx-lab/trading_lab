# AlgoPack FO witnessed V1 — отдельный forward source

## Назначение и текущий статус

Новый target-free источник для последующей проверки добавочной информации
TradeStats/OBStats. В отличие от [истории 2020–2025](ALGOPACK_FO_HISTORY_V1.md),
он должен сохранять свидетельствуемое время получения каждой версии ответа.
Сбор данных не является экспериментом с доходностью, backtest или live trading.

**Manual PASS; timer enabled, automated captures ещё проверяются.** Config SHA
`feecf891fd501849795615e1c0432c184c41b2125d99acd69a1b2f2b33b50605`;
7-file closure `67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26`.
Pre-request commit/push `7cd5371`; Linux regression343/343 и runtime seal PASS.
Актуальный runtime и завершённые результаты — в [STATUS.md](STATUS.md).

Pre-request local regression: 341 passed / 4 Windows-only symlink/lock skips
(весь AlgoPack FO set и encoding). Новые source tests: 69 passed / 1 Linux skip.
Ruff и closure verification PASS. Это проверки synthetic fixtures, не market result.

Manual capture: `20260907T115659545856Z_b813c3346d94`, 2026-09-07
11:56:59.545856–11:57:12.184771UTC. 4865rows/16pages, TS2329/OB2536,
55files/303925 stored bytes. Current SECIDs: BRV6/BRX6, MXU6/MXZ6, RIU6/RIZ6,
SiU6/SiZ6; это metadata expiry selection, не оценка ликвидности.
Canonical root `/srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1/`,
manifest SHA `d0e031f1e03599aa72cb0d9d1d84a78742e373bb574195918693363cd596d740`.
Встроенный full replay и отдельный PrivateNetwork audit PASS. Manual handle58685
terminal success; не запускать повторно ради нового результата. Timer включён
11:58UTC, active/waiting; фактические scheduled captures12:03/12:13UTC ещё не проверены.
Manual invocation `3d7cf776d635412697993bc714972f62`, PID1930498 (завершён).
Installed unit hashes совпадают с pushed bytes:
service `64906d427f8fc20ca1264b7e201b4774063001aa9bf3255e72dbbb5d2920dd55`,
timer `bf382fe4db6aead21da08b2f9a91c05f3e2bd9a8f48de5e92ee01c09d236bbf6`.
Ни код, ни config/seal после первого запроса не менялись.

Audit без ключа/сети:

```text
/opt/trading_lab/.venv/bin/python -m market_lab.futures.moex_algopack_fo_witnessed_v1 --seal-sha256 67a11050689b42802b1f33797a98c47ef9974249803de72601c2b8dffb099c26 --audit <exact-capture-directory>
```

Не передавать `--output-root` вместе с `--audit`. Проверять manifest SHA и receipt
перед downstream admission; никакие economic permissions этим audit не выдаются.

Отдельный модуль: `market_lab.futures.moex_algopack_fo_witnessed_v1`.
CLI: `--seal-sha256 <зафиксированный SHA>` и
`--output-root /srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1`.
Параметр `--storage-root` у этого интерфейса не предусмотрен.

## Metadata discovery и фиксируемый universe

Discovery использует только official RFUD и series metadata: идентичность инструмента,
базового актива, тип контракта и даты истечения. Никаких цен, marketdata, объёмов,
ликвидности или выбора по результатам. Карта активных контрактов 2025 года не подходит.

Для BR/MIX/RI/SI выбрать ближайшие два подтверждённых outright futures. Оба выбранных
срока истечения должны быть строго позже текущего московского дня `D`. RFUD и series
должны согласоваться; неоднозначность, недостаток подходящих контрактов или missing
required metadata означают fail-closed/неполное покрытие, не выдуманный SECID.
Точные поля, aliases, фильтры и tie policy должны совпадать с новым sealed config.
Сохранять metadata responses и выбранный план с собственной receipt provenance.

Удержание ранее выбранных, но уже вышедших из ближайшей пары контрактов **не обещано
в V1**. Без такой реализации overlap относится только к текущему discovery set:
после roll возможна потеря поздних revisions старого контракта. Это ограничение
coverage, не разрешение восстановить исторический выбор сегодняшним universe.

## Предложенное окно и пагинация

Зафиксированное окно: календарные даты `[D−2, D+14]`, где `D` определяется явно в
`Europe/Moscow` в начале capture. Для каждого exact SECID и dataset — per-contract
FO route, `from/till`, `latest=0`, `iss.only=data,data.cursor` и закрытый список полей.
Все страницы проходят schema, identity, request-date, cursor и duplicate checks.
Missing numeric fields сохраняются с mask, не превращаются в нулевой flow/depth.

Такой overlap позволяет повторно увидеть пятиминутные записи между соседними
десятиминутными опросами; `latest=1` для этого не подходит. Но он не гарантирует
доставку при длительном простое, поздней публикации вне окна или отсутствии контракта
в новом discovery set. Пустой ответ является записью о полученном ответе, не
доказательством отсутствия торгов и не набором нулевых наблюдений.

Верхняя граница включает будущие календарные **метки**, а не будущие наблюдения:
ответ получен сейчас. Это конечный запас для next-trading-day labels выходных и
праздников, не доказательство полного календаря. Vendor tradedate/tradetime не
сдвигаются; SYSTIME не обязан быть позже их конкатенации. [MOEX описывает](https://www.moex.com/n92862)
выходную сессию как часть следующего торгового дня. Эта общая информация не доказывает
семантику каждого поля Super Candles. Новое окно не разрешает чтение prices/outcomes.

Изменение TOTAL во время pagination означает incomplete capture. Не склеивать
страницы разных attempts в якобы атомарный vendor snapshot. Ограничить pages,
transport retries и общий runtime; schema/auth failures не обходить другим route.
V1: не более 8 страниц на job, 8 MiB декодированного ответа, 420 секунд на capture,
0 retries и пауза 0,5 секунды между запросами. Публичная metadata TLS проверяется
обычным CA bundle; pinned Russian CA используется только на apim.moex.com.
Следующий slot создаёт новую попытку, а не переписывает прежние raw или failure evidence.

## Receipt, validation и неизменность

У каждого ответа должны быть собственные request-start, response-completion и
validation-completion timestamps в UTC, exact safe request identity, schema/cursor,
raw byte hash и связь с capture/plan. Один timestamp в начале общего batch не является
временем получения его последующих ответов. Wall-clock consistency проверяется;
скачок часов не исправляется скрытым переносом timestamps.

Raw/provenance и normalized records (deterministic gzip JSON) публикуются атомарно в отдельный immutable
capture directory после проверок. Не перезаписывать ранее полученную версию того же
ключа. Сохранять повторные наблюдения и изменения содержимого, incomplete staging
и безопасную failure evidence отдельно от complete output. Не прошедшее закрытый
schema whitelist тело не архивируется; ранее проверенные страницы/receipts сохраняются.
Один собственный advisory
lock защищает writer; lock-файл сам по себе не доказывает живость процесса.

`SYSTIME` остаётся vendor system timestamp. Он не доказывает первую публикацию,
отсутствие revisions, конец пятиминутного bucket, exchange latency или исполнение.
Потенциальная forward availability всех версий в capture — общий `available_at`
после полного raw/normalized replay, не раньше индивидуальных receipts/validation.
Это не разрешение считать их известными в прошлом. Даже при неизменном TOTAL серверная
атомарность нескольких страниц не доказана: `vendor_atomic_snapshot_proven=false`.
Если downstream требует завершённый бар, его completion semantics проверяется
отдельно, не выводится из одного факта receipt.

Source-only остаётся true; historical model eligibility, original-version proof и
live permission остаются false. Price/return/label/target/PnL columns запрещены.
Новый collector не ослабляет protected-2026 правило для рыночных outcomes.
Для будущей модели всё равно нужны отдельный economic seal, causal admission,
разделение inference/labels, проверка издержек и доказуемого исполнения.

## Изолированный service и timer

Definitions находятся только в `deploy/algopack_fo_witnessed_v1/`:

- `trading-lab-algopack-fo-witnessed-v1.service` напрямую вызывает новый модуль;
- `trading-lab-algopack-fo-witnessed-v1.timer` срабатывает круглосуточно каждый день
  в `:03/:13/:23/:33/:43/:53 UTC`, `Persistent=false`, без randomized delay.

Это acquisition cadence, не утверждение о расписании торгов. Service работает как
`trading-lab:trading-lab`, timeout 8 минут, `Restart=no`, `MemoryMax=1G`,
`CPUQuota=100%`, `TasksMax=64`, `Nice=10`. Одновременные timer activations одного
oneshot не создают второй writer; отдельный lock нужен также для ручного запуска.
После пропуска slot не назначается фиктивное старое receipt time.

`ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges` и `UMask=0077`;
единственный явно writable persistent root:
`/srv/trading_lab_data/data/forward/algopack-fo-witnessed-v1`.
Исходная история, её locks, другие forward roots и код не должны изменяться.

Token только в обязательном `/etc/trading-lab/collector.env` (root:trading-lab 0640),
только Authorization header. Не печатать env, headers, response body, raw exception
или credential в journal; не передавать token в CLI. Никаких broker endpoints/orders.

Application-only `REQUESTS_CA_BUNDLE`:
`/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem`.
Ожидаемый SHA-256 PEM:
`aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399`.
Новый module/config preflight обязан проверить bytes: одна env-переменная этого
не обеспечивает. TLS и hostname verification обязательны, redirects запрещены;
не менять global trust и не использовать `verify=False`.

## Порядок deployment и наблюдения

1. Завершить metadata review, synthetic tests и новый source seal; commit/push до
   первого persisted response. Зафиксировать границу acquisition до первого capture.
2. Сверить SHA в service. Не создавать self-referential seal, включающий
   собственное значение через unit; финальные deployment bytes фиксировать отдельно.
3. Проверить точные destination paths и создать только новый ordinary output root с
   владельцем trading-lab и private mode. Передать exact новые файлы из pushed commit.
4. Установить только два новых unit; выполнить Linux `systemd-analyze verify` и
   `systemd-analyze calendar` для явного UTC расписания. Сделать `daemon-reload`.
5. Пока новый timer выключен, один manual service capture и его replay/quality audit.
   После PASS включить только новый timer и проверить две фактические activations.

**Не запускать `scripts/install_linux_collectors.sh` для этой установки:** он
переустанавливает общий service template и перезапускает все старые timers.
Не менять frozen `ops.forward_collector`, прежний microstructure module или 15
существующих timers. Локальные Windows `TradingLab*` tasks остаются выключены.

Проверять конкретный unit через `systemctl show` (ActiveState/SubState/MainPID/Result/
ExecMainStatus) и его safe phase/count journal. Observation timeout не является
разрешением запустить второй процесс. После остановки или failure учитывать реальные
missed slots и late receipts; не выдавать восстановленные сегодня ответы за старые
independent forward observations. Аварийный откат ограничен новым timer/service.

## Структурная нагрузка и ограничения

144 slots/сутки. Для `C` контрактов и двух datasets число запросов примерно
`144 × C × 2 × pages_per_request`, плюс discovery и retries. При восьми контрактах
и одной странице это 2304 запроса/сутки; это расчёт схемы, не измеренный расход API.
Overlap повторно передаёт уже виденные строки. Payload bytes, subscription quota,
скорость endpoint и достаточность memory/runtime должны проверяться отдельно.

Нет обещания полного охвата пяти минут, полного revision archive, известных
торговых часов, PIT истории или доходности. Следующие gates определяются по
фактическим safe coverage/latency/failure evidence, а не по наличию включённого timer.
