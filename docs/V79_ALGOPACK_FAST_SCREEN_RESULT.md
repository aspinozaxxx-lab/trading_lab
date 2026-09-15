# V79 R1: три conditional event-screen гипотезы отсеяны

2026-09-15. [Протокол](V79_ALGOPACK_FAST_SCREEN.md), [техническая R1](V79_ALGOPACK_FAST_SCREEN_R1.md).
Все3 candidates REJECT_STAGE1; ни один не направляется на более дорогую проверку.
Это условный final-vintage2020–2025 assay, не доказанный PIT backtest или реальные сделки.

## Основной результат

Все значения результата ниже — средний bps на завершённый плановый60min эпизод.
1bps=0,01%. Costs1×/2× =5/10bps на сторону, то есть10/20bps за полный эпизод.
Это фиксированное research hurdle, не точный тариф брокера/реальное исполнение.

| Гипотеза | Selected | Completed | Unknown | Gross, bps | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Давление потока | 15943 | 15902 | 41 | 0.2909 | -9.7091 | -19.7091 |
| Поглощение | 4716 | 4698 | 18 | 0.2932 | -9.7068 | -19.7068 |
| Изменение глубины | 21922 | 21861 | 61 | -0.2257 | -10.2257 | -20.2257 |
| Price momentum (контроль) | 39513 | 39430 | 83 | -0.1909 | -10.1909 | -20.1909 |

У каждого arm254352candidate asset/opportunities,219271feature-eligible (одинаковая
информационная маска). Nonzero signals pressure26358/absorption5858/depth46398/
control213331. Nonoverlap selection независим от будущих labels. Всего82094planned
эпизода включаяcontrol:81891completed/203unknown. Эти эпизоды не считаются
независимыми наблюдениями или фактическими биржевыми сделками.

Средний gross pressure/absorption всего около0,29bps; depth/control уже отрицательны
до costs. Все6годовых mean net1×/2× у всех4arms отрицательны. Это отсев данных правил,
не доказательство бесполезности AlgoPack или невозможности иных микроcтруктурных эффектов.
Missing target path41/18/61/83 сохраняется unknown, не0 и не удалённый intent.
Все candidates дополнительно провалили completeness gate; отрицательные средние
относятся только к complete subset, полной исполнимости/портфельного результата нет.

Median net1×/2× у всех arms−10/−20bps. Доля positive1×/2×:
pressure34,4045%/23,0851%; absorption32,7373%/21,0515%;
depth34,9938%/23,3933%; control35,0951%/24,2151%.
Break-even one-way cost у двух положительных gross candidates всего0,1454/0,1466bps;
это арифметический потолок среднего данного assay, не практически доступная комиссия.

CAGR/Sharpe/MDD=null: нет capital sizing, integer fills, capacity, margin или MTM ledger.
Не annualize event means и не объявлять достигнутой цель20–50%. Уровень2=0.
V65–V79 теперь22economic screens:20rejected+1incomplete(V73)+1invalid(V74).
V75/V77 source-only отдельно; пустой технический V79 V1 не отдельная экономическая гипотеза.

## Давление потока: все годы и активы

| Год | Selected | Unknown | Gross, bps | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020 | 1881 | 4 | 0.7830 | -9.2170 | -19.2170 |
| 2021 | 2248 | 4 | -0.0048 | -10.0048 | -20.0048 |
| 2022 | 2267 | 9 | 1.1676 | -8.8324 | -18.8324 |
| 2023 | 3241 | 20 | 0.1394 | -9.8606 | -19.8606 |
| 2024 | 3207 | 2 | 0.5584 | -9.4416 | -19.4416 |
| 2025 | 3099 | 2 | -0.5517 | -10.5517 | -20.5517 |

| Актив | Selected | Unknown | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: |
| BR | 4551 | 8 | -10.4855 | -20.4855 |
| MIX | 4686 | 18 | -9.6539 | -19.6539 |
| RI | 3109 | 9 | -8.9530 | -18.9530 |
| SI | 3597 | 6 | -9.4514 | -19.4514 |

## Поглощение: все годы и активы

| Год | Selected | Unknown | Gross, bps | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020 | 497 | 4 | -4.5637 | -14.5637 | -24.5637 |
| 2021 | 614 | 0 | 1.4954 | -8.5046 | -18.5046 |
| 2022 | 545 | 5 | 6.7759 | -3.2241 | -13.2241 |
| 2023 | 982 | 8 | -1.1260 | -11.1260 | -21.1260 |
| 2024 | 1008 | 1 | 0.1046 | -9.8954 | -19.8954 |
| 2025 | 1070 | 0 | 0.0389 | -9.9611 | -19.9611 |

| Актив | Selected | Unknown | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: |
| BR | 1150 | 2 | -11.9306 | -21.9306 |
| MIX | 1496 | 7 | -8.8430 | -18.8430 |
| RI | 495 | 4 | -9.5400 | -19.5400 |
| SI | 1575 | 5 | -8.9521 | -18.9521 |

## Изменение глубины: все годы и активы

| Год | Selected | Unknown | Gross, bps | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020 | 2808 | 8 | -1.0849 | -11.0849 | -21.0849 |
| 2021 | 2888 | 3 | -0.2489 | -10.2489 | -20.2489 |
| 2022 | 3975 | 16 | -0.3494 | -10.3494 | -20.3494 |
| 2023 | 4163 | 25 | 0.7639 | -9.2361 | -19.2361 |
| 2024 | 4023 | 3 | -0.1727 | -10.1727 | -20.1727 |
| 2025 | 4065 | 6 | -0.5574 | -10.5574 | -20.5574 |

| Актив | Selected | Unknown | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: |
| BR | 4181 | 12 | -10.7493 | -20.7493 |
| MIX | 5853 | 22 | -10.4716 | -20.4716 |
| RI | 5185 | 12 | -9.7361 | -19.7361 |
| SI | 6703 | 15 | -10.0637 | -20.0637 |

## Price momentum (контроль): все годы и активы

| Год | Selected | Unknown | Gross, bps | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2020 | 5820 | 13 | 0.6072 | -9.3928 | -19.3928 |
| 2021 | 6934 | 8 | -0.1602 | -10.1602 | -20.1602 |
| 2022 | 6247 | 21 | -1.4875 | -11.4875 | -21.4875 |
| 2023 | 6994 | 29 | -0.3931 | -10.3931 | -20.3931 |
| 2024 | 6511 | 4 | -0.1902 | -10.1902 | -20.1902 |
| 2025 | 7007 | 8 | 0.4707 | -9.5293 | -19.5293 |

| Актив | Selected | Unknown | Net1×, bps | Net2×, bps |
| --- | ---: | ---: | ---: | ---: |
| BR | 9932 | 16 | -10.5466 | -20.5466 |
| MIX | 9786 | 37 | -10.0216 | -20.0216 |
| RI | 9851 | 16 | -10.3602 | -20.3602 |
| SI | 9944 | 14 | -9.8341 | -19.8341 |

## Идентичности и проверка

R1 pre-outcome commit755387f; config0ec1c23bd2a656ce86680a9c0c04627bbfbbd620f7562655e664614b11397f90.
Seal da9d02c55cce324e25a3731936419e2663ea664b9853a74da862dec3a1ac7bd6.
Canonical /srv/trading_lab_data/runs/v79_algopack_fast_screen_r1_da9d02c55cce.
Metrics81ca9e5b56b0bb3dd29437c5c35325a6f69d63f62148fe49ce59dcd7fa8ac21a.
Events SHA dc9894cd545529b8a17ec6867ca22905066ed46b46a51f7ff9b62c4c302ba96c;
intents f1bdc0475ab446f6e7b83327b4b1d03f517b76cc4fa0e76e426616697469a842;
signals0af649c65a229f942177122b4fc8248064197eab480a43dbda3724c7a487c0a9.
Economic runtime1,624885s; это не полное время разработки/проверок.
Server unit trading-lab-v79-r1-da9d02c55cce.service completed success/0.

Local20/server20target tests PASS; Ruff clean. Post-run audit проверил4artifact hashes,
все82094signal→intent, nonoverlap/entry/exit clocks, исходный separate label→signed
simple return и оба costs, все annual counts/means; input/code seals unchanged.
Аудит не перезапускал simulation/fit и не изменял canonical files.

Parent V1 output /srv/trading_lab_data/runs/v79_algopack_fast_screen_v1_f2aa4f47daea
сохранён с metrics4fee492544624ce3e9570984a8a03d05b26eec2a57e0475494cc62700c7cbd7d.
Его0eligible — ошибка распознавания READY_ARCHIVE_ASSUMPTION, не три экономических
провала. R1 не менял source statuses/flags, фактическую availability или параметры.

## Дальше

Не менять signs/thresholds/horizon/costs/годы этих3механизмов по результату. Не строить
под них новую модель или исполнение ради спасения. Продолжается независимое
[сохранение полного архивного information set](ALGOPACK_ARCHIVE_V1_STATUS.md):
EQ/FXOrderStats, полные trade/depth поля, HI2/Alerts для новых заранее оформленных
гипотез. До применения нового набора — manifest/boundary/source и отдельный протокол.
Старый paper bootstrap, live,2026 и подписка не менялись.

