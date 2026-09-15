# V94 — месячная премия за асимметрию доходностей

Одна новая гипотеза первого уровня, не новая модель или сборщик. До её численного
прогона фиксируются config/code/source hashes. Никаких значений2026.

## Механизм и границы вывода

Предпочтение инвесторами редких крупных выигрышей может завышать цену инструментов
с положительной асимметрией и оставлять премию у противоположных инструментов.
Основание — [Fernandez-Perez, Frijns, Fuertes, Miffre, 2018](
https://openaccess.city.ac.uk/id/eprint/17843/), abstract в репозитории авторского
университета. Там исследованы товарные фьючерсы; наши BR/MIX/RI/SI — смешанный,
маленький и коррелированный набор. Это самостоятельная непроверенная экстраполяция,
не репликация опубликованного результата и не обещание дохода.

В реестре/code нет самостоятельного realized-skewness allocation: прежний skew
использован в robustness statistics и будущих option features. V94 не меняет
провалившиеся trend/carry, continuous timing, opening или RVI corridor rules.

## Фиксированное правило

После первого завершённого торгового дня месяца вычислить sample skewness последних
126 последовательных daily returns каждого из четырёх активов. Каждый return —
две соседние календарные сессии одного exact contract, выбранного предыдущим
планом. На roll отношение цены нового контракта к старому запрещено. Требуются
положительные close и volume обеих сессий; missing не сжимает окно и не становится0.
Применяется unbiased Fisher-Pearson pandas skew, nonzero std>1e-12.

Long единственный минимум, short единственный максимум, по0.45 капитала.
Все4 skews должны быть конечны; ничья на экстремуме/неполное окно переводят весь
месяц в cash. Между месяцами направления сохраняются; существующий ledger ежедневно
пересчитывает integer quantity и проводит causal rolls. Control — заранее
объявленная зеркальная позиция с теми же masks, не запасной кандидат для promotion.

Период экономического теста2021–2025, warmup2018–2020; предыдущий месячный state
разрешён на старте, но начальных открытых позиций нет. Нет fit/calibration/порогового
поиска. История уже исследовалась другими семьями, independent holdout=false.

## Данные и исполнение

Повторно используются sealed recent inputs V64: active map, contract observations,
lagged spec proxies. Exact path/SHA/bytes/rows берутся из parent declarations и
проверяются до market values; V64 seal
`b60a02b4ba1d5ea3dedcc0f82e5090cc82fea40cc1c7864f851a97b0ee39bbff`.
Никаких AlgoPack numeric reads, новых HTTP, моделей или engine.

Решение после close, исполнение следующим factual open, gap>7calendar days masks.
Начальный1млнRUB, target gross0.9/cap1.0, margin buffer2, participation1%, cash rate0.
Два сценария:1tick+1×fee и2ticks+2×fee. Unexecutable target cancel-and-clip по активу;
failed exits/halt/marks остаются в общем ledger, последнее решение flat. Это
research-proxy исполнение, не доказанная синхронная рыночная сделка.

## Отсев и сохранение

Оба costs primary: CAGR≥5%,Sharpe≥0.5,MDD≤25%,≥50round-trip episodes, все5years,
≥3positive years,worst≥−15%,primary CAGR>control. Coverage≥80%; все4ledgers без
critical/unresolved и terminalflat. Иначе reject/invalid; нулевые сделки тоже результат.
Порог5% — только Stage2 component, цель20–50% не меняется. Контроль не продвигать.
После результата нельзя менять знак/окно/размер/актив/период/обработку пропусков.

Сохраняются features, оба targets, четыре orders/positions/ledgers, counts/coverage,
годовые показатели, cash-accounting checks и hashed manifest во внешнем server runs.
Новый каталог `runs/v94_skewness_premium_v1_<seal12>`; существующий никогда не повторять.
Запуск только UID999 на gpu-mlserver после push/seal/tests. Downloads не трогаются.
