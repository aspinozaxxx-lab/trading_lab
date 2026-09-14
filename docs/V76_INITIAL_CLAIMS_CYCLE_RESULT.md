# V76 — initial-claims cycle: REJECT_STAGE1

Завершён 2026-09-14. [Протокол](V76_INITIAL_CLAIMS_CYCLE.md) и все executable bytes
отправлены до market outcomes: commit `f4fb8c18d093edd5fb5e691e808613fafeb45041`.
Один canonical economic run на gpu-mlserver, затем отдельный read-only audit.
Цель относительно предсказуемых20–50% не достигнута; Stage2 кандидата нет.

## Вывод

Годовой цикл новых US unemployment claims не дал полезного эффекта для заданной
корзины BR/MIX/SI. Primary убыточен до затрат, хуже constant risk-on контроля,
прибыльны лишь3/8лет. CAGR, Sharpe, MDD, число положительных лет, худший год и
excess gates не пройдены в обоих costs. Дополнительно провален source coverage gate.

Execution complete во всех4сценариях, critical/unresolved0, terminal flat.
Это законченный условный development screen, но НЕ causal/independent validation:
original FRED vintages не доказаны. Не менять знак, активы, окна, лаг или freshness
после результата. Не строить нейросеть/новый engine для спасения отрицательного gross.

## Все сценарии и годы

Период2018–2025 полностью сохранён:2 025factual sessions,1 000 000руб. исходного cash.
Base1tick+1fee/double2ticks+2fees. Requested gross0.9, risk cap1, по0.3на каждый
из3активов, collateral income0. MDD — положительная глубина просадки.

| Arm / costs | CAGR | Sharpe | MDD | Прибыльных лет | Closed asset episodes | Filled legs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| primary / 1× | -5,6847% | -0,4551 | 41,5803% | 3/8 | 1067 | 2256 |
| primary / 2× | -6,0728% | -0,5040 | 42,4253% | 3/8 | 1053 | 2204 |
| control / 1× | -1,6809% | -0,0779 | 28,6908% | 4/8 | 1105 | 2372 |
| control / 2× | -3,1851% | -0,2073 | 30,7571% | 3/8 | 1065 | 2242 |

| Arm / costs | Gross VM, руб. | Costs, руб. | Net PnL, руб. | Ending cash, руб. |
| --- | ---: | ---: | ---: | ---: |
| primary / 1× | -280 214,24 | 93 271,54 | -373 485,78 | 626 514,22 |
| primary / 2× | -213 792,31 | 179 998,28 | -393 790,59 | 606 209,41 |
| control / 1× | -12 751,60 | 113 908,41 | -126 660,01 | 873 339,99 |
| control / 2× | -17 563,51 | 210 306,46 | -227 869,98 | 772 130,02 |

Costs меняют cash и последующее integer sizing: double gross не обязан равняться
base gross. Все суммы выше непосредственно из соответствующего ledger.

| Год | Primary1× | Primary2× | Control1× | Control2× |
| --- | ---: | ---: | ---: | ---: |
| 2018 | -10,1822% | -11,4862% | -10,1822% | -11,4862% |
| 2019 | +11,1575% | +7,6522% | +7,9117% | +5,9480% |
| 2020 | -33,4258% | -31,7015% | -5,0017% | -7,9430% |
| 2021 | +0,9838% | +0,8985% | +13,8896% | +12,9640% |
| 2022 | +10,3040% | +9,5890% | -7,1508% | -5,3661% |
| 2023 | -3,2356% | -2,7366% | -14,5132% | -16,7961% |
| 2024 | -5,5194% | -6,0594% | +1,3981% | +0,5806% |
| 2025 | -7,4401% | -7,8017% | +3,4772% | -0,0264% |

Primary worst2020 −33,4258%/−31,7015%. В контроле положительны4/8 и3/8лет.
Все historical20/50 flagsfalse; один удачный год не выбран как новая стратегия.

## Coverage и существенный результат временного admission

Raw522 weekly-ending Saturdays2016-01-02…2025-12-27 без missing или duplicate dates.
Дата недели не publication date. Условная availability после конца Saturday+7days
в New York и source-age<=14days at fill были зафиксированы до цен.
521date создаёт1 563asset states,1 398ready states; последняя raw-неделя имеет
assumed availability2026 и не создаёт targets. Warmup использует только claims.

На2018–2025:6 072asset decisions /2 024decision dates в каждой arm.
Обе arms:4 804nonzero targets,417used releases, feature_unavailable0,
source_unavailable17, stale_at_fill1 251. Ready calendar coverage79,3972%, ниже90%.

Read-only проверка сохранённых targets установила причину всех1 251stale asset-dates:
source age>14days; decision-to-fill gap>7days0. Это417effective dates:
397Mondays,15Tuesdays,4Wednesdays,1Thursday. Все stale targets flat.
Friday decision ещё не знает следующую субботнюю условную публикацию; к части
следующих opens предыдущая observation уже старше14дней. Это следствие объявленных
временных правил, а не1 251пустая строка CSV или неопубликованные котировки.

Повторные закрытия/входы из-за freshness увеличили число asset episodes; их нельзя
считать1 067/1 053независимыми трудовыми шоками. Настоящий original release calendar
не восстановлен. Post-outcome удлинение TTL или укорочение lag запрещено, результат
не пересчитан. Вывод для следующей НОВОЙ идеи: перед market load проверять достижимость
coverage и minimum-event gates по source/decision/fill clocks, без цен и нового engine.

## Исполнение и ограничения

Во всех4сценариях по3target cancellations no-liquidity,0factual halts/carry,
0gross/margin/participation/atomic critical rejections. Эти отмены сохранены.
Exposed asset-sessions primary3 759/3 709, control3 862/3 773.
Maximum participation0,970874% во всех4. Primary maximum close gross1,006390/0,890993:
requested allocation не ограничивает автоматически уже изменившуюся close valuation.

Daily open, spec/fee/margin proxies и lagged-volume cap не являются доказательством
реальных BID/OFFER, брокерского тарифа или доступного размера; broker_exact=false.
[US ETA / FRED ICNSA](https://fred.stlouisfed.org/series/ICNSA) — число новых обращений,
не unemployment rate/payroll growth/consensus surprise. FRED допускает revisions;
назначенный lag сам по себе не доказывает original receipt. Применение к BR/MIX/SI
является проверяемым предположением, российские события и политика Fed могут доминировать.

Навык таблиц повлиял на обработку: observation оставлена концом отчётной недели,
availability вынесена отдельно; count типизирован, missing не заменяется0, все недели
и исходные bytes сохранены. Исходный CSV не редактировался/пересчитывался.
Первый graph-page downloadHTML200 сохранён отдельно и отклонён до parsing; использован
только exact fredgraph.csv V2. Никакие зависимости или текущие сервисы не менялись.

## Воспроизводимость

Canonical: `/srv/trading_lab_data/runs/v76_initial_claims_cycle_v1_fd9332b3e121`.
Вне Git сохранены inputs, claims, claim_states, обе targets и все4ledger/orders/
positions, metrics, identity. Source canonical:
`/srv/trading_lab_data/source_evidence/v76_fred_claims_20260914/ICNSA_2016_2025_v2.csv`;
локальная копия в `D:\Projects\trading_lab_data\source_evidence\v76_fred_claims_20260914`.

- Seal: `fd9332b3e121a6afd11d1ef958014a1db21cc38c5ad0441771dd7e6eddfcb3a0`.
- Config: `18aa0166e7476df88b1abb7aac5e6d40f275e42896e23c66524280e5b52a1930`.
- Code: `2e0d896afecd70d1ff1813765b55d0cc9d27d456ca19ae17f1c024f20ccf3a1d`.
- Source CSV: `c80c5d1660ea514a23c8c04d8377445eb0892bce518b29ef86d7cda9ee3ab64f`.
- Metrics: `e611b2d33d0f32e4366af755732fe8446f46be7e09e69c6e2b17922c4a3bfce4`.
- Identity: `a3627ce92b59f1c20b23d7d10cad2e231737252111fba79102126c8958c03ef2`.

Local73 /server21tests PASS, Ruff/diff PASS. Server pytest использовал новый scoped
basetemp, общие каталоги/права не менялись. Единственный economic runtime5,503150s
после source preflight, не общее время разработки/доставки.
Audit18/18child hashes,4/4metric-count-cash replays, exact rawCSV-state-target replay
PASS. Audit не повторная portfolio simulation и не доказательство будущей доходности.

V65–V76:17economic screens=15REJECT_STAGE1+1INCOMPLETE_NO_PROMOTION
+1INVALID_EXECUTION_NO_PROMOTION,0Stage2. V75 отдельно source-only rejection, не18-й
economic backtest. Protected2026 market outcomes, paper bootstrap и collectors
не затронуты. Продолжение — новое содержательное information set/механизм.
