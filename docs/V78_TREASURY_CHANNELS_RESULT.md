# V78 — два Treasury-сигнала: оба REJECT_STAGE1

2026-09-14. Завершён один пакет из двух заранее объявленных гипотез, без подбора
параметров после результата. Ни одна не проходит на Stage2; цель 20–50% не достигнута.
V65–V78: 19 economic screens = 17 REJECT_STAGE1 + 1 INCOMPLETE + 1 INVALID, 0 Stage2.
V75/V77 — отдельные source-only проверки, в эти 19 не входят.

## Экономический результат

[Протокол](V78_TREASURY_CHANNELS.md): изменения за 20 наблюдений реальной ставки
DFII10 и инфляционной компенсации DGS10−DFII10. Каждый сигнал управляет общей корзиной
BR/MIX/SI с абсолютными весами 0.3; constant risk-on control и одинаковые masks.
Весь 2018–2025, исходный капитал 1 млн руб., без процентов на свободные деньги.
Это conditional current-vintage development, не независимый holdout или live evidence.

В каждой ячейке показатели при обычных / удвоенных издержках:

| Вариант | CAGR, % | Sharpe | MDD, % | Закрытые asset episodes | Прибыльные годы |
| --- | ---: | ---: | ---: | ---: | ---: |
| Реальная ставка | −8.3438 / −9.0121 | −0.6494 / −0.7064 | 62.4708 / 63.8287 | 523 / 523 | 4/8 / 4/8 |
| Инфляционная компенсация | 1.0018 / −2.1002 | 0.1409 / −0.0778 | 31.5756 / 38.1346 | 685 / 657 | 5/8 / 4/8 |
| Constant risk-on control | 0.2046 / 0.1222 | 0.0866 / 0.0806 | 41.5446 / 41.1373 | 159 / 161 | 4/8 / 4/8 |

Контроль в двух case runs получился идентичным и показан один раз; это не четыре
разных гипотезы. Episodes учитывают выход в flat, смену знака или контракта;
изменение размера без смены знака/контракта не новый episode. Это не независимые shocks.

Реальная ставка: gross VM −452 485 / −434 663 руб., costs 48 972 / 95 107,
net −501 457 / −529 771; конечный капитал 498 543 / 470 229 руб.
Инфляционная компенсация: gross VM 167 397 / 1 710, costs 84 505 / 157 686,
net 82 892 / −155 976; конечный капитал 1 082 892 / 844 024 руб.
Control: gross VM 40 622 / 58 749, costs 24 155 / 48 947,
net 16 467 / 9 801; конечный капитал 1 016 467 / 1 009 801 руб.

Double costs — отдельная симуляция с feedback капитала в целочисленные размеры,
не простое вычитание ещё одной комиссии из тех же позиций. Поэтому отличаются также
gross VM, exposures и число сделок; это не скрывать. Для compensation exposed
asset-sessions 5375 / 4987, filled legs 1233 / 1224. Такой результат не устойчив.

Оба варианта провалили CAGR>=5%, Sharpe>=0.5, MDD<=25%, worst year>=−15% и
meaningful excess>=2 п.п. при обоих costs. У compensation 2018 дал 28.80% / 27.30%,
но 2019 потерял 24.82% / 25.39%; нельзя выбирать только успешный год.
Его преимущество перед контролем при base всего 0.7971 п.п., при double отсутствует.
У real-discount худший 2020: −49.53% / −49.88%, отрицателен даже gross VM.

## Все календарные годы, %

| Год | Real 1× | Real 2× | Compensation 1× | Compensation 2× | Control 1× | Control 2× |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2018 | 6.3468 | 5.1073 | 28.8032 | 27.2984 | −8.3210 | −8.5777 |
| 2019 | 16.1250 | 15.2608 | −24.8239 | −25.3942 | 22.4446 | 22.5246 |
| 2020 | −49.5312 | −49.8816 | 6.3511 | 0.2979 | −25.7311 | −25.2926 |
| 2021 | −2.6343 | −4.1980 | 9.7653 | 9.2637 | 17.2483 | 16.9796 |
| 2022 | −17.4688 | −18.4091 | 4.0741 | 6.4527 | 5.3475 | 5.1703 |
| 2023 | 2.6617 | 3.2955 | −6.0007 | −8.4645 | −2.3063 | −2.8509 |
| 2024 | 3.6451 | 2.6935 | −8.8094 | −14.4499 | −5.0282 | −4.8117 |
| 2025 | −6.4490 | −6.5977 | 7.3876 | −2.7197 | 6.3860 | 6.0648 |

## Покрытие и исполнение

До MOEX prices выполнен отдельный presence/clock-only run: coverage 100%,
1996 ready source dates за 2018–2025, 2246 state dates с warmup, 6738 asset states.
6072 asset decisions / 2024 decision dates на arm; feature-unavailable/stale 0.
17 source-unavailable относится к contract plan, не к Treasury values; это не fills.
Raw CSV за конец 2025 сохранены, states с availability>=2026 не формировались.

Real primary: 5947 nonzero targets / 1894 используемых source dates.
Compensation primary: 5833 / 1858. Control: 6052 / 1926. Каждый ledger имеет
2025 NAV sessions: первоначальная session не добавляет ещё одно решение.

Все 8 arm/cost executions complete, critical/unresolved 0, terminal flat.
Real сохранил по 2 halt/carry observations, no-open cancellations 2 и no-liquidity 2.
Compensation сохранил по 17 halt/carry и no-open cancellations, no-liquidity 2 / 3.
Control: по 17 halt/carry/no-open и 3 no-liquidity. Эти строки не удалены из экономики.
Maximum close gross real 0.9172 / 0.9447, compensation 0.9140 / 0.9877;
maximum participation real 0.4808%, compensation 0.8772%, control 0.6024%.
Execution PASS относится к research proxy ledger; broker-exact/spec-vintage/BBO
доказательства от этого не появляются, исторические original quotes не подтверждены.

## Источники и сохранение

Pre-source rules push `8e1df10`, pre-outcome code/config seal push `81bee94`.
Seal `8be2ac519e78183c51838d5a93d9ea068fe8b902c0dd59678c40b0c48607ce2e`.
Единственный economic batch: 10.739700 s после preflight; это время расчёта,
не общее время разработки/загрузки. Никакого rerun с другими параметрами.

Canonical: `/srv/trading_lab_data/runs/v78_treasury_channels_v1_8be2ac519e78`.
Metrics SHA `2edb4e9c1aea7e391a3ebfeafe160fd4eb19b5b65e39e08ace610633698dc5b8`.
Identity SHA `e4f213fed40497edad78184b7f2a1ddac90c2def15b0b14ce7e0ccfe3f9903ce`.
Предварительная проверка: sibling root с suffix `_feasibility`, файл `feasibility.json`,
SHA `eafd100d076f8291ef9926b06d3d928f0d494803da392e2f4be7f873fd197328`.

Raw root: `/srv/trading_lab_data/source_evidence/v78_treasury_2017_2025_v2`.
Manifest SHA `e34034552bb6d3b3bb9ad9f4179673f939b0bfc807176b0d7a95c5698a88fb2a`.
DGS10: 37183 bytes, SHA `3172654eadbb3f21ae6552f63b8fe9644f0201b262d143761887811e91ecbc32`.
DFII10: 37750 bytes, SHA `fd0f4448f1bcf19cb8858c58e2aed08b433862b04681042f17d769b72af3dd5b`.
Оба по 2347 rows / 98 missing, 2017-01-03…2025-12-31. Пропуски не заменялись нулями;
CSV rates переводились точно в bps, исключая ложные знаки из floating-point вычитания.
Receipt 14:22:15.847977Z / 14:22:16.891329Z. Actual request URLs в manifest;
`source_url` в states — synthetic joint locator пары/date, не новый HTTP request.

Local default-header transport получил 2 timeouts без source files; пустой local V1
directory сохранён. Server V2 использовал прежние identifying V27 FRED headers,
same bounded URLs, 2 HTTP200. Ни successful raw, ни старые config/run не перезаписаны.
Методика/известные задержки: [H.15](https://www.federalreserve.gov/feeds/h15.html).
Date floors/максимальная доступность всех 21 компонентов зафиксированы до outcomes,
но это не полная original-vintage история. Публичные raw не выкладывались в Git.

Local 70 / server 27 synthetic tests PASS, Ruff/diff/BOM PASS. Отдельный audit
восстановил raw CSV→states→targets, проверил 35 child hashes и 8 metric/annual/
count/cost/cash reconciliations, control equality. Simulation reruns 0.
Никакой новый service, collector, fit, paper restart или реальные сделки не запускались.

## Следующее действие

Оба варианта закрыты. Не настраивать знак, lookback, lag, размер или годы; не выдавать
control за найденный alpha. Не усложнять эту ветку моделью/новым engine для спасения
результата. Следующий быстрый конкурс требует иного экономического механизма или
независимой информации и предварительной проверки её дат/покрытия.
