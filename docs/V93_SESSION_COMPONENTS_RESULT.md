# V93 R1 — слабый ночной компонент, без продвижения

Canonical R1 completed **2026-09-15T17:30:56.492938UTC**, service success/exit0
наблюдён17:32:17UTC. Оба прогона сохранены; R1 — исправление единиц после просмотра
контроля, не новая независимая гипотеза. [Исходный протокол](V93_SESSION_COMPONENTS.md),
[причина и формула исправления](V93_SESSION_COMPONENTS_R1.md).

## Результат

Вечер→утро: средний наблюдённый net **+2.2994bp** при базовых издержках,
**−0.3805bp** при двойных. Один bp =0.01%, то есть +0.0230%/−0.0038% **на известный
интервал от цены входа**, не годовая доходность и не результат счёта. Последние три
года отрицательны даже при обычных costs. Дальнейшая настройка этого варианта не нужна.

| Arm/cost | Календарные кандидаты | Входы | Известные выходы | Unresolved | Покрытие календаря | Mean gross bp | Mean net bp |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Вечер→утро,1× | 1271 | 595 | 591 | 4 | 46.499% | +4.9792 | +2.2994 |
| Вечер→утро,2× | 1271 | 595 | 591 | 4 | 46.499% | +4.9792 | −0.3805 |
| Дневной контроль,1× | 1271 | 1150 | 1053 | 97 | 82.848% | −3.0695 | −5.7420 |
| Дневной контроль,2× | 1271 | 1150 | 1053 | 97 | 82.848% | −3.0695 | −8.4145 |

Вечерние requests598:653 дня не прошли prior volume,19 missing plan/decision bar,
1 terminal sleep,3 no-entry. Из595 entered4 не имеют доказанного выхода/объёма.
Контроль requests1154:100 low prior volume,17 missing plan/bar,4 no-entry,
97 unknown exits. Maximum actual participation ≤1% у обоих arms.

На583 matched entry dates ночной компонент лучше дневного на16.9499/16.9453bp при
1×/2×. Это сравнение двух условных наблюдённых выборок, а не доказательство устойчивой
прибыли: дневной контроль слабее, но сам overnight не проходит стресс издержек.

| Год | Ночных/дневных известных интервалов | Overnight1×,mean net bp | Overnight2× | Control1× | Control2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021 | 90 /238 | +3.1980 | +1.0430 | −2.5862 | −4.7219 |
| 2022 | 30 /117 | +61.0517 | +58.0064 | −13.2875 | −16.5927 |
| 2023 | 70 /206 | −4.7247 | −7.4003 | +8.3158 | +5.4784 |
| 2024 | 157 /241 | −1.7707 | −4.5316 | −10.9522 | −13.6031 |
| 2025 | 244 /251 | −0.6218 | −3.3994 | −11.7520 | −14.5240 |

Overnight unresolved по годам2/2/0/0/0; control0/69/22/5/1. Неизвестные результаты
не равны нулю. Все статистики условны по известным парам;2022 содержит только30
известных ночных интервалов, не полный инвестируемый год. Это не30 завершённых
портфельных сделок: независимые probes не моделируют свободный капитал после missing exit.

Формальный verdict **INCOMPLETE_SOURCE_NO_PROMOTION**. Дополнительно failed gates:
46.5%<80% coverage, только2 из5 positive years, double-cost mean<2bp. Число известных
пар≥500 и преимущество над контролем не компенсируют провалы. Stage2=false,
goal_verified=false. **CAGR/Sharpe/MDD/portfolio PnL=null** по дизайну, не нули.
Воронка остаётся25 прежних portfolio-screen hypotheses,0Stage2; V93 отдельно как
один component diagnostic с сохранённой unit correction, не два новых механизма.

## Воспроизводимость

- V1 run `/srv/trading_lab_data/runs/v93_session_components_v1_e1b16d43124d`;
  manifest `8e7c1cf9463f98b9109d083b2a19ca665c4db21a41dfd2565bb4a6c100f4c638`.
- R1 run `/srv/trading_lab_data/runs/v93_session_components_r1_0ff19911e604`;
  manifest `93bfd7183d26cf39c76ea944d6b22839eba7e38a51dba6e6e3eade715684f713`;
  metrics `c6de0d9b2ec65dd0a9215e46e1f29697a9a80f8012852c62f7b5b4fe1a0bd6c4`.
- Config R1 `e44e836c958ab89829b3f65636f4e537dcbc73ebbebeda85a53f73484d3bf074`;
  seal `0ff19911e604394bae0d131957bd57c02c2f5cf89beb1a5a0fe29cb733532f93`.
- Pre-run commits V1 `d1592fe`,R1 `1ede572`, pushed before their numerical runs.
  Local28 combined tests PASS6.59s; server15 R1+parent tests PASS0.51s, both seals verified.
- V1/R1 `requests.parquet` **побайтно совпадают**, SHA
  `18522f937faee12b2f74557f4c990efe447d0cbc79639a3835c275b77be4fa7d`.
  Контрольные mean bp совпадают до float roundoff; source/clock/volume eligibility не менялись.
- Output artifacts проверены по manifest SHA; canonical не перезаписывались.

Следующий шаг — другой механизм, либо уже готовый V92 после terminal V89 source.
Не создавать следующий unit correction/ledger/audit для V93, не снижать volume/coverage
пороги, не менять часы/знак/asset/year. Новая информация может обосновать отдельный
будущий протокол, но не превращает эти observations в независимый holdout.
