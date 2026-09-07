# Portfolio command/anchor journal V1

Дата: 2026-09-07. Технический протокол восстановления, не новая экономическая гипотеза.
Код: `src/market_lab/futures/algopack_paper_portfolio_anchor_v1.py`.
Использует неизменённые portfolio/session/journal V1; требует собственный SHA в полной
activation closure. Production activation отсутствует, F=null, реальных операций нет.

## Порядок записи

Два отдельных private Linux root: portfolio ledger и control journal. Перед первой
операцией только явный `initialize` создаёт genesis anchor в пустых dedicated roots.
Обычный restart никогда не вызывает initialize и не восстанавливает отсутствующий
журнал как новый счёт с миллионом виртуальных рублей.

Под общим control transaction lock: immutable UUID command → portfolio event со
ссылкой на command → sequential anchor с SHA portfolio event и предыдущего anchor.
Команда содержит activation/root/sequence/previous-portfolio SHA/operation/data.
Runtime-owned command reference нельзя передать вызывающему коду. Hot path проверяет
последний control anchor и portfolio tail; full replay выполняется при каждом reopen.
Все timestamps фактические; отсутствующие подтверждения не датируются задним числом.

## Восстановление и сбои

- Reopen проверяет непрерывность anchor chain, referenced portfolio records и полное
  соответствие каждой операции ранее сохранённой команде, включая chronology.
- Ровно один полностью committed portfolio event без anchor разрешено подтвердить
  после проверки команды и предыдущего SHA. Его операция не исполняется повторно.
- Потерянное acknowledgment уже записанного anchor не создаёт дубликат.
- Orphan command без portfolio event сохраняется, но никогда автоматически не
  исполняется. Следующая новая команда получает другой UUID.
- Partial portfolio/anchor record, missing positive anchored history, foreign writer
  без command, gap или mismatch блокируют восстановление. Ничего не перезаписывается.
- Любая неопределённость записи инвалидирует процессный cache; нужен reopen.

## Границы гарантии

Это отдельный журнал, но НЕ независимый сервер/backup/disaster domain. Потеря обоих
каталогов требует внешнего восстановления, а не повторной инициализации. Hot path не
проверяет произвольную порчу всех старых байтов; для этого startup/offline full replay.
Orphan commands сохраняются как след отказа, но не считаются исполненными событиями.
Протокол не является защитой от администратора, переписавшего обе полные цепочки.

Command equality доказывает согласованность учёта, но не происхождение Fill от
рыночного source/forecast evidence. Evidence-bound runtime, пропущенные выходы,
daily snapshot producer, scheduler и полная публикация до F остаются обязательными.
Нет broker API, реальных сделок, backfill, HTTP, обучения или PnL-эксперимента.

## Проверка

13 synthetic tests: no activation, missing genesis, reserved-capital restart, two
anchor loss points, lost portfolio ack, orphan command, truncation, partial anchor,
competing writer, missing cached anchor, foreign reference, legacy unbound writer.
На Windows 1 PASS/12 Linux skips; Linux результат фиксируется отдельно после deploy.
