# Census M3: source feasibility отложена, экономического теста нет

Проверка выполнена после закрытия V100; предыдущий goal turn — PROGRESS, а не
ожидание: V99 отклонён на Stage2 и результаты сохранены. Цель 20–50% остаётся active.

Найдены официальные [advance archives](https://www.census.gov/manufacturing/m3/adv/historical_data/index.html).
У Census есть [политика открытых публичных данных](https://www.census.gov/topics/research/research-transparency-public-access/open-data.html)
и [правила атрибуции](https://www.census.gov/about/policies/citation.html); выводы
исследователя не являются выводами Census. Публичные статистические таблицы не
следует смешивать с restricted-use microdata. Privacy policy не заменяет эти основания.

Просмотрен извлечённый текст трёх исторических PDF: March2018, December2018,
October2025. Первый лист содержит явную дату/время выпуска и текущий месячный
рост новых заказов без транспорта. Это не consensus surprise и не рост реального
объёма: данные сезонно скорректированы, но не очищены от изменения цен.
March2018 имеет "virtually unchanged", что нельзя превращать в положительный сигнал.
Исследование не основано на вероятностной выборке; стандартные sampling-error
интервалы не публикуются. Последующие отчёты и annual benchmarks пересматривают оценки.

[December2018 report](https://www.census.gov/manufacturing/m3/historical_data/pressreleases/adv/2018/dec18adv.pdf)
вышел 21 February2019 после остановки финансирования государства, а не в декабре.
[October2025 report](https://www.census.gov/manufacturing/m3/historical_data/pressreleases/adv/2025/oct25adv.pdf)
вышел 23 December2025; [schedule](https://www.census.gov/manufacturing/m3/release_schedule.html)
показывает November/December2025 releases уже в2026 — их нельзя допускать к решениям<=2025.
Текущие series bundles не загружались. Календарные метаданные2026 не использовались
как признаки и не являются чтением рыночных исходов2026.

## Фактический блокер, не результат стратегии

Первый серверный GET inventory получил **HTTP403 / Cloudflare** в
2026-09-16T21:23:58.873271UTC. Raw отказа 5488 bytes,
SHA `2f8d8ccab12522f8ce096c3b79701442c5a396e8eb763f07250d9127937b9472`.
Root `/srv/trading_lab_data/source_evidence/census_m3_probe_20260917_v1`,
manifest `c5184b69a1eb96bc4a9f259ffd0d143cd06a7cdc09a898827de59c0b6e6d565d`,
status FAILED_SOURCE_NO_RETRY. Скрипт чтения, запущенный до проверки этого отказа,
также остановился на отсутствии manifest; затем терминальный failure manifest
добавлен без изменения raw. HTTP не повторялся, обходов доступа не было.
Ни один PDF не скачан на сервер, полноценный корпус не создан.

Навык PDF применён для выбора проверки заголовков, footnotes и визуального
контроля страниц. Screenshot-запросы дали неполный результат: две страницы
недоступны с cache-miss; полный визуальный контроль не состоялся. Извлечённый
текст не объявляется заменой проверки страниц. Никакие PDF не редактировались.

Не создано Census economic config/seal/run; в счётчик гипотез источник не входит.
Ветка отложена до нормального доступа к пригодному корпусу. Это не статистический
отказ гипотезы и не глобальный блокер: следующим выбран отдельный источник ФРС G.17
о фактическом промышленном производстве, не подмена Census значений.
