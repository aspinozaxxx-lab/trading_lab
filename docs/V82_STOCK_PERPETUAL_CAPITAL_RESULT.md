# V82 Фандинга на капитал с резервом пока недостаточно для цели 20 процентов

2026-09-15. [Замороженный протокол](V82_STOCK_PERPETUAL_CAPITAL.md).
Диагностика капитала завершена для ОБОИХ кандидатов V81. При унаследованном резерве30%
фандинг после заданных издержек даёт17,39%/19,02% простой годовой нормировки; при
double costs17,20%/18,84%. Это полезный предел именно наблюдавшегося funding component,
не завершённый backtest пары и не подтверждение дохода20–50%.

## Результаты на всём условном капитале

Период2024-10-01…2025-12-30:455calendar days,320source sessions/319payments на тикер.
Все funding payments известны, coverage100%, missing0. Резерв30% и30/60bps roundtrip
взяты из существующего stock-pair research config, не подобраны по этому пересчёту.

| Показатель | SBERF | GAZPF |
| --- | ---: | ---: |
| Начальный proxy номинал100акций, RUB | 26685,00 | 13490,00 |
| Условный резерв30%, RUB | 8005,50 | 4047,00 |
| Полный условный капитал, RUB | 34690,50 | 17537,00 |
| V81 funding APR только на номинал | 22,8465% | 24,9730% |
| Фандинг после base fee за455дней, RUB | 7514,598 | 4156,186 |
| Фандинг после double fee за455дней, RUB | 7434,543 | 4115,716 |
| Funding-less-fee APR на капитал, base | 17,3890% | 19,0247% |
| Funding-less-fee APR на капитал, double | 17,2037% | 18,8395% |
| Сам funding component покрывает20% APR | Нет | Нет |
| Полная парная доходность установлена | Нет | Нет |

Вердикт обоих: FUNDING_ALONE_BELOW_TARGET_PAIR_UNRESOLVED.
Нельзя называть это двумя полными отрицательными portfolio backtests: для пары есть
неизвестные слагаемые. Это2post-selection capital diagnostics поверх уже известных V81
результатов. 23V65–V80economic screens и2V81funding screens считаются отдельно, Stage2=0.

## Годовые потоки компонента

| Период | SBERF funding, RUB | Доля начального капитала | GAZPF funding, RUB | Доля начального капитала |
| --- | ---: | ---: | ---: | ---: |
| 2024, только часть с октября | 1461,591 | 4,2132% | 824,780 | 4,7031% |
| 2025, по последнюю наблюдаемую сессию | 6133,062 | 17,6794% | 3371,876 | 19,2272% |

Это суммы funding до fees и доли неизменного первоначального капитала, НЕ годовые
portfolio returns. За15месяцев имеется лишь один полный календарный год.

## Какого вклада не хватает

При double costs до20% простой годовой нормировки на тот же условный капитал не хватает
1208,40руб. на SBER-пару и253,53руб. на GAZP-пару за весь455-дневный период. Если бы этот
недостаток закрывался ТОЛЬКО доходом30%-го резерва, требовалось бы соответственно
12,1172% и5,0289% simple APR самого резерва. Это арифметические условия, не доступная
доходность, не начисление cash и не разрешение одновременно считать залог свободными
деньгами. Для50% соответствующий required reserve APR142,1172%/135,0289%: этот исторический
funding component сам по себе не близок к верхней цели.

Максимальный дополнительный капитал к stock principal, при котором один наблюдавшийся
funding после double fee ещё давал бы20%APR:11,8242%/22,4566% номинала. Это diagnostic,
не инструкция уменьшить залог: точные margin и variation cash requirements пока неизвестны.
Замороженный reserve30% не меняется. Нельзя выбрать только GAZPF по меньшему shortfall.

Поступления по акции и dividend debit короткого perpetual компенсируют друг друга до
налогов при совпадающем gross dividend. Поэтому дивиденды не добавляют бесплатный второй
доход: после удержаний и задержек они могут ухудшить результат. Даты, amounts и реальные
платежи для данной пары ещё не прочитаны; неизвестные события не заменяются нулями.

## Что подтверждено и чего ещё нет

Из архива MOEX сохранены3исторические DOC редакции спецификации, покрывающие весь период.
Текстовое извлечение подтвердило funding/dividend signs, отдельный режим первого дня,
nontrading record-date shift, право пересчёта VM и возможность forced conversion.
Native Word page layout не отрендерен: штатный renderer недоступен; это ограничение
source review, а не неявно успешная визуальная проверка. Подробные ссылки/хеши и история
неверной26107HTML response находятся в замороженном протоколе. Правильный catalog response
локально305847bytes, SHA8571d97feced151c732508e436c9a4995a1a23c71e06e0430e40228a46a3c2e2.

Семь unresolved групп для каждого тикера: paired entry/exit и исполнение; полный dividend
adjustment corpus; реальные shareholder cash receipts/tax; dated margin и VM cash liquidity;
forced-conversion calendar/исполнение; broker fees/BBO; same-period cash benchmark и
доступность доходного обеспечения. Counts решений/сделок0; pairedPnL/CAGR/Sharpe/MDD/
cashBenchmark=null, Stage2=false, goal_verified=false. Ни 30%reserve, ни fee proxy не
подтверждают историческую достаточность капитала или брокерскую исполнимость.

## Воспроизводимость

- Pre-derived-result commit1c9d9d9 pushed до серверного расчёта. V81 values уже были
  известны: этот факт явно отмечен, независимый holdout не заявляется.
- Config353328a496e856a8d9349fefc7cb8b1fb865fa584889eb6d20077b68c43399f6.
- Nine-file seal874998a9cce6f9c00ef544218d4622027bb03832dd19d5cab31e436231063bce.
- Canonical /srv/trading_lab_data/runs/v82_stock_perpetual_capital_v1.
- Metrics8dafcb552bab1899fdc903f03d03c2b636e3dc97db80b469f16eb2807e87c46c.
- Local64tests(43V82+21V81) и server43tests PASS, Ruff clean.
- Расчёт11:12:43.980972UTC, завершён с replay11:12:44.357751UTC. Exit0.
- Независимые46Decimal проверок арифметики и flags/counts/null PASS, без вызова
  implementation-функции; terminal metrics SHA совпал. Новых HTTP requests0.
- Transfer2fe7536561887cc6d961e62d199d5519975e42f914abc153905296ca2546443b,
  совпал local/server. Existing sealed code не перезаписывался. Только созданный здесь
  document-tools leaf получил owner trading-lab для чтения pinned DOC; общего chmod/chown нет.

## Следующий шаг

Проверить реальную возможность принимать активы в обеспечение и получать отдельный
доход, без двойного счёта капитала. Вопрос о брокере/типе счёта задан необязательно и пока
не отвечен. Это не разрешение открыть счёт, купить фонд или включить торговлю. Для обеих
пар полный price/dividend/conversion/benchmark test требует отдельного economic seal;
этот короткий diagnostic его не заменяет. Гипотезы вне MOEX пока не расширены:
предыдущий optional crypto вопрос также не получил ответа.

## Архивирование AlgoPack

На11:14:18.760792UTC оба исходных systemd services active/running, без restart.
14-family archive1106/26305jobs,14000122rows/14747pages,failed0/blocked0;
FUTOI V3 archive127/2192days,7275ticker-days/2259693intraday rows. Финальных manifests
ещё нет. Актуальные счётчики и правила хранения зависимостей V3/V2/core4 в
[14-family status](ALGOPACK_ARCHIVE_V1_STATUS.md) и [FUTOI status](ALGOPACK_FUTOI_ARCHIVE_STATUS.md).
Полного Windows mirror новых архивов пока нет. Данные/модели вне Git, подписки,
автопродление, broker, paper и защищённые2026outcomes не менялись.
