# V90 — торговое правило реализовано, пока synthetic-only

2026-09-15. Продолжение [предэкспирационной гипотезы](OPTION_PINNING_RESEARCH_NOTE_20260915.md)
параллельно V89/AlgoPack downloads. Предыдущий goal turn — PROGRESS: завершён census,
запущено конечное metadata acquisition. Этот шаг реализует само правило и его
подключение к готовому daily ledger, не ещё один сборщик или ожидание таймера.

## Что готово

`src/market_lab/futures/option_strike_convergence.py` — чистые функции без I/O,
HTTP, model fit, CLI, нового ledger или автоматического economic запуска.
Config `configs/v90_option_strike_convergence_design_v1.json` имеет
`economic_runner_enabled=false`; это design snapshot, не полный input/economic seal.

На конец завершённой сессии, строго по более раннему доступному weekly release:

1. Находится ближайшая точно сопоставленная экспирация того же фьючерса в пределах
   семи календарных дней. При достижении даты экспирации к следующему open — flat,
   без замены более дальним сроком. Не воссоздавать фьючерс из одного кода года.
2. В одной совместимой series/unit/lot/exercise-style находятся два ближайших
   reported страйка ниже/выше фактического decision close того же contract_id.
   Основной сигнал направлен к большему call+put OI этой пары; контроль — к ближайшему
   страйку без сравнения OI. Дальний страйк с огромным OI не перехватывает выбор.
3. Равенство OI/расстояния даёт flat для соответствующего arm; цена ровно на observed
   страйке — оба flat. Не менять tie policy по будущему результату.
4. Цель каждого актива ±0.225 капитала, joint target gross≤0.9, без cash interest;
   actual integer quantities и costs считает прежний ledger с gross admission cap1.
   Последняя declared effective date каждого актива принудительно flat. Это не
   непрерывная гарантия gross≤1 после неблагоприятного gap или просадки капитала.

Новые плохие releases замещают старые хорошие. Опоздавший более старый source date
не вытесняет уже доступный новый. TTL source10days/fill-delay7days; calendar не
обрезается по отсутствию будущих цен/сделок. Отдельный exact decision-close join,
без open/exit/labels в feature schema и без подстановки старого контракта при roll.

OI NaN/nonfinite/negative маскируется, unusable counts сохранены; NULL не ноль.
Known zero сохраняется как reported, но нулевая пара не порождает сигнал.
Неразрешённая metadata у usable OI маскирует весь asset release, а не только неудобную
строку. Явно классифицированные nonfuture products исключены с counts; SI currency
options не смешиваются с margined future options. Duplicate strike/side, несовместимые
series/units/lots, конфликт lifecycle/underlying expiry не превращаются в сигнал.

## Проверка

42 новых synthetic tests PASS. Вместе с V89/V88/V68/V64 —95 локальных PASS, Ruff clean.
На gpu-mlserver после проверки SHA всех трёх новых config/code/test files —42/42 PASS
за2.64s. Это synthetic-only запуск, без чтения настоящих OI/market inputs.
Проверены основной/контрольный знак, OI ablation, ties/zero/missing, поздняя публикация,
новая плохая публикация, nearest-expiry без fallback, прямой exact-contract join,
2026/duplicate/label/schema guards и неизменность прошлых решений при изменении
будущих source/price values. Empty source сохраняет весь decision calendar с flat.

Integration test действительно вызывает существующий integer-contract ledger:
2arms×2costs, terminal flat, no critical/unresolved, сделки ненулевые. Искусственная
цена постоянна; результат отрицательный только из-за издержек, при double хуже.
Это проверка арифметики/совместимости, **не** отрицательный или положительный
исторический результат стратегии. Метрики/round trips берутся из V68 reporting,
где подсчёт идёт отдельно по активам, а не склеиванием position rows разных активов.

Идентичность snapshot до каких-либо новых реальных numeric inputs:

- Config SHA `25b5d6266b9c968bb7adacf4261b5af0333d379cdb7f7b4853aeaa7e8e6f3429`.
- Adapter SHA `31788d6a8c00f6bf1bd7e205c0cc1f7adb7fcb449bc894588a467bd79140cf74`.
- Tests SHA `4504c94eba5a87004da39f1d8b98bf20cca7f145abcace81bf6283a79a1e6969`.

## Что ещё необходимо до исторического результата

V89 всё ещё должен закончить immutable source manifest. После него один metadata
mapping/coverage pass по полному source, не по первым удобным BR records. Публичные
описания должны доказать explicit expiry/underlying/quote-unit binding, в том числе
неоднозначный SI. Флаги `metadata_ready` и `quote_units_compatible` в чистом adapter
**не доказывают** это сами: их нельзя заполнить True без source-bound mapper.

До admission также сверить полный source calendar261dates×4assets=1044groups по
sealed manifest/config. Нельзя считать отсутствующий/пустой scheduled release старым
сигналом только потому, что для него нет строк. Данный adapter покрывает сохранённые
releases, включая all-NULL; если фактически есть пустые/пропущенные группы, нужна
явная source-calendar обработка до economic seal, не молчаливый fallback.

Далее отдельный полный economic config/code/input SHA с gates, один server run и
общий отчёт по обоим arms/costs/годам/coverage/trades. Готовый daily convergence
adapter не измеряет последние минуты экспирации и не даёт option execution admission.
OI magnitudes и market values для новой гипотезы не читались, реальных targets/PnL,
fit/обучения/live нет. Economic screens остаются25, Stage2=0; цель20–50% не подтверждена.
