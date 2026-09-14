# V73 — SBER/SBERP: INCOMPLETE_NO_PROMOTION

Завершён 2026-09-14. [Замороженный протокол](V73_SBER_SHARE_CLASS_PAIR.md) и код
опубликованы до чтения market outcomes, commit `2e2c71dac9e8703095b21d82041d17fb64d1f871`.
Один server economic run, затем read-only source→candidate→endpoint→metrics replay.
Ни смены параметров, ни выбора лучших лет/сделок после результата.

## Вывод

Гипотеза возврата относительной цены двух классов акций одного эмитента не проходит
первый уровень. Выбрано 16 событий, полностью наблюдаются 12, unresolved 4 (25%).
Даже на полной части слабый gross-эффект поглощается затратами; при double costs
средние отрицательны во всех трёх годах. Число полных событий ниже объявленного минимума30.
Primary лучше статического контроля, но этого недостаточно для продвижения.

Формальный verdict — `INCOMPLETE_NO_PROMOTION`, а не полный доказанный убыточный
portfolio backtest. Четыре неизвестных исхода не заменены нулём и не выброшены.
Метрики ниже описывают только 12 полных событий; по всем16 доходность неизвестна.
Не строить новый portfolio engine и не собирать новый поток только для спасения V73.
Знак/пару/порог/историю/время/срок/затраты этой гипотезы больше не настраивать.

## Результаты предварительного screen

2023–2025, ближайшие односрочные SBER/SBERP, weekly signal, five-session horizon.
Все проценты в таблицах — результат события относительно суммы начальных quoted
notionals двух ног, НЕ доходность счёта или margin. Costs5/10bps per side включают
вход и выход обеих ног. Event opportunities могут пересекаться, складывать или
годовать их нельзя. CAGR, Sharpe и MDD во всех4 сценариях равны `null`.

| Правило / затраты | Полных событий | Среднее gross | Среднее net | Медиана net | Доля net>0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary / 1× | 12 | +0,079791% | −0,020497% | −0,005145% | 50,00% |
| Primary / 2× | 12 | +0,079791% | −0,120785% | −0,104427% | 25,00% |
| Control / 1× | 12 | −0,043001% | −0,143289% | −0,158113% | 25,00% |
| Control / 2× | 12 | −0,043001% | −0,243577% | −0,260474% | 8,33% |

Средние base costs составили 0,100288% начального gross notional, превышая средний
primary gross0,079791%. Control — всегда short common / long preferred на тех же
событиях; он не превращается в новую гипотезу после просмотра результата.

| Год | Выбрано / полно / unresolved | Primary net1× | Primary net2× | Control net1× | Control net2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2023 | 4 / 4 / 0 | +0,067856% | −0,033094% | −0,211995% | −0,312946% |
| 2024 | 5 / 4 / 1 | −0,058022% | −0,157842% | −0,084449% | −0,184269% |
| 2025 | 7 / 4 / 3 | −0,071325% | −0,171418% | −0,133423% | −0,233516% |

Это средние на событие по годам, не годовые returns. Primary positive years1/3 при
base и0/3 при double. Положительные mean/median, all-years и minimum-count gates не
пройдены в обоих costs. Проверка превосходства контроля пройдена, completeness — нет.

## Покрытие и исполнимость

157 weekly decisions:99 below threshold,28 insufficient history,16 selected,
9 missing completed pair,5 no eligible maturity. Из16 выбранных12 имеют все шесть
ежедневных15:50 наблюдений обеих точных контрактных ног. Unresolved decisions:
2024-01-29,2025-02-17,2025-10-06,2025-10-27. Причина каждого в frozen output:
`missing_or_inactive_endpoint_or_intermediate_bar`; отсутствующее исполнение не выдумано.

Ни одно из12 полных событий не удовлетворяет diagnostic one-contract<=1% объёма
во всех12 наблюдаемых барах. Максимальная доля одного контракта в каждом событии
составляет от4,7619% до33,3333%. Это дополнительное ограничение размера, не доказательство
невозможности любых сделок: intermediate-bar volume не BID/OFFER, а candle open не
подтверждает одновременное исполнение обеих ног. Исторические PIT specs/fees/margin
и полная cash accounting ещё не доказаны; до Stage2/демо/live допуска нет.

## Воспроизводимость и сохранение

Canonical server directory:
`/srv/trading_lab_data/runs/v73_sber_share_class_pair_v1_74a9f44d7669`.
Сохранены `inputs.json`, `decisions.parquet`, `events.parquet`, `metrics.json`, `identity.json`.

- Seal SHA256: `74a9f44d76699acd04bc821b40b340d6611afbada5741003d3c4d06de54dd501`.
- Config: `419dd413c01e5fb869a99cd216e99d1ff98b7046157aeea086c22268591a977d`.
- Code: `83cb0009b0cc5540b977382898b037a34b085787173b2358608e5cdbe1a4cf4d`.
- Metrics: `4a9101bf828e851fd794353c42824b2a63f8423a27cab3ec4a8deebc8bdaf4ff`.
- Identity: `c6e63730387b93ddfea0ed07c35341844cc36b30e02e103582c273d0e2947302`.
- Decisions: `882be27b73ba51935f949d4ca255d059b354b952d2ed9f4c70a39d3446634ab2`.
- Events: `d045cfdc38916ecf40983f32990156b4cf2161580c13696f5cb2faefe0df0f84`.
- Inputs: `a5fbaec485534a68d32752193f35d04a1e4cee5460a4186a03977a9e8e1e5f90`.

Local35 tests PASS (V73, shared V64, encoding), server16 V73 tests PASS; Ruff/diff PASS.
Audit4/4 child hashes и exact source/candidate/endpoint/all-metric replay PASS;
source/PDF/calendar identities, row counts и pre2026 clocks verified.
`runtime_seconds=1.1058005730010336` — время внутри economic run после preflight,
не общее время разработки/переноса. Единственный economic run; audit не новая симуляция.

Первая установка не смогла писать в root-owned `/opt/trading_lab` под trading-lab;
до тестов/чтения цен. После проверки отсутствия всех6 targets неизменный tar установлен
владельцем code tree с `--keep-old-files`. Existing code/data не перезаписаны; сам run
выполнен trading-lab. В pandas replay был FutureWarning о Parquet null NaN/None;
текущая pinned версия считает оба missing, числовые/временные поля совпали. Замороженные
байты не менялись для подавления warning.

V65–V73:15 screened hypotheses =14 REJECT_STAGE1 +1 INCOMPLETE_NO_PROMOTION,
0 Stage2. Цель предсказуемых20–50% годовых не достигнута. Следующее направление должно
иметь другой содержательный механизм/information set, не retune V73 или старых families.
Protected2026 outcomes, старый paper bootstrap и schedules collectors не затронуты.
