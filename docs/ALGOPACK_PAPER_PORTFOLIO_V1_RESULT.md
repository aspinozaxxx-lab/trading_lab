# Paper portfolio V1 — server verification

2026-09-07. Pushed/deployed `3f4767d`. От trading-lab UID999 на gpu-mlserver290/290
связанных тестов PASS за14,69сек, включая13portfolio tests. Local11+encoding2PASS,
2Linux-only skips, Ruff/diff-check PASS. Нет actual portfolio run или market requests.

Проверены independent arms/reservations, четыре asset budgets без повторного использования,
missing/stale marks→unknown equity, liquidation costs1×/2× без double-counting, exit once,
cancel только unfilled и сохранение unique slot, unresolved/conversion changes, late
durable intent, corrupt sequence/previous SHA. Linux restart восстановил pending position
и budgets из journal, bad/truncated external tail отклонён. Partial event не пропущен
и не перезаписан. Activation замокана только в synthetic persistence fixtures.

| Файл | SHA-256 |
| --- | --- |
| algopack_paper_portfolio_v1.py | 859db849a4f9d9accf917543ddc1889a36e3c76d9c826d19ac1e158c46433837 |
| test_algopack_paper_portfolio_v1.py | 46cd207ce71cee459b95732851613ec1fc3c09480c5a219709cd188d9c446e47 |
| ALGOPACK_PAPER_PORTFOLIO_V1.md | 90b32b1ca0583440cb0496d41e6431b8bab2ac09889a89ceef8ea12b636ec876 |

Все3local/server SHA совпали. Metadata-only training44/witnessed7 parent closures PASS.
Production activation отсутствует/verifier REFUSED; F=null. Actual new source requests,
forecasts/trades0. Модели не переобучались, protected2026prices не читались.

Осталось: source-evidence-bound event builder, actual deadline enforcement, missed-exit
recovery policy, fixed evaluation и scheduler/complete activation. Portfolio reducer
сам по себе не доказывает происхождения переданного Fill. External tail сохранять
отдельно в runtime, иначе полное удаление хвоста не обнаруживается одним self-hash chain.
Append V1 выполняет full replay: synthetic test не является нагрузочной проверкой;
нужны verified incremental runtime state/checkpoints или измерение latency до долгого run.
Нельзя превращать эти ограничения в разрешение пересчитывать прошлые fills/PnL.
Цель20–50% ещё не подтверждена; economic CAGR/Sharpe/MDD нового опыта N/A.
