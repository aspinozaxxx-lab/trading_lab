# V69 — monthly futures-chain open-interest growth, Stage 1

Одна фиксированная гипотеза: расширение общего объёма открытых фьючерсных позиций
отражает спрос на риск, который не полностью отражён в цене. Проверяем знак 63-session
изменения суммарного reported OI, независимо для BR/MIX/RI/SI, против constant-long
контроля с тем же availability mask. Контроль не является новым кандидатом.

Мотивация — [Hong / Yogo](https://www.nber.org/papers/w16712): авторы исследуют
информацию открытого интереса о макроэкономике и доходностях. Это не репликация их
исследования: здесь российские активы, количество контрактов, квартальное изменение
и конкретное месячное правило. Рост OI сам по себе не означает net buying: у каждого
контракта две стороны. Эффект для MOEX и направление экономически не доказаны.

В V7/V8 уже были active-contract OI changes 1/5 sessions внутри нейросети. Новизна V69
не в существовании поля OI: здесь вся наблюдаемая цепочка, другой target/horizon и
отдельная причинная проверка механизма, без перенастройки старой модели. Не V16 FUTOI
participant crowding и не опционный V68; все их исходы остаются закрытыми.

## Дизайн до outcomes

- Входы: прежний sealed V64 recent execution catalog и исходный V5 audit с 478
  проверенными artifact identities. Hash, bytes, dates и linkage проверяются до цен.
  Dates 2018–2025; protected 2026 не читается. Никаких новых downloads или моделей.
- До этого протокола прочитаны только schema и OI missing counts: 66 052 rows;
  missing BR/MIX/RI/SI = 117/562/339/63. Из 2025 asset dates полны все присутствующие
  OI cells в 1915/1512/1735/1963 случаях. Цены/OI growth/new PnL для дизайна не считались.
- Один NULL в reported chain маскирует весь дневной total. Не удаляем NULL контракты
  и не объявляем их нулевыми. Состав полученного source не доказывает полный рынок.
- Сравниваем total с 63-й предшествующей factual asset date: оба положительны,
  не должно быть calendar gap >7 дней в интервале. Missing между endpoints не
  интерполируется; OI не является доходностью, endpoints остаются наблюдёнными.
- Availability proxy: source date +1 calendar day 00:00 Moscow. Первое factual
  decision day нового месяца берёт только строго предшествующий доступный source.
  Последующие daily targets сохраняют это решение. Invalid новый месяц = flat весь
  месяц, без fallback на старое хорошее значение. Нет future month-end selection.
- Monthly direction, daily target-weight sizing и причинные роллы; next factual open.
  Целевой вес каждого актива ±0,25, общий gross <=1, миллион рублей, integer contracts,
  margin buffer 2, participation <=1%, cancel_and_clip. Проценты на cash не добавляются.
- Два costs: 1 tick/1x fee и 2 ticks/2x fee. Terminal flat. Missing execution сохраняет
  фактическую позицию/риск в готовом ledger, не создаёт выдуманную сделку.
- Fit, threshold search и новый engine отсутствуют. Уже открытая история 2018–2025
  не считается independent holdout. Все восемь лет и оба costs публикуются.

## Отсев

Численные правила находятся в `configs/v69_futures_chain_interest_v1.json`.
Нужно не менее 60% доступных месячных asset decisions, включая initial warmup;
это заранее мягкий screen с учётом уже известных missing counts, не source admission.
Оба costs: >=100 closed episodes, CAGR>=5%, Sharpe>=0,5, MDD<=25%, >=5/8 прибыльных лет,
худший год >=−15%, CAGR выше constant-long контроля. Все четыре executions complete,
critical/unresolved=0, terminal flat. Только STAGE2_CANDIDATE; цель20–50% не снижена.
Если проходят — следующая проверка охватывает устойчивость к coverage/membership и
зависимость от прежнего лидера, затем доказуемое исполнение и новый prospective период.
Если нет — никаких смены знака, горизонта, состава активов, расписания или missing policy.

Код использует неизменные V64 input checks/ledger и V68 count/metric/gate helpers,
но не вызывает старые стратегии и не повторяет их runs. Новый config/code/test/doc
seal публикуется до единственного server run. Итог будет отдельной RESULT note.
