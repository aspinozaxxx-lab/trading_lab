# Серверные forward collectors

## Authoritative runtime

С `2026-09-02 14:59 Europe/Moscow` единственный активный scheduler forward-источников
работает на SSH host alias `gpu-mlserver`. Локальные Windows tasks `TradingLab*`
сохранены как recoverable definitions, но все отключены. Не включать их одновременно с
сервером: это создаст два места записи и риск дублирующих immutable snapshots.

Серверная раскладка:

```text
/opt/trading_lab                         code checkout/archive deployment
/opt/trading_lab/.venv                   Python 3.11 collector environment
/opt/trading_lab_runtime/cpython-3.11.4  standalone readable Python runtime
/srv/trading_lab_data/data               forward and processed data
/srv/trading_lab_data/runs               run artifacts
/srv/trading_lab_data/models             model artifacts
/etc/trading-lab/collector.env           secrets outside Git, root:trading-lab 0640
```

Сервис запускается от непривилегированного пользователя `trading-lab`. Unit использует
`ProtectSystem=strict`, разрешает запись только в `/srv/trading_lab_data`, пишет stdout
и stderr в journal и не запускает PowerShell.

## Расписания

Все времена московские, Mon–Fri:

| Timer | Job | Время |
|---|---|---|
| `trading-lab-cross-market.timer` | joint 35-instrument BBO | 10:09–18:39, каждые 10 минут |
| `trading-lab-broad-carry.timer` | 30 stock/futures pairs | 10:09–18:39, каждые 10 минут |
| `trading-lab-*-decision.timer` | cash-carry/LQDT/fund-pool | 15:49 |
| `trading-lab-*-fill.timer` | cash-carry/LQDT/fund-pool | 15:59 |
| `trading-lab-cny-relative-value.timer` | CNY relative value | 18:30 |
| `trading-lab-moex-rms.timer` | MOEX RMS | 23:35 |
| `trading-lab-v27-decision.timer` | V27 official CLOSE | 23:45 |
| `trading-lab-option-surface.timer` | option surface | 23:55 |
| `trading-lab-v27-execution.timer` | V27 observed execution | 10:05 |

`market_lab.ops.forward_collector` сохраняет прежнюю семантику wrappers: audit before
skip, deterministic decision/fill identity, source-date probes, independent V27
components и отсутствие anonymous fallback после authenticated FRED failure.

## Проверка и журнал

```bash
ssh gpu-mlserver 'systemctl list-timers --all --no-pager "trading-lab-*"'
ssh gpu-mlserver 'systemctl --failed --no-pager "trading-lab-*"'
ssh gpu-mlserver 'journalctl -u "trading-lab-collector@*.service" --since today --no-pager'
```

Проверка конкретного сервиса:

```bash
ssh gpu-mlserver 'systemctl show trading-lab-collector@cross-market.service \
  -p Result -p ExecMainStatus -p InactiveEnterTimestamp'
```

Первый автоматический серверный цикл `2026-09-02 14:59` завершил `cross-market` и
`broad-carry` с `Result=success`, `ExecMainStatus=0`. Оба новых snapshot прошли полный
source audit с `all_true=true`.

## Установка и обновление

Репозиторий приватный, поэтому серверу не передаются GitHub credentials. Deployment
делается exact `git archive` уже запушенного commit через SSH в `/opt/trading_lab`,
после чего:

```bash
ssh gpu-mlserver 'TRADING_LAB_PYTHON=/opt/trading_lab_runtime/cpython-3.11.4/bin/python3.11 \
  /opt/trading_lab/scripts/install_linux_collectors.sh'
```

Installer не заменяет существующие data directories, создаёт symlinks
`data/runs/models` только при безопасном отсутствии и проверяет systemd units до
enable. Значение `FRED_API_KEY` или будущего `MOEX_ALGOPACK_TOKEN` допускается только в
`/etc/trading-lab/collector.env`; ключи нельзя коммитить, передавать аргументами или
печатать в journal.

## Аварийный откат

Сначала остановить server timers и убедиться, что активных service jobs нет. Только
после этого можно временно включить нужные локальные definitions. Одновременная работа
обоих scheduler запрещена. После восстановления сервера снова отключить все локальные
`TradingLab*` и проверить новый audited snapshot до признания миграции завершённой.
