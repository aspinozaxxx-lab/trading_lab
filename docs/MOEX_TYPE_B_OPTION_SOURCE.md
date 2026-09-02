# Исторический MOEX Type B для опционов

## Назначение

Ветка восстанавливает причинный лучший BID/OFFER по официальному бесплатному примеру
MOEX `OrderLog20241001_B.7z`. Это один торговый день, включающий вечернюю сессию
`2024-09-30` и основную сессию `2024-10-01`. Он пригоден для проверки parser, BBO state,
свежести и displayed depth, но не для оценки ожидаемой доходности, CAGR или стабильности.

Официальные страницы:

- описание Type B: <https://www.moex.com/a1681>;
- услуга исторических данных: <https://www.moex.com/a2863>;
- бесплатный каталог примеров:
  <http://ftp.moex.com/pub/info/data/Derivatives%20Market/>.

В бесплатном каталоге на `2026-09-03` присутствует только один Type B архив. Полная
история является отдельной платной услугой; покупать её без разрешения пользователя
нельзя.

## Canonical source V3

Каталог на `gpu-mlserver`:
`/srv/trading_lab_data/data/processed/options/moex-type-b-derivatives-sample-2024-10-01-v3`.

- config SHA `c2c659f39ff6cfea9d8bdffca28ac15e968c14c3204f6173516f7dd949f4662a`;
- raw archive SHA `afccc1602d81c15dd064eadd44dd91a3aff53bcb3213fe96840f0b8188601e30`;
- manifest/audit SHA `8317b756.../9e9ad48...`, audit `10/10`;
- `6 561 395` option tick rows: `5 569 089` quote updates, `975 553` quote clears и
  `16 753` trades;
- отдельный deals файл содержит те же `16 753` unique trade IDs.

V1 неверно считал `source_trade_date` календарной границей. V2 исправил вечернюю сессию,
но до output fail-closed остановился на официальном `PRICE,VOLUME = null`; V3 трактует
только парный null без trade ID как явную очистку соответствующей стороны BBO.

## Strict-prior BBO V2

Каталог:
`/srv/trading_lab_data/data/processed/options/moex-type-b-core4-bbo-2024-10-01-v2`.

- config SHA `fdf8b6555010dadbe87e1194bd87ad476b8a37b7df510f06dbc685322ab1ffd2`;
- manifest/audit SHA `e3a7934b.../7e2656d8...`, audit `12/12`;
- `1 671 909` mapped core-four events, `957 259` final BBO states after exact timestamp;
- `13 670` trade contexts, из них `13 607` имеют strictly-prior two-sided BBO;
- prior locked/crossed contexts: `0`.

V1 ошибочно разрешал quote row с тем же timestamp, что сделка. V2 сначала фиксирует для
всех trades состояние конца предыдущего distinct timestamp и только затем применяет
updates/clears текущего блока. V1 остаётся immutable forensic artifact и не используется.

## Defined-risk vertical admission

Source-only V1 сопоставляет только prior identity `2024-09-27`, одинаковый underlying,
тип и encoded expiry, соседние страйки и debit call/put vertical. Grid заранее задан:
99 десятиминутных точек. Вход использует long OFFER и short BID; debit обязан быть между
нулём и шириной страйков. Naked short и synthetic midpoint запрещены.

| Максимальный возраст всех четырёх сторон | Возможности | Grid timestamps |
|---:|---:|---:|
| 1 сек | 9 | 4 |
| 5 сек | 72 | 19 |
| 15 сек | 403 | 57 |
| 60 сек | 1 465 | 74 |

Config SHA `f6c95bc1...`; manifest/audit SHA `3455302a.../6e062f04...`; audit `12/12`.

## Displayed capacity и crossing friction

Следующий protocol был запечатан commit `82af580` до чтения depth/friction values:
config SHA `cd32510e506b038546ced9a499f7b696d143d881529c2bb6e88bbde5ee0df26c`.
Implementation commit `771db67`; canonical output:
`/srv/trading_lab_data/data/processed/options/moex-type-b-vertical-execution-diagnostics-2024-10-01-v1`.
Manifest/audit SHA `5ed6ef18.../86a28f55...`; replay `11/11`.

Основной вывод: displayed depth существует, но немедленное пересечение четырёх сторон
стакана дорого. Для 15-секундной свежести медиана entry/exit capacity равна 3 контракта,
а медианный four-side crossing cost — `16,6%` ширины страйков. Только `44/403` случаев
имели friction `<=5%` ширины; `129/403` имели displayed capacity обеих сторон хотя бы
5 контрактов, `35/403` — хотя бы 10. При 5 секундах соответствующие значения:
медианная capacity 5, median friction `16,8%`, friction `<=5%` у `11/72`.

Это не разрешает выбирать порог `5%`, freshness или контракт по этому дню. Результат
лишь показывает, что market-order vertical требует очень сильного edge, а limit-order
модель потребует отдельных queue/latency данных. Экономический тест ждёт независимые
дни; PnL и live trading запрещены.
