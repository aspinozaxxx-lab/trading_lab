# Activation/capture V1 — серверная проверка

2026-09-07. Код из pushed commit `43c4cd9` перенесён на gpu-mlserver без перезаписи
родительских модулей. Это инженерная проверка, не economic run и не проверка подписки.

## Результат

- Linux: 211/211 тестов activation/capture/journal/market/inference/model/alignment/training.
- Отдельно service user trading-lab (UID999): 21/21 activation/capture tests.
- Fake HTTP integration: 18 responses, 20 immutable source events; full replay и
  observed clock mapping. При failure сохраняются partial responses, COMPLETE отсутствует.
- Пять transferred файлов совпали побайтно; training44 и witnessed7 parent closures PASS.
- Реальных forward config/seal/activation нет. Вызов production verifier от UID999
  отвергнут до сети; F=null. Новые price HTTP requests, реальные forecasts/trades: 0.

## SHA-256 перенесённых файлов

| Файл | SHA-256 |
| --- | --- |
| algopack_paper_activation_v1.py | 85f73f1c4f1d6dad09c75edc526848813e9257737d619237707307dc1166b33d |
| algopack_paper_capture_v1.py | f048ed4665ab88c02e75172517abf17341b183af2c7a341db1d41b1a32289322 |
| test_algopack_paper_activation_v1.py | ea28e70ba0a8d4e6a4b2ffac7723ad89db9b4f5725d1bcc459a2fe1dfa8a812d |
| test_algopack_paper_capture_v1.py | f1f2696579fd611f97b63135cfc95963adfa98a369861253ab93ea9eed3b3f1a |
| ALGOPACK_PAPER_CAPTURE_V1.md | 476d3906fdee8e9f34a58ac1e4025094b2a2234f414a7252bbd8901182d31731 |

Первый metadata-only verification command завершился ImportError из-за неверного имени
константы в проверочном скрипте. После исправления имени проверка PASS; код модулей не
менялся, исходный сбой не запускал сеть, чтение рыночных значений или модели.

Следующая незавершённая часть: witnessed flow→journal→inference и полная synthetic
цепочка прогнозирования, затем fixed execution/evaluation/runtime. Комиссии брокера
ещё не подтверждены. Текущие результаты не доказывают целевые 20–50% годовых;
CAGR/Sharpe/MDD для нового эксперимента N/A, экономических сделок 0.
