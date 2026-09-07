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
