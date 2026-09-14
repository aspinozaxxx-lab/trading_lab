# V75 — dividend-revision drift: недостаточно сопоставимых событий

2026-09-14, `SOURCE_FEASIBILITY_REJECTED`, до market join/PnL. Не economic screen
и не ещё один валидный отрицательный backtest. V65–V74 остаются 16 screened /0Stage2.

Идея: после изменения ожидаемой выплаты могла сохраняться направленная реакция
акции. Это иной target, чем уже закрытый dividend-adjusted calendar spread, но
доступные RMS records сами по себе не являются исходными объявлениями эмитентов.
[MOEX, 2023-06-02](https://www.moex.com/n56497?nt=107) определяет `T` как дату потока,
`CF` как величину потока и `CFRISK` отдельно. Они не равны выплаченным дивидендам
или surprise относительно аналитического консенсуса.

Проверены только исходные cashflow records и contract identity, без рыночных значений.
Источник: `data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4`:

- Manifest SHA: `e88360d3f1a3476e3e34a67b947fb7aa1a656a2c290aa46e27add84dd397b2e3`.
- Cashflow SHA: `be7f9a32bf2b085edb01df4cee8d3a895be10b182e9708fd5e033616dfefad19`.
- 10 817 rows, 170 global snapshot dates, source/update clocks до2026.
- 27 stocks /28 RMS codes из прежней frozen broad-carry mapping. ENPG/CBOM/RUAL
  не получают выдуманный нулевой CF. PLZL/PLZLM не соединяются через смену identity.

До цен выбран простой admission: сравнить две последовательные global snapshots
по одному RMS asset. Только будущие даты `T >= current tradedate +21calendar days`,
один и тот же непустой набор `T` в обеих snapshots. Одинаковый current cutoff применяется
к обеим сторонам. Missing/первая snapshot не означает zero. При изменении календаря
выплат comparison masked, а не сопоставлен по порядку строк. Изменение — сумма
`current CF - previous CF` по exact matching T, tolerance1e-10; CFRISK не alpha.
Если asset отсутствует в очередной global snapshot, предыдущий state сбрасывается.

Получено 2 165 mapped asset-state comparisons:

| Причина | Количество |
| --- | ---: |
| First / missing previous asset | 71 |
| Empty / different future payment schedule | 290 |
| Unchanged CF | 1 799 |
| Nonzero matched CF change | 5 |

Пять изменений: 4 в2024 и1 в2025,0 в2023; четыре повышения и одно снижение.
По одному у CHMF/PHOR/TRNFP/LKOH/PLZL. Это ещё не пять сделок: admission по времени,
split semantics, реальные объявления и исполнение не проверялись. Достаточности
для планируемого трёхлетнего event screen с минимум30complete events уже нет.

Решение: не переносить отсутствующие на server spot/RMS datasets, не писать новый
portfolio engine и не открывать цены ради этих пяти событий. Не расширять сравнение
через missing/new payment dates, не менять lag/universe ради увеличения счётчика.
Для иной будущей dividend-news гипотезы нужны original issuer announcements с
revision chain; это не основание повторять текущую source feasibility.

Прямой SSH probe подтвердил отсутствие двух точных canonical manifests RMS/spot
в `/srv/trading_lab_data/data/processed/...`; локальный source-only count использовал
уже сохранённые файлы в `D:\Projects\trading_lab_data`, без экономических вычислений.
Широкий web search также вернул нерелевантные snippets о новых продуктах2026; эти
страницы не открывались, сведения не использованы в mapping, правиле или результатах.
Факт source-only отсечения не доказывает убыточность dividend strategies вообще.
