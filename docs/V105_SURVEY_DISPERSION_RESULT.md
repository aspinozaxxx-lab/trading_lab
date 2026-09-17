# V105 — REJECT_STAGE1: сужение разброса прогнозов не дало преимущества

2026-09-17. Один economic screen completed **00:38:45.793800 UTC**. Условная покупка
MIX при сокращении квартильного размаха прогнозов ВВП проиграла и cash, и заранее
выбранной постоянной покупке на том же доступном календаре. Четыре сценария прошли
проверки research execution; это экономический отсев, не исправление торгового
правила под результат. Независимым holdout история2021–2025 не является.

## Основной результат

Стартовый капитал — 1 млн RUB, cash interest0. Все числа после указанных издержек.

| Вариант | CAGR, % | Sharpe | MDD, % | Завершённые сделки | Конечный капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, base | -12.3913 | -0.58853 | 50.8977 | 19 | 517076.61 |
| Primary, double | -12.4209 | -0.58892 | 50.9756 | 19 | 516206.65 |
| Constant-long control, base | -8.9998 | -0.30838 | 47.6055 | 19 | 624879.62 |
| Constant-long control, double | -9.1891 | -0.31703 | 47.6755 | 19 | 618424.46 |

| Год | Primary base, % | Primary double, % | Control base, % | Control double, % |
| --- | ---: | ---: | ---: | ---: |
| 2021 | -1.6191 | -1.6431 | -2.6251 | -2.6651 |
| 2022 | -32.4351 | -32.5243 | -33.8885 | -33.9682 |
| 2023 | 10.7061 | 10.6023 | 29.0757 | 29.0232 |
| 2024 | -20.6021 | -20.4779 | -11.3895 | -11.4898 |
| 2025 | -11.5003 | -11.5659 | -15.1322 | -15.7434 |

Всего один положительный год из пяти у каждого сценария. Primary total return
-48.2923%/-48.3793%. Не пройдены gates по числу сделок, доходности, Sharpe, просадке,
положительным годам, худшему году и преимуществу над control. Coverage и execution
gates пройдены. Ни historical20%, ни50% не подтверждены; goal_verified=false.
Порог5% Stage1 — лишь отбор компонента, не замена цели устойчивых20–50%.

## Данные, решения и издержки

- 37 survey months в source,36 доступны до2026,35 valid predecessor comparisons,
  21 contraction states. December2025values исключены до numerical read, поскольку
  их консервативная availability ужеJanuary2026. No fit/search/new HTTP/parser.
- По1271 decision dates2021-01-04…2025-12-30 на arm. Primary670 nonzero targets,
  control1086; использованы21/35 уникальных survey states. Trades включают rolls
  и не равны независимым публикациям или числу переключений сигнала.
- Source/feature readiness86.7034%; joint source/feature/plan/fill1087/1271=85.5232%.
  Feature-unavailable169, stale-at-fill125,
  plan/source-unavailable15 на каждом arm; flags могут пересекаться. Первоначальный
  недоступный период2021 сохранён в полном календаре, не вырезан ради CAGR.
- Primary gross VM -480043.22/-478192.99 RUB, costs2880.18/5600.36,
  net -482923.39/-483793.35. Control gross -372080.18/-375655.13,
  costs3040.20/5920.41, net -375120.38/-381575.54.
- Commission primary1080/2100, slippage1800.18/3500.36; control1140/2220 и
  1900.20/3700.41. Doubled costs могут менять integer sizes и gross PnL;
  gross между сценариями не обязан совпадать.
- Filled legs43/41 primary,40/38 control. Position entries/round trips19 у всех.
  Exposed sessions685 primary/1101 control, включая сохранённый halted exposure.

All4 execution_complete=true, critical failures0, unresolved0, terminal_carried=false.
Unknown required spec/price/liquidity fields0; gross/margin/participation/atomic
rejections0. Max close gross0.901085/0.900489 primary,0.900441/0.893012 control,
max participation0.61350% у всех при cap1%. Factual halt/mark/carry counters15,
cancel-no-open15, cancel-no-liquidity1, cancel-roll-capacity1 на scenario; clip0.
Это counters, не утверждение о15 независимых эпизодах. Они не удалены из ledger.
Модель исполнения/specs/fees не broker-exact; успешный research ledger не live admission.

## Идентичность и завершение

[Правило V1](V105_SURVEY_DISPERSION.md), [identity-only V2](V105_SURVEY_DISPERSION_V2.md).
V1seal `db89197a975f962a1af7b2f7060fa08c33dc22356d21eb3471d131c36e595edf`,
pre-outcome commit `efca3154b5f4df378131eab58c81f520b3cf162d`.
V1failed00:30:46UTC: row source_url содержит официальный workbook, не indexpage.
Это остановка до states/targets/marketread/economics, не отдельный portfolio entrant.
Numeric source был загружен вRAM, но не преобразован/напечатан. Failedroot сохранён:
`runs/v105_survey_dispersion_v1_db89197a975f`, толькоinputs.json3173bytes,
SHA `f2032b793bcf044ccfd3bd6c9dd800b7dc87156b463d660265938f1de4bb12df`.
V2изменяет только protocolID/expectedURL и добавляет metadata identity check;
sign/quantiles/period/availability/TTL/control/costs/size/gates неизменны.

Canonical `runs/v105_survey_dispersion_v2_2ec8e075107a`:

- Seal: `2ec8e075107a8935138df0c9c28a70f1fd60cd53a238ee3cb4be1292933e6146`.
- Correction config: `ff74a20cbf35da675c0cc1798e3fd440fc2fb91b52ae0e4b951cf21e1e8da934`.
- Wrapper code: `f710133645d8b030e620f8184ae1bd93244b41d1a91ec831520dea3264b4f25a`.
- Pre-outcome commit: `bb7189c8ff27725052c0bb07ff60c1e3451c4121`.
- Manifest: `1fb4ae8edba6a939608c1528773792c4092ec72c03e0960e08f374485edd7b75`.
- Metrics: `baee47d5cc941ef127036f6d3a6b6a8b41ae4a044eeebbabb48aaebe924cf792`.
- Unit: `trading-lab-v105-survey-dispersion-v2-2ec8e075107a.service`.
- Original invocation: `ce7d4e5d7eaa4c3e81c5a892733918c5`.

Четыре completion records в original invocation journal00:38:44–45UTC плюс manifest
доказывают окончание. При чтении00:40UTC transient unit ужеLoadState=not-found;
его default Result=success/ExecMainStatus=0 сами по себе не доказательство успеха.
Audit00:40:06.121732UTC:18 artifact hashes,36state recomputations,2targetframes,
4cash/cost/metric/annual/position-count replays и assessment совпали. Это не
независимая реконструкция всех execution risk counters. Pandas сообщил FutureWarning
о null-equivalence NaN/None при Parquet target replay; текущая проверка прошла,
unknown numeric returns не заменялись нулями. Code/config не менялись после результата.

118 synthetic tests local5.03s/server1.66s PASS; Ruff clean. Source/futures hashes,
schemas/dates и URL/unit/vintage metadata verified before numerical use inV2.
Пять существующих sourcefiles скопированы наserver. НовыхHTTP-загрузок нет;
числовые значения взяты из прежнего набора после соответствующих gates.
Source transfer SHA72fbf041d44bb5a8ce10e4c97c0f90c3a282ca2750b0fc263cb2920a228e6d2c;
V2code transfer SHAd59210c78f7e33c20d1e5f96eb36f6c088a051e9fccf27931037b9b0a572bf45.

Full local backup в `D:\Projects\trading_lab_data\runs` —18hashes+manifest PASS,
failedV1inputs также SHA-verified. Result archive19files443653bytes,
SHA `c970272125dc2b47d4e58d16569c8b2164d0598405dc2266fb2ab0ac73622ae9`.
Raw/results/models не вошли вGit. Server archive/credentials/Windows tasks не менялись.

## Воронка и следующий шаг

**36 portfolio entrants =29 REJECT_STAGE1 +1 REJECT_STAGE2 +1 incomplete +5 invalid**,
0active Stage2/3. V93separate component,V102source-only и V105failedV1 не дополнительные
entrants. Goal20–50%active/unverified. Не flip-ить sign, менять quantiles или подбирать
другой survey channel после результата; не повторять canonical/replay без новой причины.

Следующий bounded review — CFTC producer hedging demand / speculative risk capacity
на существующих данных, с novelty check против закрытых V58/V59/V87. Поля producer
long/short, spreading, total_traders найдены в source schema, но новые values не
читались; правило/окно/актив ещё не выбраны, V106config нет. Сначала обоснование,
metadata coverage и строгие publication overrides; не новый CSV parser/collector,
не net-managed-money retune и не ослабление2026/broaderAlgoPack scope.

## Скачивание параллельно исследованию

Снимок00:41:32UTC: main archiveactive/running, PID1663880, прежняяinvocation,
18521/26305jobs70.4087%,167082007rows,180105pages,failed0/blocked0. Finalmanifest
отсутствует;RUNNING не COMPLETE. Это fraction заданий, не конечного объёма/времени.
Du закончен00:41:35.905773UTC: **13932033521bytes /13.932GB data+source**, из них
**11971120904bytes /11.971GB AlgoPack**. Apparent bytes при записи, не deduplicated
unique corpus; models/runs/tmp/transfers исключены. Localdata+source2.747GB частично
копии, не прибавлять. Новая servercopy CBRsource не новая unique информация междуhosts.
FUTOI прежние550unresolvedticker-days отдельно, не переаудированы; mainfailed0 не
устраняет эти gaps. Подробности в [archive status](ALGOPACK_ARCHIVE_V1_STATUS.md).
