# AlgoPack archive V1 — all-field historical preservation

2026-09-15. [Разрешение пользователя](ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md).
Это source-only archival batch, не новая стратегия, не price-based universe selection.

## Область

14 endpoint families: EQ/FX TradeStats, OBStats, OrderStats; FO TradeStats, OBStats;
EQ/FO/FX HI2 и Alerts. Полный рынок каждого дня, все возвращаемые API columns, без
ограничения сегодняшними известными тикерами. Super Candles/HI2:2020–2025;
Alerts:2024–2025 по заявленному началу истории. 26305 day/dataset jobs, включая
выходные/праздники как explicit empty responses, не выдумывая trading calendar.
Первый день2024-10-15 для всех14families; затем дни в обратном порядке, без дублирования.

Официальные источники: [каталог](https://moexalgo.github.io/),
[EQ OrderStats](https://moexalgo.github.io/docs/api/get-eq-orderstats/),
[HI2](https://moexalgo.github.io/docs/api/get-hi-2/),
[Alerts](https://moexalgo.github.io/docs/api/get-alerts/),
[авторизация](https://moexalgo.github.io/docs/api/algopack-api/).
Точные даты/права/схемы каждого маршрута устанавливает actual ответ, не каталог.
FO OrderStats не обещан текущим меню; он не подставляется по аналогии с EQ.
FUTOI уже имеет отдельный сохранённый intraday bundle; full-market expansion и
исторические справочники — отдельная следующая проверка, в14routes не входят.
Current-only live стаканы/ленты без historical bound не запрашиваются.

## Сохранение и безопасность

Только gpu-mlserver UID999, отдельный /srv/trading_lab_data/data/algopack-archive.
Code/config/protocol/auth/tests hashes фиксируются до network. Секрет EnvironmentFile
не показывать; pinned application CA, verification включена, apim-only, no redirects.
Serial0.5sec interval; transport/429/5xx retries5/15/45sec; 401 останавливает batch,
403/unsupported schema закрывает family с записью неполноты, остальные продолжаются.
До хранения проверяются tradedate=exact request<2026, полный cursor и ширина строк.
Числовые поля не выбираются/не агрегируются и не выводятся в diagnostic.

Каждая response страница gzip lossless + raw/compressed SHA + retrieval + cursor/schema,
atomic publication directory, file/directory fsync. Resume replay уже committed pages
без сети, неизменный TOTAL/schema внутри дня; changed/tampered страницы не autoheal.
Partial temporary directories сохраняются и не считаются completed evidence.
Полный day manifest содержит ordered page identities; global manifest перечисляет все
полные/empty/failed/unattempted jobs. status.json — только operational checkpoint,
не источник доказательства полноты. Повторный запуск completed archive запрещён.

Disk reserve128GiB, archive ceiling500GiB проверяются перед работой; page max64MiB,
page ceiling5000/day. Это safety ceilings, не разрешение обрезать данные и объявить
полноту. При достижении — STOPPED_INCOMPLETE с сохранённым resume point.
Старый FO subset содержит меньше полей/контрактов: новый full-market архив пересекается
с ним по некоторым ключам, но не заменяет и не перезапускает canonical source.
Новых локальных Windows jobs, покупок, реальных сделок или paper bootstrap нет.

Original-version/PIT/economic flags false; raw storage не разрешает PnL без отдельного
протокола. Права personal use подтверждены ранее; безусловные права после expiry
отдельно не установлены. Нельзя распространять архив или объявлять его полным до итогового audit.
