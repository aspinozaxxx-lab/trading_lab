# V77 — доступность исторического состава IMOEX, без цен

Объявлено 2026-09-14, до source requests. Статус: `PLANNED_SOURCE_ONLY`.

Новая проверка источника для гипотезы о потоках индексных фондов. Это НЕ запуск
приостановленного nine-article news sample и не замена времени объявления датой
вхождения в индекс. Исторический состав может дать проверочный universe/event census;
сам по себе он не доказывает заблаговременную публикацию или покупки фондов.

## Ограниченная проверка

- Только официальный документированный route
  `https://iss.moex.com/iss/statistics/engines/stock/markets/index/analytics/IMOEX/tickers.json`.
- Два заранее выбранных среза: `2018-01-03` и `2025-12-30`, по одному GET, без retries.
- Query: date, tradingsession=3, iss.meta=off, iss.only=tickers,
  tickers.columns=ticker,from,till. Никаких price/weight/return fields.
- Timeout 30 seconds, максимум 128 KiB на ответ. Redirect/access bypass запрещены.
  Остановиться при non-200/не-JSON, неожиданном блоке/поле или превышении размера.
- До разбора сохранить raw bytes во внешнем versioned server root; затем manifest
  с URL, retrieval clock, HTTP status, bytes/SHA, columns, row counts и датами метаданных.
  Ничего не перезаписывать. Работать от trading-lab, без credential.
- Данные, включая сырьё, не публиковать в Git. Новый collector/service не создаётся.

## Заранее установленное решение

Два среза не являются полным корпусом и не допускают PnL. Проверить, возвращает ли
источник разные исторические memberships, пригодные для отдельного полного census.
Нужны идентичность ticker/исторической бумаги, полнота всех изменений и исключений,
first available date vs actual membership, original publication/revision evidence.
Минимум для будущего event screen: 30 distinct security events на полном периоде
2018–2025, не удобная выборка известных публикаций/сегодняшних 30 акций.
Без этого `economic_admission=false`, CAGR/Sharpe/MDD/trades=null.

Если источник не даёт исторические срезы или только proxy first/last dates, записать
точное ограничение и не строить экономический engine. Если даёт — сначала отдельный
ограниченный census protocol и clock/event-count feasibility, затем economic seal.
Не менять paused news config/seal, не читать outcomes >=2026, не возобновлять paper.

Документация поставщика: [ISS reference 141](https://iss.moex.com/iss/reference/141)
описывает date-specific tickers; [reference 73](https://iss.moex.com/iss/reference/73)
отдельно описывает date analytics. Public endpoint не доказательство прав на
перепубликацию индексного датасета или historical original-vintage availability.

## Результат

Ещё не получен. Реальные данные и hashes будут указаны после bounded source run.
