# AlgoPack paper alignment V1 — реализация до economic seal

2026-09-07. [Разрешение пользователя](ALGOPACK_PAPER_AUTHORIZATION_20260907.md) получено.
Новый pure core `src/market_lab/futures/algopack_paper_alignment_v1.py` и38 synthetic tests.
Нет file/network IO, fit, модели, orders, PnL или CLI обхода admission. Это компонент
будущего paired price-only/price+flow эксперимента, не законченный paper runner.
Только синтетические2025 значения в тестах; реальные prices/labels не загружались.

## Новое свидетельство о времени

Официальный SDK MOEX, commit `5a232b6b07e4ac224468909e6c43038b3b148eef`,
[`moexalgo/beta/resample.py`, lines19–33](https://github.com/moexalgo/moexalgo/blob/5a232b6b07e4ac224468909e6c43038b3b148eef/moexalgo/beta/resample.py#L19):
normalizer соединяет tradedate/tradetime в конец интервала и отнимает5мин для начала.
Файл19362bytes, SHA `e668c2a402f784491898ab67e86805ac3bb3ee4e7abd997aecbdf12db709b242`.
Просмотрено code-only, не notebook/API response examples. SDK не исполнялся/не установлен.

Это первичный пример интерпретации bucket, не гарантия отсутствия revisions и не
доказательство всех vendor trade-date conventions. SDK создаёт naive datetime.
Moscow/UTC+3 используется как явно заявленное предположение paper adapter, опираясь на
[официальное расписание срочного рынка](https://www.moex.com/ru/derivatives/unified-trading-session).
Страница также сообщает переход на ЕТС23марта2026 и отнесение вечерних торгов к текущему
дню. Нельзя переносить это правило на историю2020–2025. Исследование расписания не
читает защищённые рыночные outcomes2026. У страницы есть различающиеся часы утренней
сессии в схеме и FAQ; полное расписание из неё не синтезируется.

Правило core ограничено weekday/same-local-date, exact5m/10m keys; выходные и неоднозначное
сопоставление остаются unresolved. Это не полный official session calendar. Для future
runner нужны отдельные session/expiry guards и проверка выбранной intraday области;
не объявлять TIME/SCHEMA полностью доказанным только по этим38 тестам.

## Точные функции

`select_flow` принимает только flow versions, asset/SECID, information_end и decision_at.
На один актив нужны TS и OB за два bucket с концами E−5мин и E; E кратен10мин.
Каждый input несёт фактический available_at и version SHA. Выбирается последняя версия,
полученная не позже D; tied conflicting versions отвергаются. Receipt до конца source
bucket даёт LABEL_RECEIPT_CONFLICT. Данные старше10мин не переносятся на новое решение.
SYSTIME не используется как разрешение backdate. ASSETS = BR/MIX/RI/SI.

`select_training_flow` — отдельный явно названный current-vintage training path.
Source information_end только2020–2025, обе UTC/vendor-date границы проверяются.
Actual available_at должен быть <=training_cutoff, но не подменяется historical clock.
Успех помечается READY_ARCHIVE_ASSUMPTION, а не online READY. Это не backtest accessor.
Никакие flags parent history не изменяются. Labels также должны быть <=2025 — отдельный
обязательный guard будущего manifest-bound runner, не ответственность flow selector.

Одинаковая projected numeric schema для training и inference:

- TS: trades_b, trades_s, vol_b, vol_s; сумма двух5m buckets.
- OB: vol_b_l1, vol_s_l1, vol_b_l10, vol_s_l10; среднее двух5m summaries.
- Features: четыре normalized imbalances `(buy−sell)/(buy+sell)` для trades, flow volume,
  L1 depth, L10 depth; пятый — `asinh((sum_vol_b−sum_vol_s)/(mean_L10_b+mean_L10_s))`.

Это vendor buy/sell categories, не доказанная агрессорная классификация. OB average —
явное агрегирование двух summaries, не восстановленный instantaneous order book.
Missing field, undefined zero denominator и numeric overflow имеют разные статусы.
Known one-sided activity допустима. Spreads, prices и future targets не входят в selector.
Нет подстановки null в0, отбора по следующей сделке или inferred executable capacity.

`mature_label` отдельно формирует60мин open-to-open target. Entry — первая10m граница
СТРОГО позже decision; нужны семь последовательных observed opens одного SECID.
Exit open относится к седьмому бару; его источник допускается только после завершения
этого10m бара и фактического получения. Evaluation до этого — NOT_MATURE.
Missing/roll/duplicate/invalid open не исправляются. Label — не доказательство fill.
Цена доступна только label-side функции, не inference eligibility.

## Проверка входного размещения на сервере

Предположение о top-level `/srv/trading_lab_data/data/processed/futures_v7_10m/` оказалось
неверным: файл там отсутствует. Read-only поиск нашёл ранее скопированный V62 bundle:
`/srv/trading_lab_data/data/v62-legacy-source-v1/data/processed/futures_v7_10m/`.
Его top manifest1785bytes SHA `f620ff77a5368c93d6415fc1b5785f9eaaba6cef873a4425fcd98e9b69f3ba01`
совпадает с frozen V32 reference. Проверены bytes/SHA всех четырёх asset manifests:
Si/RTS/BR/MIX; requested_end=2025-12-31, protected_from=2026-01-01.
Это только manifest identity, не завершённая transitive/raw/Parquet admission.
OHLCV файлы не открывались. Новый loader должен использовать этот exact external root,
а не менять пути или identities старых V32/V62 runs. Новая выгрузка истории не нужна
при успешной последующей transitive verification.

При последней проверке server FO timer: active/waiting, LastTrigger16:43UTC, next16:53UTC;
service terminal success/exit0. Это operational property check, не новый quality run.
Существующие timers и credentials не изменены. Новых manual captures не было.

## Что осталось до обучения

1. Новый manifest-bound loader с полной transitive closure, protected boundaries и
   row-level active-map/session matching; не использовать V32 learning eligibility.
2. Price features, joint four-asset matrix и paired Ridge, train-only preprocessing;
   заранее зафиксировать числа модели, train ranges, expected coverage и evaluation rules.
3. Полный executable config/code/input seal до реальных labels и fit; server-only run.
4. Immutable model/scaler publication, будущая F, отдельный price/execution source после F.
   Existing price streams2026 не открывать для разработки. Net ledger и costs нужны до
   экономической оценки; прогнозы и38 synthetic tests не доказывают прибыль.

Local tests38/38, Ruff PASS; encoding suite проверяется с остальными handoff changes.
Core ещё не economic-sealed; следующие правки до первого source/model run допустимы.
