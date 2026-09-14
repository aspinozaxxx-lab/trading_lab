# V74 — Baker Hughes rig-supply: INVALID_EXECUTION_NO_PROMOTION

Завершён 2026-09-14. [Замороженный протокол](V74_BAKER_RIG_SUPPLY.md), код и seal
отправлены до market outcomes: commit `d405dff43753ad2a558a6fd5457b0755002a5990`.
Один server economic run, затем отдельный read-only audit; retune и повторной
симуляции после просмотра результатов не было.

## Вывод

Новая physical upstream investment hypothesis не допускается на Stage2. Во всех
четырёх сценариях `execution_complete=false`, `critical_failure_count=2` и
`gross_limit_rejection_count=2`. Формальный verdict —
`INVALID_EXECUTION_NO_PROMOTION`, НЕ валидный `REJECT_STAGE1` backtest.

Даже исходные диагностические расчёты не дают экономической зацепки: primary
теряет капитал до затрат, хуже constant-long контроля, имеет только 3/8 прибыльных
лет и очень большую просадку. Это не основание менять знак/окно/плечо, ослаблять
execution gate или строить новый engine ради спасения V74. Наблюдённые результаты
не доказывают невозможность любого сигнала по бурению, но эту frozen ветку закрывают.
Ни доходности 20–50%, ни пригодной для демо стратегии не найдено.

## Диагностика отказа исполнения

У всех четырёх сценариев по два gross-limit counter events, но **нет записанных
отклонённых ордеров**: все 743/716/392/398 order legs имеют `filled=true`, reason
`filled`. `atomic_rejection_count=0`, `critical_blocked_asset_count=0` на всех датах.
Нельзя описывать эти счётчики как «две отклонённые сделки».

В общем ledger `_risk_reasons` вызывается и при пустом наборе готовых новых legs,
проверяя retained desired positions; counter может увеличиться без rejected order.
Сохранённый daily ledger отдельно показывает отмену новых targets по capacity
admission 2022-03-01 и 2022-03-02 во всех arms/costs. Есть по одному factual halt,
halt mark/carry, target cancellation no-open и no-liquidity. На этих датах позиции
сохранены, а primary close gross leverage достигает 1,8753/1,7443 при requested1x.
Дневной журнал не содержит отдельного timestamp каждого gross counter event;
совпадение числа событий не выдаётся за точную инструментированную attribution.

Другие critical counters равны нулю, unresolved halts0, terminal carried=false.
Это не отменяет frozen gate critical0: его четыре execution checks провалены.
Ни counter, ни ledger, ни параметры после результата не исправлялись.

## Исходные числовые результаты — только forensic, не validated returns

Полный календарь 2018–2025, 2 025 сессий, исходный капитал 1 000 000 руб.
Primary: `-sign(US oil rigs[t] - rigs[t-13])`; control: long при тех же masks.
Base: 1 tick +1 fee; double: 2 ticks +2 fees. Проценты ниже сохранены из исходного
ledger для воспроизводимости; из-за execution failure нельзя представлять их как
подтверждённый результат исполнимой стратегии. MDD показана положительной глубиной.

| Arm / costs | Исходный CAGR | Sharpe | MDD | Положительных лет | Closed episodes | Filled legs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Primary / 1× | −7,9384% | −0,0516 | 86,0480% | 3/8 | 118 | 743 |
| Primary / 2× | −8,9712% | −0,0854 | 86,9237% | 3/8 | 118 | 716 |
| Control / 1× | +0,1416% | 0,1856 | 77,4700% | 5/8 | 93 | 392 |
| Control / 2× | −0,8294% | 0,1588 | 78,0454% | 3/8 | 93 | 398 |

| Arm / costs | Gross VM, руб. | Costs, руб. | Net PnL, руб. | Ending cash, руб. |
| --- | ---: | ---: | ---: | ---: |
| Primary / 1× | −389 429,29 | 94 136,82 | −483 566,11 | 516 433,89 |
| Primary / 2× | −347 087,25 | 180 990,18 | −528 077,42 | 471 922,58 |
| Control / 1× | +73 538,29 | 62 172,09 | +11 366,20 | 1 011 366,20 |
| Control / 2× | +55 849,53 | 120 221,29 | −64 371,76 | 935 628,24 |

Costs меняют cash и последующее integer sizing, поэтому gross VM и количество
исполненных legs различаются. Нельзя считать double простым вычитанием второй комиссии.

Все годовые результаты исходного ledger, также forensic-only:

| Год | Primary1× | Primary2× | Control1× | Control2× |
| --- | ---: | ---: | ---: | ---: |
| 2018 | +15,3355% | +13,8858% | −20,6877% | −21,6873% |
| 2019 | −3,0540% | −3,6906% | +35,0243% | +34,2516% |
| 2020 | +59,6267% | +56,6513% | −45,8387% | −46,7270% |
| 2021 | −45,2766% | −45,6637% | +64,4938% | +62,3318% |
| 2022 | −38,7449% | −39,3304% | +27,9716% | +28,3558% |
| 2023 | −15,9972% | −17,7574% | −17,7558% | −18,7304% |
| 2024 | −21,6284% | −22,7272% | +0,4043% | −0,5054% |
| 2025 | +31,1138% | +31,1034% | +0,3105% | −0,8489% |

Исходные economic gates CAGR/Sharpe/MDD/positive years/worst year/control excess
также false в обоих costs. Только source coverage, episode count и полный список
годов проходят; execution invalid имеет приоритет над экономическим отсевом.

## Источник и покрытие

Неизменённый [архив Baker Hughes](https://rigcount.bakerhughes.com/na-rig-count),
`North America Rig Count New Report (2013-Aug 2025)`: 169 309 subgroup rows,
661 publication dates 2013-01-04…2025-08-29, 615 ready source states.
Навык чтения таблиц повлиял на admission: labels/types проверены, latest total/oil/date
сверены с publisher summary; 11 ambiguous weeks2013 и все зависимые окна masked,
не суммированы/дедуплицированы. Все raw rows сохранены, 13 optional County blanks
не превращены в missing/zero rig counts. Исходный Excel не редактировался и не пересчитывался.

На economic calendar ready fraction96,1957%. По 2 024 daily decisions на arm:
primary1 922 nonzero targets/396 used releases; control1 946/401.
По77 stale-at-fill и1 source-unavailable; exposed sessions1 923 primary/1 947 control.
После истечения freshness позднего2025 targets flat; все2025сессии остаются в отчёте.

Оригинальные исторические версии не доказаны: это current-vintage archive и условная
доступность после конца US_PublishDate в Chicago, не historical causal admission.
Rig count не равен добыче и не измеряет surprise относительно консенсуса. Daily opens,
spec/fee/margin proxies не доказывают реальные BID/OFFER, broker tariff или размер.

## Сохранение и проверки

Canonical: `/srv/trading_lab_data/runs/v74_baker_rig_supply_v1_0e2c21e3964f`.
Сохранены inputs, raw-derived rig counts/states, обе targets, все четыре ledger/orders/
positions, metrics и identity. Raw workbook вне Git:
`/srv/trading_lab_data/source_evidence/v74_baker_rigs_20260914/baker_na_2013_aug2025.xlsx`.
Локальная копия в `D:\Projects\trading_lab_data\source_evidence\v74_baker_rigs_20260914`.

- Seal: `0e2c21e3964f316b9c5c1fa98e6a09c5b3802e8779a0db48684eb092da37fd97`.
- Config: `1e062a8eaa9801581934aebebe124978d7fdc7f18323e29cdf725a88a87d449d`.
- Code: `b89cd0ea0a7f79cb4025c30346868a0f89a34192172bf6e44bf582c9d4e5a663`.
- Source XLSX: `38ceac39bb7d791d3cf739de68a3c267c626198f695e2fea47c6dd9d6d501f0f`.
- Metrics: `f6ceff245a47431406419adcd3830fdcb900e277cfb844148543545ca3edf6b7`.
- Identity: `6e21a7ac9e54100fae5e47d98b447b66b9c39f26b1f72dcf8c4c9b11d444f775`.

Local73 tests PASS (21new,22V72,11V68,17V64,2encoding), Ruff/diff PASS.
Server21 tests PASS. Первая попытка pytest дала12PASS/9setupERROR из-за root-owned
общего `.pytest_tmp`, до economic run. Повтор только synthetic tests с новым scoped
`--basetemp` прошёл; старые каталоги/права не менялись.

Единственный economic run: 3,678092s внутри расчёта после source preflight, не общее
время работы. Audit:18/18 child hashes,4/4 metric/count/cash replays и exact raw
workbook→counts→states→targets replay PASS. Это проверка воспроизводимости исходных
артефактов, не снятие execution failure и не повторная portfolio simulation.

V65–V74:16 screened =14 REJECT_STAGE1 +1 INCOMPLETE_NO_PROMOTION
+1 INVALID_EXECUTION_NO_PROMOTION,0 Stage2. Цель20–50% не достигнута.
Следующее направление — иной information set/механизм; V74 и закрытые семьи не retune.
Protected2026 outcomes, paper bootstrap, collectors и их schedules не затронуты.
