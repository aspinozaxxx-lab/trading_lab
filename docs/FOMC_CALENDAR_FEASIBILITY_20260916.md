# FOMC calendar — bounded source feasibility, 2026-09-16

**Позднейшее обновление:** исходная проверка ниже сохранена. Public press-call
PDF page5 подтвердил замену March17–18meeting;10source GETs/64events завершены,
один [V98economic screen](V98_FOMC_EVENT_PREMIUM_RESULT.md) дал REJECT_STAGE1.
Source/economic canonical roots не повторять. Это отменяет только прежнее
ожидание cancellation evidence ниже, не снимает original-receipt limitations.

Следующий независимый механизм-кандидат после V97: возможная премия за риск
перед заранее запланированными объявлениями FOMC, с переносом на российские
индексные фьючерсы. Это ещё **не V98 protocol**, не новый тест и не прибыльный
кандидат. Код, targets, рыночные outcomes, raw corpus и source manifest не созданы.
Поиск FOMC/Lucca/Moench/pre-announcement поdocs/configs/src не нашёл прежнего теста.

Мотивировка — [NYFed Staff Report512](https://www.newyorkfed.org/research/staff_reports/sr512.html)
и [объяснение международного эффекта2012](https://libertystreeteconomics.newyorkfed.org/2012/07/the-puzzling-pre-fomc-announcement-drift/).
Это внешняя исследовательская гипотеза, не доказательство доходности MOEX.
[Обновление NYFed2018](https://libertystreeteconomics.newyorkfed.org/2018/11/the-pre-fomc-announcement-drift-more-recent-evidence/)
отмечает различие meetings с/без press conference; новый дизайн ещё не выбран.
Нельзя после MOEX outcomes выбрать удачный тип meeting, знак или окно.

## Найденные первичные расписания

Официальные страницы содержат даты будущих meetings и дату исходного выпуска.
При следующем bounded fetch сохранить HTML/SHA/receipt и проверить сам текст,
не принимать текущую сводную historical calendar за witnessed original history.

| Год расписания | Исходный выпуск Board | Страница |
| --- | --- | --- |
| 2018 | 2017-05-11 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20170511b.htm) |
| 2019 | 2018-05-25 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20180525a.htm) |
| 2020 | 2019-05-17 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20190517a.htm) |
| 2021 | 2020-07-02 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20200702a.htm) |
| 2022 | 2021-06-04 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20210604a.htm) |
| 2023 | 2022-06-24 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20220624a.htm) |
| 2024 | 2023-06-23 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20230623a.htm) |
| 2025 | 2024-08-09 | [Release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm) |

Последняя страница также содержит будущие2026/2027calendar dates. Это не market
outcomes; в экономический набор всё равно брать только meetings<=2025.
[Board disclaimer](https://www.federalreserve.gov/disclaimer.htm), прочитан16сентября:
собственные материалы Board обычно public domain с атрибуцией; third-party
материалы/логотипы отдельно. Не переносить это разрешение на NYFed datasets или
чужие market calendars. Обхода paywall/auth, платного доступа и bulk crawl нет.

## Что ещё проверить до economic seal

1. Отмена scheduled17–18March2020 после emergency15March: нужна исходная публичная
   публикация/press-conference clock, не поздняя историческая пометка. [FOMC statement
   15March2020](https://www.federalreserve.gov/newsevents/pressreleases/monetary20200315a.htm)
   имеет5pmEDT timestamp, но сам текст не устанавливает время объявления отмены.
   [Board cancellation notice](https://www.federalreserve.gov/aboutthefed/boardmeetings/20200317closed.htm)
   относится кBoard, не автоматически кFOMC; LastUpdateJune15 нельзя backdate кMarch13.
   Minutes/внутренние agenda/transcript, опубликованные позднее, тоже не contemporaneous.
2. Исходное2019расписание ещё говорит оquarterly press conferences; последующее
   изменение наeverymeeting нельзя выводить из обновлённого retrospective calendar.
   All-meetings design может не требовать этого фильтра, но правило нужно зафиксировать.
3. С existing daily ledger можно проверить лишь заранее определённый coarse
   open-to-open window, не выдавать его за точный24hannouncement effect. MOEX holiday
   или halt могут перенести выход после события. Нельзя отфильтровывать входы по
   будущему наличию exit price. Нужны causal intent/expiry и явный unresolved handling.
4. До outcomes закрепить один primary/control, source clocks, entry/exit window,
   costs и gates; сохранить все годы/неуспехи. Не строить новый intraday engine:
   V93 уже показал ограниченное историческое intraday coverage.

В этой проверке читались primary HTML/web-search summaries; PDF documents не
открывались. Нет fit/PnL/нового значения в воронке. Пока cancellation source clock
не подтверждён, calendar corpus не объявлять ready. Не повторять EIA-consensus
ветку без нового основания прав; broader AlgoPack разрешение всё ещё не получено.
