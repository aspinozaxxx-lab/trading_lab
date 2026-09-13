# CBR policy releases2018–2025 — bounded source for V72

Новая информация — текст официального guidance о следующих решениях, а не уровень
ставки V27, macro-survey revisions V21 или бюджетный liquidity forecast error V71.
Дальнейшая гипотеза: явная готовность к ужесточению/смягчению политики может содержать
направленный сигнал для MIX/SI после выхода новости. Первый контроль — только
принятое решение в headline, без forward guidance. Source не вычисляет сигналы/PnL.

Существующие альтернативы проверены по реестру без новых economic runs: simple term
structure/calendar spreads уже закрыты; premium options требуют quotes/spec identity;
volatility-curve catalog V2 имеет0/6eligible archives. Их gates не ослабляются.
Индексный sample/paper bootstrap/collectors остаются без изменений. Для новой текстовой
гипотезы нужна небольшая однократная загрузка, не новый сервис/очередь/LLM engine.

## Фиксированный источник

[Раздел решений ЦБ](https://www.cbr.ru/dkp/mp_dec/) использует отдельный news category
84035 для пресс-релизов ключевой ставки. В исходной разметке наблюдены continuation URL
`/Crosscut/NewsList/LoadMore/84035?intOffset=0&extOffset=10`; offset0 задаёт начало.
Только эту категорию последовательно читаем до первого release до2018; максимум20pages,
128HTTP requests,0.25s spacing,30s timeout,2MiB/response, no redirect/retry/credential.
Сохраняем все2018–2025 релизы, включая внеочередные; не выбираем headline/action или год
по последующим ценам. Требуются descending page boundaries/unique URLs, повтор первого
page header set для detection изменения списка и минимум8релизов каждого года.
Это полнота наблюдаемого provider catalogue, не доказательство несуществования удалений.

До article fetch проверяется дата2018–2025. Headlines следующих лет могут встретиться
в listing только как macro metadata, но сами2026 articles не загружаются, protected
market prices/returns/labels/PnL не читаются. В старом релизе будущий прогнозный год —
известное тогда заявление, не будущий realized outcome.

Article: h1, header date и footer exact timestamp сверяются с catalog; извлекаются лишь
paragraphs внутри landing-text, без меню/scripts. Source URL, raw SHA, actual receipt,
headline и clocks сохраняются. EOD23:59:59Moscow — conservative development availability;
внутридневной исторический receipt и неизменность original/revision bytes не доказаны.
CBR [календарь2021](https://cbr.ru/press/pr/?file=10092020_130000PR2020-09-10T12_46_47.htm)
прямо указывает московский часовой пояс плановой публикации; runtime требует и
фактический printed footer clock, не выводит его только из обычного расписания.

Raw/Parquet/manifest на gpu-mlserver во внешнем root; Git только code/config/tests/doc.
Атрибуция Пресс-службы Банка России обязательна, raw redistribution не предполагается.
Source PASS не равен economic admission, original-vintage PASS или доходности.
После сбора один replay/schema/clock audit, затем отдельный V72 economic config/seal
с фиксированными словарём/negation handling, контролем, размером, holding, costs и gates.
Не читать рыночные результаты до этого seal. Полная история — development, не holdout.
