# Forward broad stock–futures carry protocol

## Идея

Исторический fully-funded cash-and-carry на пяти акциях дал редкий, но устойчивый sleeve:
15 сделок, все primary прибыльны, CAGR около 5,2% standalone и маленькая просадка. Новый
source проверяет, можно ли повысить частоту и суммарную доходность тем же экономическим
механизмом на всей фиксированной 30-stock корзине, а не увеличением directional leverage.

Config `configs/moex_forward_broad_stock_futures_carry_source_v1.yaml`, SHA-256
`5cd396e0033f26d161227dfbbdaef8812769d852dd3940d9e8f5bf8c8faabf70`, seal commit
`228edb8`. Collector `5266903`, readiness/task `4d1cf7a`. Все они запушены до первой
котировки пары.

## Preseal metadata evidence

Официальный MOEX futures-series каталог был прочитан только по полям identity/dates,
без цен и marketdata. Все `30/30` акций имеют активный matching underlying и RFUD
quarterly futures. Exact mapping зафиксирован в config; perpetual `GAZPF/SBERF`
исключены. Для выбранных контрактов description подтвердил `TYPE=futures`, RFUD и
LOTVOLUME от 1 до 10 000 акций.

Contract выбирается только по metadata: exact asset-code/underlying, `is_traded=1`,
30–120 календарных дней до expiry, ближайшая expiry, затем SECID. Цена, объём, basis и
будущая доходность не участвуют в roll.

## Unit identity и snapshot

Каждые 10 минут `10:09..18:39` МСК collector делает три запроса:

1. futures series metadata;
2. filtered bulk TQBR для exact 30 stocks;
3. filtered bulk RFUD для выбранных 30 futures.

TQBR `LOTSIZE` — число акций в spot-лоте; RFUD `LOTVOLUME` — число акций в одном
futures. `LOTVOLUME / LOTSIZE` обязан быть положительным целым числом spot-лотов.
Fractional/missing units делают пару invalid. Все 30 пар нужны для complete snapshot.

Сохраняются только обе executable sides, best/total depth, cumulative volume/value/OI,
current IM/spec fields, exchange clocks и actual retrieval. Basis, fair value,
annualized yield, opportunity rank, return, label, signal, trade и PnL запрещены.

## Readiness и будущая экономика

- discovery: 20 sessions, в каждой минимум 30 complete 30-pair snapshots;
- затем отдельный economic seal до outcomes;
- calibration: 20 sessions;
- unseen evaluation: 60 sessions;
- annualization только после unseen evaluation; live false.

Будущий protocol обязан покупать spot по OFFER и продавать futures по BID, а закрывать
по противоположным сторонам; полностью резервировать spot principal, futures margin и
operational buffer; учитывать exchange/broker/clearing fees, tax, settlement, delivery,
corporate actions и capacity. Dividend разрешён только из original-timestamp disclosure
с correction chain. Обязательны doubled costs, zero-dividend и delayed-fill stress.

## Команды

```powershell
.\scripts\run_forward_broad_stock_futures_carry.ps1

.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_broad_stock_futures_carry_readiness

.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_broad_stock_futures_carry_source `
  --audit-directory <snapshot-directory>
```

Task `TradingLabForwardBroadStockFuturesCarry10m`: Mon–Fri, 10:09, repeat PT10M for
PT8H31M. Invalid snapshot сохраняется и не считается нулём или допустимой парой.

## Ограничения

Public BBO/depth не доказывает queue/fill. Current contract metadata не заменяет broker
delivery/tax rules. Наличие 30 пар не гарантирует, что basis после всех расходов будет
положительным. Source не разрешает live trading.
