# AlgoPack: обучение сегодня, проверка только вперёд — admission review V1

Дата: 2026-09-07. Статус: **DESIGN_REVIEW_COMPLETE / NOT_ADMITTED**.
Это разбор допустимости, не sealed economic protocol и не запущенный эксперимент.
Новые prices, labels, targets и PnL не читались; fit, predictions и trades не выполнялись.
Цель 20–50% годовых остаётся неподтверждённой. Документ не изменяет frozen source flags.

## Решение

Схема «архив получен сегодня → обучение сегодня → новые прогнозы» логически отличается
от исполнения сделок в прошлом по сегодняшней версии архива. Но одного этого различия
недостаточно для допуска по действующим правилам репозитория. Есть два отдельных запрета:
current-vintage training без original availability и чтение market outcomes начиная
с 2026-01-01. Ни покупка подписки, ни автоматическое продолжение goal их не отменяют.

Следующий шаг — явный выбор пользователя о новом ограниченном paper-only эксперименте:
разрешить архив2020–2025 как предположительно переносимый учебный материал и отдельный
будущий период цен/результатов, начинающийся только после фиксации нового протокола
и моделей. Это не разрешение ретроспективного CAGR по AlgoPack и не открытие старого2026.
Согласия пока нет. Не запускать обучение, outcome loader или новый predictor timer.

## Почему текущий архив не превращается в causal backtest

Проверенные исходные свидетельства:

- [Publication audit](ALGOPACK_FO_PUBLICATION_METADATA_V1.md): 1 802 758 из 2 067 949
  текущих записей имеют publication date позже vendor trading date; для1056 строк
  публикация уже2026. Это не доказательство отсутствия исходных биржевых событий раньше.
- [Ответ MOEX](ALGOPACK_VENDOR_REPLY_20260907.md): личное использование подтверждено,
  SYSTIME назван временем публикации; поведение timestamp при исправлениях не объяснено.
- [Witnessed source](ALGOPACK_FO_WITNESSED_V1.md): сервер сохраняет фактическое получение
  каждой версии; original vintage, bucket completion и атомарность vendor batch не доказаны.

Две временные проверки нельзя подменять друг другом:

| Проверка | Необходимое условие | Чего оно не доказывает |
| --- | --- | --- |
| Обучение в момент T | Все использованные версии X и завершённые y получены и проверены до T | Что final-vintage X существовал до исторического y |
| Новый прогноз в момент D | Модель опубликована до D; все используемые версии X имеют available_at <= D | Что source bucket завершён и историческое распределение переносится в online |
| Оценка прогноза | Неизменяемый прогноз записан до начала target interval; outcome присоединён отдельно после окончания | Исполнимость сделки и доходность после затрат |

Исправленный исторический X может содержать информацию, связанную с последующим y.
Даже если всё это известно в T, полученная зависимость может не работать на первых
полученных версиях новых данных. Поэтому обучение на архиве здесь — явно оговорённая
гипотеза переноса, а не доказательство отсутствия leakage или исторической доходности.
Нельзя переставить available_at на vendor label time, подобрать искусственный lag по
публикационным bins или назвать исторические2021–2025 folds независимым подтверждением.

Общее правило разделения train/test и обучения preprocessing только на train описано в
[официальной документации scikit-learn](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).
Вывод о допустимости именно AlgoPack — наш разбор приведённых source свидетельств,
а не утверждение scikit-learn о качестве этого поставщика.

## Один кандидат для нового протокола — ещё не seal

Механизм: дисбаланс потока сделок относительно встречной глубины может содержать
дополнительную информацию о последующем краткосрочном движении; совместное состояние
BR/MIX/RI/SI может отличать общий рыночный импульс от локального. Эффект не установлен.

Сохранить один дешёвый paired comparison: joint price-only baseline против того же
baseline с joint TradeStats/OBStats, фиксированная Ridge без перебора параметров.
Обе модели должны использовать один календарь решений, одинаковый target, costs и
общий execution adapter. Отдельно показывать полный календарь и пересечение покрытия,
чтобы отсутствие flow не улучшало результат скрытым удалением неудачных решений.
Это тест добавочной информации, не доказательство пользы joint architecture отдельно.

Кандидатный горизонт —60мин, частота решений —10мин. Это сохраняет continuous timing,
но частые решения не объявляются независимыми наблюдениями. Параметры модели, точные
формулы признаков, часы, eligibility, training ranges и оценочный горизонт должны быть
зафиксированы в новом executable protocol до первого нового label load; здесь они
не выданы за готовую конфигурацию. Scaler обучать только на training subset.

Не включать spreads в качестве отрицательной стоимости исполнения. Не считать buy/sell
поля доказанной агрессорной классификацией без документации. OHLC label не означает fill.

## Оставшиеся gates и порядок их снятия

1. **AUTHORIZATION — отсутствует.** Нужен явный ответ на описанное ограниченное
   current-vintage training / future-only paper предложение. Старый вопрос о hypothetical
   historical screen не получил ответа и не даёт этого разрешения. При отказе от archive
   assumption возможен отдельный witnessed-only training после накопления выборки;
   он всё равно требует допуска новых будущих outcomes и отдельного протокола.
2. **TIME/SCHEMA — не доказан.** Установить timezone, mapping vendor date/time к
   completed5m bucket и10m decision, weekend labels и revision policy. Receipt clock
   обязателен, но не заменяет completion clock. Ни фиксированное ожидание, ни стабильные
   три снимка не доказывают завершённость. Пока mapping не обоснован — sleep, не fit/run.
   Переход на receipt-window target был бы другой гипотезой; его не подставлять молча.
3. **INPUT/IMPLEMENTATION SEAL — отсутствует.** Новый config должен pin-ить точные
   manifests, байты кода и разрешённые columns; training labels только из manifest-bound
   <=2025 bundle. Нет новых downloads истории. Source date admission=false разрешать
   только через явную row-level политику exact keys/session; не менять parent flag.
4. **INFERENCE/EXECUTION — ещё не реализован.** Раздельные tables: features/eligibility,
   predictions, matured labels, orders/ledger. Eligibility не читает будущий контракт,
   target presence, path completeness или exit volume. Все missing/gap/roll cases
   остаются видимыми. Same exact contract и successor нужны для label validity, но
   становятся известны evaluator позже и не могут удалить ранее записанный прогноз.
5. **FUTURE WINDOW — отсутствует.** После допуска сначала sealed code/config, затем
   training только на разрешённой истории, immutable model/scaler hashes и публикация.
   Начало evaluation F — заранее определённая будущая UTC boundary строго после всех
   этих seals. Не начинать F задним числом; до F цены/результаты2026 остаются закрытыми.
   Иной collection scope requires отдельный source seal; существующие timers не ослаблять.
6. **EVIDENCE — ещё нет.** До outcomes зафиксировать calendar duration, minimum coverage,
   expected decisions, допустимые gaps, paired forecast metric, net execution и1x/2x
   costs, stability gates и stop rules. Эти численные параметры пока не заданы: review
   не является полным протоколом. Прогнозная точность не заменяет прибыль. CAGR/Sharpe/MDD
   считать только при допущенном ledger; missing economics обозначать N/A, не нулём.
   Короткий paper период не доказывает предсказуемые20% годовых.

Source-only collection остаётся на gpu-mlserver. Обучение и оценка также только там;
данные/модели вне Git. Никаких broker orders, live trading или новых расходов.

## Проверка пригодности существующего кода

Просмотрен код, не рыночные значения:

- `src/market_lab/futures/curve_regime_intraday.py::_label_structure` строит
  same-contract/exact successor labels. Это только label-side reference.
- Там же `build_learning_frame` включает `exact_label_path` и наличие всех future
  targets в `eligible`. Его результат нельзя использовать как календарь online inference.
- `src/market_lab/futures_v32_curve_regime_intraday.py::_load_causal_active_plan`
  использует effective_date и strictly-prior decision_date, но предназначен для <=2025.
  `_load_active_bars` с metadata_only=False читает OHLCV. В этом review он не вызывался.
- Current-contract metadata selection witnessed V1 нельзя заменить картой2025;
  nearest-expiry selection не является доказательством достаточной ликвидности.

Frozen modules не исправлялись. Полный новый framework, config, runner или synthetic
«успешная модель» не создавались: пока нет admission, они не устраняют оставшийся запрет.

## Handoff

Review завершён. До ответа пользователя следующий допустимый шаг — объяснить выбор,
а не повторять publication/quality audits, запускать очередное обучение или открывать2026.
Если разрешение получено, начать с TIME/SCHEMA и узкого executable protocol; оно само по
себе не доказывает source semantics и не заменяет остальные gates. Если условие осталось
тем же, учитывать повтор как тот же blocker, а не переименовывать его в новый прогресс.
Global goal не достигнут; эта запись сама по себе не означает, что выполнен трёхходовый
blocked audit. Решение по goal принимать по фактической последовательности turns.
