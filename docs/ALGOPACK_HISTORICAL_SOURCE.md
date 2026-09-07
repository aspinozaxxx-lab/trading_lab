# AlgoPack — исторический FO источник, подключение 2026-09-07

Пользователь сообщил о покупке подписки и явно разрешил использовать предоставленный
API key. Прежнее откладывание покупки и отсутствие credentials больше не актуальны.
Агент не оформляет новую подписку, не меняет тариф/автопродление и не подключает брокера.
Цель 20%/50% остаётся непроверенной: подписка открывает источник, а не гарантирует alpha.

## Секрет и область использования

Ключ установлен через скрытый SSH-ввод в `/etc/trading-lab/collector.env` на
`gpu-mlserver`; имя переменной `MOEX_ALGOPACK_TOKEN`, файл `root:trading-lab 0640`.
Значение не помещается в Git, local `.env`, аргументы команд, manifest, raw или journal.
Читать и логировать разрешено только наличие/статус, не JWT payload, личные поля или key.
Штатные server timers не перезапускались. Два собственных orphan installer процесса,
оставшихся после прерываний SSH до ввода, завершены; это не остановка collectors.

Технический GET доступ проверяется отдельно от сообщения о покупке. HTTP 200 сам по себе
недостаточен: нужны ожидаемая схема, правильный день, контрактные идентификаторы и полный
cursor. Право на личное хранение/ML и revision semantics не доказываются bearer token;
сохраняется отдельный запрос MOEX, но его нельзя дублировать по умолчанию.

## Официальная API-схема и ловушки

- [Авторизация](https://moexalgo.github.io/docs/api/algopack-api/): Bearer header,
  только `https://apim.moex.com` для authenticated route. Redirect/другой host запрещены.
- [FO TradeStats](https://moexalgo.github.io/docs/api/get-fo-tradestats/): весь рынок
  `/iss/datashop/algopack/fo/tradestats.json?date=2024-10-15&latest=0`;
  OBStats — аналогичный dataset route.
- [Контрактный route](https://moexalgo.github.io/docs/api/get-fo-tradestats-for-ticker/)
  использует SECID и `from/till`, не underlying symbol и не `date` по аналогии с рынком.
  `latest=1` — последняя пятиминутка, а не полный день; для истории не использовать.
- Cursor содержит `INDEX/TOTAL/PAGESIZE`. [Официальный пример загрузки](https://github.com/moexalgo/moexalgo/blob/main/samples/download_algopack_data.ipynb)
  использует `start`, но пример EQ не заменяет проверку поведения FO на sample.
  Задержка 0,5 с — наш консервативный интервал, не установленная договорная квота.
- В [OpenAPI](https://moexalgo.github.io/openapi/openapi.yaml) `tradetime` описан как
  время сделки, `SYSTIME` — время системы. Это не доказательство начала/конца bucket,
  первой публикации или журнала исправлений. Пример может иметь SYSTIME много позже
  tradedate. Историческая доступность остаётся unresolved, retrieval сохраняется.
- Не выводить response examples OpenAPI: среди них есть рыночные строки 2026 года.
  В техническом исследовании subagent случайно увидел такие примеры; они не использованы
  для выбора признаков/параметров или оценки. Не заявлять, что весь thread pristine unseen.
- Отдельного FO OrderStats в проверенных меню/OpenAPI нет; наличие equity-метода не
  доказывает FO entitlement. Не объявлять отсутствие продукта по одному HTTP-ошибочному GET.

Существующий `moex_forward_microstructure_source` **не запускать** для этой задачи:
он запрещает даты до 2026, использует latest=1 и не делает полный historical cursor.
Frozen forward guard и его schema/availability нельзя ослаблять для нового sample.

## Первый source-only протокол: контрактный инвентарь одного дня

`configs/moex_algopack_fo_historical_inventory_v1.yaml` фиксирует `2024-10-15`,
два набора TradeStats/OBStats и только поля
`tradedate, tradetime, secid, asset_code, SYSTIME`. Нет цен, объёмов, targets или PnL.
Рыночные числа не нужны, чтобы сначала установить фактические SECID и asset aliases.
SI/RI/BR/MIX нельзя автоматически подставлять вместо конкретного фьючерса: например,
документация отдельно различает контракт RIM4 и asset_code RTS.

До запросов: отдельные config/code SHA, commit/push и synthetic tests. Сбор — только
`gpu-mlserver`, immutable external output, secret reflection guard, без fallback на
unauthenticated/latest route. Все страницы обоих наборов проверяются по cursor,
дате, уникальному `(dataset,secid,tradedate,tradetime)` и фиксированной схеме.
Raw-to-normalized replay нужен сверх hash/row-count checks. Source-only admission не
даёт model/PnL/live admission, даже если все технические проверки зелёные.

После полного metadata inventory: запечатать отдельный flow/depth sample с фактически
найденными контрактами четырёх underlying, затем историю 2020–2025 и causal time rules.
Лишь после пригодного источника фиксировать экономический тест новой информации:
aggressive-flow/depth imbalance против price-only baseline, реалистичные costs и
исполнение. Агрегаты 5 минут не восстанавливают очередь и не доказывают passive fills.

Canonical run/текущие counts — [STATUS.md](STATUS.md), общий журнал —
[EXPERIMENTS.md](EXPERIMENTS.md). Незавершённая индексная ветка сохранена как prototype,
не запечатана и не запущена; сейчас приоритет имеет оплаченный пользователем AlgoPack.

Pre-request identity: config SHA
`47b78865c891e3631acf1e97b89175533c42443224af102e25c34785925c86cf`, closure SHA
`5e3b01bad972fa06123ae99754ea1578d3cacf4446e06d4a66c52ba6c3543cc8`.
Local closure check без сети пройден; targeted synthetic/legacy/encoding slice 45/45,
в том числе новый inventory 20/20 и индексный parser 18/18. Ruff clean.
Индексные временные synthetic fixtures перенесены из нестандартного pytest-каталога
во внешнее test_scratch; frozen encoding tests не менялись.

## Application-scoped TLS recovery — 2026-09-07

Первый service launch остановился до сети: `/srv/trading_lab_data/data/processed`
root-owned, новый child `algopack` ещё отсутствовал. Создан только этот child с owner
`trading-lab`, без chmod/chown остальных данных. Второй launch не получил HTTP-ответ:
TLS verify code 19, self-signed certificate in chain; validated pages 0, raw не сохранён.
Это не отрицательный ответ о подписке. Failed diagnostic сохранён отдельно, canonical
inventory не опубликован; sealed code/config не менялись.

MOEX [объявила переход на НУЦ](https://www.moex.com/n103530?nt=107) 20.08.2026.
Её [официальный SDK](https://github.com/moexalgo/moexalgo/blob/f596a066e9939fa50db441a0417902875d95748c/moexalgo/_tls.py)
добавляет Russian Trusted Root CA локально для приложения с сохранением TLS verification.
Используется [сертификат из закреплённого commit](https://raw.githubusercontent.com/moexalgo/moexalgo/f596a066e9939fa50db441a0417902875d95748c/moexalgo/certs/russian_trusted_root_ca.crt):

- PEM 2057 bytes, SHA `aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399`.
- DER SHA `d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31`.
- Public CA path `/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem`, не API key.
- `scripts/prepare_algopack_tls_v1.py`: verified HTTPS download без Authorization,
  оба hash проверяются до использования; существующий сертификат не перезаписывается.
- После no-auth TLS/hostname probe только конкретный transient AlgoPack service получает
  `REQUESTS_CA_BUNDLE` с этим файлом. System trust, shared collector.env и остальные
  collectors не изменяются. `verify=False`/отключение hostname check запрещены.
- TLS transport — явно записанная операционная зависимость; query/schema/source closure
  `5e3b01bad972...` остаётся byte-identical. До такого recovery было 0 source pages.

## V1 actual access and V2 metadata correction — before V2 collection

После TLS recovery оба dataset route подтвердили authenticated HTTP 200. V1 получил
и провалидировал все TradeStats: 15 023 строки, 16 страниц. Первая OBStats остановила
strict parser: metadata-only diagnostic обнаружил 19 отсутствующих asset_code на
1 000 строк; остальные проверки SECID/date/time/SYSTIME/duplicate не дали аномалий.
OBStats cursor `[0,65550,1000]` сообщает заявленный total, не completed coverage.
Canonical V1 не создан. Failed staging `.moex_algopack_fo_historical_inventory_v1_yhft9uwr`
под external algopack root сохранён (16 validated pages, failed response не сохранён).
Не выдавать его за canonical: полная per-page provenance не была опубликована.

V1 closure `5e3b01bad972...` остаётся неизменным. Отдельная V2 с новым config/code/output
исправляет только source metadata contract: `asset_code=None` и `""` сохраняются
буквально, добавляются `asset_code_missing` и `missing_asset_code_rows` по dataset.
Числовые коды, missing SECID, неправильные даты/времена/схема/cursor по-прежнему fail.
Не удалять строки, не заменять нулём и не выводить отсутствующий alias по SECID.
Source-only, current-vintage, original availability unresolved, historical/live false.
V2 closure включает frozen V1 helper dependency, config/sidecar/tests/init/pyproject
и pinned TLS preparation helper. До API — review, synthetic tests, commit/push.

V2 pre-request config SHA
`6dcd660c252b9b653e5bcaf67881e1143de00f1041175f68f7f372f889b95293`, closure SHA
`1da8655bf03da09c5c6670951d3acb9acfc77536e48f9b0f9e38aae3439d09f4`.
Local targeted 73/73 (V2 28/28), Ruff clean, complete closure verified без сети.
Staged diff check отметил один cosmetic blank EOF в sealed V2 module; оставлен
без изменения frozen bytes. Это не ошибка тестов или source schema.

Независимый metadata-only active-map check существующего V36 source на sample date:
effective 2024-10-15, decision/observed_through 2024-10-14; SI=SiZ4, RI=RIZ4,
BR=BRX4, MIX=MXZ4. Source SHA
`40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823`,
`/srv/trading_lab_data/data/processed/futures_v5/development_panel_2018_2025_active_contract_map.parquet`.
Цены/объёмы/returns не читались. Actual API asset aliases и совместное покрытие этих
SECID установить после полного V2 replay; не считать внутренние SI/RI/MIX API aliases.

## V2 canonical result

Pre-request commit `31bfc79`; server synthetic 28/28, один service run 64,4 s, exit0.
Canonical `/srv/trading_lab_data/data/processed/algopack/moex_algopack_fo_historical_inventory_v2_1da8655bf03d`.
Manifest SHA `89896f3a1647db6a7d1c794cc98745dec48123a4dbe6355baccfac2d8894f242`;
inventory SHA `34b473d3035c03e9ee9076eb929db4953ad16bd2ba8f95e99d51972751a392b9`.
Отдельный read-only raw replay audit 11/11. TradeStats 15 023 rows / 16 pages /
284 SECID; OBStats 65 550 / 66 / 384. Missing asset_code 0 / 1 218, все сохранены.

| SECID | API asset_code | TradeStats rows | OBStats rows | Shared time keys |
| --- | --- | ---: | ---: | ---: |
| SiZ4 | Si | 163 | 174 | 163 |
| RIZ4 | RTS | 163 | 174 | 163 |
| BRX4 | BR | 163 | 174 | 163 |
| MXZ4 | MIX | 163 | 174 | 163 |

У этих четырёх missing asset_code=0. TradeStats 10:00–23:50, OBStats 09:05–23:50;
11 OB-only timestamps у каждого не означают 11 наблюдений нулевого trade flow.
Не подбирать часы или universe по будущему PnL; это только source coverage.

## Следующий source-only протокол: four-contract flow/depth sample V1

Config `moex_algopack_fo_flow_depth_sample_v1.yaml` фиксирует тот же день и четыре
SECID из предыдущей active-map identity; parent inventory path/seal/manifest pinned.
Per-contract TradeStats/OBStats route использует `from/till`, latest=0, full cursor.
Общие metadata5 плюс TradeStats `trades,trades_b,trades_s,vol,vol_b,vol_s,val,val_b,val_s,disb`;
OBStats `spread_l1,spread_l10,levels_b,levels_s,vol_b_l1,vol_s_l1,vol_b_l10,vol_s_l10`.
OHLC/VWAP/returns/OI/IM не загружаются; derived features и экономические расчёты запрещены.

Проверки: numeric finite/null, bool/string fail, count nonnegative integral (2.0 допустим
и сохраняется), средние depth/levels не обязаны быть целыми. Spreads/disb допускают
знак; negative counts явно диагностируются, не скрываются. Null и реальный 0 различаются.
Полный raw replay, per-field missing/zero/negative counts, отдельное сравнение ключей
каждого dataset с parent; совместное TS/OB покрытие не требует равенства их множеств.
Расхождение parent/source означает coverage failure, не автокоррекцию или удаление.
Retrieval записывается, available_at=None, original_version_verified=False; historical
model/live false даже при source coverage PASS. Артефакты только во внешнем server root.

Семантика по [официальным FO-полям](https://moexalgo.github.io/docs/description/supercandles/#фьючерсы)
и [методологии](https://moexalgo.github.io/docs/method/supercandles/): число сделок,
контрактные/лотовые объёмы и рублёвый оборот разделены на buy/sell. Точный алгоритм
классификации агрессора ещё не подтверждён, поэтому buy/sell не объявлять доказанным
aggressive flow. spread_l1 указан в bps; единицы spread_l10 и depth FO уточнить отдельно.
Общий метод описывает знак disb, но точную FO-формулу/zero-volume treatment не угадывать.
Ни SYSTIME, ни пятиминутная сетка не доказывают момент первой публикации/ревизии/очередь.

После пригодного sample следующий source scope — 2020–2025, exact contracts из
причинного active map, не сегодняшние активные серии. Дешёвый будущий economic screen
должен сравнивать одну модель price-only и ту же модель с flow/depth, плюс заранее
фиксированный контроль. Проверяемый механизм — дисбаланс потока при недостаточной
встречной глубине и последующее краткосрочное движение. Это пока проект, не sealed
эксперимент и не разрешение вычислять labels/returns. Результаты прежних V32/V35 не
использовать для настройки часов, thresholds или нового universe.
Frozen `curve_regime_intraday.simulate_next_open_portfolio` — возможный reused ledger,
не разрешение запустить старый experiment runner. Десятиминутные OHLCV/active-map/
spec-proxy identities уже перечислены в `futures_v32_curve_regime_intraday.yaml`.
До economics отдельно pin-ить transitive data/code, trade clock, execution/costs,
expanding train/test и честный статус current-vintage diagnostic. Искусственный лаг
не превращает неизвестное first-publication time в подтверждённую PIT историю.

Sample pre-request config SHA
`1817e7b63bd97e0ff674ee8e4c340aa84d376a9aebb0c1adc542307a12af4580`, closure SHA
`49502b17c35a3739b24000c5ef0bed7fd6795cbc024f6cbd263f1b55914bd33d`.
Local targeted 110/110, включая sample 37/37; Ruff clean; независимый static review
не нашёл critical defects. Parent hash/replay проверяется ещё раз на сервере до сети.
Sample V1 не рассчитывает total-vs-buy/sell discrepancies; это отдельная последующая
source-quality проверка, не уже пройденный численный gate.

Metadata-only план расширения проверен на gpu-mlserver с active-map SHA выше: период
2020-01-03..2025-12-30, 1 519 дат × 4 актива = 6 076 плановых asset-day строк.
По SECID: BR 72, SI/RI/MIX по 25, всего 147. Missing/empty metadata и duplicate asset-date
нет; decision_date=observed_through<effective_date (1–5 календарных дней). Каждый SECID
образует непрерывный участок active-map. 147 min/max диапазонов × 2 dataset = 294
задания до пагинации; вариант contract-year — 334, подневный — 12 152.
Это покрытие плана, не доказанные торговые дни или наличие flow/depth; tradability и
рыночные значения не читались. Контракты с expiry-суффиксом 6 допустимы лишь для
наблюдений строго до 2026; нельзя отсеивать/допускать строку только по имени контракта.

## Flow/depth sample V1 canonical result

Pre-request commit `09ac39f`; server tests 37/37. Один bounded transient service на
gpu-mlserver завершён за 6,1 s, exit0; постоянный новый collector не включён.
Canonical `/srv/trading_lab_data/data/processed/algopack/moex_algopack_fo_flow_depth_sample_v1_49502b17c35a`.
Manifest SHA `6a14b3f9c724725375e99363e2ed26ae247b9e52e6bb1d4a9523e7ac11749502`;
sample SHA `9621c3a1d6d88e71068838c7d949e7e64695fed3681a03af85c1685b9694772c`.
Отдельный raw replay audit 11/11. 8 pages: 652 TradeStats и 696 OBStats, всего 1 348.
Все 8 contract/dataset combinations точно совпали с parent по ключам/asset/SYSTIME;
`sample_coverage_admitted=true`. Missing/extra/revised keys=0, shared163 на контракт.

Качество числовых данных не сводится к этому флагу. У каждого контракта spread_l1 и
spread_l10 имеют по 2 null: 09:55 и 10:00. Первый ключ OB-only, второй shared TS/OB;
следовательно даже объединённая строка не доказывает доступность всех признаков.
Остальные selected numeric fields без null на данном sample; true zero buy/sell
counts встречаются и сохранены. Отрицательный disb допустим по определению, не ошибка.
Никакие значения/часы/инструменты по ним не подбирались, rows не удалялись.
Source technical PASS означает доступ/формат/воспроизводимость, не economic signal.

Следующий разрешённый шаг — новый resumable source-only historical collector 2020–2025
на byte-pinned active-map contract ranges, с по-request provenance, rate pacing,
новыми code/config seal и external outputs. Не расширять frozen sample CLI/config.
После source quality — отдельный заранее зафиксированный economic diagnostic;
original availability, личные ML rights и exact execution остаются отдельными gates.
