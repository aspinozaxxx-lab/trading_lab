# V103 — премия за неликвидность: REJECT_STAGE1

Единственный economic run завершён **2026-09-16 23:29:52.849986 UTC**.
Зафиксированное правило не прошло первый отбор: основной и обратный варианты
убыточны. Нового Stage2-кандидата нет; цель относительно предсказуемых 20–50%
годовых не достигнута. Параметры, знак, окно, активы и плечо больше не подбирать.
Это результат конкретного development screen, не доказательство отсутствия любой
премии за неликвидность и не независимое подтверждение на новых данных.

## Что проверено

[Протокол](V103_ILLIQUIDITY_PREMIUM.md): ежемесячно long самый высокий / short самый
низкий 63-session absolute-return-to-notional-volume proxy, веса +0.45/−0.45,
BR/MIX/RI/SI. Признак заканчивается строго предыдущей завершённой сессией;
same-contract returns, lagged sizing point value, полное окно, без заполнения
неизвестных данных нулями. Контроль — заранее объявленный точный sign mirror.
Daily resize/roll и integer execution — прежний ledger. Новых HTTP, collector,
source parser, обучения модели или поиска параметров не было.

Экономика: 2021-01-04…2025-12-30, 1271 сессия, начальный капитал 1 млн RUB,
процент на свободные деньги 0. История 2018–2020 нужна только для warmup; она не
входит в PnL. Рыночные исходы 2026 не использовались. Исполнение research-spec-proxy,
не доказанный broker-exact результат и не разрешение демо/live.

## Все варианты и годы

| Вариант | CAGR | Sharpe | MDD | Round trips | Конечный капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, base costs | −3.1976% | −0.13765 | 40.8299% | 61 | 850416.87 |
| Primary, double costs | −3.1702% | −0.13632 | 41.1017% | 61 | 851619.78 |
| Mirror, base costs | −1.4459% | −0.01311 | 28.7542% | 63 | 929959.31 |
| Mirror, double costs | −0.6929% | 0.03442 | 28.2267% | 63 | 965928.83 |

| Год | Primary base | Primary double | Mirror base | Mirror double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | +6.2279% | +6.0426% | −7.3063% | −7.3888% |
| 2022 | −22.1505% | −22.4825% | +12.8574% | +15.1473% |
| 2023 | −6.9266% | −6.8249% | +5.0739% | +5.0056% |
| 2024 | −9.1070% | −9.0759% | +8.7715% | +9.6294% |
| 2025 | +21.5574% | +22.2888% | −22.2190% | −21.3157% |

Primary: только 2 положительных года из 5, худший год −22.1505%/−22.4825%.
У mirror 3 положительных года, но итоговая доходность также отрицательна; выбор
обратного направления после результата запрещён и здесь даже не даёт кандидата.

Primary gross VM PnL −142375.71/−134293.50 RUB, издержки 7207.41/14086.72,
net −149583.13/−148380.22. Mirror gross −60011.71/−14195.44, издержки
10028.98/19875.73, net −70040.69/−34071.17. Следовательно, дело не только в комиссиях:
gross PnL отрицателен во всех четырёх сценариях. Double costs меняют капитал и
последующие целочисленные размеры сделок, поэтому это не вычитание удвоенной суммы
из одного фиксированного ряда позиций; net/gross PnL не обязаны быть монотонными.
Все четыре результата сохранены, не отобран лучший сценарий.

## Покрытие, риск и причины отсева

- На каждый arm: 5084 asset-decisions за 1271 дату, 2404 nonzero targets.
  Feature unavailable 240, plan/source unavailable 32, stale-at-fill 0.
  Frozen feature/fill readiness **95.2793%**; дополнительная описательная joint
  feature/plan/fill readiness **94.6499%**, не новый gate после outcomes.
- 60 monthly-rebalance dates внутри evaluation, из них 57 ready. Счётчик
  `used_releases=58` переиспользован старым reporting adapter: здесь это **58
  состояний выбора**, включая carry от **2020-12-01**, а не 58 макрорелизов.
  В feature frame 8100 строк, 8060 наблюдаемых daily illiquidity ratios.
- Monthly nonzero targets: SI short 57 раз, BR long 14, MIX long 21, RI long 21.
  Это указывает на концентрацию ранжирования по инструментам; результат нельзя
  трактовать как независимую премию по четырём одинаковым рискам. Четыре рынка не
  beta/FX-neutral, показатель не фактическое воздействие заявки на стакан.
- Primary: 61 entries / 61 round trips, 231/222 filled legs, 2418 exposed
  asset-sessions. Mirror: 63/63, 217/220 filled legs, 2379 exposed asset-sessions.
  Роллы входят в round trips; это не 61/63 независимых наблюдения механизма.
- **Все четыре execution_complete=true, critical failures=0, unresolved halts=0,
  terminal_carried=false**; последняя дата содержит 4 flat asset rows.
  Неизвестные contract/open/settle/point/tick/fee/margin/liquidity counters — 0.
  Gross/margin/participation/atomic rejection counters — 0.
- При этом halts не удалены: factual halt/mark/carry — по 16 на каждый сценарий,
  target cancel no-open 16; no-liquidity cancel 4 primary / 3 mirror.
  Exposed-session count не обязан совпадать с количеством ненулевых intents.
- Max close gross leverage: primary .91680/.91963, mirror .92817/.91395;
  max participation .16340% primary / .18282% mirror. Intraday adverse MDD
  41.7996%/41.9477% primary, 29.3423%/28.8005% mirror, отдельно от close MDD в gates.
  Turnover/start capital: primary 47.9337/46.6454, mirror 62.2760/61.7939.

В обоих costs пройдены coverage, execution, >=50 trips и 5 yearly segments.
Провалены CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=3 positive years, worst year>=−15%,
превосходство над mirror и excess>=2 п.п. Historical20/50=false, goal_verified=false.
Порог 5% был только Stage1 component gate, не подмена пользовательской цели.

Воронка: **34 portfolio hypotheses = 28 REJECT_STAGE1 + 1 REJECT_STAGE2 +
1 incomplete + 4 invalid**, активных Stage2/Stage3 кандидатов 0. V93 — отдельный
component diagnostic; V102 не считается economic entrant, поскольку TIC source
не дошёл до экономического теста. Этот run добавляет один отсев, не четыре идеи.

## Воспроизводимость и сохранение

- Pre-outcome commit/push: `c068bea59ffc3978a6788c49eb7f4c1acffaf536`.
- Seal: `7d88dc5ca55e9510238930ed17c505ce5d6b342ba09968c8a4a54e7429f31041`.
- Config: `a16d81725e506dcffcf67da9b7d604950b8d854e50de60178c92bef35f63aa01`;
  отдельный `.sha256` сохранён. Code:
  `fa7a62e91efeb34087bfea49d263fb03c446f8605a13aa7571c1983d92d6d0b0`.
- Шесть direct file hashes, включая parent V101 seal и V94 synthetic fixture;
  transitive V64 input/code and V78 ledger closure. Exact input SHA/границы в
  протоколе; preflight bytes/schema/date прошёл до числового чтения.
- 13 новых / 79 combined local tests PASS за 8.41s, 79 server tests PASS за 2.95s,
  Ruff clean. Tests — проверка реализации, не доходность.
- Unit: `trading-lab-v103-illiquidity-7d88dc5ca55e.service`, invocation
  `922eb3258c2e4729ba8a846f52d7935e`. Журнал содержит ровно четыре completed cases
  23:29:50…23:29:52 UTC. На чтении systemctl — inactive/dead, Result=success,
  но invocation/start/exit уже отсутствуют у выгруженного transient unit; completion
  подтверждается manifest и журналом original invocation. Это не успех стратегии. UID999/GID989,
  no EnvironmentFile, CPUQuota100%, MemoryMax2G, отдельный write root.
- Canonical server run:
  `/srv/trading_lab_data/runs/v103_illiquidity_premium_v1_7d88dc5ca55e`.
- Manifest: `d995d9ce3f862eb484f0ca1394787a923ee64da0e74386d706c2e1ca7f627c7c`.
  Metrics: `18b06a8202acd54954c321b3059369dc1b42e1e9f827daa883f3a4413ed1eba2`.
- Read-only audit **23:31:07.278984 UTC**: 18 artifact hashes, 8100 feature-row
  recomputation, 2 exact target-frame replays, 4 cash continuity/daily identity/
  order-cost/performance/annual/position-count replays и assessment comparison PASS.
  Parquet roundtrip дал предупреждения Pandas о разных представлениях null
  (`None`/`NA`/`NaN`), не изменение numeric values. Полная независимая реконструкция
  всех risk counters не заявляется. Канонический economic run не повторялся.
- Backup bundle 19 файлов / 1343243 compressed bytes:
  `6ccee7273874324c8001074b1306ff1b030e5885e153592cb9b51fbe7ba98c8b`.
  Локальная копия сохранена в
  `D:\Projects\trading_lab_data\runs\v103_illiquidity_premium_v1_7d88dc5ca55e`:
  18 artifact hashes + manifest PASS после переноса. Это не Git и не объём raw data.

Следующий шаг — другая обоснованная гипотеза на готовых разрешённых данных после
проверки новизны по реестру. Не продолжать audit/replay V103, не писать TIC parser V4,
не возвращаться к threshold-only continuous timing или leverage/смеси старых лидеров.
Широкое AlgoPack economic scope не расширялось; live/demo/покупок/ключей не касались.

## Параллельная загрузка и объём данных

Снимок **17 сентября 02:33 МСК / 16 сентября 23:33 UTC**: main archive active/running,
прежние PID1663880 и invocation `d562f0748c4341b48eb7f4d34d64b4a1`, без перезапуска.
**17895/26305 jobs (68.0289%)**, 161817583 rows, 174443 pages; failed0, blocked0,
stored completed-job bytes9573268214, status updated23:33:18.194910UTC. Final manifest
отсутствует: это ещё не complete archive. Доля jobs не доля конечного объёма или времени.

Последовательный `du -sb`, завершён23:33:21.584027UTC:

| Что включено | Байты | Десятичные GB |
| --- | ---: | ---: |
| `data/algopack-archive` | 10218270607 | 10.2183 |
| Прежний `data/processed/algopack` | 1456918554 | 1.4569 |
| **Весь учтённый AlgoPack** | **11675189161** | **11.6752** |
| Весь `data` | 13071450187 | 13.0715 |
| `source_evidence` | 559319597 | 0.5593 |
| **Всего data + source_evidence** | **13630769784** | **13.6308** |

AlgoPack уже входит в общий итог. Это apparent bytes при продолжающейся записи,
без models/runs/tmp/transfers, не точное физическое занятие диска и не утверждение
byte-level дедупликации. Корни считались раздельными `du`, без дедупликации вложенных
аргументов одного вызова.

Локальный замер23:26UTC: data10841files/2719842747bytes + source25files/27598511bytes
= **2747441258bytes / 2.7474GB**. Есть серверные копии; не складывать локальный и
серверный итоги как уникальный набор. Result backup в `runs/` сюда не входит.
FUTOI V4 остаётся COMPLETE_WITH_SOURCE_GAPS с прежними 550 unresolved ticker-days;
повторный audit не проводился. Main archive failed0 не означает устранение этих gaps.
Серверный downloader, его credential и Windows tasks не менялись.
