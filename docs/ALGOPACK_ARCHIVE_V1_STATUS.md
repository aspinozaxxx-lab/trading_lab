# AlgoPack archive V1: RUNNING, сохранение до окончания подписки

Актуальный checkpoint2026-09-15T13:47:00UTC: основной unit active/running,
MainPID1663880,1963/26305completed jobs,24634122rows,25973pages,failed0/blocked0;
stored_bytes1465733921completedjobs. CurrentEQOrderStats2025-08-14,
status.updated_at13:46:58.750161UTC. Final manifest отсутствует, unit неизменён.
FUTOIV4active/runningPID2522946:294/2192processed days,4261365logicalrows,
13125resolved/68unresolvedticker-days,6gapdays;finalmanifestabsent.
ВесьAlgoPack apparent1670849835bytes (1,671GB),allocated2094641152bytes (2,095GB).
Serverdata4380590905bytes + source_evidence150734614bytes =4,531GB,includingarchive,
excludingmodels/runs/tmp. Server/local не складыватькакdeduplicatedcorpus.
V86economiccontest параллельно завершён, [INVALID result](V86_STEO_REVISIONS_RESULT.md).
Downloader/runtime/seal/Windows schedules не менялись. Files grow without economic PASS.

Предыдущий checkpoint2026-09-15T12:41:05.610159UTC: основной unit active/running,
MainPID1663880, прежний invocation;1583/26305completed jobs,20095301rows,
21175pages,1200372370stored bytes completedjobs,failed0/blocked0.
status.updated_at12:41:00.427669UTC,currenteq/tradestats,date2025-09-10.
Final manifest отсутствует. Основной service не менялся.
FUTOI V3 остановился; [V4 correction теперь RUNNING](ALGOPACK_FUTOI_ARCHIVE_STATUS.md),
PID2522946,185processed days/3073888rows,47unresolved ticker-days явно сохранены.
Нельзя объявлять оба service running по более старому snapshot ниже.

По запросу пользователя actual du на12:41:05UTC: весь AlgoPack archive включая
FUTOI/oldcore4 —1375471252apparent bytes (1,375GB),1706717184allocated bytes (1,707GB).
Это lossless compressed raw + metadata, не распакованный объём и не сумма logical rows.
Основной server data root4080174365bytes (4,080GB), включая этот архив.
Local data folder2719842747bytes (2,720GB),10841files; не складывать как unique corpus
из-за дублей. Models/runs/tmp не включены. Main counters выше относятся только к
completed jobs, поэтому не равны размеру всего каталога. Экономический V84 параллельно
завершён, [результат](V84_STOCK_PERPETUAL_BASIS_RESULT.md), не новый income PASS.

Исторический снимок 2026-09-15T11:14:18.760792+00:00. Это промежуточный operational результат, НЕ полный архив.
[Разрешение](ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md),
[замороженный протокол](ALGOPACK_ARCHIVE_V1.md).

## Что реально работает

- Server gpu-mlserver, unit trading-lab-algopack-archive-v1-5b7c66fa0e04.service.
- После source audit systemctl подтвердил active/running, MainPID1663880,
  начало2026-09-15T07:51:16UTC. Result=success/ExecMainStatus0 во время active
  НЕ означает завершение; смотреть ActiveState/SubState/MainPID и final manifest.
- Root: /srv/trading_lab_data/data/algopack-archive/algopack_archive_v1_5b7c66fa0e04.
- 1106/26305 completed day/dataset jobs,
  14000122 rows, 14747 pages, failed0, blocked datasets0.
  837551970bytes compressed+page metadata по завершённым jobs;
  это не весь disk usage и не учитывает ещё не завершённый текущий день.
  status.updated_at11:14:13.912672UTC,current_dataset fx/alerts,current_date2025-10-15.
- 14families EQ/FO/FX,2020–2025 (Alerts2024–2025), все API fields, исходные bytes
  lossless gzip. Никаких2026 prices, fit, PnL в collector, broker или Windows tasks.
- Оставшийся объём зависит от фактического числа страниц; может занять несколько дней.
  Это оценка по наблюдаемой скорости, не обещанный срок или подтверждённая дата expiry.

Actual systemctl по-прежнему active/running, тот жеPID1663880 и invocation
d562f0748c4341b48eb7f4d34d64b4a1. Final manifest отсутствует. Свободно899059843072bytes
на общем storage в момент снимка. С прошлого checkpoint688jobs/9002346rows прогресс
реальный; V81/V82 component diagnostics не меняли этот service.

Все14routes дали ожидаемую схему на первом дне2024-10-15. Отдельно проверены raw gzip/
SHA/metadata/cursor/date для всех183pages/173439rows этого дня,14/14PASS. FXAlerts
вернул0rows; EMPTY не ошибка, но один пустой день не доказывает отсутствие истории.
Остальные completed pages проверяются при сохранении; глобальный завершающий audit
ещё не выполнялся. Полный archive manifest пока не опубликован.

| Dataset | Rows первого дня | Pages | Fields | Day-manifest SHA256 |
| --- | ---: | ---: | ---: | --- |
| eq/tradestats | 21819 | 22 | 27 | 25403e53eaf4c8b5bc49738d215a9e929ed5de3adcd046390861d949e37c41ae |
| eq/obstats | 39445 | 40 | 21 | de24335c5eff9d2bd5e32aaed5d781d717661cceb297057947953de42c6e18f7 |
| eq/orderstats | 28399 | 29 | 26 | 9328f8d1ed043b6264a691663c0dd4f21f6a11453c712ee6dffdff3c11cd8cf1 |
| fo/tradestats | 15023 | 16 | 33 | 8e3201fdbf14e3e7b872122d0b323d41ca022d578890b5ce71b7d489aa7c1475 |
| fo/obstats | 65550 | 66 | 35 | 2903097c11d58504adcf81ec3d2daf2df82f95c812c437cc955bd4544ec6e0b9 |
| fx/tradestats | 203 | 1 | 27 | e934217c3c355468d5f6120f07e907589006cb15e55175116fc2805d81ba576b |
| fx/obstats | 216 | 1 | 30 | 4d2267eca249f520b62ba27565bbd38e414f92dac140bb1e6b2be0bdfb120e56 |
| fx/orderstats | 202 | 1 | 20 | 44213a16b46ce83405b6299a7fe64d76cc835cf0c75a839b8552da656fa38343 |
| eq/hi2 | 1089 | 2 | 7 | 85c0cbe65cba79648a8e5a81b843375ba3fad1b409b0945bb9780f520fd0ad21 |
| fo/hi2 | 858 | 1 | 8 | 8a4b40e5024c30e46039c3235305a22c8e4e07518365a66404a7a59ff38a4a38 |
| fx/hi2 | 55 | 1 | 7 | 7d6a223282c66c59ce6e10513e580f8ed6de28c32a40e1b6c38ec6f8af2047de |
| eq/alerts | 328 | 1 | 8 | 8d662458bd200395ef3dc110464e98485b0c12e2da70d1b5e58d30ee47f13cae |
| fo/alerts | 252 | 1 | 9 | ede060579282c2ca42b012a118e5e08aa36a98cd7215098262a3c0a050f6d34a |
| fx/alerts | 0 | 1 | 8 | 26d4f54c3d42b50cfea954d82179918b4d4c6aa26c93a7e44f8c8ef8d4d4db31 |

## Идентичность

Pre-request commit5bf0f90; archive config SHA
61e160297bf4d62f18c80f86fc839d92db1e490c2599b4b483225134a0c6eedc;
seal5b7c66fa0e0446eb3b395d3776c4496907e2c4cc760c5a87bc38e57da32f97e0.
8file closure verified до HTTP. Local30/server30tests PASS; Ruff clean.
Transfer tar d30c9fd15659f0ae0db0c014dc2f3879e5875cff75fc2ba716609329f608ef30
совпал local/server. Initial deployment прошёл, затем отдельный shell Python-c verify
получил quoting SyntaxError ДО network. Исправлен только способ invocation через stdin;
повторной deployment/tests/загрузки данных не было. Настоящий seal verification PASS
предшествовал единственному запуску service.

## Продолжение и завершение

1. Не запускать второго writer, пока systemctl подтверждает этот MainPID/active.
   SSH/tool observation timeout не означает остановку. Не опрашивать timer поминутно
   вместо другой полезной работы. Это bounded archive service, не timer ожидания paper.
2. При фактическом stopped/failed проверить status.json и stopped/failure records.
   401 означает потерю доступа, не разрешение платить; 429/transport уже имеют
   ограниченные retries. Сначала причина, затем явный resume той же code/config identity.
   systemd Restart=no: после исчерпания retries нужен отдельный resume, не обещать autoheal.
3. Пока transient unit загружен и действительно terminal, systemctl start того же
   unit повторяет проверенный command. При исчезнувшем unit воспроизвести первоначальный
   systemd-run с exact seal/User/EnvFile/CA; не менять source protocol или старые файлы.
   После server reboot transient unit сам не восстанавливается. Живость/наличие output
   проверять до любого перезапуска; completed global manifest запрещает повторный run.
4. По окончании проверить planned26305=complete/empty+failed+unattempted, все day/page
   identities и bounded dates. Только тогда объявлять полноту по конкретным наборам.
   PARTIAL_UNAVAILABLE_DATASETS/STOPPED_INCOMPLETE нельзя выдавать за полную копию.
5. Большие данные остаются вне Git. Полное зеркало на Windows сейчас НЕ создано.
   Перед будущей локальной резервной копией сверить размер и свободное место;
   текущий Get-PSDrive D показал256924540928free bytes, server перед запуском
   900594368512free bytes. Get-Volume D оказался неподходящим к этому mount;
   это не отсутствие самого каталога D. Ничего не удалялось/не переносилось.

FUTOI core4 history ранее сохранена отдельно; она не входит в14routes и не заменяет
full-market FUTOI archive. [Отдельный V3 supplement теперь RUNNING](
ALGOPACK_FUTOI_ARCHIVE_STATUS.md):3pilot/150pages audited PASS,120V2pages reused,
127/2192complete days/2259693intraday rows на11:14:18UTC. Full archive ещё не complete;
V1/V2 technical failed roots сохранены и не перезапускаются. По
[официальной FUTOI документации](https://moexalgo.github.io/docs/api/get-all-futoi/)
анонимный доступ задержан, поэтому сначала сохраняются подписочные SuperCandles/HI2/Alerts.
Current-only quote streams не являются доступным полным историческим архивом.
Не утверждать, что весь продукт AlgoPack уже скопирован или что сохранение чисел даёт
original-version/PIT/live admission. Подписка/автопродление/тариф не менялись.

Экономический результат отдельного быстрого конкурса: [V79 R1](V79_ALGOPACK_FAST_SCREEN_RESULT.md),
3REJECT_STAGE1. Сбор не объявляется подтверждением20–50% доходности.
