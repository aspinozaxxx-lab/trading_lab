# Резервные источники после V99: bounded discovery, не economic tests

Проверены параллельно сбору H.4.1, без новых цен/доходностей или массовой загрузки.
**V99 прошёлStage1, поэтому сначала его Stage2**, а не реализация этих источников.

## ОПЕК — источник найден, массовый корпус не разрешён условиями

Найдены original dated HTML releases:
[18July2021](https://www.opec.org/pr-detail/209-18-jul-2021.html),
[2June2022](https://www.opec.org/pr-detail/127-02-jun-2022.html),
[5October2022](https://www.opec.org/pr-detail/73-05-oct-2022.html).
В них есть направление/размер изменения production plan и effective months.
Объявленный прирост не обязательно новая информация: часть планов подтверждается,
часть ускоряется. Нельзя превращать каждое повторение предыдущего плана в surprise.
Полный корпус/clock/revision chain и отличие обязательных квот от добровольных
сокращений не проверены. Старый V6GDELT oil_supply query уже включал OPEC; отдельного
source-bound production-plan change теста поиском docs/src/configs не найдено.

[Terms and Conditions](https://www.opec.org/terms-and-conditions.html), пункты6–9,
ограничивают shared electronic archive и коммерческое копирование; определение
commercial purpose включает исследование в надежде будущего заработка. Occasional
attributed internal/research references не равны разрешению на полный trading corpus.
Без отдельного достаточного основания не делать bulk download/server archive.
Не обходить условия через Wayback/перепечатки; ничего ОПЕК не скачано в server corpus,
не отправлены запросы на разрешение, не сделана покупка. Политика privacy — другой
документ, не лицензия. Относительные footerlinks на pr-detail сначала дали404;
нужные действующие root-level terms были прочитаны, не предположены.

## Census M3 — следующий незаблокированный source candidate при необходимости

Найден[официальный архив full manufacturing releases](https://www.census.gov/manufacturing/m3/historical_data/index.html)
и[архив advance durable-goods releases](https://www.census.gov/manufacturing/m3/adv/historical_data/index.html).
Идея для feasibility: новая информация о заказах/запасах и возможном спросе на сырьё,
не ещё одна комбинация нефтяных цен. Правило/актив/окно ещё не выбраны, V100seal/run нет.

Прочитан только HTML inventory; PDF/Excel не открывались и corpus не загружался.
2026links/поисковые snippets не импортируются и не используются как признаки.
Месяц observation не release date: December2018advance search metadata указывает
публикациюFebruary2019. Late2025observations могут быть опубликованы уже2026 и не
допустимы для decision<=2025. На HTML index August/September2019fullreport ведут к
одному linkID: обязательно сверять идентичность документа, не полагаться на label.

При продолжении: bounded historical-format/publication/rights check, original vs
revised release distinctions и existing-family review до нового короткого протокола.
Не загружать текущий full-series bundle с2026 и не строить новый ledger. Пока это
источник для проверки, не утверждение причинности/прибыльности и не гипотеза в счётчике.
