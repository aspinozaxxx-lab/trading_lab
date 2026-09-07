# Portfolio anchor V1 — server verification

2026-09-07. Core/doc pushed/deployed `2e81686`; corrected synthetic test `266d269`.
`gpu-mlserver`, `/opt/trading_lab`, Python3.11.4, runtime UID999.

Related synthetic suite: **328 PASS, 18,43сек**, включая13anchor tests.
Local:1anchor+2encoding PASS/12Linux skips; Ruff/diff check PASS.
Первый server run:327PASS/1FAIL, тест invalid-operation передавал пустой data и ожидал
ValueError, тогда как frozen reducer выдал KeyError до этой проверки. Fixture исправлен
на `position=none`, как в parent session test. Core не менялся. Первый test file сохранён
в `/tmp/test_algopack_paper_portfolio_anchor_v1_2e81686_retained.py`, не удалён.
Окончательный полный suite приведён выше; runtime closures44training/7witnessed PASS.

Local/server SHA256 совпадают:

- core: `1bddb7a110339fe4194eb3d8e57584177831fafa31a391308664c00bcc9975db`
- corrected tests: `150a3b46fc090c6ee473737b69eb04f22c1b479d59f63a3334d4ab1894c59082`
- protocol doc: `61b8f218d619c965af180e330145218850e9ac099469bd8fab8d07f5f86d828f`

Проверены restart с резервированием, потеря подтверждений portfolio/anchor, orphan
command без автоматического повторения, incomplete/truncated journal и stale writers.
Тесты используют synthetic clocks/данные и mock activation; production activation
отсутствует (проверено metadata-only), F=null. Реальных HTTP/forecast/trades/PnL нет.
Результат не доказывает доходность, source-bound Fill или независимое резервирование
двух журналов. Следом integrated evidence runtime, recovery policy и daily snapshots.
