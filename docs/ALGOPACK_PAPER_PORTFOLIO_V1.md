# Paper portfolio V1 — event replay and risk accounting

2026-09-07. Добавлен reducer и dedicated Linux journal для двух независимых бумажных
счетов price_only/price_flow. Это не activated runner; F=null, actual trades0.

## Состояние и переходы

RESERVE закрепляет уникальный arm/asset/entry slot и резервирует бюджет. Открыть второй
pending/open slot одного asset нельзя; canceled/closed slot тоже нельзя повторить.
Размер сравнивается с marked primary equity: aggregate notional≤basis и margin≤40%basis,
per-entry≤25%notional/10%margin. Basis≤1млн, поэтому прибыль автоматически не увеличивает
лимит. Pending positions резервируют полные утверждённые budgets, а не ноль.

ENTRY требует прежний durable intent строго до entry, совпадающий Intent и Fill;
повторное открытие запрещено, fill notional не превышает reservation. EXIT реализует
conditional1×/2×net из execution core один раз; затем освобождает резерв. Ни integer
quantity, ни full-arm capital не занимают деньги независимого baseline счёта.

CANCEL разрешён только для позиции без entry, с явной причиной; открытый риск так
удалить нельзя. UNRESOLVED сохраняет entry и блокирует новые reservations этой arm.
Conversion-change exit тоже остаётся unresolved, не преобразуется в zero PnL.
Автоматической ликвидации после пропущенного exit window пока нет: нельзя выдумать
позднюю цену или применить старый fill как якобы своевременное восстановление.

## Оценка капитала

MARK заменяет полный набор текущих marks; отсутствующее наблюдение не forward-fill-ится.
Для open positions используется условная liquidation value по встречной стороне с
adverse tick, entry+estimated exit fees, отдельно1×/2×. Это консервативная оценка для
бумажного риска, не фактический брокерский денежный баланс. Closed net начисляется в
cash целиком; open costs учитываются в valuation, поэтому их не списывают дважды.

Дата/свежесть/exact contract/spec conversion и10%visible exit depth проверяются снова.
При missing/stale/недостаточном depth equity/free margin/free notional=null, не0 и не
последний известный капитал. Existing unresolved position может иметь текущую оценку,
но всё равно не разблокирует новые входы. Insolvent equity не получает новый бюджет.
Перед append нового intent aggregate capacity сверяется ещё раз по actual append clock.

## Persistence и границы доказательства

Dedicated root содержит только portfolio_00000001… source events, без дырок и foreign
events. Каждый event связывает previous record SHA, последовательность и actual clocks.
Append требует complete activation с source/execution и новым portfolio module; два
writer сериализуются Linux flock, внутри используется parent immutable journal/fsync.
Переход валидируется до publication и затем с actual durable clock. Parents не меняются.

Recover повторно проверяет committed record/payload hashes и применяет все переходы.
Неполный event не пропускается/не перезаписывается: recovery останавливается с ошибкой,
артефакты остаются для расследования. expected_tail из внешнего checkpoint обнаруживает
усечение раньше этого anchor или подмену соответствующего record. Без external anchor
нет криптографического доказательства против удаления всего хвоста/всего каталога.
Runtime должен сохранять и сверять этот anchor, а не считать пустой root новым счётом
после уже начатого опыта.

Ledger проверяет state consistency и clocks, но не заменяет повторную проверку каждого
Fill/Intent по source/forecast references. Runtime обязан выбирать источники причинно,
проверять фактическую своевременность вычисления/публикации и хранить full evidence.
Прямо передать придуманный Fill в reducer — не доказательство совершения сделки.
Ещё нужны integrated event builder/evidence replay, missed-exit recovery policy,
evaluation и scheduler с полным учётом failed slots до первого actual post-F запуска.

13synthetic tests, в том числе2Linux persistence/restart cases. Actual server results
смотреть в STATUS. Никаких market requests/обучения/реальных сделок этот модуль не делает;
broker fee всё ещё assumption, доходность20–50% не подтверждена.
