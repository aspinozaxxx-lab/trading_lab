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
    сильнейшего 28,38% development-кандидата без backfill и post-hoc tuning.
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
    historical CAGR, строгий `NO_GO` и отдельный post-seal paper arm без backfill.
21. [Official MOEX OFZ source](docs/MOEX_OFZ_SOURCE.md) — новый audited источник
    независимого carry/roll-down engine и точные запреты до V52 economic seal.
22. [Текущее состояние](docs/STATUS.md), раздел V54 — audited RGBI futures source
    `2022–2025`; market values нельзя читать для design до отдельного V55 seal.
23. [Текущее состояние](docs/STATUS.md), раздел V60/V61 — causal `2x/1x` shadow-equity
    governor прошёл development, но fixed robustness не подтвердил minimum 20%; его
    126-session rule и multipliers больше не настраивать на той же истории.
24. [Runbook](docs/RUNBOOK.md), раздел Forward MOEX option surfaces — timestamped V2
    intraday admission SHA `fb598938...`, dual server schedule и запрет экономических
    расчётов до 20 полных post-boundary discovery-сессий.
25. [Historical MOEX Type B options](docs/MOEX_TYPE_B_OPTION_SOURCE.md) — один бесплатный
    sample day, strict-prior BBO, defined-risk vertical coverage и высокий crossing
    friction; не использовать его для выбора economic threshold или CAGR.

На вопрос «на чём остановились?» отвечай по `docs/STATUS.md`, при необходимости сверяя
указанный там canonical JSON/Markdown. На просьбу «продолжай эксперименты» бери первый
незаблокированный пункт из раздела «Очередь работ» в `docs/STATUS.md`.

## Неприкосновенные исследовательские правила

- Не читать цены, доходности, labels, targets или PnL с `2026-01-01` и позже. Использовать
  только наборы, manifest которых доказывает границу не позже `2025-12-31`.
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
