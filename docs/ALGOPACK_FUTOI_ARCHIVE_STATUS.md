# FUTOI full-market archive: V3 RUNNING

Снимок2026-09-15T09:00:00.974609UTC. Это operational checkpoint, НЕ полный архив
и не новая стратегия. [Разрешение](ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md),
[актуальный sealed протокол](ALGOPACK_FUTOI_ARCHIVE_V3.md).

## Что работает

- gpu-mlserver unit trading-lab-algopack-futoi-archive-v3-721f2418b0dc.service,
  MainPID1913099, active/running; начало2026-09-15T08:58:37.517695UTC.
  Invocation b92369457f26436dad586a928c01da82. Result=success/ExecMainStatus0 во время
  active не означает завершение.
- Root /srv/trading_lab_data/data/algopack-archive/algopack_futoi_archive_v3_721f2418b0dc.
  4/2192completed calendar days,147ticker-days,48876intraday rows по completed days.
  Current2025-12-29:43/64tickers обработано; partial day's rows ещё не входят в totals.
  10266intraday rows в новом V3 root,120V2pages reference-reused, core4reuse0.
  201989compressed+page-metadata bytes по completed days только в новом root:
  это НЕ размер всего logical archive и не включает V2/current partial day.
- Final root manifest отсутствует. Schema13columns, включая trade_session_date.
  Пул определяется отдельно для каждой исторической даты;46/37/64tickers в3pilots.
- [Независимый14-family batch](ALGOPACK_ARCHIVE_V1_STATUS.md) по-прежнему работает,
  PID1663880. На08:59:25UTC338/26305jobs,4772919rows,4980pages,
  284104725bytes по completedjobs,0failed/0blocked. Его код/unit не менялись.

## Проверенные контрольные дни

Для всех150raw pages трёх дней выполнен отдельный read-only replay: actual gzip/raw
SHA, page-metadata SHA, exact URL/date/width/cap/duplicate/group guards, manifest
universe/counts и exact global-final-point proofs. Все3PASS, без повторного HTTP,
перезаписи страниц или source admission для экономического теста.

| Date | Tickers | Intraday rows | Raw pages | Reused V2 pages | Day manifest SHA256 |
| --- | ---: | ---: | ---: | ---: | --- |
| 2024-10-15 | 46 | 15050 | 47 | 47 | c90c10f8507cac2bd104b365801847196869c1b333ad9c873c6d1e3611adb494 |
| 2020-05-04 | 37 | 11899 | 38 | 38 | 81b1de1462fcf3b8c5308ad86818eb09173065d6095a36a699b4a90e79af40e7 |
| 2025-12-30 | 64 | 21927 | 65 | 35 | 2e0d353584f1872cc54f5aae9a0589b6d5ce989b1bbf9aaeec5e2408417617f4 |

VI содержит только FIZ на последних срезах:166/163/174unpaired sequence points;
у MY2025-12-30 ещё171unpaired points. Они сохранены, не заполнены нулями и не удалены.
Это качество source, не готовность FIZ-minus-YUR признака. trade_session_date может
указывать следующую сессию2026 при observation tradedate2025; это не2026 trading outcome.

## Что обязательно сохранить вместе

1. V3 root выше: новые страницы и итоговые referencing manifests.
2. /srv/trading_lab_data/data/algopack-archive/algopack_futoi_archive_v2_345204a8a962:
   120immutable pages, используемые V3 по ссылкам. V2 failed, НЕ перезапускать/удалять.
   V3 удерживает его существующий writer lock read-only, чтобы исключить второго writer.
3. /srv/trading_lab_data/data/algopack-archive/futoi_core4_preserved_20260831:
   точная78,726,995byte копия5файлов прежнего core4. Manifest
   cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed;
   all4artifact SHA+5872coverage/proof keys/2015624rows checked before HTTP.
   Исходник D:\Projects\trading_lab_data\data\processed\info_radar\moex-futoi-intraday-dev-2020-2025-v2
   сохранён. Ничего не перемещалось и не удалялось. Новая13-column history не заменяется
   старой12-column, поэтому observed core4reuse пока0.

Полного Windows зеркала НОВЫХ больших архивов сейчас нет. Нельзя считать V3-only backup
самодостаточным: он ссылается на V2 и потенциально core4. Raw/model/run данные вне Git.

## История технических исправлений

- V1 seal8cb976fa0276ed76cc704f2c5f104bdd0d7a307d7c44c9bf7edb1933cb9a7ff2,
  pre-request5af65e1, local62/server62tests. Unit
  trading-lab-algopack-futoi-archive-v1-8cb976fa0276.service started08:38:18UTC,
  затем unpaired_sequence,0saved pages; failed root сохранён.
- V2 seal345204a8a9624fa5f6778107193187e4e14edd72d195da28d920eb8ec2e73ca8,
  pre-requestc4a4ecf, local94/server94tests. Unit
  trading-lab-algopack-futoi-archive-v2-345204a8a962.service started08:44:37UTC,
  2complete days/120pages, затем intraday_daily_latest_mismatch на MY третьего дня.
  Source audit: FIZ final row совпала; лишним для сравнения был YUR11:55 вместо
  общего final23:50. V2 MainPID0/failed подтверждён до V3. Никакого PnL не было.
- V3 pre-request6601bb3. Новый narrow adapter поверх frozen V2 primitives, без
  изменения старых модулей, нового engine или изменения trading rule. Исправлен
  только final common sequence proof, все raw rows сохранены. Local103/server103tests
  PASS, Ruff clean; pre-HTTP whole closure/core/prior120page inventory PASS.

Актуальный V3seal721f2418b0dcbfb65a76e45af387b4c7da9964276ba67e81db500dd45400c69b;
config SHA14ae607e0a42708a59e40f07951265ebe614988efe3d9515f8f54049ea47de72.
V2 inventory f87c78960dac533ea64477f2205210801851ca7162a17d7f1290ba9a1b658e31,
identity257e6587a030bff24a43db2e5fc60e955aec04782a8dca7727e897d13ceeab48,
status12f68327b7adea5cf9b3f5187d63006c3bb9850e8788d12cde403bcf97e7f8b3.
V3 transfer c653f63ff0365ef97e4bd232568040087e627a61eceb61ec96ba0e0151e8fd67;
V2 transfer91d2dd6145886e88c59aaec30913c6c296eb881c9110849e57bd1c570bc8c845;
V1 transfer906ce42448530788ce78ae3866f7b149ae4c411f81605c47b7354888c8a66ca9;
core transfereea7e593193f6dd155130ec37e8eca46ad63bbd98946c3219409c74d90109b2d.
Все tar SHA совпали local/server; existing files не redeploy/overwrite.

## Продолжение без нового скачивания уже сохранённых страниц

Не опрашивать service поминутно вместо поиска новых гипотез. Если он active, оставить
его работать; SSH/tool handle завершён, service независим. V1/V2 НЕ запускать.
При реально stopped сначала status/stopped evidence, code seal, source failure и
свободное место. current-only/undated routes и защиту2026 не ослаблять.

V3 Restart=no, transient unit не boot-persistent. После расследования ошибки тот же
loaded terminal unit можно возобновить systemctl start с неизменной identity. После
reboot/исчезновения unit восстановить exact systemd-run только при отсутствии writer
и final manifest. Required invocation:

```sh
systemd-run --unit=trading-lab-algopack-futoi-archive-v3-721f2418b0dc \
  --uid=trading-lab --gid=trading-lab --working-directory=/opt/trading_lab \
  --property=Type=exec --property=EnvironmentFile=/etc/trading-lab/collector.env \
  --setenv=REQUESTS_CA_BUNDLE=/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem \
  --property=NoNewPrivileges=yes --property=ProtectSystem=strict \
  --property=ProtectHome=yes --property=PrivateTmp=yes \
  --property=ReadWritePaths=/srv/trading_lab_data/data/algopack-archive \
  --property=MemoryMax=2G --property=Nice=10 --property=IOWeight=50 \
  --property=Restart=no --property=RuntimeMaxSec=864000 \
  /opt/trading_lab/.venv/bin/python -m market_lab.futures.algopack_futoi_archive_v3 \
  --seal-sha256 721f2418b0dcbfb65a76e45af387b4c7da9964276ba67e81db500dd45400c69b
```

После terminal сверить2192=complete/empty, все discovered ticker plans и все page
references/hashes. Failed/stopped не полный архив. Credential только existing server
env, original-version/economic/live flagsfalse, тариф/покупки/автопродление/Windows
tasks/old paper не менялись. Безусловные права использования после expiry не доказаны.
V79 остаётся3REJECT_STAGE1, V65–V79count22/0Stage2; цель20–50% не достигнута.
