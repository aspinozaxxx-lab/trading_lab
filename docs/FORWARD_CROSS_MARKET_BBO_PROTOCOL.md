# Forward cross-market BBO protocol

## Зачем он нужен

Источник проверяет две гипотезы, которые нельзя честно восстановить из старой истории:
непрерывный выбор момента сделки вместо одного прогноза в сутки и совместное обучение
на состоянии акций, фьючерсов, валюты и денежного остатка. Он не является стратегией и
не вычисляет доходность.

Sealed config: `configs/moex_forward_cross_market_bbo_source_v1.yaml`, SHA-256
`80d5202db7c0d85542f79f775a29a30ebe16ec94f8d745abd9ec9d7ab4f27d3d`, seal commit
`95ca5b3`. Implementation commit: `33b002c`; pre-value pagination-safe server-side
universe filter: `97806f8`.

## Фиксированный universe

- 30 TQBR-акций, уже использованных в независимом V35 source;
- ближайшие SI/RI/BR/MIX с минимум семью календарными днями до expiry; выбор только по
  metadata, цене/объёму/будущей доходности запрещено влиять на roll;
- `CNYRUB_TOM` на CETS;
- `LQDT/SBMM/AKMM/TMON` только как дополнительный контекст денежного остатка.

Core состоит из 35 инструментов: 30 акций, четыре фьючерса и CNY. Отсутствие одного из
четырёх фондов не портит core, но сохраняется как invalid context. Для каждого core
инструмента обязательны положительные non-locked BID/OFFER, положительная depth лучшего
уровня, lot/minstep и хотя бы один exchange clock.

## Время и причинность

По будням создаётся immutable snapshot каждые 10 минут с `10:09` до `18:39` МСК.
Фактический `retrieved_at_utc` — жёсткая нижняя граница доступности; SYSTIME/UPDATETIME
сохраняются, но не заменяют retrieval clock. Снимок может стать признаком только для
строго более позднего решения. Anonymous ISS может быть delayed — задержка измеряется,
а не предполагается нулевой.

Каждый snapshot содержит четыре canonical raw response: futures series, bulk TQBR,
bulk RFUD и bulk CETS. Нормализованный Parquet содержит BBO, лучшую/общую depth,
количество заявок, cumulative volume/value/trades/OI и clocks. Returns, labels, targets,
signals, predictions, trades, equity и PnL запрещены.

ISS all-securities endpoints могут быть paginated. Поэтому после metadata-only выбора
контрактов запросы используют server-side `securities=...` ровно для sealed universe;
это сохраняет четыре запроса и не зависит от того, на какой странице оказался тикер.

## Readiness и будущий эксперимент

1. Первые 20 полных сессий — только discovery качества/задержки источника; нужно не
   меньше 30 `complete_core_valid` snapshots в каждой сессии.
2. До использования outcomes отдельно запечатывается economic/model protocol.
3. Следующие 20 сессий — calibration.
4. Затем 60 полностью unseen evaluation sessions.
5. Только после evaluation разрешено annualized reporting; live остаётся false.

Заранее обязательны четыре сравнения: full cross-market neural timing, та же архитектура
без depth/activity, фиксированный немодельный baseline и always-abstain. Исполнение
проверяется при primary/doubled/stress costs; broker fee, margin, short locate/borrow и
order rejection records должны быть отдельными byte-pinned входами.

Гипотеза volatile-corridor также может использовать этот source, но TP, distant stop,
maximum hold, overlap и risk должны быть запечатаны до calibration outcomes. Параметры
провалившегося исторического V34 переносить или настраивать по его результату нельзя.

## Команды

```powershell
.\scripts\run_forward_cross_market_bbo.ps1

.\.venv\Scripts\python.exe -m `
  market_lab.futures.forward_cross_market_bbo_readiness

.\.venv\Scripts\python.exe -m `
  market_lab.futures.moex_forward_cross_market_bbo_source `
  --audit-directory <snapshot-directory>
```

Task `TradingLabForwardCrossMarketBBO10m` должен запускать wrapper по будням каждые
10 минут с 10:09 до 18:39 МСК. Повтор одного slot fail-closed и не перезаписывает данные.

## Ограничения

Public BBO не доказывает queue priority или fill. Cumulative marketdata слабее
AlgoPack TradeStats/OrderStats/OBStats; после появления `MOEX_ALGOPACK_TOKEN` богатый
источник подключается отдельным protocol, не задним backfill. Накопление snapshots не
гарантирует прибыль и не разрешает торговлю реальными деньгами.

## V2: delayed-BBO source correction

После первого V1 snapshot anonymous ISS подтвердил двусторонний BBO, но не вернул
значения best depth и показал задержку примерно 15 минут. До следующего значения были
запечатаны V2 config SHA `d4d8910c...` и seal `b152720`. V2 требует BBO, clocks и
identity, но depth хранит как unresolved; realtime, size, queue и fill не утверждаются.
Wrapper: `scripts/run_forward_cross_market_bbo_v2.ps1`; task:
`TradingLabForwardCrossMarketBBO10mV2`. V1 task отключён.

## V3: CNY source-completeness correction

Десять V2 slots подряд дали одинаковые `34/35`: у `CNYRUB_TOM` были exchange clocks
и сделки, но anonymous CETS ISS не отдавал BID/OFFER. V3 SHA `f680f8bb...`, seal
`aab247a` не zero-impute этот ряд и не смешивает экономические объекты: spot остаётся
optional `unresolved`, а отдельный exact `CNYRUBF` становится core currency state.
Официальная карточка контракта:
`https://www.moex.com/ru/derivatives/perpetual-futures/CNYRUBF`; MOEX указывает лот
1 000 CNY и cash-settled one-day automatic prolongation.

Первый persisted V3 snapshot `2026-09-02 11:59` имеет 40 rows, 35/35 complete core,
пять raw responses и audit 18/18. V3 task заменил только cross V2 task; broad V2
остался активен. Source остаётся примерно 15-minute delayed без depth, поэтому current
bucket timing, queue и fill всё ещё не доказаны.
