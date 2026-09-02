# Запросы платных и лицензируемых данных

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
