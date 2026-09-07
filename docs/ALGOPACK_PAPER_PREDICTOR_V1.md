# AlgoPack future-paper predictor bridge V1

2026-09-07. Target-free соединение witnessed flow, market packet и immutable forecasts.
Не меняет frozen training/inference/source parents. Модели не переобучаются.

`load_flow` требует действительную activation и включение текущего predictor module
в её проверенный bundle. Принимает только exact canonical capture ID и manifest SHA
из fixed server witnessed root. Сначала metadata/hash/start>=F/available<=now, затем
полный parent raw replay. Источник содержит только FO flow/depth, не prices/outcomes.
Временные labels не заменяют receipt clocks. Проекция включает четыре поля каждого
dataset по training mapping; строки до F и ещё не завершённые к source availability
исключаются. Missing/mismatched vendor asset metadata даёт missing fields, не нули.

`import_flow` сохраняет проекцию и source binding в immutable journal. `observe_flow`
повторяет source replay и сверку с журналом; все версии получают фактическое время
ПОСЛЕ наблюдения/проверки. Version identity связывает manifest, normalized artifact и
индекс строки. Подмена исходных bytes вызывает отказ даже после предыдущего импорта.

`predict_slot` наблюдает market packet и optional flow event, загружает pinned модели,
фиксирует actual input cutoff, готовит признаки без labels, вычисляет обе arms и
сохраняет forecast через existing journal. Sources входят в forecast provenance.
При flow=None baseline может работать; испорченный указанный flow вызывает отказ,
а не скрытый переход к baseline. Опоздавший расчёт не сохраняется как READY;
опоздавший consumer дополнительно маскируется parent journal. Повторный слот не
перезаписывает прогноз. Forecast всё ещё execution_admitted=false.

## Проверка и границы готовности

Synthetic Linux integration создаёт оба источника через fake HTTP, с полным raw replay,
семью ценовыми барами и двумя завершёнными flow buckets. Используются явные fake model
bytes и mocked activation/parent seal внутри fixtures. Ни одной реальной цены/прогноза,
API request или production activation это не создаёт. Локально Linux tests пропускаются;
server результаты будут записаны в STATUS/EXPERIMENTS после pushed deployment.

Нет CLI, таймера, выбора F, execution/evaluation, session-admission или profit report.
Runtime должен выбирать witnessed capture по доступности, импортировать его один раз,
фиксировать причины missing source/failed slots и исполнять только новый post-F период.
Нельзя выбирать источники или пропускать неудачные слоты по увиденному PnL.
Следом fixed paper execution/evaluation и общий activation/runtime до первого NEW price HTTP.
Доходность20%/50% не подтверждена; historical AlgoPack economic run запрещён.
