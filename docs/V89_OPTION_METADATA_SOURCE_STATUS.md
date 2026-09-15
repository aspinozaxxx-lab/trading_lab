# V89: census завершён, описания RUNNING

Actual checkpoint2026-09-15T16:08:58UTC: unit active/running, тот же PID3208549 и
invocation8a874553a92f4860bc235656c6e4e9b0. 5896/40820 processed/requested/exact,
unavailable0/reused0, 23397538 raw bytes, updated16:08:57.292492UTC.
Final manifest отсутствует, writer не менялся. V91 source-bound mapper готов,
59 new /126 combined local tests PASS; полного V89 join ещё нет.
В16:16 завершён [V91 binding check восьми saved V88 descriptions](V91_OPTION_CONTRACT_MAPPING_RESULT.md):
7exact futures +1currency exclusion, без повторного HTTP; не economic universe и не
full V89 coverage. Raw source units/AlgoPack продолжаются независимо.

Новый whole-volume du16:08:59UTC: data5000705958 + source_evidence197321491 =5198027449
bytes (5.198GB), включая AlgoPack archive2280167368 + oldprocessed1456918554 =3737085922
(3.737GB). Allocated6048841728 (6.049GB), без models/runs/tmp; sequential snapshot.
Local2.720GB ниже — старый замер15:09:20UTC, не current unique сумма.

Previous checkpoint2026-09-15T15:39:01UTC: unit active/running, тотжеPID3208549 и
invocation8a874553a92f4860bc235656c6e4e9b0.2908/40820processed/exact descriptions,
unavailable0,reused0,requested2908,11048391rawbytes;updated15:39:01.846037UTC.
Finalmanifestabsent; canonicalwriter/configнеизменны. Старые5checksнерепетировались.
Параллельно[реализованV90adapter/ledgerbridge](V90_OPTION_STRIKE_CONVERGENCE_ADAPTER.md),
покаsynthetic-only/noeconomicrun. Ниже сохранёнprevioussnapshot15:12.

Checkpoint 2026-09-15T15:12:20UTC. [Протокол](V89_OPTION_METADATA_SOURCE.md).
Pre-census/pre-HTTP commit `cc4d737`, pushed; 25 local + 25 server tests PASS,
Ruff clean, server closure verified. После запуска расширенная локальная группа
V89/V88/weekly-source/V64:44tests PASS, без новых economic values. Seal:
`1c71ebb0df2a69ce45b9dcf5ae00400fbf228f7a7feec9d26e68923b4ea19f5d`.
Это source-only подготовка нового reported-OI expiry mechanism, не economic screen.

## Завершённый census

Root: `/srv/trading_lab_data/source_evidence/v89_option_metadata_census_v1`.
Completed `2026-09-15T15:07:09.592000+00:00`; terminal PID0/exit0/inactive/dead
наблюдался 15:08:04UTC. Unit `trading-lab-v89-option-census-1c71ebb0df2a.service`,
launch invocation `98d72bc28461490191015a51ff196d9b`, PID3199650.
Manifest SHA `e990fdc9d091d7a0abab7d3f3c329e14053e3771b96d934d2ccd4b171dfd26d1`.
Artifacts verified before acquisition:

- contracts.parquet: `07b242ef8f9151aa4c7bad9a5bbcbcbd8a9ef829e4cb44d4f0c494f24c1c256e`.
- presence_by_asset_year.parquet: `e4917f7f8a40c6b3245157dfa109d7ed509efa5ed51db550fc877090ccf5216d`.

1327744 rows, 211024 non-NULL OI / 1116720 NULL; числовые величины OI не читались.
Все 108104 SECIDs сохранены, из них 40820 нуждаются в description и 67284 полностью
NULL остаются в inventory. Non-NULL не означает positive/finite/usable OI.

| Asset | Все SECIDs | Нужны descriptions | Non-NULL rows |
| --- | ---: | ---: | ---: |
| BR | 30634 | 8944 | 32295 |
| MIX | 6224 | 1569 | 12408 |
| RI | 21388 | 9846 | 55591 |
| SI | 49858 | 20461 | 110730 |

## Текущий writer

Root: `/srv/trading_lab_data/source_evidence/v89_option_metadata_source_v1`.
Unit: `trading-lab-v89-option-metadata-1c71ebb0df2a.service`.
Started `2026-09-15T15:09:25.549784+00:00`.
Actual 15:12:20UTC: active/running, PID3208549,
invocation `8a874553a92f4860bc235656c6e4e9b0`.
297/40820 processed, 297 HTTP requests / 297 exact descriptions, unavailable0,
reference reused0 пока, new raw1118174bytes. Final manifest отсутствует.
Пять первых новых raw проверены отдельно по hash/length/HTTP/identity. Это не full audit
будущих 40820 responses. BR examples имеют exact SERIES_NAME и underlying BRG1/BRH1;
canonical plan sample содержит `BR:BRG1:2021-02-01`. Полный join ещё не выполнялся.
Active-map SHA проверен; читались только dates/IDs, без market values.

Restart=no, RuntimeMaxSec864000, MemoryMax2G, Nice10, UMask0027; UID999/GID989.
Новый public ISS service запущен **без** EnvironmentFile/credentials. Основные AlgoPack
services не изменены. Не перезапускать этот root; при failure сохранять partial raw и
делать отдельный continuation с reference reuse. V88 root обязателен для старых ссылок.
Не считать RUNNING checkpoint доказательством актуальной жизни после этого времени.

## Объём всех данных и параллельный AlgoPack

Измерение server `du` 15:08UTC, apparent bytes (сжатый сохранённый архив, не decoded size):

| Каталог | Bytes | Decimal GB |
| --- | ---: | ---: |
| data/algopack-archive | 2034059450 | 2.034 |
| data/processed/algopack, отдельная старая history + samples | 1456918554 | 1.457 |
| Эти два AlgoPack roots вместе | 3490978004 | 3.491 |
| Весь server data | 4749973781 | 4.750 |
| server source_evidence | 151640987 | 0.152 |
| Всего server data + source_evidence | 4901614768 | 4.902 |

Allocated: data5503385600 + source153509888 =5656895488bytes (5.657GB).
Оба server totals включают AlgoPack; не прибавлять его второй раз. Models/runs/tmp
исключены. Из-за параллельной записи это последовательный snapshot, не атомарный census.
Локально в `D:\Projects\trading_lab_data\data` на15:09:20UTC:10841files,
2719842747bytes (2.720GB). Не складывать с server как unique corpus: есть копии.

Основной archive actual15:08UTC active/running, PID1663880, прежний invocation:
2492/26305jobs,30197166rows,31908pages,failed0,blocked0,
1792478834storedbytes по завершённым jobs. Updated15:07:55.826700UTC,
currentfx/alerts2025-07-08. Final manifest отсутствует.
FUTOI V4 actualactive/running, PID2522946, прежний invocation:
429/2192days,5655556logicalrows/3358619new-rootrows,17380ticker-days,
17158resolved/222unresolved,28dayswithgaps,7524reference-reusedpages,
67181463new-rootstoredbytes. Updated15:08:03.690929UTC,current2024-10-30,VB44/46.
Final manifest отсутствует. Unresolved/gaps не превращать в complete coverage.

## Что изменилось для исследования

Теперь есть точный конечный план acquisition вместо догадки о 108104 HTTP requests.
Новые series/type/underlying поля доступны в первых BR карточках. Числовые OI,
market prices/returns/labels/targets/PnL в V89 не читались, original PIT/full underlying
mapping/economic/live admission false. Воронка прежняя:25 screens V65–V87,
21 rejected +1 incomplete +3 invalid,0 Stage2, цель20–50% не подтверждена.
Следующее правило и execution caveats: [research note](OPTION_PINNING_RESEARCH_NOTE_20260915.md).
Не ждать таймер минутным polling: подготовить bounded synthetic adapter; после source
closure один mapping/coverage check и отдельный economic seal перед values.
