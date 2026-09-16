# V101 — проверка завершена, INVALID_EXECUTION_NO_PROMOTION

Единственный economic run V2 завершён **2026-09-16T22:06:06.050849UTC**.
Нового кандидата нет: frozen verdict **INVALID_EXECUTION_NO_PROMOTION**.
Это не подтверждённая доходность и не валидная статистическая фальсификация
механизма. Даже диагностические цифры не проходят CAGR/Sharpe/MDD/стабильность.
Цель относительно предсказуемых20–50% не достигнута; Stage2/демо/live не разрешены.

[Правило V1](V101_MANUFACTURING_DEMAND.md) сохранено: BR long0.9gross, если
последнее опубликованное manufacturing month-on-month изменение >0; иначе cash.
Контроль constant-long на том же valid-source календаре. [V2](V101_MANUFACTURING_DEMAND_V2.md)
меняет только распознавание combined year/month header, не economics.

## Все четыре расчёта и годы

2018–2025,2025 сессий, старт1млнRUB, cash interest0. Daily spec-proxy ledger,
известная development история, не независимый holdout. Все суммы ниже сохраняются
для диагностики несмотря на execution-invalid; не обозначать их исполнимым доходом.

| Вариант | CAGR | Sharpe | MDD | Round trips | Итоговый капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary base | +3.9579% | 0.28120 | 44.9365% | 103 | 1363568.93 |
| Primary double | +3.3871% | 0.25766 | 45.4158% | 103 | 1304894.87 |
| Control base | +0.6795% | 0.17936 | 68.3451% | 124 | 1055589.67 |
| Control double | +0.2687% | 0.16531 | 68.3907% | 124 | 1021670.10 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2018 | −8.6275% | −9.1190% | −19.6666% | −20.4866% |
| 2019 | −1.5599% | −2.1752% | +23.5638% | +22.6027% |
| 2020 | −6.3462% | −7.2611% | −27.8682% | −27.8666% |
| 2021 | +70.3018% | +68.6672% | +54.4951% | +53.7249% |
| 2022 | +19.2211% | +19.6959% | +15.5391% | +15.9686% |
| 2023 | −3.4208% | −3.6676% | −11.8746% | −12.8849% |
| 2024 | −0.7157% | −1.1160% | +0.5612% | +0.3429% |
| 2025 | −16.8566% | −17.7031% | −6.8020% | −6.7671% |

Primary имеет2положительных года из8, control4. Успех2021 не разрешает отбирать
удобный период или повышать плечо. Превосходство над control не компенсирует
провалы остальных gates и не даёт основания для продвижения.
Primary grossVM444134.90/462993.94RUB, costs80565.97/158099.06, net363568.93/
304894.87. Control gross134964.89/177573.67, costs79375.22/155903.57,
net55589.67/21670.10. Издержки меняют капитал и дальнейшие integer quantities;
annual differences/gross PnL не обязаны монотонно ухудшаться при double costs.

## Coverage, исполнение и gates

- 2024 решения на arm, first effective2018-01-04, last2025-12-30. Primary1260
  nonzero targets/1261exposed sessions,61used releases; control1962/1963,96releases.
  Разница в один день сохраняет halt carry, не выдуманную нулевую доходность.
- Feature unavailable28, plan unavailable1; stale-at-fill18primary/32control.
  Ready coverage97.7273%. Source96releases; original receipt verified=false.
- Flat-to-nonzero transitions44primary/34control;103/124roundtrips включают роллы
  и не равны103/124независимым макронаблюдениям. Filled legs364/379primary,452/452control.
- **Все4execution_complete=false**, critical_failure_count2 в каждом, весь этот
  счётчик приходится на gross_limit_rejection_count2. Unresolved halt0, terminal
  carried=false. Пропуски contract/open/settle/point/tick/fee/margin/liquidity0;
  initial-margin/participation/atomic rejection0. Factual halt/mark/carry по1;
  capacity no-open cancel1, no-liquidity cancel1, roll cancel0, participation clip0.
- Это срабатывания aggregate risk check в frozen engine, не доказательство двух
  конкретных неисполненных заявок: gross-reason rows в orders и critical-blocked
  ledger rows отсутствуют. Даты срабатываний отдельно не реконструированы. Aggregate
  counter не обнулялся; отсутствие таких rows не снимает execution-invalid.
- Maxclosegross1.09219/1.12082primary,1.10203/1.12198control; target0.9 не гарантирует
  fixed realized leverage. Maxparticipation.35330%/.33969%primary,.54459%control.
  Intraday adverse MDD45.6779%/46.3811%primary,72.5708%/72.5667%control, отдельно от
  closeMDD в gates. Глубокая просадка не скрывается final positive NAV.

Frozen23checks: false все4execution; для обоих costs false CAGR>=5%,Sharpe>=.5,
MDD<=25%,positiveyears>=5,worstyear>=−15%. True coverage,>=20trips,8years,
beats-control и excess>=2pp. Historical20/50=false, goal_verified=false.
Воронка теперь **33 portfolio hypotheses =27rejectedStage1 +1rejectedStage2
+1incomplete +4invalid**, активных Stage2/Stage3кандидатов0; V93 отдельно.
V1/V2 — один участник, не два; V100 — Stage2 V99, не отдельная гипотеза.

Не повторять V101 и не подбирать sign/asset/TTL/threshold/size/control. Исправление
исполнения не имеет приоритета ради этой слабой диагностической ветки; frozen
рисковые gates и результаты не переписывать. Никакого предположения независимости
дохода от существующих macro/trend семей. Далее — новый механизм/источник.

## Source failure V1 и успешная V2

V1source unit завершился FAILED_SOURCE_NO_RETRY21:46:53.848649UTC после3GET/2parses.
Combined `2018 Jan. [p]` в20180215 не поддерживался; HTTP200, не access refusal.
Все V1 код/config/seal/raw сохранены. V1 economic root не создавался. Полная
provenance и причина исправления — в[V2 protocol](V101_MANUFACTURING_DEMAND_V2.md).

V2source `/srv/trading_lab_data/source_evidence/v101_manufacturing_v2/a6a7b6fee939`,
COMPLETE22:05:27.921750UTC,90newGET+6reused releases,96parses,0errors.
Manifest `6917986dc9d9f55613d80e4fafc9b3c9b219eb826e7ce83dae5fae19fd611a0a`;
releases `d9d21eb935995b8f57797a477724f7fafc0feed1a560c434f176689c9b308afd`.
197artifacthashes/96rawreparses/96HTTP200metadata+bodySHA+size+URL проверены
22:06:01.400881UTC до economics. Source unit
`trading-lab-v101-manufacturing-v2-source-a6a7b6fee939.service`, invocation
`04bb8315325d40c0982e40bd6f96fcef`, launch22:03:56.701304UTC, terminal success.
Ни6reuse, ни97index/releaseHTML не новые независимые гипотезы. Current-retrieved
dated archives остаются conditional development, не witnessed PIT/revision proof.

## Economic provenance и повторная проверка

Pre-outcome commit/push `cd84c432d1d73cbc42cb01713b0418e49f8c7c15`.
V2 seal `a6a7b6fee93973de9cb71a98dca1f0503898b70ed69aca40a8eec57ab272a85d`;
5direct files+V1/V64transitiveclosure. V2sourcecode SHA
`e897ec310e04a5035b2b64dc04be653a278b18d1341e0459330e3708a5f287d9`.
Config `6f744befa64081304fa8af12591cc116a8d784fd1df390a72ac6abbd7d2b7d97`.
Bundle `6aab16c0567bb1e4f3f53b378f278d1a0cae770948eee8585de9c59bcd763188`.
16new/118combinedlocaltestsPASS9.57s;16post-formatPASS.47s;33servertestsPASS.27s,
Ruffclean. UID999/GID989, no EnvironmentFile/credentials, no Windows collection.

Economic unit `trading-lab-v101-manufacturing-v2-economic-a6a7b6fee939.service`,
invocation `db3202b932fb4749bacf41e64a856cc1`, launch22:06:01.432529UTC,
terminal service success; research verdict при этом INVALID. Source manifest SHA
закреплён в invocation до market reads. Run
`/srv/trading_lab_data/runs/v101_manufacturing_demand_v2_a6a7b6fee939`.
Manifest `c9541cbe5dba59a63420b34c4c388c0686b15c698dcc5bc9287f4183a643f8df`;
metrics `f1c0aab1fbaab3cc85239977efa577a0773862ba30ec717e8f7ef2f0c831974f`.

Audit22:07:02.035120UTC:17artifacthashes,2source-targetreplays,4cashcontinuity/
dailyidentity/ordercost/performance/annual/position-count replays,coverage/assessment
и <=2025 source/decision/fill/ledger boundaries проверены. Journal подтверждает
ровно4завершённых расчёта. Это сохранённый ledger replay, не повторный economicrun;
полная независимая реконструкция aggregate risk counters не заявляется. Canonical
и sealed files после просмотра результатов не менялись.

## Одновременная загрузка AlgoPack

Снимок17сентября01:07МСК /16сентября22:07UTC: main active/running, прежние
PID1663880/invocation `d562f0748c4341b48eb7f4d34d64b4a1`,16734/26305jobs(63.6153%),
155497164rows,167334pages,failed0/blocked0,9226678808completed-jobbytes,
status22:07:02.031232UTC,finalmanifestabsent. Du22:07:04.981760UTC:
data12719948835 + source_evidence546678333 = **13266627168bytes/13.267GB**;
archive9869984717 + earlierprocessed1456918554 = **11326903271bytes/11.327GBAlgoPack**.
AlgoPack входит в общий итог. Последовательный apparent-byte замер при записи,
без models/runs/tmp и локальных копий; не утверждение byte-level дедупликации.
Доля jobs не доля конечного объёма. FUTOI terminal с550unresolved,не повторноaudited.
Archive/token/Windows unchanged, source gaps не скрыты. Broaderscope unanswered.
