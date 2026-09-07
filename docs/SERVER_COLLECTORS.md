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

Все времена московские; большинство market jobs Mon–Fri, календарь — ежедневно:

| Timer | Job | Время |
|---|---|---|
| `trading-lab-cross-market.timer` | joint 35-instrument BBO | 10:09–18:39, каждые 10 минут |
| `trading-lab-broad-carry.timer` | 30 stock/futures pairs | 10:09–18:39, каждые 10 минут |
| `trading-lab-*-decision.timer` | cash-carry/LQDT/fund-pool | 15:49 |
| `trading-lab-*-fill.timer` | cash-carry/LQDT/fund-pool | 15:59 |
| `trading-lab-cny-relative-value.timer` | CNY relative value | 18:30 |
| `trading-lab-moex-rms.timer` | MOEX RMS | 23:35 |
| `trading-lab-v27-decision.timer` | V27 official CLOSE after publication | Tue–Sat 00:45/01:15/06:00 retries |
| `trading-lab-option-surface.timer` | timestamped option surface V2 | 10:09–22:59 каждые 10 минут; 23:09/19/29/39/55 |
| `trading-lab-option-surface-eod.timer` | V1 compatibility for V39/V49 | 23:57 |
| `trading-lab-v27-execution.timer` | V27 observed execution | 10:05 |
| `trading-lab-futures-calendar.timer` | official MOEX futures calendar | ежедневно 00:20 |

`market_lab.ops.forward_collector` сохраняет прежнюю семантику wrappers: audit before
skip, deterministic decision/fill identity и independent V27 components. При валидном
`FRED_API_KEY` выбирается только authenticated FRED V1; без ключа — только anonymous
header V2. Failure выбранного route не включает другой route в том же process.
Job `option-surface` пишет root `moex-options-surface-v2-timestamps-margin`, а
`option-surface-eod` — прежний `moex-options-surface-v1`; смешивать эти roots нельзя.
После каждого V2 capture тот же service публикует sealed counts-only quality report в
`moex-options-surface-v2-quality-v1`; failure source replay/clock validation виден в
journal и не скрывается успешным capture.

Commit `799656f` развернул FRED V2 dispatcher/readiness. Первый scheduled-equivalent
manual service run создал один 57-row component
`snapshot_macro_fred_transport_v2_20260902T221948066517Z`; replay `15/15`, readiness
4 valid/0 invalid, FRED/CBR ready. Повторный service run аудировал и пропустил его,
нового manifest не создал. Commit `8cee8cd` добавил downstream V48/V49 readiness;
server tests `4/4`, V48 видит FRED V2 как valid, а не invalid. Commit `df8c57e`
добавляет отдельный component successor для V39 вместо пустого legacy atomic root.

Commits `b6b39c4/d829d81` запечатали и развернули public-page transport официального
MOEX futures calendar до первого persisted response. Первый run завершён
`Result=success`, `ExecMainStatus=0`: `485` future dates, unknown `0`, raw replay
`18/18`, manifest/audit SHA `19a2858e.../35a0283b...`. Calendar timer стал 15-м
активным server timer. V49 readiness V3 (`218d7aa`) принимает источник только как
дополнительный fail-closed AND-condition; экономику и PnL он не вычисляет.

## Проверка и журнал

```bash
ssh gpu-mlserver 'systemctl list-timers --all --no-pager "trading-lab-*"'
ssh gpu-mlserver 'systemctl list-units --state=failed --no-pager "trading-lab-*"'
ssh gpu-mlserver 'journalctl -u "trading-lab-collector@*.service" --since today --no-pager'
```

Проверка конкретного сервиса:

```bash
ssh gpu-mlserver 'systemctl show trading-lab-collector@cross-market.service \
  -p Result -p ExecMainStatus -p InactiveEnterTimestamp'
```

Два последовательных автоматических серверных цикла `2026-09-02 14:59/15:09`
завершили `cross-market` и `broad-carry` с `Result=success`, `ExecMainStatus=0`.
Все четыре новых snapshot прошли полный source audit с `all_true=true`; forward root
после второго цикла содержит `331` file.

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
enable. После `daemon-reload` он перезапускает timers, чтобы изменение `OnCalendar`
сразу обновило фактический next elapse; одного `enable --now` для уже active timer
недостаточно. Значение `FRED_API_KEY` или будущего `MOEX_ALGOPACK_TOKEN` допускается только в
`/etc/trading-lab/collector.env`; ключи нельзя коммитить, передавать аргументами или
печатать в journal.

## Bounded AlgoPack historical batch — 2026-09-07

Это отдельный transient service, не новый recurring timer:
`trading-lab-algopack-fo-history-v1-c5fb0b96b12d.service`.
Code seal `c5fb0b96b12d77f5c01b1625b0b9b7ab582ed82d09117dc6217d577de33751d1`,
pre-request commit `84a1661`, Linux synthetic101/101, actual metadata preflightPASS.
Работает как trading-lab, ProtectSystem=strict, NoNewPrivileges=yes, UMask0077,
MemoryMax4G, Nice10; writable только `/srv/trading_lab_data/data/processed/algopack`.
Token берётся из existing server env, REQUESTS_CA_BUNDLE задаётся только этому unit:
`/etc/trading-lab/ca/moex_russian_trusted_root_ca_v1.pem`, hash проверен до запуска.
Python bytecode writes отключены. Другие timers и Windows jobs не менялись.

Проверять живость через systemctl show именно этого unit, не по наличию work/lock.
Пока MainPID живой/active-running, новый writer не запускать. После terminal success
нужен полный audit с actual manifest SHA; completed canonical не перезапускать.
После terminal failure сначала прочитать безопасные records из
`.moex_algopack_fo_history_v1_c5fb0b96b12d.failures`; если причина допускает повтор,
новый uniquely named transient unit запускает тот же module/seal/storage-root.
Collector сам replay-проверит checkpoint до сети и продолжит с первого незавершённого
cursor. Не удалять lock/checkpoint, не править frozen code/manifest для обхода ошибки.
Промежуточные файлы после аварии сохраняются вне canonical в `.work.orphans`.

См. [полный протокол](ALGOPACK_FO_HISTORY_V1.md) и текущий [STATUS](STATUS.md).

## Аварийный откат forward scheduler

Сначала остановить server timers и убедиться, что активных service jobs нет. Только
после этого можно временно включить нужные локальные definitions. Одновременная работа
обоих scheduler запрещена. После восстановления сервера снова отключить все локальные
`TradingLab*` и проверить новый audited snapshot до признания миграции завершённой.
