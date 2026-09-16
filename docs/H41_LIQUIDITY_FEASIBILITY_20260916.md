# H.4.1 — следующий source candidate, 2026-09-16

После закрытого V98 исследовать не ещё одно окно заседаний, а иной механизм:
изменение доступной банковской долларовой ликвидности и её возможная связь с
последующим глобальным спросом на риск. Это гипотеза, не установленная причинность
и не готовая торговая стратегия. Нет V99 config/seal/targets/economic run.

Поиск `WALCL`, `WTREGEN`, `RRPONTSYD`, `H.4.1`, `net liquidity`, `dollar liquidity`
и русских сочетаний ФРС/ликвидность в docs/src/configs не нашёл прежнего теста.
Это не доказательство отсутствия каждого связанного macro feature в старых моделях;
перед дизайном всё равно проверить ближайшие V71/V72 и ранние macro protocols.

[Официальное описание H.4.1](https://www.federalreserve.gov/releases/h41/about.htm)
указывает обычную публикацию по четвергам около16:30 ET и описывает балансовые
данные резервных банков. [Датированный выпуск19March2020](https://www.federalreserve.gov/releases/h41/20200319/)
доступен в HTML, с отдельными ASCII/PDF ссылками, release clock и таблицей1.
Она содержит reserve balances, Reserve Bank credit, Treasury General Account и
reverse repo; важно различать weekly averages и Wednesday levels. В том же выпуске
есть предупреждение об изменении структуры table5. Значения этого исторического
sample были видны при проверке формата; соответствующие рыночные outcomes не читались.

Предпочтение original dated releases, не текущему DDP/FRED ряду со всеми исправлениями.
Один пример не устанавливает multiyear completeness/PIT. Перед экономикой нужны:

1. Bounded проверка доступности и устойчивости выбранной строки/колонки в2018–2025,
   actual release dates/clocks, announcements о задержках и revisions. При Thursday
   publication нельзя использовать Wednesday observation date как доступность.
2. Явный выбор одного экономического показателя и правила до market outcomes.
   Популярная формула assets−TGA−RRP не эквивалентна банковским резервам во всех
   режимах; не выбирать формулу по будущему PnL. Старые уровни должны происходить
   из тех выпусков, которые были доступны тогда, без позднего revision overwrite.
3. Новый краткий protocol/seal и готовый ledger. Не строить новый engine, не
   перерабатывать отрицательные V98/V97, не запускать перебор знаков/окон.

Текущие DDP downloads/`current` releases не скачивались. Search выдал также2026
metadata/посторонний macro snippet; он не импортируется, не становится признаками
или поводом выбора стратегии. Использовать только primary dated<=2025 documents.
Raw corpus, manifest и economic admission ещё отсутствуют. Права на собственные
Board materials — по [политике Board](https://www.federalreserve.gov/disclaimer.htm),
не автоматическое разрешение на сторонние источники/логотипы.

Не добавлять этот source discovery в число economic tests. Broader AlgoPack scope
остаётся без ответа; вопрос не повторять автоматически, downloader не менять.
