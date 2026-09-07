# Portfolio process session V1

2026-09-07. Устранение repeated full replay перед каждой записью; экономические
правила, parent reducer/journal и их байты не меняются. F=null, actual trades0.

## Измеренное основание

Metadata/state benchmark на gpu-mlserver отUID999 использовал только synthetic MARK
events, fake2099clocks и process-local mocked activation. После100events full recover
0,018840сек, append0,054221сек; после500events recover0,092412сек, append0,133502сек.
Это одиночные наблюдения, не SLA и не измерение реальных market/position workloads.
Пока задержка небольшая, но full replay зависит от длины истории. Только idle-state
MARK не измеряет цену большого state/seen-ID набора. Синтетический root сохранён:
`/tmp/trading_lab_synthetic_portfolio_scaling_t7iq5u45`,501events, actual HTTP0.

## Новый hot path

PortfolioSession при создании ВСЕГДА выполняет полный parent recover и проверяет
external expected_tail. Произвольный serialized cash/state загрузить как доверенный
checkpoint нельзя. Snapshot и anchor возвращаются копиями; caller mutation не меняет счёт.

Перед append: complete activation/свой module SHA, тот же portfolio flock, проверка
последнего committed record по known SHA и отсутствие следующего reserved event.
Затем тот же reducer validation, immutable parent publish/fsync и применение actual
durable clock. В штатном случае перечитывается один tail event, не весь префикс.
Стоимость копирования текущего state/seen IDs всё ещё зависит от его размера; это
bounded journal-read path, не обещание абсолютногоO(1) времени.

При competing writer, partial next event или повреждённом tail cached session
инвалидируется. После любой неопределённой публикации, в том числе lost acknowledgment,
нужен новый full replay; retry старой snapshot запрещён. Committed event не стирается.
Неверная операция, отклонённая до начала publication, не портит валидный cache.

Cold replay проверяет полную sequence и byte integrity. Hot path не перечитывает все
старые bytes и не является полной forensic проверкой каталога против произвольного
изменения старой истории. Для обычных writers действует общий lock/contiguous sequence.
External tail нужно хранить отдельно; session его только возвращает и проверяет на
входе, но не устанавливает самостоятельный durable checkpoint. Потеря всего журнала
без внешнего anchor не обнаруживается самоссылочным hash chain.

## Готовность и следующий шаг

8synthetic tests,7Linux-only: hot append без full replay/с одним observe, restart parity,
защита snapshot, competing writer, lost ack, rejected operation, incomplete event,
сохранение reserve. Локально1PASS/7skips; server verification после push.
Нет CLI/timer/actual activation/market IO. Новый module должен войти в общий bundle.

Далее integrated runtime event/evidence builder и его external anchor publication,
missed-exit recovery, daily snapshot/evaluation и scheduler. Не повторять benchmark
как отдельное исследование; эта проверка не доказывает прибыль или реальную latency/SLA.
