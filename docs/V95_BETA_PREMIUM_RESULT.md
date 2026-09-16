# V95 — завершён, REJECT_STAGE1

Один исторический screen завершён **2026-09-16T10:11:42.747061UTC**.
Низкая beta с выравниванием расчётного риска не дала положительной доходности.
Контроль с равными суммами также убыточен. На второй уровень ничего не прошло;
цель 20–50% годовых не подтверждена.

## Все сценарии

Период 2021–2025, 1271 сессия, стартовый капитал 1 млн RUB. Это полный
research-proxy cash ledger с сохранёнными пропусками и остановками, не набор
отобранных удачных сделок и не независимый holdout.

| Сценарий | CAGR | Sharpe | MDD | Round trips | Итоговый капитал, RUB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Primary, base costs | −8.1837% | −0.54263 | 38.2516% | 54 | 653323.60 |
| Primary, double costs | −8.2129% | −0.54351 | 38.4035% | 54 | 652289.70 |
| Equal-notional control, base | −10.1345% | −0.68324 | 44.8037% | 73 | 586985.98 |
| Equal-notional control, double | −10.4274% | −0.70702 | 44.8049% | 72 | 577508.68 |

| Год | Primary base | Primary double | Control base | Control double |
| --- | ---: | ---: | ---: | ---: |
| 2021 | −9.0961% | −9.4272% | −15.2654% | −16.6874% |
| 2022 | −29.0267% | −28.9717% | −28.5671% | −27.3983% |
| 2023 | +12.4493% | +12.3673% | −0.6545% | −0.4845% |
| 2024 | +4.7446% | +4.9216% | +3.1016% | +1.8826% |
| 2025 | −14.0269% | −13.9984% | −5.3207% | −5.8305% |

Primary gross VM: −339456.00 / −333390.15 RUB; costs: 7220.39 / 14320.15 RUB;
net: −346676.40 / −347710.30 RUB при base/double. Control gross VM:
−402762.24 / −402338.06 RUB; costs: 10251.78 / 20153.26 RUB;
net: −413014.02 / −422491.32 RUB. Провал не объясняется одними комиссиями.
Издержки меняют integer sizing и путь капитала, поэтому отдельные годы или gross
VM при double не обязаны быть хуже; конечный net capital ниже в обоих arms.

## Coverage и исполнение

- 5084 asset-date решения в каждом arm; 1992 nonzero targets, 1092
  feature-unavailable, 32 source-unavailable, stale-at-fill = 0.
- Готовность **78.5208%**, ниже заранее заданных 80%. Из 60 месячных решений
  47 готовы, 13 имеют неполное окно beta. Использовано 48 monthly states, потому
  что в начале 2021 разрешён предшествующий state из warmup 2020.
- 8100 source return rows, 8060 наблюдаемых same-contract returns. Missing не
  удалялся из 252-сессионного окна и не заменялся нулём.
- Все четыре ledgers execution_complete = true, critical = 0, unresolved_halt = 0,
  terminal_carried = false. Filled legs: 163/162 primary, 240/227 control.
  Round trips учитывают актив, знак и смену контракта, не смешивают строки активов.
- В каждом сценарии сохранены 16 factual halt/carry/mark events, 16 no-open
  target cancellations, 3 no-liquidity cancellations и один participation clip.
  Максимальное участие 0.16340%, ниже cap 1%.
- Максимальный close gross: 0.902538/0.904973 primary и 0.961535/0.962036 control.
  Intraday adverse drawdown: 41.4457%/41.6269% primary и 45.4348%/45.4728% control.

Primary лучше control при обоих costs, но проваливает coverage, CAGR, Sharpe,
просадку, число положительных лет и worst year. Проходят trade-count, присутствие
всех пяти лет и проверки исполнения. Формальный итог — **REJECT_STAGE1**, не
техническая ошибка расчёта и не разрешение укоротить окно ради улучшения coverage.

Оценка прошлой beta определяет фиксированные веса; это не обещание будущего
хеджирования реального RUB PnL. Малый смешанный factor, включающий сами четыре
инструмента, не является внешним рыночным портфелем. Литературная гипотеза на этом
universe не подтверждена; знак, factor, window, assets, size и masks не менять.

Воронка: **28 portfolio-screen hypotheses = 24 rejected + 1 incomplete + 3 invalid;
0 Stage2**. V93 — отдельный component diagnostic. V94 и его контроль остаются
закрытыми. Следующий шаг — иной независимый разрешённый механизм или источник,
не повтор этих правил и не увеличение плеча по увиденным результатам.

## Идентичность и выполнение

- [Замороженный протокол](V95_BETA_PREMIUM.md), pre-outcome commit `a265730`,
  наличие этого commit на GitHub проверено перед server deployment.
- Config SHA: `d64451a77eaf1abb4efe8d81da6da4ca1b14e4a2d77bb89d9ea9e96517aede1b`.
- Seal: `0aa70e7f3223cef28ebd05bcd464719c10b1f52ef34c66a80d13aa8300ad89eb`;
  10 direct files и transitive V64 source/code closure.
- Local 9 новых / 47 combined synthetic tests PASS за 13.73s, Ruff clean.
  Server 47/47 PASS за 2.38s. Первая server test-попытка: 35 PASS / 12 setup errors
  из-за общего `.pytest_tmp`, до запуска экономики. Повтор с новым внешним
  `/srv/trading_lab_data/tmp/v95-tests-8folmnig/pytest` исправил только окружение;
  ни code, ни config, ни frozen seal не менялись. Старую папку не удаляли.
- До numeric reads source hash/schema/date preflight 15/15 PASS; источник
  2018-01-03–2025-12-30. Данные 2026 не использованы.
- Unit `trading-lab-v95-beta-0aa70e7f3223.service`, launched
  `2026-09-16T10:11:39.227313UTC`; invocation `a5319b8bb9a84b8ab9dcf738875f0863`,
  initial PID 2818358. UID999/GID989, Restart=no, RuntimeMax3600, MemoryMax8G,
  Nice10, UMask0027, без credential EnvironmentFile.
- Canonical: `/srv/trading_lab_data/runs/v95_beta_premium_v1_0aa70e7f3223`.
- Manifest SHA: `baad4ba2285bc17da4d1b731fe6e6dca6ac99045b1b62832d472da4fcecbc71e`.
- Metrics SHA: `82c57c150e04fe255e510fe97b62a38c72915ebdbf37501ae87f0357fe8a3e0c`.
- В 10:14:01UTC проверены все 20 artifact hashes; журнал подтверждает четыре
  рассчитанных сценария и `Deactivated successfully`. Повторного economic run нет.

Параллельно завершён [FUTOI archive](ALGOPACK_FUTOI_ARCHIVE_STATUS.md) с явными gaps;
[основной AlgoPack archive](ALGOPACK_ARCHIVE_V1_STATUS.md) продолжает скачиваться.
Новых numeric AlgoPack admission, моделей, покупок, Windows tasks, paper/live запусков нет.
