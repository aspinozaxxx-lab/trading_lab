# V95 — премия за низкую чувствительность к общему рынку

Одна новая гипотеза первого уровня. Источники и симулятор уже есть; нового
сборщика, торгового движка или нейросети не требуется. Протокол фиксируется до
расчёта новых beta states, targets и экономического результата.

## Экономический механизм

Инвесторы с ограничениями на плечо могут переплачивать за высокий рыночный риск.
Тогда покупка низкой beta и продажа высокой beta с одинаковым расчётным риском
может получать премию. Основание — [Frazzini и Pedersen, Betting Against Beta](
https://www.aqr.com/insights/research/journal-article/betting-against-beta), 2014.
Авторы рассматривают ограничения заимствований и несколько классов активов.
Наш малый смешанный MOEX universe не является репликацией их исследования.

Это не trend direction, correlation-aware trend sizing, RI–MIX corridor или
перестановка знака V94. Скос доходностей не вычисляется. Гипотеза может оказаться
слабой или зависимой от уже известных источников прибыли — это нужно проверить.

## Фиксированное правило

Для BR/MIX/RI/SI использовать exact-contract daily returns: close текущей сессии
к close предыдущей сессии того же контракта. Контракт выбран до текущей сессии;
обе цены и объёмы положительны. Смена контракта не создаёт ценовой скачок;
пропуски не удаляются из календаря и не заменяются нулями.

Фактор — средний return всех четырёх инструментов с равными весами. Если хотя бы
один return неизвестен, весь фактор за день неизвестен. Beta — sample covariance
с фактором, делённая на его sample variance, за 252 последовательные сессии.
Требуется полное окно и variance > 1e-24; нет shrinkage или подбора estimator.

В первый завершённый торговый день месяца должны быть известны все четыре beta.
Среди положительных beta выбрать единственные минимум и максимум; при менее двух
допустимых значениях, ничьей или missing весь месяц cash. Покупка минимума и
продажа максимума имеют веса:

`w_long = 0.9 * beta_high / (beta_low + beta_high)`

`w_short = -0.9 * beta_low / (beta_low + beta_high)`

Поэтому сумма модулей весов 0.9, а экспозиция к прошлой оценке beta равна нулю.
Это не гарантия будущей рыночной нейтральности или нейтральности фактического RUB PnL.
Численно используется отношение beta_low / beta_high, без огромных промежуточных
обратных beta. Control берёт те же активы с весами +0.45/−0.45, отделяя эффект
выравнивания beta от самого ранжирования. Control не запасной кандидат для promotion.

## Период, исполнение и отсев

Экономика 2021–2025; 2018–2020 только для warmup и предшествующего monthly state.
Новый портфель начинает с 1 млн RUB, не наследует позиции. После close — следующий
factual open; gap более 7 календарных дней отменяет target. Между месяцами веса
фиксированы, quantities ежедневно пересчитываются существующим causal ledger.
Gross cap 1.0, margin buffer 2, participation 1%, collateral interest 0. Издержки:
1 tick + 1×fee и 2 ticks + 2×fee. Последний target flat, unresolved exits не удалять.

Primary при обоих costs: CAGR ≥ 5%, Sharpe ≥ 0.5, MDD ≤ 25%, ≥ 50 round trips,
все пять лет, минимум три положительных, worst year ≥ −15%, CAGR строго выше control.
Готовность ≥ 80%; все четыре ledgers complete, без critical/unresolved и terminal risk.
Порог 5% — только предварительный компонентный отбор; цель 20–50% неизменна.
Никаких sign/window/factor/asset/size/mask изменений после результата.

V64 recent declarations фиксируют source paths/SHA/bytes/rows, parent seal
`b60a02b4ba1d5ea3dedcc0f82e5090cc82fea40cc1c7864f851a97b0ee39bbff`.
Перед numeric reads обязательны byte/schema/date checks. Защита 2026 сохраняется.
Используется готовый V78 simulate_case и V68 reporting, не их старые экономические
правила. Данные final-vintage/proxy, история уже исследовалась: independent holdout=false.

Сохранить exact returns, beta states, оба targets, четыре ledgers/orders/positions,
counts, coverage, все годы/costs и manifest во внешнем новом каталоге
`/srv/trading_lab_data/runs/v95_beta_premium_v1_<seal12>`. Existing run не повторять.
Запуск только на gpu-mlserver после push и synthetic tests; downloads не менять.
