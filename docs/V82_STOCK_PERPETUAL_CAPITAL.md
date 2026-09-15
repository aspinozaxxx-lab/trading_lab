# V82 Проверка капитала для фандинга SBERF и GAZPF

Зафиксировано2026-09-15T11:04:13Z после результатов V81, до данного пересчёта.
Это короткая диагностическая часть следующей парной проверки, не новый независимый
backtest. Финансовые inputs — только уже просмотренные, сохранённые V81 aggregates.
Новые stock/perpetual entry-exit prices, dividend outcomes и2026 не открываются.

## Проверяемое утверждение

Хватает ли ранее наблюдавшегося фандинга для20% простой годовой нормировки на капитал
«полный номинал акции плюс резерв под фьючерс»? Оба тикера сохраняются независимо от
результата. Самостоятельную способность компонента закрывает shortfall хотя бы при
double costs. Это не отрицание возможной отдельной прибыли от базиса или подтверждённого
доходного обеспечения. Для них нужны новые inputs и полный заранее запечатанный расчёт.

Резерв30%, stock10/futures5bps на сторону и удвоение взяты из неизменённого
configs/stock_futures_cash_carry_intraday_v1.yaml, SHA
aa35b0d864483b30e0b6ffec67dec9b5efeab945362dc9cf5b91e60c06c1885e.
Это прежние исследовательские допущения, а не актуальный тариф брокера или доказанная
достаточность historical ГО. Fees нормированы на начальный номинал:30/60bps roundtrip,
не на неизвестные пока фактические entry/exit notionals.

Для nominal N, funding F, span T, reserve fraction r и fee fraction c:

- капитал C = N × (1 + r);
- funding-less-fee APR = (F − c × N) / C ×365.25/T;
- максимальный дополнительный капитал для target a = ((F/N − c) ×365.25/T)/a −1;
- требуемая простая доходность только резерва = max(0, (a ×(1+r) −
  (F/N − c) ×365.25/T)/r).

Отрицательный maximum-extra-capital означает, что даже одного principal уже слишком
много для данной цели. Required-reserve-income — только условие, никогда cash credit:
заложенные деньги нельзя одновременно считать свободным доходным инструментом без
подтверждённых collateral eligibility, haircut и достаточной ликвидности.
Targets20/50% не означают обещанный APR и не заменяют цель устойчивого portfolio CAGR.
Никакого fit, выбора удачных месяцев, reinvestment или изменения количества контрактов.

## Правила парного учёта из исторической спецификации

Архив редакций [MOEX26831](https://www.moex.com/ru/documents/26831) покрывает все даты:
01.10.2024–04.08.2025,05.08.2025–28.08.2025,29.08.2025–22.03.2026. Последняя дата —
срок действия документа, не доступ к2026market outcomes. Три DOC сохранены вне Git;
источники и SHA находятся в config. Original binaries сохранены также локально в
D:/Projects/trading_lab_data/tmp/pdfs/v82_stock_perpetual_spec_20260915/.
Название каталога историческое: это DOC, не PDF.

Первоначальная ссылка из новости2024 fs.moex.com/files/26107 сейчас перенаправляет на
страницу другого документа об индексах. Сохранённый310015-byte response под расширением
.pdf имеет HTML header и НЕ принят как спецификация. Правильная ссылка из карточки
продукта —26831, затем dated revision downloads.

Извлечены текст и формулы всех трёх версий без запуска Office или макросов: antiword
0.37-16 из подписанного Ubuntu package index, отдельная unpacked directory на сервере,
без установки системного пакета. Штатный Word renderer в окружении недоступен; native
page layout визуально не подтверждён. Ни одним PDF source этот файл не объявляется.
Формулы присутствуют в текстовом извлечении, не заменены изображениями/догадками.

В редакции01.10.2024, пункт2.1.3, evening VM для перенесённой длинной позиции включает
изменение settlement плюс DivAdjustment, умноженные на W/R, и вычитает SwapRate × Lot;
W/R=Lot=100. Для короткой позиции знаки обратные: funding credit, dividend debit.
Для впервые открытой в текущую основную сессию позиции dividend adjustment отсутствует.
Величина DivAdjustment равна дивиденду и относится к record date; если это не торговый
день — к предыдущему торговому дню. Неизвестный event corpus не разрешает заполнить нулями
все дни. Пересмотр дивиденда допускает пересчёт VM. Settlement определяется официальной
ценой закрытия акции с округлением к шагу, не произвольным last10mclose.

Корректная cashflow identity пары:
stock price MTM + short perpetual price MTM + short funding − dividend adjustment debit
+ net actual stock dividend cash − all costs. Missing любого слагаемого даёт null.
До налогов одинаковые gross stock dividend и dividend debit взаимно компенсируются;
после удержания налога может остаться убыток, а до поступления выплаты нужен cash buffer.

Пункт2.2 допускает исполнение в quarterly future без поручения владельца. Текущие правила
конвертации нельзя переносить назад: [новость11.12.2024](https://www.moex.com/n75703)
содержит1%commission по добровольному поручению и0%при forced execution, тогда как
нынешняя [страница продукта](https://www.moex.com/a8805) содержит иной порядок платежей.
Полный historical conversion calendar/clearing rule и его ledger ещё не собраны.

## Inputs и защита от неверных выводов

Parent metrics SHA6b90b9fb66a4b146156c28ed31ead1a7b6ff78cfd1d779ce12211f612fe68874;
V81 seal a9e4299e3a8846d6dba8d19588af18baaf63b7b2818e107e13b59b587e5ac89a.
V81 audited320sessions/319payments на тикер,2024-10-01…2025-12-30. Этот архив не
перекачивается и полный source audit не повторяется. Consumer сверяет SHA, даты,
полноту, счётчики, суммы годов/месяцев и уже опубликованный nominal APR.
Суммы V81 не округлены как реальные daily VM receipts; здесь остаются component proxies.

Existing SBER/GAZP spot schemas: open/high/low/close/value double, volume int64,
timestamp[ns, UTC] — pandas index. Проверена только схема, price projection не читалась.
На сервере подтверждены CBR manifest4609bytes и daily102901bytes с прежними SHA;
схема имеет observation/effective/publication_date/available_at/value. Rate values не
открывались, benchmark в этом кратком диагностическом расчёте не вычисляется.
Эти источники доступны для следующего полного теста, но не являются уже выполненным тестом.

Outputs: immutable identity/metrics JSON под отдельным /srv/trading_lab_data/runs root.
Все2names×2costs, годовые funding cashflows и их доля фиксированного капитала, явно
partial2024. Decisions/fills0. PortfolioPnL/CAGR/Sharpe/MDD/cash benchmark=null,
полный список unresolved pair inputs, Stage2=false, goal_verified=false.
Перед расчётом — synthetic tests, SHA config/code/protocol/lineage. Economic compute
только service-user999 на gpu-mlserver. Replay не делает HTTP и не изменяет canonical.

## Следующий допустимый шаг

Сохранить вывод по capital capacity и список недостающих частей. При наличии отдельного
экономического запаса проверить BOTH full pairs: actual matched next-bar fills,
dividends/tax/VM, dated margin/cash liquidity, conversion handling и same-period cash
comparison. Нельзя выбрать только GAZPF, уменьшить reserve/costs по результату или
приписать резерву RUONIA без доступного инвестируемого обеспечения. Нельзя объявить
funding shortfall полным экономическим провалом пары, пока остальные слагаемые unknown.
