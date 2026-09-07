# Predictor V1 — synthetic end-to-end server result

2026-09-07. Pushed commit `e83a045`, deployment на gpu-mlserver; все проверки от
пользователя trading-lab UID999, temporary synthetic roots вне repository.

11/11 новых тестов PASS за12,70сек. Связанный набор activation/capture/journal/market/
inference/model/alignment/training/predictor:222/222 PASS за14,66сек.
Local:1pure+2encoding PASS,10Linux integration skips. Ruff/diff-check PASS.

Проверена цепочка fake market HTTP→18response journal→packet replay; fake witnessed
flow capture→full raw replay→projection journal→actual observation→paired inference→
forecast journal→consumer. Все prices и model bytes искусственные; production
activation и source-parent seal validation замоканы ТОЛЬКО внутри synthetic fixtures.
Никакой права доступа аккаунта или исполнения реальной сделки эти тесты не доказывают.

Проверенные случаи: оба READY arms, явное отсутствие flow с сохранением baseline,
32допустимые/32исключённые flow rows, новая observed availability, подмена raw/normalized,
неверный manifest SHA/path, pre-F capture refusal до artifact audit, late computation
без READY predictions, duplicate forecast slot без overwrite, unverified activation до IO.

| Файл | SHA-256 |
| --- | --- |
| algopack_paper_predictor_v1.py | 593f78847aff3412493193d1c3635d6d785791e1705f6ec6cd23945a09d7f4c0 |
| test_algopack_paper_predictor_v1.py | 2b3c19977963fe0e83d3e435086c19f4aa37a91aca11767a4cba58e16c017b97 |
| ALGOPACK_PAPER_PREDICTOR_V1.md | 6dd4b93da568e5db6cb6472dfc4f6c599aacfa783894eca2a59eb1cdbf12c8fa |

Все3local/server hashes совпали. Реальные parent closures проверены metadata-only:
training44 и witnessed7 files PASS. Production activation отсутствует и verifier
отвергает запуск до HTTP. Модели не переобучались, старые2026prices не читались.

Следующая незавершённая работа: fixed paper execution с sizing/fees/session/quote
admission и ledger, fixed evaluation, scheduler/failure accounting, затем complete
config/seal/activation и deployment ДО нового F. Подтверждения broker/tariff пока нет;
assumed costs не выдавать за реальные. Новые реальные forecasts/trades0;
CAGR/Sharpe/MDD=N/A, прибыль20%/50% не подтверждена.
