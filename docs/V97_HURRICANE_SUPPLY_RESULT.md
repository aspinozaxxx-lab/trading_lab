# V97 — завершён, REJECT_STAGE1

Один frozen economic screen завершён **2026-09-16T19:46:34.548073UTC**.
Покупка BR при заранее опубликованном прогнозе ураганной угрозы northern Gulf
не дала положительной доходности. Основной вариант лучше широкого Atlantic control,
но оба убыточны. Цель20–50% годовых не подтверждена; Stage2-кандидата нет.

## Все сценарии и годы

2018–2025, 2 025 торговых сессий, начальный капитал 1 млн RUB, BR long/cash,
без процентов на свободные деньги. Это development research-proxy ledger,
не независимый holdout и не брокерский результат.

| Сценарий | CAGR | Sharpe | MDD | Round trips | Итоговый капитал,RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gulf primary, base | −0.8220% | −0.26129 | 11.3760% | 12 | 936180.80 |
| Gulf primary, double | −0.9295% | −0.29647 | 11.8357% | 12 | 928106.81 |
| Atlantic control, base | −3.1036% | −0.39310 | 32.8878% | 63 | 777335.65 |
| Atlantic control, double | −3.6421% | −0.47275 | 33.5730% | 63 | 743484.45 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | −0.1614% | −0.2147% | −14.0142% | −14.1250% |
| 2019 | −0.3604% | −0.4292% | −16.0498% | −16.5744% |
| 2020 | +2.3052% | +1.9100% | +4.4872% | +2.8162% |
| 2021 | 0.0000% | 0.0000% | +0.9524% | +0.6464% |
| 2022 | +2.7968% | +2.7549% | −5.7740% | −5.7515% |
| 2023 | +0.2300% | +0.1899% | +8.3577% | +7.2914% |
| 2024 | −10.7200% | −10.9660% | −2.4813% | −2.7981% |
| 2025 | 0.0000% | 0.0000% | +2.5326% | +2.0309% |

Primary gross VM−55745.21RUB при обоих costs, расходы8073.99/16147.98RUB,
net−63819.20/−71893.19RUB. То есть отрицательный результат не только из-за costs.
Control gross−192726.85/−197803.48RUB, costs29937.51/58712.07RUB,
net−222664.35/−256515.55RUB. Integer position sizes могут измениться из-за costs;
поэтому gross control и отдельные годы не обязаны совпадать между сценариями.

## Coverage, сделки и решение

- В каждом варианте 2 024 решения; primary: 24 ненулевых сигнала и 24 сессии
  с позицией, control: 149/149. `used_releases` 24/149 считает уникальные строки
  `source_url` у ненулевых сигналов. Строка может объединять несколько документов;
  это не число независимых ураганов или уникальных исходных документов.
- Feature-unavailable17 у обоих, source-plan-unavailable1; stale-at-fill48primary
  и97control. Primary ready coverage96.7885%, не100% source/receipt coverage.
- Primary12round trips при обоих costs, control63/63; filled legs26/26 и130/133.
  Primary3положительных года из8; нулевые2021/2025 сохранены, не вырезаны.
- Все4ledgers execution_complete=true, critical0, unresolved_halt0,
  terminal_carried=false. Missing contract/open/settle/spec/fee/liquidity counters0;
  halt/participation/gross/margin rejection и no-open/liquidity cancellations0.
- Maximum participation0.15322%primary/0.10215%control, ниже cap1%.
  Max close gross0.90656/0.90971primary и0.91098/0.91268control.
  Intraday adverse drawdown11.7694%/12.2098%primary и33.1760%/33.8613%control;
  это отдельно от close MDD в frozen gate.

Primary провалил>=20round trips,5%CAGR,.5Sharpe и>=5positiveyears при обоих costs.
Coverage, все8лет, primaryMDD<=25%, worstyear>=−15%, superiority над control и
execution gates прошли. Итог **REJECT_STAGE1**, не статистическое доказательство
отсутствия погодного эффекта вообще. Не менять знак, географию, wind threshold,
72h horizon,48hTTL, размер, годы или контроль под этот результат.

Воронка: **30portfolio hypotheses =26rejected+1incomplete+3invalid;0Stage2**.
V93 остаётся отдельным component diagnostic. Source collection и четыре arms/costs
не считаются дополнительными гипотезами. Следующий независимый источник-кандидат:
[заранее опубликованные расписания FOMC](FOMC_CALENDAR_FEASIBILITY_20260916.md),
пока только feasibility, без нового economic run. Broader AlgoPack scope unanswered.

## Источник, фиксация и проверка

[Frozen protocol](V97_HURRICANE_SUPPLY.md), pre-outcome commit`7faffad`,
configSHA`96b0ce565bf7fb77b3225f175c63df52544731eabd34186dc6c03e555aff4896`,
seal`4788fa2921a1c811a7ceabbeae8011ed6efe01ea22af41a7756edca0e93687c5`.
Push/server closure verification выполнены до запусков. Local13new/66combined tests
PASS4.67s, server13/13PASS0.15s; Ruff clean. Frozen code/config/tests/protocol не менялись.

NHC source COMPLETE**19:38:52.811462UTC**:
`/srv/trading_lab_data/source_evidence/v97_nhc/4788fa2921a1`.
838selected messages из3384versioned files/158storms за2018–2025;823parsed,
15parse gaps, HTTP errors0. Все15 — `advisory identity mismatch`; raw сохранены,
соответствующие48h периоды маскированы по заранее установленному правилу.
Ни исправления парсера после outcomes, ни ретроспективного заполнения пропусков нет.
Два ранее сохранённых indexes переиспользованы, ещё6downloaded; не более2requests
одновременно. Original receipt/economic admission flags источника остаютсяfalse.

- Source manifestSHA`2dccce4a4aa7c3a0b4cf0e16ad7e47c4a8635ebd1b5879ee247e0848fc863d40`.
- Parsed advisoriesSHA`a023621eb48d7cb57e9a9b0031494b1b467aa1b4cf864a81bdac8bf535ddf885`.
- Parse gapsSHA`ad7828cd1c87d136ce337938b3a355a22df84b3f232188035c53f262a52b8cbd`.
- Все1697source artifact hashes проверены19:45:34UTC и повторно самим runner перед
  numeric market reads. Source manifestSHA указан в economic invocation.
- Source unit`trading-lab-v97-nhc-source-4788fa2921a1.service`, invocation
  `5d6276278b1e428aaee7af107cf76e4f`, terminal success. Не перезапускать.

Economic unit`trading-lab-v97-economic-4788fa2921a1.service`, invocation
`7457b1694b804c3d910edfb70a53c7e9`, launched19:46:30.237756UTC, terminal success.
Canonical`/srv/trading_lab_data/runs/v97_hurricane_supply_v1_4788fa2921a1`.
ManifestSHA`4344480ae93d4c72ca83d2c628fbeebd53864b89fec0dffdc3a95a7b6e2e68b0`,
metricsSHA`23093ed9e15b78d532b0fe3c9f3b25fc867fc74b9ab44e2dda274ff2b5310450`.
Все17run artifact hashes и terminal journal проверены19:47:17UTC; один run.
Дневные specification/margin/fee proxies не стали exact historical execution.
Никаких2026market inputs, реальных/демо сделок, credentials или Windows collectors.

Основной AlgoPack downloader параллельно продолжает работу без изменений.
Замер19:45:37UTC:12.629GBdata+source, включая10.753GBAlgoPack;
15339/26305jobs, failed0. Это объём хранения, не торговое достижение.
