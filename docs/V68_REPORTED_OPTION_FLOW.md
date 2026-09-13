# V68 — объём торгов опционами как самостоятельный сигнал

2026-09-13: пользователь явно возобновил исследования после сохранённой паузы.
Уровень 1; новая информация — reported option VOLUME, не новая версия OI tail veto V39.
Одна гипотеза, основной и контрольный варианты, два уровня затрат, существующий
integer-contract ledger. Ни новое обучение, ни новый сборщик, ни paper не нужны.

## Механизм и ограничения

Изменение относительной активности call/put против накопленного открытого интереса
может отражать новую направленную информацию. Проверяем sign(call volume share minus
call OI share); контроль — sign(call OI share minus 0.5), без нового признака объёма.
Мотивация — [исследование информации в объёме опционов](https://www.nber.org/papers/w10925),
а не доказанный эффект на MOEX. Наши данные не разделяют покупки/продажи, opening/closing
или позиции дилеров. Направление цены из объёма — проверяемое предположение.

Первоначальная идея expiry pinning отклонена на стадии доступности: existing weekly
source прямо не доказывает exact expiry day. Её цены/PnL не вычислялись; не подменять
экспирацию догадкой из SECID. V68 — другая гипотеза, без выбора страйков/сроков/бумаг.

До нового economic seal прочитаны только source manifest/code и counts-only quality
по volume/OI без цен: 1 327 744 rows, missing volume 1 236 590, missing OI 1 116 720,
полностью заполненных asset-date groups — 0/1044. NULL не означает ноль. Поэтому
признаки по определению относятся к **двум отдельно наблюдаемым подмножествам**:
сумма только reported nonmissing values, min_count=1, с сохранением обоих denominators
и missing counts. Это не восстановленные полные объёмы рынка. При отсутствии стороны
или неположительном total состояние unavailable и позиция flat; новая плохая публикация
не заменяется старой хорошей. Даже положительный результат потребует проверки bias
неполной отчётности, а не немедленного усиления/демо.

## Фиксированные правила

- Exact source V3: 261 source dates / 1044 asset dates, 2021–2025. Все strikes/maturities,
  BR/MIX/RI/SI, одинаковые предельные веса 0.25; joint gross <=1, без процентов на cash.
- Availability: next calendar day 00:00 Moscow как current-vintage proxy, source date
  строго раньше decision session. Решение после завершённой factual session;
  исполнение на следующем factual open, без same-day option state.
- Последнее опубликованное состояние действует до следующего; maximum source age на
  дату исполнения 10 calendar days, maximum decision/fill delay 7 days. Неизвестное или
  stale состояние маскируется. Терминальная позиция flat, закрытие по старому ledger.
- 1 млн рублей, integer contracts, participation <=1%, margin buffer 2. Базовые затраты:
  1 tick и 1× fee; удвоенные: 2 ticks и 2× fee. Это proxy, не broker tariff или BBO.
- 2021–2025 уже открытая development history; никакого независимого holdout. Старый2026
  не читается. Варианты не подбираются после исхода, основной и контрольный имеют общую
  source availability mask. Нулевые trades, critical/unresolved сохраняются.

Переход на уровень 2: полное исполнение всех 4 arm/cost сценариев, terminal flat,
ready source states >=80%; основной вариант при обоих costs: >=50 round trips,
CAGR>=5%, Sharpe>=0.5, MDD<=25%, >=3 положительных года из пяти, худший год >=−15%,
CAGR выше контроля. 5% — предварительный фильтр возможного компонента, не подмена
цели 20–50%; отдельно показывать historical20/50 и всегда goal_verified=false.

Config: `configs/v68_reported_option_flow_v1.json`; собственный code/config/test/doc
seal плюс транзитивный V64 input/ledger seal. Только после synthetic tests и push —
один server run в новом canonical root. Запреты: менять знак/окно/набор/missing policy,
продвигать контроль по результату, повторять canonical или автоматически включать
старый AlgoPack bootstrap. Результат записать отдельно, этот протокол не переписывать.
