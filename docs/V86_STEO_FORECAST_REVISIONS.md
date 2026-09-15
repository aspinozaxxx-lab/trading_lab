# V86 — пересмотр прогнозного нефтяного баланса EIA

2026-09-15. Новая информация: monthly STEO forecast vintages, а не V17 фактические
weekly WPSR changes. Проверка пока SOURCE/PRE-OUTCOME, экономического результата нет.

## Фиксируемый экономический замысел

Весь2018–2025, BR, без обучения и подбора параметров. Для каждого monthly edition
сравнить current и immediately previous edition forecasts **одного и того же следующего
календарного квартала**: average(consumption-production). Рост прогнозного дефицита ->
long; снижение -> short; равенство -> flat. Контроль: constant long с теми же masks.
Сигнал удерживается до следующего выпуска, но не дольше62calendar days после release;
исполнение существующим daily next-open ledger. Нельзя сравнивать разные кварталы.
Никаких forecast-price columns,2026actualprices/returns/labels, WPSR/V17 rerun или live.

Сигнал использует только published-before2026 **физические прогнозы**, в том числе
сделанные в2025 прогнозы объёма на2026Q1. Это не2026actual observation/outcome.
Дата source edition/availability обязана быть<2026. Не читать ценовые forecasts вообще.
До чтения selected numeric forecasts/outcomes нужен отдельный economic config/code seal
с source manifest hash, costs/capital/gates и inherited engine closure.

## Ограниченная source acquisition

97monthly workbooks:2017December как предыдущий выпуск + все96выпусков2018–2025.
Archive index и привязанные notices; никаких current editions, API keys, PDF/ценовых
страниц. Запросы только public EIA,2workers,3MBresponse/40MBunzipped bounds,
3attempts только connection/timeout; redirect/auth/rate/schema errors не обходить.
Сохранить raw XLSX неизменным в отдельном server root, вне Git. История скачивается
однократно после source seal; ранее RAM-only probes не canonical corpus.

Источник: [EIA STEO archive index](https://www.eia.gov/outlooks/steo/outlook.php/archives/1Q95.pdf)
возвращает HTML, несмотря на.pdf suffix. Hrefs относительные; использовать basename,
проверенный против edition month/year, под canonical /outlooks/steo/archives/.
[Jan2024 workbook](https://www.eia.gov/outlooks/steo/archives/jan24_base.xlsx)
содержит3atab, papr_world/patc_world, monthly dates и million barrels/day units.
Archive index говорит об исходных прошлых reports, но это не независимое доказательство
полной revision chain. docProps.modified тоже не public-availability evidence.

Известны [исправления Aug2018](https://www.eia.gov/outlooks/steo/archives/notice_data_08_09_2018.php)
и [Mar2020](https://www.eia.gov/outlooks/steo/archives/notice_data_03_18_2020.php).
Нельзя автоматически считать current archive bytes доступными в original release day.
Перед economic seal принять conservative availability не ранее конца NewYork дня
max(index release, notice date, workbook modified date); отсутствующие/непонятные clocks
-> unavailable, а не дата по имени файла. Это conditional source assumption, не PIT proof.
У notices, объявляющих изменение только следующего выпуска, не подставлять будущие
исправленные значения в старый файл. Raw и структура каждого источника сохраняются.

На server отсутствуют spreadsheet artifact runtime dependencies; по spreadsheet skill
применяется bounded read-only Python stdlib ZIP/XML fallback. Только3atab parsed,
headers/series identities/doc clocks; numeric data cells не оцениваются на source этапе.
Файлы не пересчитывать/редактировать/экспортировать. Missing cached cell не равен0.

## Не повторять закрытые альтернативы

В начале работы рассмотрена, но **не запущена** CBR/Minfin program-change hypothesis:
V19 уже запрещает такой повтор/подбор days. Corporate filings остаются без пригодного
admitted corpus/точной revision chain. Это не новые экономические screens.
Расширенный AlgoPack economic scope из V85 пока unanswered; архивирование разрешено и
не останавливается. V86 не использует эту неопределённость для обхода source gates.

Goal20–50%,Stage2,live=false. Пока нет нового economic screen/trade/метрик.
