# Запросы платных и лицензируемых данных

## Текущее действие — AlgoPack куплен пользователем, key установлен на сервере

Позднее 2026-09-07 пользователь сообщил о покупке и разрешил использовать переданный
API key. Он установлен через hidden SSH stdin в `/etc/trading-lab/collector.env`,
`root:trading-lab 0640`; значение не включать в Git/log/raw/argv. Агент не совершал
новых покупок, не менял тариф или автопродление. Historical FO TradeStats/OBStats GET
подтверждены: inventory V2 complete/audited за 2024-10-15, 15 023/65 550 metadata rows.
Позднее завершены four-contract sample и вся fixed history2020–2025: 294jobs,
2067949rows; отдельный full raw audit PASS и metadata quality report сохранены.
Date admission=false и original availability unresolved не скрываются; детали —
[history](ALGOPACK_FO_HISTORY_V1.md) и [quality](ALGOPACK_FO_HISTORY_QUALITY_V1.md).
Это не доказательство прав/качества для любого продукта или оригинальной доступности.
Работа: [ALGOPACK_HISTORICAL_SOURCE.md](ALGOPACK_HISTORICAL_SOURCE.md).

Исторические статусы ниже описывают предшествующие решения; отсутствие credentials и
откладывание покупки больше не блокируют технический доступ. Переписка MOEX остаётся
одной отправленной цепочкой, не дублировать. Права на конкретное личное ML применение,
historical first-publication и correction semantics не устанавливаются по JWT.

## История — запрос отправлен через Яндекс Почту 2026-09-07

Позднее 2026-09-07 пользователь отложил покупку AlgoPack и поручил другие гипотезы.
Оформление/оплата/API key/paid collector не продолжаются; новый приоритет — бесплатный
V64 по [STATUS.md](STATUS.md). Письмо остаётся отправленным, дублировать его не нужно.

Пользователь ответил «да, делай все что необходимо!!!» на конкретное предложение
отправить запрос MOEX без покупки подписки и подключения торгового счёта. Это разрешение
на обращение получено; не возвращаться к прежнему вопросу об общей авторизации запроса.
Стоимость, договоры, подписки и live trading по-прежнему не согласованы.

Подключённого инструмента отправки почты не обнаружено. Инструменты поиска/предложения
новых подключений из навыка plugin-management также не доступны; почтовый плагин не
устанавливался. Сначала подготовлена официальная
[форма обратной связи](https://www.moex.com/ru/feedback.aspx), но она не отправлялась:
не хватало контактов, требовались CAPTCHA и принятие соглашения. Затем пользователь
открыл свой почтовый аккаунт в Chrome, и обращение отправлено через Яндекс Почту.
Неотправленная веб-форма закрыта, её CAPTCHA/соглашение не выполнялись.

Подтверждение отправки: одно письмо найдено в папке «Отправленные», получатель
`algopack@moex.com`, тема «Тестовый доступ AlgoPack FO TradeStats/OBStats для личного
исследования», отображаемое время `01:00`. Адресат и тема проверены после отправки.
Нет вложений, CC/BCC или сообщения через второй канал. Личный адрес отправителя,
account UID и идентификаторы посторонней переписки в Git не записываются.
Это подтверждение отправки сервисом, не delivery/read receipt от MOEX.

Отправленная версия сохраняет содержание нижеследующего запроса и отдельно уточняет
диапазон `2020-01-01..2025-12-31`, исходную публикацию против последующих исправлений,
применимую оферту и запрет подключать платную подписку/автопродление. Письмо не содержит
результатов стратегий, приватного URL репозитория, серверных адресов или ключей.
Статус: `SENT_EMAIL_PROVIDER_CONFIRMED_AWAITING_VENDOR_REPLY`, не `ACCESS_GRANTED`.

Следующий шаг — ответ MOEX на эту конкретную тему. Не повторять запрос и не считать
автоматическое подтверждение лицензией или выданным test token. После ответа отдельно
проверить условия, стоимость, entitlement, historical coverage и clock/revision semantics.
Sample download, source seal и economic seal остаются отдельными последующими этапами;
право на переписку не является лицензией на данные. Покупку/акцепт платных условий
без нового конкретного разрешения пользователя не выполнять.

## Тариф AlgoPack PROMO — проверка 2026-09-07 после вопроса пользователя

Пользователь предложил подписку за 610 ₽, если она подходит исследованию. В живой
карточке [AlgoPack](https://data.moex.com/products/algopack) через браузер проверены
период «на месяц», название `PROMO` и цена `610 ₽`. Это полная рекламируемая подписка,
а не только визуальные графики: API/Python, Super Candles, FUTOI, онлайн стаканы,
свечи/сделки, HI2, Mega Alerts и машиночитаемый календарь. Начальный пакет отдельно
помечает Super Candles как «скоро» с T−1; не считать его уже доступной бесплатной заменой.

В карточке и [официальной документации](https://moexalgo.github.io/) для Super Candles
заявлены акции/фьючерсы/валюта, шаг 5 минут, история с 2020 года. История raw realtime
market data при этом не обещана. Пятиминутные агрегаты не восстанавливают очереди
лимитных заявок и не доказывают исполнение пассивной стратегии.

По составу это подходящий кандидат для месячного пилота нового flow/book источника.
Критерий полезности — фактическая история FO TradeStats/OBStats, проверенная схема,
времена доступности/исправлений и затем заранее sealed сравнение с price-only baseline
после costs; не рост числа перебранных параметров. Подписка сама по себе не является
доказательством достижимости доходности 20%/50% и не открывает broker trading access.

Нажатие «Оформить подписку» только открыло экран входа DataShop на официальном SSO.
Телефон/пароль не вводились, новый аккаунт и API key не создавались. Авторизация
передана пользователю. Платная оферта, итоговый checkout и автопродление за входом
ещё не проверены; списания/акцепта не было. Условную готовность оплатить 610 ₽ нельзя
считать разрешением на иные суммы, годовую подписку или рекуррентные платежи.

После входа: проверить конкретные условия личного использования и финальную сумму,
согласовать один месяц без автопродления; если право на хранение/личное ML неясно,
дождаться ответа на уже отправленное письмо. Не покупать корпоративный тариф по
умолчанию и не создавать/раскрывать token без отдельной авторизации. После подтверждения
доступа — source-only seal и технический sample, затем отдельный economic seal.
Все сборы/расчёты по-прежнему на `gpu-mlserver`; paid route пока не включён.

## P0 — AlgoPack и право на автоматическую обработку

Public delayed ISS достаточен для source discovery, но не даёт realtime timing,
best depth/queue и aggressive/cancel flow. Официальная AlgoPack-страница предлагает
подписку и описывает обновления вплоть до realtime/1m/5m. В ранних проверках публичные
сообщения указывали `600 RUB/month`; актуальная карточка 2026-09-07 показывает
`PROMO 610 RUB/month` с API и Super Candles, как зафиксировано выше. Отдельная страница MOEX
относит автоматическую обработку для algo trading/risk management к non-display use и
публикует тариф `7 500 RUB/month` за один рынок для резидента:

- `https://data.moex.com/products/algopack`;
- `https://www.moex.com/ru/products/nondisplay`.

Общие non-display/корпоративные расценки нельзя автоматически переносить на личный
AlgoPack, равно как маркетинговую карточку нельзя подменять конкретной офертой.
Неясность личного non-display обучения/сигналов без распространения и точного
состава FO TradeStats/OrderStats/OBStats вынесена в уже отправленный запрос
`algopack@moex.com`. До подходящих условий и credentials —
`SLEEPING_NO_CREDENTIALS_NO_SPEND`; токен в Git/log/raw не сохранять.

### Проверка официальной документации 2026-09-02

Повторная проверка `2026-09-03` уточнила лицензионную развилку. Действующий официальный
enterprise-тариф указывает `50 000 RUB/month` за внутреннее использование полного
AlgoPack до 10 логинов, тогда как публичная пользовательская визуализация рекламирует
подписку `600 RUB/month`. Это разные способы использования; дешёвая подписка сама по
себе не доказывает право на unattended non-display ML collector. Вместе с тем тариф
`50 000 RUB` нельзя считать обязательным для личного исследования: ниже приведено
уточнение области корпоративных условий от 2026-09-06. До подтверждения подходящих
условий MOEX, test token и отдельного разрешения пользователя покупки нет:

- `https://www.moex.com/media/tarify-na-informacionnye-i-tehnicheskie-uslugi-1.pdf`;
- `https://www.moex.com/ru/derivatives/open-positions-online.aspx`.

- MOEX ALGOPACK заявляет Super Candles с более чем 50 flow/book features, 5-минутным
  обновлением и историей с 2020 года. Официальный futures REST endpoint
  `/iss/datashop/algopack/fo/tradestats.json` требует подписку и при авторизации
  обслуживается через `apim.moex.com`.
- Futures-раздел документации явно перечисляет `tradestats` и `obstats`; в отличие от
  equity/FX menu, отдельного futures `orderstats` там нет. Generic Python API метод
  `orderstats` перечисляет, поэтому доступность и schema именно для `FO` остаются
  неоднозначными и должны проверяться test token/sample response, а не предполагаться.
- `tradestats` даёт aggressive buy/sell volume/trades/imbalance; `obstats` — BBO/deeper
  spread, levels, depth и book imbalance. Этого достаточно для заранее запечатанного
  cross-market neural timing challenger, но не для реконструкции полной queue priority.
- Официальный `Full_orders_log` — live FAST Gate option: unlimited-depth reconstruction
  и все cancel/move events, обязательный договор на биржевую информацию и текущая
  опубликованная доплата `21 000 RUB/month` сверх FAST access. Страница не обещает
  исторический архив; этот продукт нельзя считать backtest data без отдельного
  письменного подтверждения MOEX.

Минимальный следующий запрос: test token без автоматической покупки, один sample day
для SI/RI/BR/MIX по `tradestats/obstats` и письменное подтверждение non-display ML rights,
history start, pagination, revisions и наличия/отсутствия FO `orderstats`. Collector
`market_lab.futures.moex_forward_microstructure_source` уже реализован с target-free
closed schema и не сохраняет token. До credentials server timer для paid route не
включать; public delayed FUTOI не подменяет real-time microstructure.

Официальные страницы:

- `https://moexalgo.github.io/`;
- `https://moexalgo.github.io/docs/api/super-candles-фьючерсы/`;
- `https://moexalgo.github.io/docs/api/get-fo-tradestats/`;
- `https://moexalgo.github.io/docs/method/supercandles/`;
- `https://www.moex.com/a588`.

### Проверка после V63, 2026-09-06: доступ ещё не получен

Проверены только metadata/schema/hashes существующего server source, без чтения
рыночных значений. В `/srv/trading_lab_data/data/forward/moex-microstructure-v1/`
найден один manifest: `snapshot_20260901T214719330521Z`, source date `2026-08-18`,
retrieval `2026-09-01T21:47:19.330521Z`, `authenticated=false`. В нём четыре запроса
`futoi`, восемь normalized rows и ни одного `tradestats/obstats/orderstats` запроса.
Parquet schema соответствует FUTOI, а не потоку сделок/стакану. Manifest SHA
`8b781cb4eb1a03ff578f0886adbf586e6b0e7e043fd9d9c678bdb367a62f5324`;
read-only source audit 11/11. Это ограниченная проверка указанного каталога, не
доказательство отсутствия любого файла микроструктуры на всех дисках.

В `/etc/trading-lab/collector.env` отсутствуют непустые `MOEX_ALGOPACK_TOKEN`,
`EDISCLOSURE_API_LOGIN`, `EDISCLOSURE_API_PASSWORD`. Проверялось только наличие,
секреты не выводились. Готовый collector не означает наличие пригодной истории.

Уточнение официальных условий и возможного доступа:

- Раздел 34 [условий ИТО MOEX](https://www.moex.com/files/43sepmkqqv48p5et6mhhv58155)
  прямо описывает предоставление AlgoPack **юридическим лицам**. Нельзя переносить
  корпоративную стоимость на персональный API без проверки конкретной оферты.
  Это не заключение, что персональная подписка автоматически разрешает наше
  использование: [общие non-display условия](https://www.moex.com/ru/products/nondisplay)
  требуют отдельной проверки применимости.
- [Индивидуальное использование](https://www.moex.com/ru/products/personal) включает
  API и выгрузку по публичной оферте. Требуются именно условия персонального AlgoPack,
  а не предположение, что API означает только визуальный просмотр или все права на ML.
- На [странице MOEX](https://www.moex.com/a6341) по-прежнему есть ссылка на демодоступ
  AlgoPack. Но доступный индексированный текст старой
  [инструкции](https://fs.moex.com/f/20389/instrukcija-po-polucheniju-dostupa-k-demo-versii-p.pdf)
  предлагает продукт «Открытые позиции». Полный PDF при проверке web transport
  не получен. Действующий бесплатный доступ к SuperCandles и его историческому архиву
  **не подтверждён**; регистрация, заявка и акцепт условий не выполнялись.
- [FO TradeStats](https://moexalgo.github.io/docs/api/get-fo-tradestats/) и
  [FO OBStats](https://moexalgo.github.io/docs/api/get-fo-obstats-for-ticker/) явно
  доступны подписчикам через `apim` с обновлением раз в пять минут. Публичный delayed
  FUTOI не является бесплатной заменой этих двух наборов. Агрегаты не доказывают
  исполнимость лимитной заявки, queue priority или восстановление отдельных заявок.

На 2026-09-06 следующий шаг требовал разрешения пользователя на внешний запрос,
не нового обучения; разрешение получено 2026-09-07, текущий статус указан выше.
Приоритет — узнать условия небольшого теста персонального доступа, а не покупать
полный корпоративный продукт или писать ещё один downloader. Исторический черновик
запроса `algopack@moex.com` приведён ниже; уточнённая версия отправлена 2026-09-07,
её статус и проверка описаны в начале документа:

> Нужен исследовательский доступ физического лица к AlgoPack без распространения
> данных и без live trading. Есть ли бесплатный или ограниченный тест API SuperCandles
> FO TradeStats/OBStats? Просим подтвердить возможность хранения истории и личного
> автоматического анализа/обучения моделей на собственном сервере, условия и стоимость
> после теста без автоматического подключения платной подписки. Для проверки схемы
> нужен один день 2024-10-15 по SI/RI/BR/MIX с точными идентификаторами контрактов;
> также нужны границы доступной истории до 2025-12-31, семантика времени публикации,
> исправлений и пагинации. Есть ли отдельный FO OrderStats? Если нет — достаточно
> подтвердить его отсутствие. Тестовый токен нужен только на чтение данных.

Sample day выбран для технической проверки, не поиска доходности. До sample/download
нужен отдельный source-only seal; до labels/PnL — economic seal. Ни sample, ни ответ
поставщика не подтвердят цель 20%/50% сами по себе. Статус на 2026-09-06 был
`AWAITING_USER_AUTHORITY_FOR_ACCESS_REQUEST`; существующие бесплатные forward
collectors продолжают работать на сервере по прежним протоколам.

## P0 — original-timestamp dividend disclosures

### Зачем

Dividend calendar spread V1 получил 31 RMS cashflow-change events и 0 допустимых
following-quote entries. Следующий источник обязан сообщать рекомендацию совета
директоров, сумму на акцию, record date и исправления раньше RMS repricing.

### Предпочтительный источник: Интерфакс-ЦРКИ «Шлюз данных»

- Официальная страница: `https://e-disclosure.ru/poluchenie-informacii/shlyuz-api`.
- Swagger: `https://gateway.e-disclosure.ru/swagger/ui/index.html`.
- Public OpenAPI bytes на `2026-09-02`: 51 030, SHA-256
  `a27621f62dd86e60bfdd14dc7649116e26748b8862986f9576010f26f843d1d5`.
- Нужный продукт: сообщения в ленте новостей, JSON REST API. Публично объявленная
  цена на дату проверки: 16 180 RUB/месяц без НДС, minimum 3 months; условия и доступ
  к exact 2023–2025 history надо письменно подтвердить у поставщика до оплаты.
- API surface: `POST /api/v1/auth`, dictionaries message/file types,
  `GET /api/v1/disclosure/events`; token передаётся header `APIKey`.
- Событие содержит server `eventId/eventDate`, subject, message UID/type/text,
  `originalMessageUid`, public URL и attachments. Это позволяет сохранять publication
  clock и correction chain без LLM-догадок.

### Universe

| Asset | Equity | CBR issuer code | Public page id/status |
|---|---|---|---|
| GAZR | GAZP | `00028-A` | e-disclosure `934`, подтверждено |
| SBRF | SBER | `01481-B` | e-disclosure `3043`, подтверждено |
| ROSN | ROSN | `00122-A` | e-disclosure `6505`, подтверждено |
| TATN | TATN | `00161-A` | e-disclosure `118`, подтверждено |
| NOTK | NVTK | pending vendor/API identity check | не угадывать |

### Readiness

- Credentials в окружении отсутствуют; подписка и внешний spend не разрешены агенту.
- После выдачи test credentials использовать отдельные переменные
  `EDISCLOSURE_API_LOGIN`/`EDISCLOSURE_API_PASSWORD`; никогда не писать их в log,
  manifest, Git или raw bundle.
- До message text/PnL сначала сохранить и запушить source-only config: exact universe,
  dates `2023-01-01..2025-12-31`, message-type dictionary, pagination/cursor contract,
  original event clock, correction/deletion semantics, rights and output schema.
- Raw JSON сохранять immutable вне Git; каждое событие replay-ить по UID/eventId.
- LLM может извлечь только dividend amount/record date/decision status с page evidence;
  prices, returns, target и PnL ей недоступны.

### Альтернатива: MOEX Центр корпоративной информации

MOEX ЦКИ заявляет structured corporate actions, IR calendar, API и historical issuer
data примерно за 10–15 лет. Публичный тариф на дату проверки начинался от 35 000
RUB/месяц для internal corporate-actions access. Перед выбором запросить sample JSON и
проверить наличие original publication timestamp, update/delete chain и board
recommendation, а не только current-vintage payment facts. Без этих полей более дорогой
источник не решает причинную задачу.

## Решение о покупке

По умолчанию `SLEEPING_NO_CREDENTIALS_NO_SPEND`. Пользователь должен отдельно разрешить
подписку/test access. До этого приоритет — уже работающие forward V39/V27 collectors;
они не требуют покупки нового исторического права.

## P0 — broker execution, margin and idle-cash evidence без передачи доступа

Для V41 и broad cash-carry сначала не нужен API-ключ брокера. Достаточен обезличенный
byte-pinned пакет документов и экспортов, который пользователь может положить во
внешний каталог `D:\Projects\trading_lab_data\data\raw\broker_evidence\`:

1. PDF/HTML действующего тарифного плана с названием счёта и effective date;
2. правила списания broker/exchange/clearing fees для TQBR и RFUD, включая minimum fee;
3. таблица фактической initial margin и дополнительных broker multipliers по выбранным
   stock futures, с timestamp выгрузки;
4. правила зачёта long stock, short deliverable futures, variation margin, delivery и
   достаточности денежных средств; рекламное «единая позиция» не заменяет формулу;
5. условия LQDT/SBMM/AKMM/TMON: комиссия, settlement, возможность/невозможность залога,
   haircut, cutoff и срок высвобождения денег после продажи;
6. обезличенный CSV/JSON paper или минимального тестового счёта с submitted/accepted/
   rejected/cancelled/filled timestamps, requested/filled quantity, price и всеми fees.

Логин, пароль, refresh/access token, номер счёта, ФИО и participant identifiers в пакет
не включать. Агент не отправляет заявки и не подключает live account без отдельного
явного разрешения. Сначала ingestion фиксирует SHA/schema и только затем допускает
paper execution audit; отсутствие любого поля остаётся unresolved, а не нулём.
