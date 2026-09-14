# V72 — qualitative CBR next-action guidance, Stage1

## Механизм и неизменяемое правило

Проверяем новую текстовую информацию: явные заявления о возможных будущих повышениях
или снижениях ключевой ставки. Предположение: ужесточение давит на оценку акций и
поддерживает рубль, смягчение действует обратно. Это проверяемая экономическая гипотеза,
не установленная реакция рынка. Не V27 rate level, V21 survey или V71 fiscal error.

Primary: short MIX и SI при явном будущем повышении, long обоих при снижении.
Половина номинального капитала на каждый, совокупный target gross1. Контроль использует
только уже принятое решение в заголовке: повышение/снижение/сохранение. Он не учитывает
направление guidance и не может быть отдельно продвинут после просмотра результата.

Exact sentence-level dictionary хранится в sealed `classify()`. Требуются future marker
и действие непосредственно над ключевой ставкой (допустимо «уровня»/«величины» между
ними); произвольные промежуточные слова запрещены, чтобы снижение инфляции не стало
снижением ставки. Обрабатываются explicit negation и уже принятое решение; «не исключает»
не считается отрицанием. Mixed directions/нет явного направления дают flat. Unknown
headline или пустой body маскируют оба arm. Новое flat/invalid сообщение отменяет старое.
Это узкий индикатор следующего действия, не общая оценка тональности; косвенные формулировки
и higher-for-longer могут быть пропущены. Никакого fit, LLM, grid или подбора по доходности.

## Источники и часы

Полная наблюдаемая категория key-rate releases2018–2025 по [каталогу ЦБ](
https://www.cbr.ru/dkp/mp_dec/), источник — Пресс-служба Банка России. В V2 сохранено
68релизов:8/8/8/8/11/9/8/8 по годам, включая внеочередные. 77raw responses, один полный
raw/normalization replay PASS. Минимум2018-02-09, максимум2025-12-19; нет2026articles.
[V1](CBR_POLICY_RELEASES_SOURCE_V1.md) остановился на29-м article; [V2](
CBR_POLICY_RELEASES_SOURCE_V2.md), pre-acquisition push e0c5fad, корректно сохраняет
40date-only midnight footers как неизвестное время. Не заменяет их историческим receipt.
Source manifest SHA83a89218c16785d961632c4a715e8f26d0fda0e0299e39ac98257f2621d75b70,
Parquet SHA463c8018a43b2f77a1cc11b11b3c9110fa1c1e6789ed127ebb60ff26cbecdd72.

Source availability23:59:59Moscow, decision в конце того же дня, execution строго на
следующем фактическом open. Same-date source допустим лишь после своего completed clock;
не сдвигаем дату назад и не вводим лишнюю сессию задержки. Выход при возрасте источника
больше14calendar days, новом flat сообщении, missing plan или terminal flat. Delay между
decision и fill не более7calendar days. Weekend source не backdate-ится в Friday plan.
Оригинальные исторические версии текстов не доказаны; только current-vintage development
assumption, не независимое подтверждение доходности или оригинальных publication clocks.

## Исполнение и быстрый отсев

Тот же byte-pinned V64 recent input catalog, V68 metrics/count helpers и готовый integer
cash/variation-margin ledger. Полный matching obs/spec join строится до общего фильтра
MIX/SI и2018–2025; никаких изменений frozen helper files. Initial1млн, margin buffer2,
participation1%, costs1tick+1×fee и2ticks+2×fee, без дохода свободного капитала.
Daily sizing/roll causal; halts/cancelled/unresolved остаются в отчёте. Исторические
quotes/specs/fees — research proxy, не брокерский тариф или доказанная ликвидность.

Все4executions complete, critical/unresolved0, terminalflat обязательны. Primary в
каждом costs: CAGR>=5%, Sharpe>=0.5, MDD<=25%, не менее5/8 положительных лет,
worst year>=−15%, не менее80closed asset/contract episodes и CAGR выше контроля хотя
бы на2pp. Readable-state coverage>=90% всех релизов; отдельно counts directional/flat.
5% — отсев потенциального компонента, не замена цели20–50%. Никаких выбранных лет,
полярности, horizons, веса по исходу или post-hoc доработки словаря на тех же outcomes.

## Воспроизводимость

`configs/v72_cbr_policy_guidance_v1.json`, отдельный `.sha256` и closure seal включают
код/тесты/документ/V64 helper seal/V68 helper/source V2 seal до market loading.
Выход `/srv/trading_lab_data/runs/v72_cbr_policy_guidance_v1_<seal12>` создаётся один раз.
Сохраняются inputs, извлечённые facts/evidence, targets,4ledgers/orders/positions,metrics,
identity. Audit сверяет source→states→targets,4metrics/counts/cash, все child hashes.
Все восемь лет already-open development, не unseen holdout. Старый paper bootstrap,
сервисные расписания, protected2026 и live admission не меняются.
