# Portfolio session V1 — server tests and bounded benchmark

2026-09-07. Pushed/deployed `799c935`. От trading-lab UID999315/315related Linux tests
PASS за17,40сек, включая8session tests. Local1+encoding2PASS/7Linux skips, Ruff PASS.

Подтверждены hot append без full recover и с одним tail observe, cold restart parity,
сохранение reservations, невозможность изменить cash через snapshot, competing writer,
lost acknowledgment, invalid operation и partial next event. Synthetic fixtures только;
production activation отсутствует. Parent economic/source modules не менялись.

На существующем synthetic MARK-only журнале501events:

- Old append:0,135614сек (одно измерение).
- New cold startup/full replay:0,096583сек (одно измерение).
- New hot append:10samples, median0,040063сек; min0,037588/max0,050174сек.
- Final512events; full parent recover == session snapshot, external-tail check PASS.

Root `/tmp/trading_lab_synthetic_portfolio_scaling_t7iq5u45` сохранён, не удалён.
Clocks2099 и activation только in-process mocks; actual network/market requests0.
Это не SLA, не реальная торговая задержка и не benchmark большого position/seen-ID
state. Сравнивается конкретная цена повторного чтения journal; повторять его вместо
дальнейшей интеграции не нужно. Полный cold replay и source evidence replay остаются.

| Файл | SHA-256 |
| --- | --- |
| algopack_paper_portfolio_session_v1.py | 7dc7de1d5c309302f7e24e947879b685570b69c25420ca5727b9dfe5c3aabb4b |
| test_algopack_paper_portfolio_session_v1.py | 8ff41a9e741bd8b99f9a6c987d3c82cfc31b31e05642b53128d58cd76a190beb |
| ALGOPACK_PAPER_PORTFOLIO_SESSION_V1.md | d097137929449b6ae85d181a0b1fa3da479546163a32937c0ea4053d272314a3 |

Все3SHA совпали local/server; metadata-only training44/witnessed7 closures PASS.
Никакой production activation/F/actual forecasts/trades не создавалось.
Следом integrated runtime/evidence builder + durable external anchors, missed-exit
recovery policy и daily snapshots. Нет income20–50% verification; actual metrics=N/A.
