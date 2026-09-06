# V64 — бесплатная проверка налогового календаря SI

Покупка AlgoPack отложена пользователем 2026-09-07. Это самостоятельная новая family,
не повтор V19: там использовался опубликованный знак операции Минфина, здесь только
заранее известный календарь. Предположение — спрос компаний на рубли для налогов может
поддерживать рубль перед платежами. Реальные продажи экспортёров не наблюдаются.

[ФНС, 2015](https://www.nalog.gov.ru/rn18/news/tax_doc_news/5639218/) указывает
25-е число для уплаты НДПИ; [объявление ФНС, 2022](https://www.nalog.gov.ru/rn92/news/activities_fts/12571840/)
описывает единый срок 28-го числа с 2023 года. Используется номинальный календарный
ориентир, не точный налоговый календарь: переносы выходных, отсрочки конкретных компаний
и размеры платежей не моделируются. Для периода до 2015 года дата 25 является заранее
объявленной календарной proxy, а не доказанной original-vintage юридической выборкой.

## Фиксированные правила

- Primary: short SI после закрытия сессии с датой в интервале `[anchor−7, anchor−1]`.
  Anchor — 25 до 2023, 28 с 2023. Fill не раньше следующего фактического open.
- Control: тот же short и те же costs, но ориентир на 14 календарных дней раньше.
  Control не превращается в новую стратегию, если primary проигрывает.
- Вне окна — flat. Запоздавшая заявка отменяется при открытии, если настал другой
  месяц или дата уже позже anchor. Missing contract/tradability отмечается как sleep.
- Целевой номинал до 1× капитала, integer sizing, 1% prior-volume capacity,
  gross cap 1×, двойной buffer modeled IM. Старый проверенный cash-pool ledger;
  фактические позиции/издержки/settlements, не доходность склеенного графика.
- Отдельные eras 2008–2011, 2012–2017, 2018–2025 используют byte-pinned архивы.
  Каждый начинает с 1 млн ₽ и принудительно закрывается по последнему допустимому
  next-open mapping; через разрывы источников позиции/NAV не склеиваются.
- Primary/doubled/stress — 1/2/4 ticks slippage и 1×/2×/2× fees. Доход на остаток
  не начисляется. Это research proxy, без broker-exact quotes/fees/specs.

Модели и подбора параметров нет, поэтому nested fitting не применяется. Весь доступный
период рассматривается по трём eras и годам. История уже открыта другими экспериментами:
это development screen, не независимое подтверждение и не live admission.

## Отсев до сложной модели

Все 18 ledgers должны быть complete и terminal-flat. Primary — минимум 12 round trips
в каждом era, не менее 60% положительных year segments; primary и stress net returns
положительны и CAGR выше control в каждом era. Отдельно показываются gates 20%/50%.
Прохождение механического screen не означает достижения цели и не разрешает капитал.
Нельзя менять окно, знак, размер, годы, стоимость или control после результата.

Количество решений, nonzero targets, пропуски, round trips, экспозиция, оборот,
gross/net PnL, CAGR/Sharpe/MDD, годы и причины неисполнения сохраняются отдельно.
Разные январские праздники и длительность экспозиции control — явное ограничение,
поэтому сравнение не является причинной оценкой налогового эффекта.

## Запуск и продолжение

Протокол: `configs/v64_si_tax_calendar_v1.yaml`, closure seal:
`configs/v64_si_tax_calendar_v1.seal.json`. SHA seal передаётся явно через `--seal-sha`.
До первого market load нужны commit/push, synthetic tests и server metadata preflight.
Все economics выполняются только на `gpu-mlserver`:

```bash
cd /opt/trading_lab
.venv/bin/python -m market_lab.futures_v64_si_tax_calendar \
  --storage-root /srv/trading_lab_data --seal-sha <verified-seal-sha> --preflight-only
```

После успешного preflight тот же вызов без `--preflight-only` создаёт единственный
`/srv/trading_lab_data/runs/v64_si_tax_calendar_v1_<seal-prefix>`. Повторный запуск в
существующий каталог запрещён, в том числе после частичной ошибки. `--audit <run-path>`
проверяет hashes и пересчитывает метрики из сохранённых ledgers, не повторяет сделки.
Текущий результат/путь — [STATUS.md](STATUS.md); реестр — [EXPERIMENTS.md](EXPERIMENTS.md).

## Канонический результат 2026-09-07 — NO_GO

Экономический запуск выполнен один раз на `gpu-mlserver`, под `trading-lab`.
До результатов запушен commit `238a0ed`; local synthetic/execution/encoding slice
42/42, V64 server synthetic 17/17. Сначала metadata-only проверка обнаружила отсутствие
старого source bundle на сервере; economics не запускались. Существующий byte-identical
локальный bundle скопирован с запретом overwrite, после чего preflight прошёл 45/45.
Никакие цены/доходности 2026 года в V64 не использованы, collectors не менялись.

- Config SHA `e26e5156ec49c8187983526236aec9a9a65c9050125ebf1d1d0fa1fc8d8566f6`.
- Closure SHA `b60a02b4ba1d5ea3dedcc0f82e5090cc82fea40cc1c7864f851a97b0ee39bbff`.
- Canonical `/srv/trading_lab_data/runs/v64_si_tax_calendar_v1_b60a02b4ba1d/`.
- Metrics SHA `e6b1372dcfe59dde395bb418f20f6391435ce54df488250a904c03384540f277`.
- Identity SHA `e272a725f268883201d4850df9bdfc7c2393181c5b15e050c9f18f611bcaee6d`.
- Read-only identity/metric replay audit: 156/156. Все 18 execution ledgers complete,
  terminal-flat, critical failures и unresolved halts — 0.

| Era (фактические границы source) | Arm | CAGR 1× / 2× / stress | Sharpe 1× | MDD 1× | Round trips 1× |
| --- | --- | ---: | ---: | ---: | ---: |
| 2008-10-08…2011-12-15 | Tax | 2,8228% / 2,4292% / 2,2876% | 0,528 | 9,3030% | 37 |
| 2008-10-08…2011-12-15 | Control | −1,1166% / −1,5618% / −1,7777% | −0,170 | 10,8034% | 36 |
| 2012-01-03…2017-12-01 | Tax | 2,0282% / 1,6571% / 1,5461% | 0,291 | 19,2656% | 70 |
| 2012-01-03…2017-12-01 | Control | 0,5287% / 0,1575% / 0,0532% | 0,110 | 13,8733% | 71 |
| 2018-01-03…2025-12-30 | Tax | −0,1589% / −0,2292% / −0,3149% | 0,019 | 25,1107% | 96 |
| 2018-01-03…2025-12-30 | Control | 0,5827% / 0,2823% / 0,2595% | 0,110 | 19,6703% | 96 |

Границы источника не означают полные календарные начальные/конечные годы или непрерывную
историю между eras. Не суммировать их CAGR и не склеивать отдельные NAV в новый backtest.
Целевое плечо до 1× не является непрерывной гарантией: между rebalance при изменении
цен максимальное фактическое close-плечо primary достигало 1,028× / 1,066× / 1,087×.

| Tax primary | Early | Middle | Recent |
| --- | ---: | ---: | ---: |
| Decision rows | 780 | 1 478 | 2 024 |
| Nonzero targets | 170 | 328 | 449 |
| Exposed / ledger sessions | 170 / 781 | 328 / 1 479 | 449 / 2 025 |
| Expired calendar signals | 11 | 19 | 27 |
| Filled legs (включая rebalance) | 125 | 210 | 258 |
| Gross VM PnL, ₽ | 105 805,51 | 143 051,90 | 653,97 |
| Costs, ₽ | 13 120,00 | 17 029,99 | 13 280,03 |
| Net PnL, ₽ | 92 685,51 | 126 021,91 | −12 626,06 |
| Turnover / starting equity | 80,062× | 150,899× | 196,421× |
| Positive year segments | 2 / 4 | 2 / 6 | 5 / 8 |

Primary source-unavailable target rows — 0 во всех eras. У control таких rows 6/2/0,
expired signals 12/21/30; они явно сохраняются, не заменяются вымышленным исполнением.
4 282 primary decisions дали 203 завершённых входа/выхода; filled legs и cost replays
нельзя выдавать за дополнительные независимые сделки. Каждый era начинает с 1 млн ₽.

Tax primary доходности годовых сегментов, после затрат:

| Год | Доходность | Год | Доходность | Год | Доходность |
| --- | ---: | --- | ---: | --- | ---: |
| 2008 (часть) | −4,73% | 2014 | 20,65% | 2020 | −4,53% |
| 2009 | 19,63% | 2015 | −0,54% | 2021 | 1,09% |
| 2010 | −6,32% | 2016 | −6,57% | 2022 | 8,52% |
| 2011 (до 15.12) | 2,35% | 2017 (до 01.12) | 2,00% | 2023 | −9,05% |
| 2012 | −0,57% | 2018 | 1,79% | 2024 | −6,99% |
| 2013 | −0,98% | 2019 | 5,61% | 2025 | 3,68% |

Все unrounded yearly/cost/control metrics, targets, orders, positions и ledgers лежат
в canonical run вне Git. Early/middle не достигли 60% положительных годовых сегментов;
recent primary/stress отрицательны и уступают control. Verdict `NO_GO`, 20%/50% gates
false, independent holdout false, live trading false. Это отрицательная проверка именно
объявленной proxy; менять дату, знак, плечо или делать стратегию из control запрещено.
Новая NN на этой же механике не обоснована результатом.

Разрешённое продолжение — новый source/mechanism; текущий кандидат описан в
[MOEX_INDEX_REBALANCE_SOURCE.md](MOEX_INDEX_REBALANCE_SOURCE.md). Для проверки V64
достаточен `--audit` по указанному canonical пути; не повторять economic run.
