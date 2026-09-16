# V103 — медленная межрыночная премия за неликвидность, Stage 1

Гипотеза: удержание риска менее ликвидного рынка может вознаграждаться большей
последующей доходностью. Проверяем относительную месячную позицию long high /
short low по заранее определённому daily price-impact-per-notional-volume proxy.
Это не обещание дохода, не маркетмейкинг по реальному стакану и не measured liquidity beta.

## Почему это не повтор V66

V66 проверял четыре signed OHLCV event rule: volume-shock reversal, pressure
continuation, thin-breakout fade и compressed-volume expansion. У V103 нет
сигнала по знаку тела свечи, диапазону или событию повышенного объёма: это
постоянный level-ranked risk premium с месячным выбором относительных позиций.
V94 использовал skewness preference, а не compensation for illiquidity.
Данные те же; новый механизм не означает независимую информацию или holdout.

[Cho, Ganepola, Garrett](https://doi.org/10.1002/fut.22007) рассматривают плату за
неликвидность и страхование в commodity markets; прочитан abstract, не выполнена
репликация статьи. Перенос идеи на смешанные BR/MIX/RI/SI — наша непроверенная
экстраполяция. [Huang, Yueshen, Zhang](https://doi.org/10.1017/S0022109023000224)
показывают в модели, что показатели воздействия на цену и премия за риск
ликвидности могут расходиться. Поэтому показатель ниже — лишь проверяемый proxy.
Никакой покупки/скачивания article datasets или нового source pipeline.

## Зафиксированное правило

Для каждого из четырёх рынков вычислить среднее за 63 полные последовательные
сессии: `1e6 × |close(t)/close(prev)-1| / (close(t) × volume(t) × sizing_point_value(t))`.
Обе цены относятся к одному заранее выбранному контракту и соседним сессиям;
point value — прежний causal sizing proxy, не realized accounting conversion.
Его observed date должна быть < t и <= predecessor, usable=true, lag=1.
Реальный нулевой return допустим; zero/missing volume/price/spec не заменяется нулём.
Пропуски календаря не сжимаются; разрыв >7 календарных дней маскирует наблюдение.

Первый decision session месяца, 18:45 Moscow: использовать окно, заканчивающееся
строго предыдущей сессией, а не close ещё не завершённого decision day. Conditional
availability = следующий гражданский день 08:00 Moscow. По четырём полным оценкам
long максимум +0.45, short минимум −0.45. При missing/tied extreme весь месяц cash;
не восстанавливать выбор задним числом в середине месяца. Контроль — sign mirror
с теми же masks, его нельзя продвигать после outcomes. Размеры/окно/знак/контроль
не подбирать. Переключение активов раз в месяц, resize/roll ежедневно старым ledger.

Выполнение — следующий фактический daily open; intent с gap >7 дней отменяется,
future-exit availability не используется. Последняя дата flat, неисполненные
выходы/halts не исчезают. Две ноги не гарантированно исполняются одновременно;
gross/net weights не означают beta/FX neutrality. Размер рынка, валютная специфика,
концентрация roll, волатильность и дискретность цены могут определять весь результат.

## Данные и gates

Только existing V64 recent declaration: active map8100rows, observations/specs66052,
2018-01-03…2025-12-30; SHA соответственно
`40e817080676f906e6ae33bb5c4d7f98f0c753fd43d6569fc7884bd618168823`,
`a1c650780d08e31668829bc5bb07d0aeb25239d44f8f3620cb2d054ded70acf6`,
`8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682`.
Parent V101 seal `067dc4ec60266536e57c51df322c74c7daaef9b91a3f46db5fcaad78a672f55a`
пинит V64 inputs/code, V94 same-contract pairing и прежний V78 ledger/reporting.
Metadata preflight до numeric read. Никаких новых input downloads; raw вне Git.

Evaluation2021–2025,2018–2020 только warmup. Нет fitted model, train/calibration/
hyperparameter selection; causal trailing features, не независимый purged holdout.
Старт1млнRUB, gross cap1.0, target gross0.9, margin buffer2, participation1%.
Base1tick/1fee, double2ticks/2fee, interest0; все прежние execution gates.
Stage1: readiness>=80%,50roundtrips,CAGR>=5%,Sharpe>=0.5,MDD<=25%,3positiveyears/5,
worstyear>=−15%,CAGR excess над control>=2п.п. в обоих costs,execution complete
у обеих сторон. PASS — лишь Stage2 robustness/attribution, не цель20–50%/demo/live.

Outputs: features, targets, orders, positions, cash ledgers, все years/costs/counts,
assessment и manifest в отдельном external run. Seal code/config/tests/protocol
до расчётов; canonical не перезапускать. Cash/metrics audit не является независимой
реконструкцией всех risk counters. При fail параметры и старый engine не менять.
TIC остаётся paused; main AlgoPack downloader и ограничения2026/broader scope неизменны.
