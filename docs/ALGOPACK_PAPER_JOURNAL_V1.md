# AlgoPack paper journal V1

2026-09-07. [Inference](ALGOPACK_PAPER_INFERENCE_V1.md) и
[market source](ALGOPACK_PAPER_MARKET_SOURCE_V1.md) получают immutable publication
primitive. Это не complete source/runtime/economic admission; actual F=null.

## Запись

`algopack_paper_journal_v1` работает с предварительно созданным private0700 ordinary
root, только Linux/fsync/flock. Нет network/credential/CLI/timer и default output path.
Future activated service обязан работать от trading-lab; tests используют synthetic
tmp directories. Module не проверяет весь будущий activation seal — это роль runner.

`publish` резервирует `root/{source|forecast}/{key}` exclusive mkdir под nonblocking
advisory lock. Key не допускает traversal; symlink ancestors и hardlinked files
отклоняются. Записывает STARTED, payload и record с SHA/bytes через O_EXCL/O_NOFOLLOW,
fsync файлов/директорий, затем readback. Payload JSON finite, максимум32MiB.
После durable payload фиксирует реальный clock и COMMITTED marker; после fsync marker
возвращает отдельный acknowledgment clock. Никаких overwrite/rename поверх canonical.

При ошибке остаётся reserved incomplete event, STARTED и уже записанные bytes. Нет
автоматического удаления, переиспользования key или подмены failed попытки успешной.
Incomplete/torn marker и неожиданные файлы не допускаются reader. Future runtime
должен учитывать такие slots как missing/unresolved, а не пытаться тихо заменить их.

`observe` под lock сначала проверяет exact record SHA, header/F/clock/membership,
лишь затем читает payload и проверяет его SHA/size. Это не semantic raw replay:
schema/candle dates/receipt provenance должны быть проверены source publisher.
Возвращаемый actual observed_at берётся ПОСЛЕ чтения/проверки, не из старого marker.
Полный source admission и закрытая схема source payload ещё обязательны.

## Прогнозы

`publish_forecast` требует computed candidate из inference V1 плюс source_observations:
source key, record SHA и фактический observed_at, зафиксированный input assembler.
Должны быть обе frozen model identities, fixed target/asset order,4finite predictions
или explicit sleep/None, valid information/cutoff/completion clocks. Reference clocks
не позже input_cutoff, не раньше F и durable публикации соответствующего source event.
Каждая source reference перепроверяется в журнале до публикации прогноза.

Forecast key определяется только information_end (`YYYYMMDDTHHMMSSZ`); обе модели
публикуются вместе, повтор того же slot запрещён. Semantic feature/model replay и
проверка соответствия per-feature SHAs source payload — следующая роль runtime/audit,
не доказательство, которое автоматически предоставляет JSON writer.

`consume_forecast` проверяет manifest/key/F и реальный post-read clock. Если чтение
произошло в E+10m или позже, обе prediction становятся None/MISSED_CONSUMPTION_DEADLINE
в возвращаемой копии, оригинал не меняется. Даже ранний durable payload не позволяет
считать позднее чтение своевременным исполнением. Consumer возвращает
OBSERVED_NOT_EXECUTION_ADMITTED, а не order/fill. Actual paper executor должен успеть
сам и сохранить собственные intent/quote receipts; журнал сам этого не доказывает.

## Проверка и продолжение

Synthetic tests проверяют malformed forecasts, future source references, hash tampering,
crash до payload/record/commit, exclusive duplicate slot, lock contention, symlink/
hardlink/path escape, F gate до payload, slow publication и late consumption.
Windows не имитирует durability: fsync/flock tests явно skipped; они обязательны на Linux.

Следующий шаг — замкнуть source capture/replay, input snapshot, forecast publication и
бумажный execution/evaluation в единый activation protocol. До готовности и byte seals
F=null и новые цены не читать. Market data/models вне Git, real trades запрещены.
Runtime/test результаты — STATUS/EXPERIMENTS. Source/forecast journal не является
доказательством прибыли20%/50% и не снимает остальные gates.
