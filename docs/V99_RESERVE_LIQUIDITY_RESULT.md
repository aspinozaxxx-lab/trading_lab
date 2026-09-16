# V99 — быстрый отбор пройден, устойчивость и цель ещё не подтверждены

Один тест завершён **2026-09-16T20:41:35.895286UTC**, вердикт frozen Stage1:
**STAGE2_CANDIDATE**. Это первый прошедший быстрые portfolio gates кандидат в
текущей воронке, не готовая доходная стратегия и не достижение20–50% годовых.

Правило: первый ежемесячный выпуск H.4.1, рост Wednesday bank-reserve level за
три календарных месяца => MIX long0.9gross, иначе cash. Контроль — постоянный
long на том же valid-source календаре. Никакого выбора по результату/плечевого
усиления. [Зафиксированный протокол](V99_RESERVE_LIQUIDITY.md).

## Все варианты и годы

2018–2025,2025сессий,начальныйкапитал1млнRUB,нулевойдоходсвободныхденег.
Уже просмотренная development история, daily spec proxies, не независимый holdout.

| Вариант | CAGR | Sharpe | MDD | Round trips | Итоговый капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary base | +6.8599% | 0.73558 | 21.9892% | 40 | 1699049.89 |
| Primary double | +6.8176% | 0.73759 | 22.4424% | 40 | 1693689.62 |
| Control base | +0.0191% | 0.11012 | 50.8622% | 61 | 1001524.41 |
| Control double | +0.0162% | 0.11027 | 50.4078% | 61 | 1001298.02 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | 0.0000% | 0.0000% | +6.1633% | +5.8233% |
| 2019 | +15.4680% | +15.3360% | +19.6654% | +19.0208% |
| 2020 | +29.6418% | +30.0928% | +20.2315% | +20.1936% |
| 2021 | +8.8298% | +8.5720% | +7.9930% | +8.5274% |
| 2022 | +13.7100% | +14.3803% | −37.7989% | −37.2808% |
| 2023 | +10.1469% | +9.9312% | +35.1854% | +34.4833% |
| 2024 | −3.4955% | −4.0717% | −12.2256% | −12.0331% |
| 2025 | −13.7155% | −13.8056% | −17.7361% | −17.8609% |

Primary grossVM712730.09/721530.00RUB, costs13680.19/27840.39, net699049.89/
693689.62. Control gross19524.83/37458.88, costs18000.42/36160.86, net1524.41/
1298.02. Integer sizing depends on remaining cash, so doubled costs change later
quantities and gross PnL; neither annual differences nor fill counts must be monotonic.

**Явная проблема устойчивости:** геометрическая годовая доходность из уже известных
годовых результатов2018–2021около12.98% при обоих costs,2022–2025только1.06%/0.98%.
За2024–2025совокупно−16.73%/−17.32%. Это описательная post-selection диагностика
того же прогона, не новая независимая проверка и не повод выбрать хорошие годы.
2018снулём не удалён. Формальный Stage1PASS не скрывает ухудшение последних лет.

## Полнота и исполнение

- 2024решения/вариант. Primary861nonzerotargets/861exposedsessions,42usedmonths;
  control1935targets/1950exposedsessions,95usedmonths. Разница control связана с
  сохранённым halt carry, не заполнением неизвестной доходности нулём.
- Feature-unavailable43, source-plan-unavailable15 у обоих; stale-at-fill16/31.
  Primaryready97.0850%. Из100выпусков99usable;95statesready после baseline/warmup
  и documented Jan2025delay. Ни clock proxy, ни coverage не доказывают originalPIT.
- 27primary/33control signal flat-to-long transitions, включая разрывы/истечения
  допуска.40/61roundtrips включают роллы, это не40независимых макрособытий.
- All4executioncomplete=true, critical0, unresolvedhalt0,terminalflat.
  Missing contract/open/settle/spec/tick/fee/margin/liquidity counters0.
  Primary filledlegs90/97,rollcapacitycancel1/1. Control filledlegs142/150,
  rollcapacitycancel11/10,noliquiditycancel1/1,noopencancel15/15,haltcarry15/15.
  Participationclip0. Эти случаи сохранены в результатах, не исключены задним числом.
- Maxparticipationprimary0.92025%;control0.90909%/0.92025%,нижелимита1%.
  Maxclosegrossprimary0.90100/0.90151,control0.90091/0.90081.
  IntradayadverseMDDprimary23.8525%/23.9469%,control53.3040%/52.8582%, отдельно
  от closeMDD в frozen gates.

Все23Stage1checks true:>=20trips,>=5%CAGR,Sharpe>=.5,MDD<=25%,5positiveyears/8,
worstyear>=−15%,excessovercontrol>=2pp,coverage>=80% и полное исполнение.
Historical20/50flags=false,goal_verified=false. Пока никаких Stage2PASS/демо/live.
Воронка: **32portfolio=27rejected+1incomplete+3invalid+1Stage2candidate**;V93отдельно.

Приоритет дальше — Stage2 этого кандидата, не очередной источник. Сначала фиксировать
план stress-проверок без подбора: causal/source/ledger evidence, временная концентрация,
дополнительные задержки и повышенные costs. Сохранить всё, включая отрицательные
сценарии; не менять базовое правило и не объявлять повторную историю unseen holdout.
Параметры/пороги нового stress-протокола пока не зафиксированы, экономических stress
прогонов ещё нет. Нет разрешения компенсировать низкий CAGR увеличением плеча.

## Воспроизводимость

Pre-outcome commit/push`8082bf35a34fac747a04493307357267bfae0752`.
Seal`c9e27fe2d1a9a56c3345ba3feeeacf213556727049bf34c08bd1a3f8179d51b4`;
config`8d4bd99ecc31fe48cca428e26a930e756f79b1a2d29d0992beaf649229c65738`.
13directfiles+V64transitiveclosure.14new/76combinedlocaltestsPASS7.13s,Ruffclean;
14servertestsPASS0.18s,UID999. Frozen files не менялись после seal.
BundleSHA`c29b4aa98d3f8c6d46790e746ad3887ea896882b395aa2ee4812ed70c94c7cad`.

Source COMPLETE20:40:43.013698UTC,100GETs,100parsed/99usable,0errors:
`/srv/trading_lab_data/source_evidence/v99_reserves/c9e27fe2d1a9`.
Manifest`ae0c56ea223297da1d3245ba85192819a46f4b7e1c719bec0e315bd02638e8fa`,
releases`bf2ebe2bdc01977ce3cc7ea35557486194b581314121156deb4f83f3a7add122`.
209artifacthashes и100rawreparses verified20:41:32.551577UTC до economic invocation.
Unit`trading-lab-v99-reserves-source-c9e27fe2d1a9.service`,invocation
`0abeedeb175c4f8ab0e6761d9723f880`, terminal success. No EnvironmentFile/credentials.

Economic sourceSHA был закреплён до market reads; запуск20:41:32.559292UTC.
Unit`trading-lab-v99-reserves-economic-c9e27fe2d1a9.service`,invocation
`638baac6cf0045d58fb55e9b2f6303dc`,terminal success. Не повторять canonical.
Root`/srv/trading_lab_data/runs/v99_reserve_liquidity_v1_c9e27fe2d1a9`.
Manifest`2b3cf798c07975ad1221a76c5df801dc8346980d0707a706b5a9949b9f65b867`,
metrics`95311cf15b665ba1458df3f542ecf69ee18b6717b17c1203fb992ecf29f0575f`.
Audit20:42:40.958561UTC:18hashes,2source-targetreplays,4performance/annual/count
replays,sourceclock/<=2025checks иterminaljournal подтверждены. Это replay из
сохранённого ledger, не повторный economicrun. Source archives conditional, не livePIT.

AlgoPack не прерывался:20:43UTC15846/26305jobs,149386185rows,160692pages,
failed0/blocked0,finalmanifestabsent. Sequentialdu20:43:12UTC:
data12374457055+source535171622=12909628677bytes/**12.910GB**;
archive9528503150+oldprocessed1456918554=10985421704bytes/**10.985GBAlgoPack**.
Это server data/source,безmodels/runs/tmp и добавления дублирующих localcopies.
