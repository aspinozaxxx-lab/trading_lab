# AlgoPack training V1 — TRAINED_NOT_EVALUATED

2026-09-07, один canonical run. Основание: [sealed protocol](ALGOPACK_PAPER_TRAINING_V1.md).
Обучение завершено; это не подтверждение доходности и не разрешение real trading.

## Идентичности

- Pre-run pushed commit: `bfc7860`, branch `agent/futoi-intraday-source`.
- Closure44files SHA `bb95784a169fd4c163c5df4ada231404321ea6e8bf5b8271425e0c869b7ebca2`.
- Config SHA `fb29aabbc6533db879c302173929ff90aa0e962c1fa2d50365d5cc90897948f8`.
- Canonical directory на gpu-mlserver:
  `/srv/trading_lab_data/runs/algopack-paper-training/algopack_paper_training_v1_bb95784a169f`.
- Manifest SHA `028b2cead7111868ef345987e696be2d70aadd8bbaa0a8233ff676dd38fd7527`.
- Price-only model SHA `2053be47dc3649904154816dc635a76c156df3d25aa647354cc0730c4d9ed5d5`.
- Price+flow model SHA `6d39dc55178bf3d893eaff91b18ab23066ca2ceed9b1db2c950587838fcb41aa`.

Started17:44:46.513872UTC, source projection cutoff17:45:56.006164UTC,
completed17:46:26.964097UTC. Около100,45сек wall time, CPU1мин43,501сек, peak1,9GiB.
Unit `trading-lab-algopack-paper-training-v1-bb95784a169f.service` завершился success/0;
User=trading-lab, PrivateNetwork=yes, ProtectSystem=strict, без EnvFile/ключа.
Никаких локальных collectors/tasks или real orders не запускалось.

## Покрытие — не доходность

| Год | Candidate rows | Joint training rows |
| --- | ---: | ---: |
| 2020 | 10416 | 8304 |
| 2021 | 10668 | 10012 |
| 2022 | 10584 | 8696 |
| 2023 | 10668 | 10149 |
| 2024 | 10626 | 9594 |
| 2025 | 10626 | 10241 |
| Все | 63588 | 56996 |

Price-only features доступны на59194rows; full features на57224; четыре targets
на62366. Обе модели fit на одном пересечении56996, больше fixed minimum5000.
Оставшиеся6592 calendar rows сохранены, не исчезли из accounting. Training intersection
не переносить в future inference: baseline должен иметь собственную feature eligibility.
Price-only/features → full-features потеря1970rows не является оценкой качества сигнала.

Причины masks: missing price lookback, missing TS/OB bucket, causal plan ineligible,
missing exact target path. Все per-asset/per-year counts в manifest. Unknown не заменялся0.
Flow provenance996019versions с source file SHA, row ordinal, exact key и actual receipt/
verification timestamp. Price source SHAs сохраняются для features и labels раздельно.

## Проверка

До запуска:105/105 целевых synthetic tests на Linux, local106pass/1Linux-onlyskip
с encoding. Расширенная проверка parent core/quality/history:Linux250/250;
local249pass/3OS-symlink skips. Ruff и closure44/44 PASS до/после fit.

Независимый read-only post-run audit от UID999 PASS:

- точное directory membership и byte hashes всех9 артефактов (manifest отдельно);
- одинаковый unique candidate index у calendar/features/labels/training_mask;
- все information dates2020–2025, независимая finite-mask reconstruction56996;
- независимая сверка annual counts и scaler mean/std обеих моделей;
- Ridge normal-equation relative residual2,65e-15/5,28e-15, без нового fit/selection;
- provenance version IDs unique, actual available_at<=cutoff, source dates<2026.

Сохранены две multioutput модели с20/40features и4targets, scaler statistics, calendar,
feature/label tables, training mask, source provenance/catalog. Модели и market data
остаются вне Git. Semantic raw replay в этом runner=false, исходные source audits
не переименованы в новый результат; frozen source admission flags не изменены.

## Вердикт и продолжение

`TRAINED_NOT_EVALUATED`. Forecasts=0, trades=0. CAGR/Sharpe/MDD, worst year и costs1x/2x
остаются N/A, не ноль. Перенос revised archive в observed forward — разрешённое
предположение, не original-vintage proof. Прибыль20%/50% пока не подтверждена.

Следующее конкретное действие: fixed future inference adapter с exact model hashes,
отдельной baseline/full eligibility и новым price/source/execution/evaluation protocol.
До назначения F и всех необходимых seals старые2026 цены/labels не читать; current
FO witnessed source продолжает source-only collection. F должна следовать за training
completion/model publication и всеми будущими seals, без backdating. Не повторять
training, не менять alpha/признаки/годы по этим артефактам и не вычислять retrospective
AlgoPack trading PnL. Canonical output и44-file closure больше не редактировать.
