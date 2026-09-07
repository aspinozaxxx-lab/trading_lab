# AlgoPack future-paper: разрешение пользователя 2026-09-07

Пользователь ответил «конечно разрешаю, делай что надо!» на конкретный вопрос:
обучение на исправленном архиве AlgoPack2020–2025 и бумажная проверка только на новом
будущем периоде после фиксации протокола и моделей, без реальных сделок и без открытия
прежнего защищённого участка2026. Это снимает AUTHORIZATION gate из
[admission review](ALGOPACK_TRAIN_TODAY_ADMISSION_REVIEW_V1.md), не остальные gates.

Разрешён один отдельный prospective-only эксперимент с явной гипотезой переноса
current-vintage training в online. Исторический AlgoPack CAGR не вычисляется и не
объявляется causal backtest; old original-version/source/model flags не изменяются.
Training features допускаются как final-vintage учебный материал, полученный до fit;
training labels должны иметь market timestamps <=2025 и быть получены до fit.

Для новой ветки будущая граница F определяется после byte seal кода/config и публикации
моделей/scaler. Она не может быть назначена задним числом. Цены/результаты в интервале
[2026-01-01,F) по-прежнему запрещены; текущие2026 flow-only snapshots не являются
разрешением читать price/outcome fields. Новый paper price source требует отдельного
seal и исполнения временного ограничения до сетевого запроса/чтения.

Остальные исследовательские правила сохраняются: predictions до target interval,
future labels отдельно от inference eligibility, exact contract/gaps, execution/costs,
полный реестр отрицательных результатов. Short paper success не доказывает20% годовых.
Никаких broker/live orders, новых покупок, локальных collectors или данных/моделей в Git.
Работа и расчёты на gpu-mlserver; код и synthetic tests допускаются локально.

Следующий шаг: time/schema mapping и новый изолированный feature/label adapter,
затем executable protocol/input closure и server training. Повторного общего согласия
не спрашивать. Review V1 сохраняет исторический статус до этого ответа.
