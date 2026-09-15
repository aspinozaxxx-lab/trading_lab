# V81 — быстрый отсев фандинга SBERF/GAZPF, не портфельный backtest

2026-09-15. Другая механика после V80: поток выплат держателю короткого perpetual,
который мог бы хеджировать акцию, а не directional news predictor. CNY perpetual/
quarterly уже закрыт и НЕ повторяется. GAZPF/SBERF исключались из прежнего broad carry;
в реестре отдельного исследования их фандинга не найдено.

## Данные и единицы до значений

[MOEX объявила](https://www.moex.com/n73437) начало торгов2024-10-01; оба контракта
котируются в рублях за акцию,100акций на контракт. [Описание MOEX](https://www.moex.com/a8805)
отдельно поясняет: фандинг на графике и в итогах торгов указан без учёта лота.
Поэтому SWAPRATE*100 — рубли на контракт, SETTLEPRICE*100 — proxy номинал; отношение
НЕ умножается на100. Текущие параметры2026 не применяются к прошлым выплатам.
В этой проверке не предполагается положительный знак SWAPRATE.

Exact public ISS RFUD history SBERF/GAZPF, from2024-10-01,till2025-12-31,
семь заранее определённых колонок; cursorINDEX/TOTAL/PAGESIZE,100rows/page,
максимум1000rows/ticker (20page requests,до3transport attempts/page),2MiB/page,
anonymousHTTPS,без ключа/покупки. Порядок колонок может различаться, exact names/row widths
и соответствие values своим names обязательны; порядок не меняет единицы.
До seal один name-only description probe на сервере подтвердил default TLS/HTTP200,
460bytes, единственная колонка name. Никаких market values или SWAPRATE в этом probe.
Исходные bytes и SHA/URL/receipt сохраняются до parser; schema/date/identity mismatch
останавливает новый root, не удаляет failure/raw. Не перезапускать existing root.
Все числа читаются только после config/code/tests/doc seal и push. No2026datasets.

Проверка пропущенных сессий использует date-only projection старой active-contract map:
SHA40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823,
500949bytes/8100rows. Все effective_date<2026; после проверки bytes/rows/hash читается
только эта колонка. Это factual core4 calendar proxy, не полный официальный календарь.
Каждая его сессия в пределах нового периода должна присутствовать в funding source;
пропуск означает неизвестный поток и APR=null, а не отсутствие начислений.
Дополнительные source dates внутри периода сохраняются. Existing market prices не нужны.

При первичном поиске документации поисковик также вставил текущие2026котировки чужих
RGBIF/IMOEXF. Эти instrument pages не открывались и snippets не использованы для design,
selection, формул или данных. Последующий источник — dated launch announcement и
текст единиц a8805, не current market API. Нет2026targets/returns/PnL.

## Фиксированная арифметика компонента

Для каждого из двух контрактов отдельно, без выбора победителя или весов:

1. Один условный100-share номинал измеряется по первой SETTLEPRICE в source.
   Первая строка задаёт только базу; её фандинг не включается, поскольку это было бы
   поступление до условного начала. Это измерение потока, не утверждение о fill по close.
2. Сумма всех последующих SWAPRATE*100 — наблюдаемый кредит короткой стороне.
   Zero/negative payments и zero-trade days не исключаются. Missing/nonfinite payment
   делает полный поток неизвестным; APR=null, никаких нулей вместо неизвестного.
3. Simple APR = credit / initial-notional *365.25/elapsed-calendar-days. Это простая
   нормировка денежных выплат, НЕ CAGR, доходность сделки или прогноз. Переоценка акции,
   perpetual и базиса не входит. Последующие цены не меняют исходный знаменатель.
4. Дополнительно показывается арифметика с20/40bps за условный полный парный roundtrip.
   Это только иллюстративный fee hurdle, не доказанные spread/fees/fills или net PnL.
5. Доходный поток достаточен для дальнейшей работы только если >=365calendar days,
   начало/конец не дальше5days от заданных границ, все payments известны,
   simple APR после double hurdle>=20% и >=75%месяцев имеют положительный funding.

Период до protected cutoff содержит лишь15месяцев,2024неполный; это не доказательство
предсказуемой20–50%доходности. Годовые и месячные выплаты публикуются полностью.
В итогах decisions/fills=0,CAGR/Sharpe/MDD/portfolioPnL=null — портфель не моделируется.
REJECT_FUNDING_COMPONENT означает отсутствие достаточно сильного funding-alone потока
при этой конвенции, не доказательство невозможности других basis/collateral механизмов.
INCOMPLETE_COMPONENT_NO_PROMOTION не объявлять экономическим отрицательным результатом.

## Только при положительном результате

FUNDING_COMPONENT_CANDIDATE не Stage2. Следующий отдельный economic protocol обязан
свести две стороны с next-factual fills, капиталом под акцию и margin buffer, обоими
bid/ask, fees, actual dividends и dividend adjustment, налоговой асимметрией и basis MTM.
[MOEX warning2024-12-11](https://www.moex.com/n75703) также описывает платное исполнение
по поручению и возможность встречного принудительного исполнения: это отдельный риск,
а не бесплатное бесконечное удержание. Нельзя считать всё будущим гарантированным income.
Если компонент слаб, не писать новый engine и не менять знак/даты/тикеры/fee hurdle.

Server-only root /srv/trading_lab_data/source_evidence/v81_stock_perpetual_funding_v1,
raw вне Git. --audit повторяет saved raw/cursor/date/unit/month/year арифметику без HTTP.
Archive AlgoPack и прежние collectors остаются независимыми. Запрошенное разрешение
на отдельную крипто-ветку пока не получено; новые crypto prices/data/PnL не запрашивались.
