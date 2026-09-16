# V96 — завершён, REJECT_STAGE1

Один economic screen завершён **2026-09-16T11:03:02.862232UTC**. Новая история
SP500 получена, но фиксированный implied-minus-realized variance proxy не улучшил
торговлю российскими индексами. Primary убыточен и хуже constant-exposure control.
Stage2 = 0; решение для цели20–50% годовых не найдено.

## Все сценарии

2021–2025, 1271сессия, начальный капитал1млнRUB, MIX/RI, без процентов на cash.
Это development research-proxy ledger, не независимый holdout или broker-exact PnL.

| Сценарий | CAGR | Sharpe | MDD | Round trips | Итоговый капитал,RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, base | −1.8441% | −0.09542 | 23.8218% | 42 | 911376.47 |
| Primary, double | −2.0091% | −0.10924 | 23.8512% | 42 | 903761.31 |
| Constant0.45gross control, base | +1.2261% | 0.19796 | 12.8946% | 32 | 1062642.83 |
| Constant0.45gross control, double | +1.1909% | 0.19331 | 12.8990% | 32 | 1060801.18 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | +1.5469% | +1.5047% | +4.3008% | +4.2723% |
| 2022 | −7.7235% | −7.9813% | −1.1645% | −1.2393% |
| 2023 | +10.5119% | +10.7380% | +3.0220% | +2.9931% |
| 2024 | −11.8742% | −12.2292% | −4.0333% | −4.0595% |
| 2025 | −0.1316% | −0.4492% | +4.2645% | +4.2488% |

Primary gross VM −85762.83/−90518.09RUB, costs2860.70/5720.60,
net−88623.53/−96238.69 приbase/double. Control gross VM64484.47/64484.47,
costs1841.65/3683.30, net62642.83/60801.18RUB. Убыток primary не объясняется
только комиссиями. Издержки могут менять integer quantities и дальнейший gross
PnL, поэтому отдельный год приdouble не обязан быть хуже base.

## Coverage, исполнение и отсев

- 2542asset-date решения/1271dates в каждом arm. Primary1996nonzero targets,
  control2510; feature-unavailable0, source-plan-unavailable30, stale-at-fill0.
- Feature coverage100%, все60месячных решений готовы. Это не100% fills:
  отсутствующие/остановленные торговые возможности сохранены отдельно.
- High cohorts по60месячным состояниям:0→12месяцев,1→19,2→27,3→2.
  Primary использовал49source states, control61, включая предшествующий warmup
  state в начале2021. Никакого выбора удачных состояний или пропуска плохих лет.
- Все4ledgers execution_complete=true, critical0, unresolved_halt0,
  terminal_carried=false. Primary90filled legs при обоихcosts, control64.
- Primary30halt/carry/mark events и30no-open cancellations; control15/15.
  No-liquidity cancellations2primary/3control. Participation clips/rejections0.
  Max participation0.18282%primary/0.30675%control, ниже cap1%.
- Max close gross0.773760/0.773959primary,0.402424/0.402585control.
  Intraday adverse drawdown26.6462%/26.6763%primary и15.2346%/15.2435%control;
  это отдельно от close-to-close MDD, использованной в frozen gate.

Primary провалил CAGR, Sharpe,>=3positiveyears и superiority относительно control
при обоихcosts. У него2положительных года, уcontrol3. Coverage,30roundtrips,
all5years, worstyear>=−15%, close MDD<=25% и execution gates прошли.
Итог **REJECT_STAGE1** — отрицательная проверка этой реализации, не доказательство
отсутствия VRP эффекта во всех рынках. Не менять знак,21/252windows,3months,
universe, size, masks или control после результата. Не продвигать control.

Воронка: **29portfolio hypotheses =25rejected+1incomplete+3invalid;0Stage2**.
Original source attempt и Retry1 — один кандидат, не два экономических конкурса.
V93 остаётся отдельным component diagnostic. Следующий шаг — другой независимый
разрешённый механизм/источник; V94–V96 и их controls не повторять/не retune-ить.

## Источник и происхождение

[Original protocol](V96_VARIANCE_PREMIUM.md), original pre-outcome commit`1ca84a1`;
[source-only correction](V96_SOURCE_RETRY1.md), pre-outcome retry commit`73b151f`.
Оба push/server byte checks выполнены до respective запусков. Original economics
byte-identical: wrapper меняет только transport/config identity; strict config
equality check разрешает только protocol_id/declared_at_utc.

- Original configSHA`cc789aa208fa932d7f4c7043f73a3a5d7f247f18eb6b4108792a23e86a0a3ca1`;
  original seal`798bfda91f931819c14c7dfa12b104b29b0bdf9b64c5c50402427fc1c12334cf`.
- Retry configSHA`016c4f2ea93b7108ea9d7eaa975870503cd4b233eabfbbb930bebdadd84a4d86`;
  retry seal`fb97e677b52775a2c8768a437871d9a08dafd0c68f97436796e1aad5308f3114`.
  15direct files плюс transitiveV64 source/code closure.
- Original10new/66combined local tests PASS24.61s, server66PASS4.54s.
  Retry5new+10original localPASS5.73s,serverPASS1.53s. Ruffclean.
  Server temp roots были новые, не общий`.pytest_tmp`; не удалялись.
- SP500 source COMPLETE11:02:59.752780UTC:
  `/srv/trading_lab_data/source_evidence/v96_sp500_fb97e677b527`.
  2087weekday rows/2011observed closes/2011XNYSsessions,2018-01-02–2025-12-31.
  ManifestSHA`79e237a6e75c23ffd90a4150a39cb0eaaefb822f606b4c9fca371db65bf688fb`;
  rawCSV`b9fb7ecc43ea5cbf36823692cc6ec4542b828dbe9f6e38dd1f0aca2f44d8d095`;
  calendar`1b146eda0140b9a32e9161a869eb5c94c563c87117a25a5ece2170534c225168`.
  All-date validation до floats. Ready rolling source states1738/2011.
- Source unit`trading-lab-v96-source-retry1-fb97e677b527.service`, invocation
  `9c5be44f383349f7a1f8e463c8b882ca`, success/exit0,1.288s.
  Parent source_evidence root:root0755 восстановлен11:02:59.809009UTC;
  повторно подтверждён11:04:16UTC. Credentials/collector env не использовались.
- Original failed root`source_evidence/v96_sp500_798bfda91f93` сохранён:
  started147bytes/SHA`2f1a7c8b3c8693c32c4d73f4d759281483f1af70a3ae93d737e09af34ff4882f`,
  calendar37103bytes/тот жеSHA. RawCSV/finalmanifest там отсутствуют.
  Original failure доHTTP и следующий timeout — не economic outcomes.
- Исторический VIX copy перенесён на сервер byte-exact, без повторногоHTTP;
  original manifestSHA`0aecc29fdc9181a0af6941fa4f3778487ba0b5d6dedce07aa843b1b0eb32b2d1`.
  Calendar package изолирован, sharedvenv не изменён.
- Current-vintage quotes и консервативный lag не доказывают original PIT.
  Daily-close realized variance — noisy proxy, не intraday RV исследования.
  Ни новое AlgoPack admission, ни источники2026, ни broker/demo/live не использовались.

Economic unit`trading-lab-v96-variance-retry1-fb97e677b527.service`, invocation
`ef4ed76ca992405387779ec2a65aa3c3`, launched11:02:59.854469UTC; journal подтверждает
все4arms/costs и Deactivated successfully. Source manifestSHA был в invocation
до numerical reads. Canonical:
`/srv/trading_lab_data/runs/v96_variance_premium_retry1_fb97e677b527`.
ManifestSHA`bc65a232715cf63e455555678d11f62d5e6da87133b0b5ea21518d48c01821c9`;
metricsSHA`e647db4e032d2f2fa01dfd7767dc5c4ebba224511ff8faa27a0f5820a33e6a77`.
Все19artifact hashes verified11:04:16UTC. Повторного economic run не было.

Параллельно [основной AlgoPack archive](ALGOPACK_ARCHIVE_V1_STATUS.md) продолжает
скачиваться. FUTOI остаётся terminal с550unresolved ticker-days; его не пересчитывали.
