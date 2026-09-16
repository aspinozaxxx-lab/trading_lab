# V102 — источник не собран полностью, экономический тест не запускался

Состояние на 17 сентября 2026, 02:05 МСК / 16 сентября 23:05 UTC.
Ветка TIC приостановлена после заранее ограниченного числа исправлений формата.
Это **INCOMPLETE_SOURCE**, не статистическое отклонение стратегии и не новый
прибыльный результат. Решения, сделки, CAGR, Sharpe и MDD не вычислялись; отсутствие
запуска нельзя изображать как экономический результат с нулём сделок.

Правило [V1](V102_TIC_BANK_FUNDING.md) не менялось: SI long 0.9 при отрицательном
последнем опубликованном месячном банковском потоке, иначе cash; constant-long
control, 2018–2025, прежний ledger, 1x/2x costs и gates. Исходные V1, [V2](
V102_TIC_BANK_FUNDING_V2.md) и [V3](V102_TIC_BANK_FUNDING_V3.md) сохранены отдельно.
Ни один run directory не создан, economic service не запускался. Воронка остаётся
33 portfolio = 27 rejected Stage1 + 1 rejected Stage2 + 1 incomplete + 4 invalid;
V102 пока не входит в этот счётчик, активных Stage2/Stage3 кандидатов нет.

## Три сохранённые попытки источника

| Версия | Parsed / raw в root | Новые GET / reuse | Причина остановки | Завершение UTC |
| --- | ---: | ---: | --- | --- |
| V1 | 18 / 19 | 18 / 1 | 2019-06-17: два одинаковых Apr-19 rolling headers | 22:45:17.276903 |
| V2 | 24 / 25 | 6 / 19 | 2019-12-16: title/unit вне таблицы | 22:53:14.656403 |
| V3 | 25 / 26 | 1 / 25 | 2020-01-16: идентификатор банковской строки `#`, не `29` | 23:01:02.773633 |

Все перечисленные responses HTTP200, то есть это не отказ доступа. Первые два
исправления затрагивали только неиспользуемый заголовок/размещение title-unit в
parser RAM, без изменения чисел или сохранённых raw. Третья причина — ещё один
неподдержанный формат; числовые данные сами по себе не объявлены ошибочными.
Согласно V3 protocol не сделана четвёртая версия и не запущена экономика на
неполном корпусе. Не возобновлять эти canonical roots и не ослаблять gates.

Всего в probes и трёх попытках получено 29 разных датированных release HTML из
плановых 96 (4 первоначальных samples + 18 + 6 + 1 новых запросов), с копиями
между roots. Это счёт уникальных дат, не byte-level dedup и не полный корпус.
Перед V3 seal 28 сохранённых страниц прошли parser check; следующий новый файл
не прошёл. Внутри canonical V3 отсутствует complete releases.json.

Failed V3 file `raw/20200116.html`,
[Treasury release](https://home.treasury.gov/news/press-releases/sm877), SHA
`272f9d16eeed7442dd1b2fecd98d1d26c674631aab805db0fdf31e1f0be34c0e`.
Article title November; datetime2020-01-16T14:09:37-05:00. Bank label присутствует,
но первый cell буквально `#`. Read-only диагностика зафиксирована, без исправления.

### Идентичность и воспроизводимость

- V1 seal `96238a5697f9f9592fea924dda1752938823f9da8ece7bcd55ce3a960f56cb59`,
  pre-outcome commit `0bb6443bbde0c3d9c5571fe4bceaff2cd9277928`;
  root `source_evidence/v102_tic_bank_funding/96238a5697f9`, manifest
  `bb11c0ac8eda14f2b64efab679011fe19e3e1b38fc164d5a813395978994611e`.
- V2 seal `1a5b61175fb2b03ad46cdc51737e7e421b6186f143503ee03515d6a7bdfeaeaa`,
  pre-outcome commit `23a8653c67e5921b7bdbc2efd0ee22aa8ae0ed9d`;
  root `source_evidence/v102_tic_bank_funding_v2/1a5b61175fb2`, manifest
  `1a1e68992ed1c12575494d6a625e6bec30a77bc8103de1246f45af0113b62eee`.
- V3 seal `bb8f518fa702b2a233b4a41d953f5796428694c85709a038895d305de571b3bc`,
  pre-outcome commit `e3ef6b48c812a3ccbea7116b59b548d37aefe1a8`;
  root `source_evidence/v102_tic_bank_funding_v3/bb8f518fa702`, manifest
  `1a2998c70a1428c65076d4e769ef5d7c6ab093976bcc94465a775cb2ffb4c953`.

V3 audit23:05:13.496757UTC:56filehashesPASS; три economic roots отсутствуют,
все три source units terminal failed/ExecMainStatus1. Invocation IDs:
V1 `01c045395c1048719d499d8342521d21`,
V2 `8da6f37b6a8b4ac5934c7e32badd08b9`,
V3 `b432656ede2143c0ae1dc70f5cc33242`.
Final local sealed closure PASS. 112 combined local tests PASS7.34s,47server
tests PASS0.47s, Ruff clean. Эти проверки не являются economic evidence.

Прежний V64 input preflight подтвердил bytes/hash/schema/count/boundary для
active map8100rows и observations/specs66052rows, максимум2025-12-30. Рыночных
outcomes2026, новой стратегии PnL, брокерских/demo/live операций не было.
Public source units не получили collector EnvironmentFile/credentials.

## Объём данных и работающий архив

Snapshot main AlgoPack23:03:38.700436UTC: **17649/26305 jobs (67.0937%)**,
159566359 rows,172035 pages, failed0, blocked[], RUNNING. Completed-job stored_bytes
9446832428 не равен полному размеру каталога во время записи. MainPID1663880,
invocation `d562f0748c4341b48eb7f4d34d64b4a1`, unit
`trading-lab-algopack-archive-v1-5b7c66fa0e04.service` active/running.

Измерение23:03:54.350730UTC на gpu-mlserver, отдельный `du -sb` для каждого root:

| Каталог/группа | Bytes | Decimal GB |
| --- | ---: | ---: |
| data/algopack-archive | 10092308846 | 10.092 |
| data/processed/algopack | 1456918554 | 1.457 |
| AlgoPack суммарно | 11549227400 | 11.549 |
| Всё data | 12944426513 | 12.944 |
| source_evidence | 559319597 | 0.559 |
| data + source_evidence | 13503746110 | 13.504 |

AlgoPack входит в общий объём, не прибавлять его второй раз. Sequential apparent
bytes при активной записи, без models/runs/tmp/transfers/local copies. Есть
внутренние raw/processed и source reuse копии, это не unique-information размер.
Процент jobs не процент байтов и не оценка оставшегося времени.

Локально в D:\Projects\trading_lab_data на23:01UTC: data10841files/2719842747bytes,
source_evidence25files/27598511bytes, вместе2747441258bytes =2.747GB.
Это сумма длин файлов без directory overhead. Есть копии серверных данных;
не складывать локальный и серверный объём как уникальный dataset. Models/runs/
downloads/transfers/tmp не включены.

Отдельный прежний FUTOI archive остаётся COMPLETE_WITH_SOURCE_GAPS с550unresolved;
не переаудирован и не перезапущен. Нулевые ошибки main job не означают отсутствие
пробелов во всех источниках. Основной AlgoPack downloader, token и Windows tasks
не менялись. Цель20–50% по-прежнему не подтверждена.

## Дальше

Вернуть приоритет короткому экономическому тесту на уже подготовленном bundle,
не ещё одной версии TIC parser. Начать с novelty review более медленной
cross-asset liquidity-risk compensation идеи на existing daily returns/volume:
сам термин Amihud/illiquidity premium в текущих configs/src не найден, но V66
уже проверил volume-shock reversal, pressure continuation, thin-breakout fade и
compressed-volume expansion. Поэтому новое имя/окно/порог недостаточны: сначала
доказать содержательное отличие механизма/target и пригодность proxy, иначе не
запускать. Это только agenda item, не выбранное правило/V103/config/результат.
Broad AlgoPack economic scope остаётся unanswered, не расширять автоматически.
