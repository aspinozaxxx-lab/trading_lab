# V94 — COMPLETE, основная гипотеза отклонена

Завершён один screen **2026-09-15T22:26:53.745476UTC**. `REJECT_STAGE1`, не
Stage2 и не подтверждение цели20–50%. Primary отрицателен во всех пяти годах.
Заранее объявленный mirror control положителен, но менять его статус/знак основной
гипотезы после просмотра результата запрещено frozen protocol. Числа контроля
сохранены полностью, не скрыты и не названы новой проверенной стратегией.

## Экономический результат

Период2021–2025,1271сессия, начальный капитал1млнRUB. CAGR/Sharpe/MDD считаются
существующим cash ledger, не по условно завершённым отдельным сделкам.

| Позиция / издержки | CAGR | Sharpe | MDD | Round trips | Итоговый капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary: low-minus-high skew, base | −12.5869% | −0.88194 | 52.9854% | 88 | 511347.21 |
| Primary, double | −13.2159% | −0.92523 | 54.5143% | 88 | 493264.05 |
| Mirror control, base | +11.7318% | 0.85402 | 12.9091% | 95 | 1738584.65 |
| Mirror control, double | +11.5278% | 0.84136 | 12.7888% | 95 | 1722819.76 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | −12.7244% | −13.2754% | +12.1737% | +12.0665% |
| 2022 | −22.5730% | −22.7973% | +16.7574% | +16.6470% |
| 2023 | −5.3895% | −5.6597% | +5.0116% | +4.7196% |
| 2024 | −15.4287% | −16.3654% | +21.0271% | +21.6373% |
| 2025 | −5.4268% | −6.6270% | +4.4481% | +3.4655% |

Primary gross VM−478640.77/−487080.44RUB, costs10012.03/19655.50RUB,
net−488652.79/−506735.95RUB. Поэтому это не только провал из-за комиссий.
Control gross VM763573.32/772741.47RUB, costs24988.68/49921.71RUB,
net738584.65/722819.76RUB. Round trips — завершённые asset/sign/contract episodes;
filled legs238/234 уprimary,399/404 уcontrol. Разные costs меняют integer sizing,
поэтому отдельный год при2× не обязан быть хуже, хотя итоговый control cash ниже.

## Coverage, риск и отсев

- 5084asset-date decisions в каждом arm,2244nonzero targets;588feature-unavailable,
  32source-unavailable,stale0. Готовность88.4343%≥80%gate.
- 60monthly selection dates,53ready;8100source return rows,8060observed exact-contract
  returns. Missing не сжаты в более короткую историю. Warmup и monthly state causal.
- Все4ledgers execution_complete=true,critical0,unresolved_halt0,terminal_carried=false.
  16factual halt/carry/mark events и16no-open target cancellations сохранены;
  no-liquidity cancellations3,participation clip1 в каждом сценарии. Не удалены изPnL.
- Maximum participation0.15898%primary/0.20222%control, ниже1%cap.
  Maximum close gross0.991486/1.000416primary и0.939274/0.921387control. Небольшое
  превышение1.0 в primary-double после движения цен не скрыто: prior sizing cap
  не гарантирует непрерывный realized gross cap после gaps.
- Intraday adverse drawdown53.5536%/54.8328%primary и13.0405%/12.9206%control.
- Primary проходит source coverage, trade-count, year-presence и execution gates,
  но проваливает CAGR,Sharpe,MDD,positive-year,worst-year и beats-control при обоихcosts.

Перенос литературной skewness-preference гипотезы на смешанный MOEX core4 не
подтвердился. Обратный контроль даёт интересное историческое наблюдение, но его CAGR
также ниже20%, universe мал и коррелирован, execution остаётся research proxy.
Этот run не доказывает источник/причину контрольной прибыли и не разрешает
post-hoc promotion, подбор плеча или повторный конкурс на этой же истории.

Воронка теперь **27portfolio-screen hypotheses:23rejected+1incomplete+3invalid,
0Stage2**. V93 отдельно — один component diagnostic. Новыхlive/demo/HTTP/AlgoPack
economic reads не было. [Замороженный протокол](V94_SKEWNESS_PREMIUM.md) не меняется.
Далее иной независимый механизм/источник в разрешённой области, не retuning V94.

## Воспроизводимость

- Pre-outcome commit `2fcfc48` pushed и byte-verified на gpu-mlserver до run.
- Config SHA `63ad7b7ff2639578669d4bb63e12916463be76c89217c4e8bdb8cc2168cee457`.
- Seal `a65085b0f4a26ecb20e4eda8163b2cb78988274fe697df9d4cb73d4650338aad`:
  6direct files + transitive V64 closure. 9new/37combined tests: local6.48s,
  server1.25s;Ruff clean. Source metadata/hash preflight15/15 before values.
- Source dates2018-01-03–2025-12-30;8100map/66052observations/66052spec rows.
  Source identities сохранены в `inputs.json` и parent declarations.
- Unit `trading-lab-v94-skewness-a65085b0f4a2.service`, launched22:26:50.156387UTC,
  observed invocation`6f45bd5e6944455a8b0eadb7e3379794`,initialPID559239.
  UID999,Restart=no,RuntimeMax3600,MemoryMax8G,Nice10,UMask0027, безcredentialEnvFile.
- Canonical `/srv/trading_lab_data/runs/v94_skewness_premium_v1_a65085b0f4a2`.
- Manifest SHA `7e0bf81c2315518faff087d643d2bcb9d91b0e7a31e7f7852cda15deedfc35ee`.
- Metrics SHA `68a948afbf230048dbc3a4d9882bb04bc0f9e69f9746ac9c0803165549e11bae`.
- Observation22:27:59.742800UTC: inactive/dead,ExecMainStatus0,Resultsuccess;
  closedmanifest and all18artifact hashes verified. No rerun/overwrite.

## Скачивание параллельно тесту

Actual22:27:59UTC /16сентября01:27:59МСК: main иFUTOI обаactive/running,
прежниеPID/invocations,final manifests отсутствуют. Main5502/26305jobs,
59033668rows,63019pages,failed0/blocked0,3475545070completed-job bytes.
FUTOI1207/2192days,13116408logical/10819471new-root rows,38996resolved/
527unresolvedticker-days,101gapdays,7524reference pages,201712671new-root bytes.
Gaps и ссылки наV2/V3 сохранены, units/token/Windows не менялись.

Du22:28:01.200608UTC: data6642182861 + source_evidence479810805 =
**7121993666bytes /7.122GB**. Включая AlgoPack3895751727archive +
1456918554oldprocessed = **5352670281bytes /5.353GB**. Это sequential apparent
stored bytes при ongoing writes, безmodels/runs/tmp; локальные копии не прибавлены.
Это объём хранения, не обещание уникальности каждой записи или полного покрытия.
