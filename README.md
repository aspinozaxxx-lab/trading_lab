# Market Lab

Market Lab — локальная CPU/GPU-лаборатория для воспроизводимого исследования торговых
стратегий на данных MOEX, CBR и CFTC. Проект строит point-in-time datasets, обучает
правила и модели, моделирует исполнение только после сигнала и сохраняет полный audit
trail. Это исследовательский код, не инвестиционная рекомендация и не live-система.

## Текущее состояние

Ни одна стратегия не разрешена для live trading. Лучшие исторические challengers:

| Candidate | Net CAGR | Sharpe | MDD | Статус |
|---|---:|---:|---:|---|
| `V49 double-risk` | 43,68% | 1,31 | 22,97% | Лучший exact history; robustness не подтвердил 20% |
| `V60 equity governor` | 39,94% | 1,24 | 22,02% | Development GO; robustness NO-GO |
| `V41/V43 stability family` | 24,1–25,6% | 1,20–1,27 | 16,8–17,5% | All-cost history >20%, robustness NO-GO |

Высокий full-period CAGR пока не означает предсказуемую прибыль: bootstrap q05 и rolling
windows опускаются ниже 20%. Новая активная ветка собирает intraday option surface на
`gpu-mlserver` и проверяет только defined-risk конструкции по observed BID/OFFER.
Исторический Type B sample подтвердил механику, но показал высокий four-side crossing
friction и содержит лишь один день. Детали: [текущее состояние](docs/STATUS.md).

## Документация

- [AGENTS.md](AGENTS.md) — обязательные инструкции для новой Codex-сессии.
- [Текущее состояние](docs/STATUS.md) — где остановились и очередь работ.
- [Реестр экспериментов](docs/EXPERIMENTS.md) — результаты, canonical и superseded runs.
- [Архитектура](docs/ARCHITECTURE.md) — модули и поток данных.
- [Данные и целостность](docs/DATA_AND_INTEGRITY.md) — PIT, hashes и protected 2026.
- [Runbook](docs/RUNBOOK.md) — установка, tests и команды.
- [Шаблон протокола](docs/EXPERIMENT_PROTOCOL.md) — правила новой гипотезы.

Новая сессия может начать с: «прочитай `AGENTS.md` и скажи, на чём остановились» или
«прочитай `AGENTS.md` и продолжай первый незаблокированный эксперимент».

## Быстрый запуск

Требуется Python 3.11:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\market-lab.exe doctor
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

GPU environment устанавливается из `requirements.sequence.lock`. Полные команды и
безопасный порядок запуска находятся в [runbook](docs/RUNBOOK.md).

## Данные и результаты

Реальные данные, models/checkpoints и run outputs не хранятся в Git. Локальный external
root:

```text
D:\Projects\trading_lab_data
```

Игнорируемые `data/`, `runs/` и `models/` в working copy являются NTFS junctions на
external root. Их безопасно создаёт `scripts/setup_external_storage.ps1`. Код пока
использует repo-relative paths; для нестандартного external root также задай
`MARKET_LAB_STORAGE_ROOT`. Git содержит только код, configs, tests, документацию и
synthetic fixtures.

Для V8/V9 запрещено читать market outcomes с `2026-01-01` и позже. Перед использованием
любого реального файла необходимо проверить manifest и SHA-256. MOEX data rights нужно
отдельно подтвердить до публичного распространения, коммерческого или live использования.
