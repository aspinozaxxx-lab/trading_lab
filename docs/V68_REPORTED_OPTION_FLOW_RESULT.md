# V68 — завершён, REJECT_STAGE1

2026-09-13. Один новый фиксированный сигнал: направление по доле reported call-volume
относительно reported call-OI. Совместный BR/MIX/RI/SI портфель, 2021–2025, без процентов
на свободные деньги. [Протокол](V68_REPORTED_OPTION_FLOW.md) не менялся после результата.

## Экономический результат

| Вариант | CAGR | Общий результат | Sharpe | MDD | Закрытых эпизодов |
| --- | ---: | ---: | ---: | ---: | ---: |
| Основной, обычные затраты | +1,7801% | +9,1953% | 0,2139 | 30,7118% | 414 |
| Основной, удвоенные затраты | +0,4407% | +2,2167% | 0,0943 | 31,2457% | 408 |
| OI-only контроль, обычные затраты | −3,4787% | −16,1824% | −0,2668 | 24,6964% | 265 |
| OI-only контроль, удвоенные затраты | −4,0018% | −18,4226% | −0,3165 | 25,2036% | 264 |

CAGR — среднегодовой сложный темп роста, а «общий результат» — весь период.
Sharpe сопоставляет среднюю дневную доходность с её изменчивостью, annualized sqrt(252),
без вычитания безрисковой ставки в данном ledger. MDD — максимальное падение от ранее
достигнутого пика капитала; положительное число означает размер потери.
Закрытые эпизоды считаются отдельно по активу, знаку и контракту, не равны числу orders.

| Год | Основной, обычные | Основной, удвоенные | Контроль, обычные | Контроль, удвоенные |
| --- | ---: | ---: | ---: | ---: |
| 2021 | +8,7927% | +7,7401% | −4,6620% | −5,1845% |
| 2022 | −10,7914% | −11,7312% | +6,7337% | +5,0162% |
| 2023 | −3,2330% | −3,0337% | +3,0180% | +3,0921% |
| 2024 | −7,2559% | −7,4542% | −6,2262% | −6,3343% |
| 2025 | +25,3671% | +19,7733% | −14,7345% | −15,1547% |

Основной сигнал лучше контроля, но положительны лишь 2/5 лет. Отдельный хороший2025
не доказывает стабильность. При обоих costs провалены заранее заданные CAGR>=5%,
Sharpe>=0.5, MDD<=25% и >=3 положительных года. Coverage, число эпизодов, худший год,
полнота исполнения и сравнение с контролем прошли свои gates. **Кандидатов Stage2 — 0**.
Порог5% был только фильтром компонента; цель20–50% не достигнута и не заменена им.

На исходный миллион: primary base gross VM +125061,41 руб., costs 33107,96 руб.,
net +91953,45 руб.; double gross VM +86044,70 руб., costs 63877,25 руб., net +22167,45 руб.
Это суммы за весь период, не годовые. Integer sizes зависят от текущего капитала,
поэтому при doubled costs изменяются и последующие количества, и gross VM.
Filled legs: primary716/704, control522/530; это также не число закрытых эпизодов.

## Данные и исполнение

- 1 327 744 option rows / 1044 source asset dates; 948 ready (90,8046%). Raw missing
  volume 1 236 590, OI 1 116 720 сохранены. Ни один полный market total не заявлен:
  признаки относятся к отдельно наблюдаемым подмножествам. Нет expiry/dealer-gamma claim.
- Каждый arm: 5084 asset decisions за1271 sessions, 4522 nonzero targets. Флаги:
  feature unavailable488, unavailable map32, stale84; они могут перекрываться.
- Все четыре ledger: execution_complete=true, critical0, unresolved0, terminal flat.
  У каждого17 factual halt marks/carries сохранены; это не17 потерянных незакрытых рисков.
  Отмены target из-за отсутствия open17; no liquidity3/3 у primary,2/3 у контроля.
- Максимальный modeled participation 0,0681%; historical fees/margin/open остаются proxy.
  Реальные BID/OFFER, брокерское исполнение и original publication vintages не доказаны.
- Source availability строго до решения; same-date option state не используется.
  Старый2026 не читался. Это уже открытая development history, не independent holdout.

## Воспроизводимость

- Pre-outcome commit `018b0084a1ace5898eadb971b07ff29ec4ff8611` pushed до единственного run.
- Config SHA `5217c084eb353f66bf453ce6c62aa20a82717a7ac9dd79a72f736f65fff8beb0`.
- V68 seal SHA `ab09fc1343f041ef04e72229e2b5cf59d2f19ecc6123cf3960bc34eceebe33ab`.
- Implementation SHA `6073148cbba63e678a85c8bad48ab572e25d7bcdbaac0ed777c20c93367e3b83`.
- Canonical server root:
  `/srv/trading_lab_data/runs/v68_reported_option_flow_v1_ab09fc1343f0`.
- Metrics SHA `1f08094e5387303d07795782fe80d528980ad4041ba9f18346009e5d49fdd840`.
- Identity SHA `7100980b63fbf9f65dd12d3ad7ef4ff468df6c37e2b7d79f720716a4f5062698`.
- В root сохранены inputs, reported states с missing counts, оба target frames,
  4 набора ledger/orders/positions, metrics и identity. Данные остаются вне Git.
- Local11 synthetic +2 encoding tests PASS; Ruff/diff PASS. На сервере первый pytest
  дошёл до11 тестов/100%, но teardown завершился exit1: UID999 не мог вернуться в `/root`.
  Повторён только synthetic pytest из `/opt/trading_lab`: 11PASS/0,49s, exit0.
  Код/config/economics не менялись и экономический run не повторялся.
- Единственный economic run: exit0, вычислительное время4,7084s. До цен проверены15
  futures input checks и отдельные option manifest/audit/bytes/schema/rows/date checks.
- Read-only audit:17/17 artifact hashes,4/4 NAV metric replays, nullable position episode
  counts и source/decision clocks; verdict replay exact. Source raw replay уже существовал
  и ради этого отрицательного screen не повторялся.

## Следующий допустимый шаг

Закрыть этот фиксированный сигнал на уровне1. Не выбирать2025, иной актив/знак/окно,
не менять missing policy и не продвигать контроль после увиденных результатов.
Этот результат не опровергает всю опционную информацию, но не даёт основания
усложнять именно этот сигнал или добавлять плечо. Нужен другой содержательный механизм
или новая информация. Вместе V65/V66/V67/V68:10 отсеянных гипотез,0 Stage2 candidates.
Paper bootstrap и модели не запускались; schedules существующих collectors не менялись.
