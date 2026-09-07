# Инструкции для агентов

## Назначение

Это исследовательская лаборатория торговых стратегий для MOEX. Главная цель — находить
воспроизводимые сигналы и проверять их с причинными данными, реалистичным исполнением и
полным учётом провалов. Ни одна текущая стратегия не разрешена для live trading.

## Что прочитать в начале каждой сессии

1. [Текущее состояние](docs/STATUS.md) — где остановились и что делать дальше.
2. [Реестр экспериментов](docs/EXPERIMENTS.md) — что уже проверено и какие run канонические.
3. [Архитектура](docs/ARCHITECTURE.md) — устройство кода и поток данных.
4. [Данные и целостность](docs/DATA_AND_INTEGRITY.md) — разрешённые источники и запреты.
5. [Runbook](docs/RUNBOOK.md) — окружение, проверки и команды.
6. [Шаблон протокола](docs/EXPERIMENT_PROTOCOL.md) — как добавлять новую гипотезу.
7. [Дополнительные источники](docs/INFORMATION_SOURCES.md) — что уже получено и какие
   point-in-time данные собирать дальше.
8. [Точные multileg-данные MOEX](docs/MOEX_MULTILEG_DATA.md) — какие market/member
   reports нужны для следующей проверки календарных спредов и как их безопасно принять.
9. [Forward equity protocol](docs/FORWARD_EQUITY_PROTOCOL.md) — как собирать новый
   TradeStats/OrderStats/OBStats период после V35 и какие gates нужны до paper PnL.
10. [Forward V27 protocol](docs/FORWARD_V27_PROTOCOL.md) — независимая проверка
    сильнейшего 28,38% development-кандидата без backfill и post-hoc tuning; текущий
    component readiness V3 принимает sealed anonymous FRED transport V2.
11. [Forward V39 protocol](docs/FORWARD_V39_PROTOCOL.md) — совместная независимая
    проверка option-OI governor и frozen V27 execution без преждевременного CAGR.
12. [Запросы лицензируемых данных](docs/DATA_ACCESS_REQUESTS.md) — какие платные
    original-timestamp sources реально устраняют блокеры и что нельзя покупать без
    отдельного разрешения пользователя.
13. [Forward cash-carry protocol](docs/FORWARD_STOCK_FUTURES_CASH_CARRY_PROTOCOL.md) —
    синхронный BID/OFFER-контур для проверки исполнимости V41 stabilizing sleeve.
14. [Forward LQDT idle-cash protocol](docs/FORWARD_LQDT_IDLE_CASH_PROTOCOL.md) —
    проверка исполнимого доходного инструмента только для неактивного капитала V41.
15. [Forward money-market fund pool](docs/FORWARD_MONEY_MARKET_FUND_POOL_PROTOCOL.md) —
    фиксированный пул альтернатив LQDT и запрет выбора по уже увиденным значениям.
16. [Forward cross-market BBO](docs/FORWARD_CROSS_MARKET_BBO_PROTOCOL.md) — causal
    10-минутные снимки для непрерывного timing и совместного анализа всех рынков.
17. [Forward broad stock–futures carry](docs/FORWARD_BROAD_STOCK_FUTURES_CARRY_PROTOCOL.md)
    — 30 fully-funded пар для расширения стабильного cash-carry sleeve.
18. [Forward V48 frontier](docs/FORWARD_V48_FRONTIER_PROTOCOL.md) — единственный
    зафиксированный aggressive mode `1.50x` и его joint warmup/evaluation gates.
19. [Серверные collectors](docs/SERVER_COLLECTORS.md) — authoritative `gpu-mlserver`,
    systemd timers, каталоги, журнал и безопасный аварийный откат.
20. [Forward V49 double-risk](docs/FORWARD_V49_DOUBLE_RISK_PROTOCOL.md) — лучший exact
    historical CAGR, строгий `NO_GO` и отдельный post-seal paper arm без backfill;
    для текущих counts использовать forward readiness V2 и paper readiness V3 с
    official calendar AND-condition.
21. [Official MOEX OFZ source](docs/MOEX_OFZ_SOURCE.md) — новый audited источник
    независимого carry/roll-down engine и точные запреты до V52 economic seal.
22. [Текущее состояние](docs/STATUS.md), раздел V54 — audited RGBI futures source
    `2022–2025`; market values нельзя читать для design до отдельного V55 seal.
23. [Текущее состояние](docs/STATUS.md), раздел V60/V61 — causal `2x/1x` shadow-equity
    governor прошёл development, но fixed robustness не подтвердил minimum 20%; его
    126-session rule и multipliers больше не настраивать на той же истории.
24. [Runbook](docs/RUNBOOK.md), раздел Forward MOEX option surfaces — timestamped V2
    intraday admission SHA `fb598938...`, quality SHA `b26c35c6...`, dual server
    schedule и запрет экономических расчётов до 20 полных post-boundary discovery-сессий.
25. [Historical MOEX Type B options](docs/MOEX_TYPE_B_OPTION_SOURCE.md) — один бесплатный
    sample day, strict-prior BBO, defined-risk vertical coverage и высокий crossing
    friction; не использовать его для выбора economic threshold или CAGR.
26. [Текущее состояние](docs/STATUS.md), раздел V62 — canonical economic `NO_GO`, 320
    сделок и CAGR `−0,65% / −1,59% / −2,53%` при трёх costs. Parent V1 не запускался;
    V2 завершён один раз, audit 157/157. Не повторять и не tune-ить opening family.
27. [Порядок исследования после V62](docs/RESEARCH_PROCESS.md) — одобренные пользователем
    приоритеты: экономический механизм, дешёвый предварительный тест, новая информация,
    вклад в независимый источник дохода. V63 attribution завершён: monthly corr V49/V60
    0,99337; нужен иной механизм/источник, не новая смесь или leverage этих же родителей.
28. [V64 налоговый календарь](docs/V64_TAX_CALENDAR.md) — закрыт `NO_GO`, audit 156/156;
    primary CAGR по eras 2,82% / 2,03% / −0,16%, 203 round trips. Не повторять и не
    настраивать окно/знак/control. [Индексные объявления](docs/MOEX_INDEX_REBALANCE_SOURCE.md)
    пока source feasibility/prototype, без полного корпуса/seal/доходности.
29. [AlgoPack historical source](docs/ALGOPACK_HISTORICAL_SOURCE.md) — пользователь купил
    подписку и разрешил key 2026-09-07; credential установлен только в server env.
    Metadata inventory V2 2024-10-15 завершён, 15 023/65 550 rows, audit 11/11;
    four-contract flow/depth sample V1 тоже завершён: 1 348 rows, audit 11/11,
    source-only PASS с null spread mask. Далее history 2020–2025 и economic протокол.
    V1 failed staging сохранён. Старый forward collector для истории не ослаблять.
30. [AlgoPack history V1](docs/ALGOPACK_FO_HISTORY_V1.md) — batch 2020–2025 завершён,
    294jobs/2067949rows, source date admission=false. Canonical не перезапускать.
    Source PASS не даёт PIT/economic admission; future execution adapter должен
    отделить inference eligibility от future label validity.
31. [AlgoPack metadata quality V1](docs/ALGOPACK_FO_HISTORY_QUALITY_V1.md) — отдельный
    full replay PASS + report завершены: shared1000331/TS-only6883/OB-only60404,
    source date admission=false, null/negative spreads сохранены. Closure b57b9b226d63;
    canonical/SHA в STATUS. Ни matching keys, ни SYSTIME не доказывают original
    availability; текущие model/live flags не ослаблять без явного нового основания.

32. [AlgoPack witnessed source V1](docs/ALGOPACK_FO_WITNESSED_V1.md) — новый независимый
    FO forward collector с current-contract discovery и actual receipt/validation.
    Status/runtime проверять в STATUS; история/старые timers не заменяются. Vendor
    date labels и SYSTIME не превращать в original publication или bucket completion.

33. [Witnessed quality V1](docs/ALGOPACK_FO_WITNESSED_QUALITY_V1.md) — COMPLETE,
    fixed3captures,4913unique/14659versions; revisions0 на коротком cohort не означают
    no-revisions guarantee. Negative L1/L10 spreads19/3 не превращать в отрицательные
    costs. Canonical не повторять; economic/model admission остаётся отдельным gate.

34. [Ответ MOEX 2026-09-07](docs/ALGOPACK_VENDOR_REPLY_20260907.md) — personal use
    подтверждено, SYSTIME описан поставщиком как publication time. Revision timestamp
    updates/original vintages всё ещё не объяснены; не повышать frozen admission.
    Короткое уточнение только подготовлено, не отправлено; разрешение не предполагать.

35. [Publication metadata V1](docs/ALGOPACK_FO_PUBLICATION_METADATA_V1.md) — COMPLETE:
    87,1761% later-date publications;1056 post2025 publication timestamps. Не сдвигать
    исторические строки произвольным lag для объявления causal backtest. Vendor reply
    note теперь входит в frozen closure; новые уточнения — отдельной dated note.
    Дизайн training-today не равен model admission или разрешению читать2026 outcomes.

36. [Training-today admission review](docs/ALGOPACK_TRAIN_TODAY_ADMISSION_REVIEW_V1.md)
    — COMPLETE; [разрешение2026-09-07](docs/ALGOPACK_PAPER_AUTHORIZATION_20260907.md)
    получено на archive-training assumption и новый post-seal future-paper период.
    Старый2026 закрыт; до нового seal/time/schema gates fit/labels не запускать. V32 frame с
    future-label eligibility нельзя подставлять в online. Не повторять source audits.

37. [Paper price inputs](docs/ALGOPACK_PAPER_INPUTS_V1.md) — COMPLETE,662files в отдельном
    server root; V2 сохраняет missing prior plan dates masked. Не повторять assembly.
    [Training spec](docs/ALGOPACK_PAPER_TRAINING_SPEC_V1.md) и
    [executable training V1](docs/ALGOPACK_PAPER_TRAINING_V1.md): paired Ridge/separate labels,
    44-file seal до fit. Runtime/run status брать из STATUS; no historical PnL, F=null.

38. [Future inference V1](docs/ALGOPACK_PAPER_INFERENCE_V1.md) — pure adapter с fixed model
    hashes, arm-specific coverage и deadline. COMPUTED_NOT_PERSISTED не означает
    опубликованный forecast/fill. До source/writer/execution/evaluation seals F=null;
    training COMPLETE не повторять, actual runtime брать из STATUS.

39. [Market source V1](docs/ALGOPACK_PAPER_MARKET_SOURCE_V1.md) — request/parser/HTTP
    primitives, но ещё не activated collector. No CLI/timer/F; response available_at=null
    до durable commit. Full activation/source/execution/evaluation seal нужен до HTTP.

40. [Paper journal V1](docs/ALGOPACK_PAPER_JOURNAL_V1.md) — immutable events, no overwrite,
    durable payload/actual observation clocks. Late consumption нельзя backdate по
    раннему COMMITTED timestamp. Full source/activation/execution admission ещё нужен.

41. [Activation/capture V1](docs/ALGOPACK_PAPER_CAPTURE_V1.md) — full market packet
    replay/journal/model-input adapter. Production forward activation/config/seal ещё
    отсутствуют; verifier требует execution/evaluation/runtime. F не выдумывать.

42. [Predictor bridge V1](docs/ALGOPACK_PAPER_PREDICTOR_V1.md) — witnessed flow→journal→
    paired forecast. Require bridge bytes in complete activation; actual observation clocks,
    no labels and no execution. Runtime/server verification брать из STATUS, F пока=null.

43. [Execution V1](docs/ALGOPACK_PAPER_EXECUTION_V1.md) — fixed paper intent/FOK/cost
    primitives, не portfolio runtime. Broker fee assumption не подтверждённый тариф;
    unresolved exits не удалять. Dated quote/session proof ещё нужны, F=null.

44. [Execution source V1](docs/ALGOPACK_PAPER_EXECUTION_SOURCE_V1.md) — dated BBO/specs
    и calendar→journal→execution inputs. Actual entitlement/schema/titles пока не
    наблюдались; unknown periods не объявлять торговыми. Runtime/F брать из STATUS.

45. [Portfolio V1](docs/ALGOPACK_PAPER_PORTFOLIO_V1.md) — dedicated immutable event root,
    reservations/MTM/restart. Missing marks=null; unresolved риск не удалять. Reducer
    не заменяет source evidence replay; external tail нужен против усечения журнала.

На вопрос «на чём остановились?» отвечай по `docs/STATUS.md`, при необходимости сверяя
указанный там canonical JSON/Markdown. На просьбу «продолжай эксперименты» бери первый
незаблокированный пункт из раздела «Очередь работ» в `docs/STATUS.md`.

## Неприкосновенные исследовательские правила

- Не читать цены, доходности, labels, targets или PnL с `2026-01-01` и позже. Использовать
  только наборы, manifest которых доказывает границу не позже `2025-12-31`.
  Единственное новое scoped исключение — [AlgoPack future-paper](docs/ALGOPACK_PAPER_AUTHORIZATION_20260907.md):
  current-vintage training <=2025 и future-only evaluation после нового code/model seal.
  До определения F и source/execution admission старый запрет2026 полностью действует.
- Признак допустим только если его `available_at <= decision_at`. Signal строится после
  завершённого бара, исполнение — не раньше следующего фактического open/бара.
- Не переносить доходность через пропуски или смену контракта. Не использовать обычную
  back-adjustment, переписывающую прошлое; допустима только причинная forward adjustment.
- Missing observation означает mask, sleep или unresolved. Не заменять неизвестную
  доходность, цену, контракт, комиссию или доступность нулём.
- До чтения outcomes зафиксировать протокол и SHA-256. После просмотра OOS 2021–2025 не
  подбирать пороги, признаки, universe или execution assumptions на этих же результатах.
- Не изменять и не перезаписывать canonical run. Новая гипотеза или исправление — новый
  versioned config, новый hash и отдельный output directory.
- Всегда показывать количество решений и сделок, coverage/unresolved, CAGR, Sharpe, MDD,
  результаты по годам и минимум сценарии 1×/2× costs. Нулевое число сделок — результат.
- Не называть validation, development probe или выбранный на тех же folds вариант
  независимым holdout. Не делать live/promote вывод без PIT specs, fees, margin, borrow и
  доказуемого исполнения.
- LLM по корпоративным документам может извлекать только факты с publication time,
  revision chain и page evidence. Ей запрещены prices, returns, labels, targets и PnL.

## Рабочий процесс агента

1. Проверь `git status`, актуальный `STATUS.md`, config seal и входные manifests.
2. Сформулируй одну проверяемую гипотезу и заполни `docs/EXPERIMENT_PROTOCOL.md`.
3. Создай изолированный config и его `.sha256` до расчёта результата.
4. Работай только с разрешённым development bundle; используй expanding/purged OOS.
5. Запусти целевые тесты, затем полный `pytest` и `ruff` в разумной для изменения мере.
6. Сохрани provenance, predictions/trades/ledger, metrics и явный verdict.
7. Обнови `docs/EXPERIMENTS.md` и `docs/STATUS.md` в том же изменении.

Не создавай ещё одну threshold-only версию провалившегося continuous timing. Не запускай
новый market graph без независимой новой информации или принципиально иной target/execution
модели. Не меняй экономику старого протокола под уже увиденный результат.

## Хранилища

- Git содержит код, configs, tests, документацию и маленькие synthetic fixtures.
- Реальные данные, run-артефакты и checkpoints лежат вне Git в
  `D:\Projects\trading_lab_data`.
- Локальные `data/`, `runs/` и `models/` в корне репозитория — игнорируемые NTFS
  junctions на соответствующие каталоги внешнего хранилища.
- Не добавляй в Git Parquet/NPZ/PT/PTH, архивы источников, модели, transfer bundles и
  содержимое `runs/`. Не публикуй рыночные данные без проверки прав на распространение.

Некоторые модули пока вычисляют `PROJECT_ROOT/data` и `PROJECT_ROOT/runs`; junctions нужны
для совместимости до отдельного рефакторинга путей.

Forward collection выполняется только на `gpu-mlserver`. Все локальные Windows
`TradingLab*` tasks отключены; не включай их, пока server timers активны. Не передавай
серверу GitHub credentials и не сохраняй API tokens вне
`/etc/trading-lab/collector.env`.
