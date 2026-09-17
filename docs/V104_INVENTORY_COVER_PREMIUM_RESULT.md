# V104 — расчёт завершён, INVALID_EXECUTION_NO_PROMOTION

Единственный economic run завершён **2026-09-16 23:59:56.755827 UTC**.
Преимущества перед постоянной позицией в нефти не получено. Даже диагностические
результаты ниже Stage1 gates и пользовательской цели20–50%; последние три года
убыточны. Дополнительно все четыре сценария не прошли execution gate из-за
gross-risk counters. Это **не подтверждённая исполнимая доходность**, не Stage2 и
не валидная статистическая фальсификация всех возможных inventory-premium моделей.

## Что проверено и все результаты

[Зафиксированное правило](V104_INVENTORY_COVER_PREMIUM.md): отношение коммерческих
запасов нефти США к загрузке НПЗ в днях; если оно ниже среднего для того же месяца
за пять предыдущих календарных лет — BR long0.9, иначе cash. По >=3 пригодные
недели в каждом year/month, равные веса yearly means, first usable published vintage.
Это current stock/use **level**, не V17 composite недельных изменений. Контроль —
постоянная long0.9 позиция на том же календаре доступности источника.

2021-01-04…2025-12-30,1271сессия,1млнRUB начального капитала, interest0.
Source2012–2020 только для causal warmup, не fitted model или outcome selection.
Прежний daily-open/spec-proxy ledger; история уже просмотрена, не unseen holdout.

| Сценарий, только диагностика | CAGR | Sharpe | MDD | Round trips | Конечный капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary base | +4.5010% | 0.29671 | 44.1430% | 58 | 1245460.79 |
| Primary double | +3.2064% | 0.24927 | 46.1466% | 58 | 1170408.61 |
| Constant-long base | +11.4097% | 0.52448 | 43.2557% | 62 | 1713741.57 |
| Constant-long double | +10.5425% | 0.49631 | 44.8493% | 62 | 1648258.34 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | +15.8003% | +15.4609% | +58.4862% | +57.4386% |
| 2022 | +30.9591% | +28.2526% | +29.4028% | +28.9999% |
| 2023 | −14.0436% | −15.3897% | −13.5970% | −14.3920% |
| 2024 | −0.5254% | −1.4689% | +0.6897% | −0.5258% |
| 2025 | −3.9506% | −5.1932% | −3.9502% | −4.6985% |

Primary имеет2 положительных года из5; control3 при base и2 при double. Показатель
запасов пропустил большую часть роста2021, а просадку не снизил. Это описательное
сравнение сохранённых сценариев, не разрешение подобрать другой период/знак/порог.
Контроль не продвигается: у него тоже execution-invalid, высокая просадка и CAGR<20%.

Primary gross VM PnL287417.57/251336.28RUB, costs41956.79/80927.66,
net245460.79/170408.61. Control gross774241.10/767311.97, costs60499.53/119053.62,
net713741.57/648258.34. Издержки меняют дальнейший капитал и integer sizing;
сценарии не являются вычитанием двух разных комиссий из одного ряда позиций.

## Покрытие, риск и gates

- 728 source-calendar issues,727 наблюдаемых stock/use ratios,465 ready states
  после пятигодичного seasonal warmup,327 scarcity states по всей source history.
  Stale2019-07-03 сохранён unready строкой, не заменён предыдущим good release.
- На arm1271решение; primary1077nonzero targets/218used releases,
  control1267/259. Feature unavailable0, source plan unavailable1, stale-at-fill2
  в обоих вариантах. Frozen readiness99.8426%, дополнительная descriptive joint
  feature/plan/fill readiness99.7640%; последний показатель не новый tuned gate.
- Primary58entries/58roundtrips,296/281filled legs,1078exposed asset-sessions.
  Control62/62,350/337filled legs,1267exposed asset-sessions. Роллы входят в round
  trips, это не58/62независимых макронаблюдения. Halt carry не удаляется ради counts.
- **Все4execution_complete=false**. Primary critical_failure_count2/1,
  control2/2; целиком совпадают с gross_limit_rejection_count2/1/2/2.
  Unresolved halts0 и terminal_carried=false у всех. Эти aggregate counters не
  обнулены; конкретные даты/заявки срабатывания независимо не реконструированы.
  Их нельзя называть соответственно2/1/2/2доказанными неисполненными orders.
- Unknown contract/open/settle/point/tick/fee/margin/liquidity counters0;
  participation/initial-margin/atomic rejection0. Factual halt/mark/carry по1.
  Cancel no-open1; cancel no-liquidity1 primary /2control. Participation clip0.
- Max close gross leverage1.12988/1.07139 primary и1.08793/1.09484 control;
  target0.9 не гарантирует fixed realized leverage. Max participation .61266%
  primary/.83957%control. Intraday adverse MDD45.8893%/47.8849%primary,
  45.0428%/46.5511%control, отдельно от close MDD в gates.
- Turnover/start capital152.2544/146.6348primary,214.7819/211.3387control.

Coverage, >=20trips и пять yearly segments прошли. Execution не прошёл у всех.
Для primary в обоих costs провалены CAGR>=5%,Sharpe>=.5,MDD<=25%,>=3positiveyears,
beats-control и excess>=2п.п.; worstyear>=−15% прошёл только base. Historical20/50
и goal_verified=false. Числа ниже даже component gates не дают основания исправлять
weak branch до её продвижения или ослаблять общие risk gates после результата.

Воронка: **35 portfolio =28 REJECT_STAGE1 +1 REJECT_STAGE2 +1 incomplete +5 invalid**,
активных Stage2/Stage3кандидатов0. V93 отдельно; V102source-only не economic entrant.
V104 добавляет одну invalid гипотезу, не четыре. Цель20–50%остаётся активной.

## Provenance и сохранение

- Pre-outcome commit/push `a746304dd196a0c9ce91f1d5c6fa1da2e63c5d54`.
- Seal `7ad56a39820717a7f65f934fb483c1a3ff2c9bd28b6c95c4abce4123fbe629fd`.
  Config `10a2aa15de016e5e28c92795f377069b19d50c5d5344ebe55a293da9c4f004a5`,
  code `e2fc435e8e1349b908a62045dae37992bb16fd6929c2c02e86c2b91b722948c5`.
  Six direct hashes плюс V101/V64 transitive source/code/execution closure.
- 16new/95combined local testsPASS17.90s,95serverPASS6.55s,Ruffclean. До seal
  исправлено распознавание string release_date в metadata-only stale exclusion;
  ни economic run, ни numeric source states до seal не запускались.
- Источник уже находился в локальном архиве. На сервере canonical EIA root был
  проверен отсутствующим; пять старых byte-identical файлов перенесены один раз,
  существующие файлы не заменялись. Source manifest
  `aac389628b61df446616cd171084af81482d09a7d4b403337a8332b5373c142b`;
  source-transfer bundle `f1ae2efe57dc80ea8d7c828cf4bcf9b4bb0fff542fe395318e1e5249432ea068`.
  Code-transfer bundle `5c1218cacee6dd3c2e510b713d8a7c7cae811f294abc4c961e8b57aaea0146b8`.
  Это не новый corpus/parser/download: fresh EIA HTTP requests0.
- До числового чтения прошли source artifact SHA/schema/date gates и V64 metadata
  preflight, включая запуск от service user999. Source: U.S. Energy Information
  Administration, WPSR Table1, release dates2012-01-05…2025-12-29; историческая
  immutability/original receipt остаются unproved, development admission прежнее.
- Unit `trading-lab-v104-inventory-cover-7ad56a398207.service`, invocation
  `06b1c1b580dd443083e498ee1962860a`; журнал этой invocation содержит ровно четыре
  completed cases23:59:55…23:59:56UTC. На позднем systemctl-чтении LoadState=not-found,
  inactive/dead и пустая InvocationID; значения Result/ExitStatus выгруженного
  transient unit сами по себе не доказательство. Completion подтверждён manifest
  и журналом исходной invocation, не вымышленным сохранённым live handle.
- UID999/GID989,NoNewPrivileges,PrivateTmp,ProtectSystem=strict,CPUQuota100%,
  MemoryMax2G,write root только runs; no EnvironmentFile/credentials/Windowscollector.
- Run `/srv/trading_lab_data/runs/v104_inventory_cover_premium_v1_7ad56a398207`.
  Manifest `20c979ed40fa51466d1b5b8f7c5b9eec748e83a4fabd07849afe02ac70d0e7ce`;
  metrics `e39f3a70b56c2a4f47b21ee4793c0834d6398143c3399bfcf91ba791ec61e396`.
- Audit **2026-09-17T00:01:13.349464UTC**:18artifact hashes,728recomputed source
  states,2target frames по1271rows,4cash continuity/daily identity/order-cost/
  metrics/annual/position-count replays и frozen assessment PASS. Это не повторный
  economic run и не независимая реконструкция всех gross-risk counters.
- Backup19files/822012compressed bytes,
  `99b94a9a2e70852f8c0e72fc84e3c6f92f429d9e488e22257a09b050d038ccf7`.
  Локальная копия `D:\Projects\trading_lab_data\runs\v104_inventory_cover_premium_v1_7ad56a398207`:
  после переноса18artifact hashes+manifestPASS.
  Canonical и sealed code/config после outcomes не изменялись; raw/runs вне Git.

Дальше не повторять V104, не tune-ить cover/season/window/sign/TTL/size/control.
Следующий ограниченный review на готовых данных — **разброс прогнозов CBR macro
survey**, не медианные revisions V21. В source-code/catalog уже есть p10/p90 и
девять statistics; сами dispersion values/новые outcomes ещё не читались, config
V105 не создан. Сначала проверить новизну, causal metadata coverage и независимый
экономический механизм; недостаточное покрытие означает отказ без большого parser.
Не добавлять каналы/пороги к старому V21 composite и не ослаблять его timing.

## Основной AlgoPack archive параллельно

На **17 сентября03:02МСК /00:02UTC** unit active/running, прежние PID1663880 и
invocation `d562f0748c4341b48eb7f4d34d64b4a1`; не перезапускался.
18153/26305jobs(**69.0097%**),164116081rows,176905pages,failed0/blocked0,
9703018417completed-job bytes,updated00:02:47.458584UTC. Final manifest absent,
архив ещё не complete. Доля jobs не доля итоговых байтов или времени.

Раздельные последовательные `du -sb`, закончены00:02:50.796131UTC:
archive10348442298 + earlierprocessed1456918554 = **11805360852bytes/11.805GB AlgoPack**;
data13205174371 + source_evidence559319597 = **13764493968bytes/13.764GB всего**.
AlgoPack уже входит в итог. Apparent bytes при записи, без models/runs/tmp/transfers,
не byte-level dedup и не точное физическое место на диске. Копия старого EIA добавлена
в server data; это не новый уникальный источник относительно локального архива.

Локальный последний отдельный замер предыдущего turn23:26UTC:2.747GBdata+source,
не обновлялся; часть — серверные копии, не прибавлять как unique data. Новые result
backup находятся в runs и не входят в data/source объём. FUTOI остаётся terminal
COMPLETE_WITH_SOURCE_GAPS с550unresolvedticker-days; его audit не повторялся.
Main failed0 не означает устранение FUTOI gaps. Broad AlgoPack scope не расширялся,
2026 защищён,TIC paused, live/demo/покупки не разрешались этим run.
