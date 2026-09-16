# V104 — премия за физическую обеспеченность запасами нефти, Stage 1

Проверяем, вознаграждается ли удержание нефтяного фьючерса в состоянии относительно
низких физических запасов. Это новая информация о **stock/use level**, а не реакция
на очередную недельную новость. Тест uses ready EIA vintages и готовый BR ledger;
нового источника, большого парсера, модели или collector не создаётся.

## Новизна и экономическое основание

V17 использовал только `reported_weekly_change` семи запасов/потоков, z-score и
знак composite для предсказания следующего недельного движения цены. Он закрыт;
нельзя менять его компоненты/знак/порог. V104 не строит такой composite и вообще
не читает weekly changes: используются два `current_value` уровня с физическим
отношением stock/use. Target — conditional long risk premium, не signed news drift.
V103 — торговая ликвидность, не физические запасы. История BR уже просмотрена;
смена информационного набора не создаёт независимого holdout.

[Gorton, Hayashi, Rouwenhorst](https://www.nber.org/papers/w13249) связывают
commodity futures premia и физические запасы. Прочитан доступный поиску abstract;
прямое HTML open вернуло403, полного paper/dataset не скачивали и доступ не обходили.
[Reeve, Vigfusson](https://www.federalreserve.gov/pubs/ifdp/2011/1025/ifdp1025.htm)
объясняют связь запасов, стоимости хранения и convenience yield, но не находят
автоматического улучшения прогноза от поправки на предполагаемую премию.
Теория не гарантирует роста spot или прибыльности правила на МОEX.

Перенос запасов и загрузки НПЗ США на BR/Brent — непроверенное предположение:
это не мировые запасы, не точный measured convenience yield и не репликация статьи.
Ремонты НПЗ, импорт/экспорт, изменение мощностей и рыночных режимов могут объяснять
весь сигнал. Эти ограничения не устраняются выбором лучших лет после теста.

## Заранее объявленное правило

`cover_days = 1000 × commercial crude stocks / crude oil input to refineries`.
Stocks: `Stocks / Commercial (Excluding SPR)`, million barrels.
Use: `Crude Oil Supply / Crude Oil Input to Refineries`, thousand barrels/day.
Получается количество дней покрытия переработки имеющимися запасами; SPR исключён.
Это исследовательский ratio, а не попытка воспроизвести отдельную официальную
серию EIA days-of-supply с иной методикой.

Для месяца, содержащего `data_week_ending`, рассчитать среднее cover_days отдельно
в каждом из **пяти предыдущих календарных лет**, затем среднее этих пяти значений.
В каждом year/month нужны минимум **три разные доступные недели**. Вес годов равный,
независимо от числа недель. Берётся первое пригодное опубликованное наблюдение
для каждой недели, доступное строго до текущего release; последующие revisions
не переписывают baseline. Текущий год/другие месяцы/future releases исключены.
Нет fallback на четыре года или zero fill при missing history.

Если current ratio строго ниже baseline — BR long0.9gross; иначе cash. Равенство
означает cash. Контроль — constant long0.9 на том же source-ready/fill календаре,
не кандидат для выбора после результата. Размеры ежедневные constant-fraction,
roll через прежний exact-contract adapter, позиция обновляется по latest release.

Latest issue с missing/нулевым/отрицательным/nonfinite stock/use, missing row или
неполным baseline означает unready/cash, не продолжение старого good-state сигнала.
Известный stale issue2019-07-03 остаётся unready строкой календаря, а не удаляется.
Исторический baseline допускает пропуски только в рамках объявленного minimum3;
это не разрешение считать неизвестное наблюдение нулевым.

Availability строго прежняя:23:59:59America/New_York официальной release date.
Decision — готовый V72 calendar-end Moscow clock, next factual open только позже.
Source age at fill <=14 календарных дней; decision-to-fill gap<=7 дней. Нет
фильтрации по будущему выходу. Terminal intent flat, unknown exits/carry не исчезают.
`year_ago_value`, `previous_value`, weekly changes и Last-Modified не признаки.

## Исходные данные и границы

Source: U.S. Energy Information Administration, release-specific WPSR Table1,
2012-01-05…2025-12-29; attribution с датой каждого release сохранена в state rows.
[EIA reuse](https://www.eia.gov/about/copyrights_reuse.php) разрешает использование
собственных государственных данных с указанием источника; сторонние защищённые
изображения/логотипы сюда не входят. Ни графики, ни новый article corpus не копируются.

Root `data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2`:
38,248 rows,727 admissible releases/728calendar issues,71 cross-release revisions.
Original receipt/историческая неизменность не доказаны криптографически; это прежнее
conditional development admission, не новый strict-PIT статус.

- Manifest `aac389628b61df446616cd171084af81482d09a7d4b403337a8332b5373c142b`.
- Processed `5fccfa968ac88f04806df87bd7179a992f0f7c57137ba46db049d67350b54f3e`,
  1169909bytes; coverage `2b219c7815d92f41321b0d1fa5c23c27f4f1737927a86a3528073ca955a01c82`,
  65672bytes. SHA raw/index входят в тот же pinned manifest.
- Exact new allowed columns и date bounds — в V104 config. Preflight сверяет все
  source artifact hashes, schemas/rows/date-only columns и отдельный stale exclusion
  **до numeric read**. Новый полный raw/CSV/PDF parse не нужен и не выполняется.
- Futures: прежний V64 recent active map / observations / specs, parent V101 seal
  `067dc4ec60266536e57c51df322c74c7daaef9b91a3f46db5fcaad78a672f55a`.
  Hashes `40e81708…`, `a1c65078…`, `8494235f…` полностью pinned в transitive closure;
  максимум2025-12-30 проверяется preflight до market values.

## Validation, исполнение и gates

Экономика2021–2025; source history2012–2020 только causal seasonal warmup. Нет
обучения, scaler/early-stopping/seed selection и поиска параметров. Это не новый
purged OOS model и не unseen holdout. Source values/новые features и outcomes
вычисляются только после code/config/tests/protocol SHA seal.

Капитал1млнRUB, gross cap1.0, margin buffer2, participation1%, interest0.
Base1tick/1fee, double2ticks/2fee, старый V64/V78 integer daily-open ledger,
asset atomicity/cancel-and-clip. Research-proxy specs/fees/margin, не broker exact
BBO/queue/внутридневное исполнение и не разрешение реальных сделок.

Stage1: coverage>=80%, >=20roundtrips, CAGR>=5%, Sharpe>=0.5, MDD<=25%,
>=3positiveyears/5, worstyear>=−15%, CAGR excess vs control>=2п.п. для обоих costs,
все4execution complete,critical0/unresolved0/terminalflat. PASS означает только
переход к Stage2 robustness/attribution. 5% component gate не заменяет цель20–50%.

Сохранить все states/targets/orders/positions/ledgers, metrics с каждым годом,
coverage/counters, manifest и verdict в новом external run. Cash/metric replay не
является полной независимой реконструкцией risk counters. Canonical не rerun;
после outcomes не менять знак, stock/use определение, сезонное окно, TTL, размер,
контроль или состав лет. При отказе — закрыть эту формулировку и идти дальше.

Предыдущий goal turn — PROGRESS (V103 завершён и сохранён); цель20–50% активна.
Большой AlgoPack archive не прерывать. Broad AlgoPack economic scope не расширять,
TIC parser не возобновлять,2026защищён; без keys/покупок/писем/demo/live/Windowsjobs.
