# Forward paper-протокол V49 double-risk

## Назначение

Historical V49 дал лучший exact CAGR лаборатории, но строгий `NO_GO`: primary
`43,6833%` не достиг заранее заданных `45%`. Поэтому historical параметры больше не
настраиваются. Config `configs/v49_double_risk_forward_validation_v1.yaml`, SHA
`520bd3d4...`, фиксирует отдельный paper arm до первого V49 forward decision/target/
order/position/PnL.

## Неподвижный arm

- frozen V39 mapped targets и option-OI/key-rate/STLFSI логика без изменений;
- multiplier `2.00x`, gross cap `4.00`, initial-margin buffer `2.00`;
- maximum prior official volume participation `1%`, exact integer contracts;
- observed OFFER для покупки, BID для продажи, atomic roll, no broad carry;
- missing/depth/margin/gross/capacity failure только отменяет или сокращает order;
- сравнение/выбор V48 1.50x и V49 2.00x по forward outcome запрещены.

V48 остаётся отдельным заранее выбранным baseline и не заменяется V49.

## Новая временная граница

Earliest eligible retrieval — `2026-09-02T12:30:04Z`. Readiness считает только
snapshot, у которого `retrieved_at_utc` не раньше этой границы. Уже накопленные option,
market, macro и execution snapshots исключены даже из V49 warmup; source date без
post-seal retrieval недостаточна. Backfill 2026 запрещён.

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
runuser -u trading-lab -- env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m market_lab.futures.v49_double_risk_forward_readiness
```

Вывод содержит только post-seal source counts, invalid/excluded counts и phase. Поля
`contains_signal_return_target_prediction_or_pnl` и `live_trading_allowed` всегда
`false`.
