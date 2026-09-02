# Forward paper-протокол V49 double-risk

## Назначение

Historical V49 дал лучший exact CAGR лаборатории, но строгий `NO_GO`: primary
`43,6833%` не достиг заранее заданных `45%`. Поэтому historical параметры больше не
настраиваются. Parent config `configs/v49_double_risk_forward_validation_v1.yaml`, SHA
`520bd3d4...`, фиксирует forward-протокол. Отдельный исполняемый paper arm запечатан в
`configs/v49_double_risk_paper_arm_v1.yaml`, SHA `56822e1e...`, до первого допустимого
V49 decision/target/order/position/PnL.

## Неподвижный arm

- frozen V39 mapped targets и option-OI/key-rate/STLFSI логика без изменений;
- multiplier `2.00x`, gross cap `4.00`, initial-margin buffer `2.00`;
- maximum prior official volume participation `1%`, exact integer contracts;
- observed OFFER для покупки, BID для продажи, atomic roll, no broad carry;
- missing/depth/margin/gross/capacity failure только отменяет или сокращает order;
- сравнение/выбор V48 1.50x и V49 2.00x по forward outcome запрещены.

V48 остаётся отдельным заранее выбранным baseline и не заменяется V49.

## Новая временная граница

Parent boundary — `2026-09-02T12:30:04Z`; окончательная paper-arm boundary —
`2026-09-02T19:16:00Z`. Paper readiness считает только snapshot, у которого
`retrieved_at_utc` не раньше второй границы. На момент seal все пять eligible counts
были нулевыми. Более ранние option, market, macro и execution snapshots исключены даже
из V49 warmup; source date без post-seal retrieval недостаточна. Backfill 2026 и
повторный перенос boundary запрещены.

После границы заново требуются:

- 54 уникальных completed option weekly levels;
- 253 common official CLOSE levels;
- хотя бы по одному причинно доступному FRED, CBR и execution component;
- затем 504 новые futures sessions, 104 weekly decisions и минимум два полных года.

До joint warmup readiness не содержит и не разрешает signal/target/return/PnL. До
полной evaluation запрещены CAGR, annualization, arm selection и promotion.

## Gates после полной paper evaluation

- CAGR не ниже `20%` во всех cost scenarios; `40%` — stretch, `50%` — только
  aspirational report;
- Sharpe не ниже `1.0`, MDD не выше `40%`, worst full year не ниже `-15%`;
- минимум два положительных полных года;
- participation не выше `1%`, zero critical failures/unresolved halts;
- все source snapshots проходят raw replay.

Даже numeric pass не разрешает live trading: обязательны broker statement
reconciliation, второй unseen period и отдельный live-admission protocol.

## Read-only readiness

Authoritative команда выполняется на `gpu-mlserver`:

```bash
cd /opt/trading_lab
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python -m market_lab.futures.v49_double_risk_paper_readiness_v3 \
  --option-root /srv/trading_lab_data/data/forward/moex-options-surface-v1 \
  --component-root /srv/trading_lab_data/data/forward/v27-validation-v3-components \
  --calendar-root /srv/trading_lab_data/data/forward/moex-futures-calendar-html-v1
```

Вывод содержит только post-seal source counts, invalid/excluded counts и phase. Поля
`contains_signal_return_target_prediction_or_pnl` и `live_trading_allowed` всегда
`false`.

Первый authoritative paper-arm run после exact deploy commit `8f7176b`: option/CLOSE
`0/54 + 0/253`, execution/FRED/CBR `0/0/0`; один option snapshot и два components,
retrieved до seal, явно исключены; invalid `0`, signal/target/PnL false.

Transport admission SHA `62ca9450...` и successor deploy `8cee8cd` принимают sealed
anonymous FRED V2 без изменения paper boundary. Текущий paper-arm readiness:
option/CLOSE `1/54 + 1/253`, post-seal execution/FRED/CBR `0/1/0`, causal join `0`,
excluded preseal option/components `1/2`, invalid `0`; CAGR/PnL всё ещё запрещены.

Calendar admission SHA `6b81c07c...` добавляет официальный MOEX calendar только как
дополнительное обязательное условие. V3 видит snapshot
`snapshot_calendar_20260902T225345007058Z`, `1 valid/0 invalid`, следующие шесть
торговых сессий известны. Calendar-ready `true`, но общий `paper_economics_may_start`
остаётся `false`, поскольку joint warmup, post-seal execution и CBR ещё не готовы.
Календарь не меняет multiplier/cap/margin/cost/gates и не разрешает live trading.
