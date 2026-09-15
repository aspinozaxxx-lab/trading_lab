# V92 — полный запускатель V90, пока без исторического прогона

2026-09-15. [V90 правило](V90_OPTION_STRIKE_CONVERGENCE_ADAPTER.md) и
[V91 exact binding](V91_OPTION_CONTRACT_MAPPING_RESULT.md) объединены с прежним
daily integer-contract ledger. Новый collector, ledger, модель и parameter search
не создаются. Этот шаг завершает код двух последовательных стадий, а не выдаёт
подготовку за новый результат доходности.

## Фиксированная экономика

Без изменений к V90: четыре актива, ±0.225 капитала на актив, target gross≤0.9,
gross admission cap1, margin buffer2, participation1%, капитал1млн RUB, cash interest0.
Два соседних reported страйка вокруг exact decision close того же фьючерса; primary
к большему call+put OI, control к ближайшему страйку без OI magnitude comparison.
Ближайшая mapped expiry в7calendar days, источник строго раньше decision date,
next factual open, TTL10days/fill-delay7days, tie/expiry/terminal flat как в V90.
Control — ablation, не запасной вариант для promotion после просмотра результата.

Критерии до каких-либо новых OI/price values зафиксированы в
`configs/v92_option_convergence_screen_v1.json`:

| Gate | Необходимый результат |
| --- | --- |
| Полнота release mapping | ≥80% **всех1044** scheduled asset releases |
| Сделки primary | ≥50 closed episodes при каждом costs scenario |
| CAGR / Sharpe / MDD | ≥5% / ≥0.5 / ≤25% при обоих costs |
| Годы | Все2021–2025, ≥3 positive, worst year≥−15% |
| Контроль | Primary CAGR строго выше control при обоих costs |
| Исполнение | Оба arms × оба costs, critical/unresolved0, terminal flat |

Costs: base1tick/fee1, double2ticks/fee2. Gate5% отбирает возможный компонент для
Stage2; он **не заменяет цель пользователя20–50%**. Даже synthetic metrics60% дают
только `STAGE2_CANDIDATE`, `goal_verified=false`. Контроль не продвигается отдельно.
При плохом mapping coverage — `INCOMPLETE_SOURCE_NO_PROMOTION`; critical execution
в любом сценарии имеет приоритет и даёт `INVALID_EXECUTION_NO_PROMOTION`.

## Стадия1: полный source-bound mapping, без economic values

Модуль `option_convergence_inputs` принимает только terminal V89 manifest с точным
SHA, всеми40820 описаниями из sealed census108104 SECIDs. RUNNING, частичный индекс,
лишние/потерянные identities, hash/path/record conflicts отклоняются. Every requested
description проверяется по собственным raw bytes и V91 mapper. HTTP errors/missing
сохраняются как gaps; 67284 all-NULL SECIDs остаются отдельными строками inventory.
Нет selection по величине OI, ближайшим удобным карточкам или будущим сделкам.

Календарь строится из exact sealed request log weekly source, а не из строк,
переживших join. Manifest содержит1044 jobs, request log13802pages, SHA
`cc160ae4b1263df3946b4d33c916a370739b5c490c2f5fe77e465600e1fc6521`.
Проверяются261dates×4assets, first2021-01-08/last2025-12-30, uniqueness, исходные
date/ID/side/availability columns и counts. Source-preflight читает только даты/
schema/hashes. Новый V92 проход по настоящему request log ещё **не выполнялся**.

Выходной leaf: `/srv/trading_lab_data/source_evidence/v92_option_convergence_mapping_v1`.
Нужен новый пустой каталог с UID999/GID989, подготовленный root на server.
Программа создаёт exclusive `started.json`; partial/canonical root не перезапускать.
Далее пишет mapping Parquet, release_calendar Parquet, mapping_quality и final manifest.
Metadata STRIKE/LOTSIZE — договорные поля; openposition/price/targets/PnL не читаются.

## Стадия2: отдельный economic admission, затем ровно один screen

Автоматического перехода к чтению OI/цен нет. Сначала должен быть отдельно создан,
byte-sealed и pushed файл `configs/v92_option_convergence_economic_admission_v1.json`:

```json
{
  "protocol_id": "v92_option_convergence_screen_v1",
  "code_seal_sha256": "<current V92 code seal>",
  "description_manifest_sha256": "<closed V89 manifest>",
  "mapping_manifest_sha256": "<complete V92 mapping manifest>",
  "allow_economic_read": true
}
```

Это техническая фиксация разрешённого historical research, не дополнительное
разрешение на live/demo, другой AlgoPack scope или2026. Admission пока **отсутствует**.
Его отсутствие/неверный SHA/неполный mapping блокируют execution до любых numeric reads.
Manifest, четыре metadata artifacts, их physical schemas/rows и общий источник должны
совпадать. Затем V64 preflight допускает только recent2018–2025 source artifacts;
active decisions/economics ограничены2021–2025. Никакого нового доступа к2026 outcomes.

Экономический output leaf:
`/srv/trading_lab_data/runs/v92_option_convergence_screen_v1_<admission-sha-first12>`.
Его тоже заранее подготовить пустым под UID999/GID989. Два arms×два costs вызывают
тот же `run_futures_portfolio_ledger`; counts/summarize/основные gates переиспользуют
V68 reporting с отдельным подсчётом asset episodes. Нарушения и flat periods не обрезаются.
Сохраняются signal_state, release_quality, targets, четыре ledger/orders/positions,
полные annual metrics/coverage/counts, assessment и manifest всех artifacts.

Server CLI, только после соответствующих preconditions:

```text
/opt/trading_lab/.venv/bin/python -m market_lab.futures.option_convergence_screen --seal-sha <V92> --phase map --source-sha <closed-V89>
/opt/trading_lab/.venv/bin/python -m market_lab.futures.option_convergence_screen --seal-sha <V92> --phase run --admission-sha <economic-admission>
```

Запуски только на gpu-mlserver/UID999; отдельные finite one-shot units без credential
EnvironmentFile, Restart=no. Не создавать Windows tasks и не менять живые archives.
Не запускать команды на placeholders или partial manifests.

## Пропуски и покрытие

Many-to-one join не теряет source identities. Source side, противоречащий точному
описанию, понижает readiness, а не меняет описанный call/put в удобную сторону.
Пустой scheduled release представлен внутренним marker с **NULL OI**, без выдуманного
наблюдения/контракта/цены. Маркер замещает старый release в неизменённом V90 adapter;
original_source_rows/original_release_rows и marker counts показываются раздельно.
Empty latest release не позволяет продолжать старый good signal. Missing не ноль.

Release mapping ready означает: есть хотя бы один finite nonnegative reported OI
с lifecycle-valid futures mapping и ни одного usable OI с unresolved metadata.
Делитель — все1044 releases, не subset с хорошими ценами/близкой экспирацией.
Готовность trading decision и фактические сделки считаются отдельно; mapping ready
не означает positive OI, bracketed price, profitable trade или полную option surface.

## Завершённые проверки / текущая граница

47 новых synthetic tests PASS; expanded V92/V91/V90/V89/V88/V68/V64/portfolio-ledger/
execution-dataset: **224 local PASS за17.62s**, Ruff clean, без warnings.
Проверены полный fake source→metadata→targets→integer-ledger, оба arms/costs,
ненулевые сделки и только расходы на constant fake price, all-NULL/zero-trade/full
calendar, целиком empty source, bad/new release без fallback, future-mutation
invariance, source-side conflicts, protected dates, partial/wrong hashes/indices,
HTTP errors, all-NULL inventory, persistence, exclusive output claim и admission gates.
Это не 47 новых торговых гипотез и не исторический результат. Server verification
ещё отдельно; actual V92 mapping/economic units не запущены.

V89 actual16:49UTC остаётся active/running:9761/40820 exact descriptions, unavailable0,
тот же PID3208549/invocation. Main AlgoPack3084/26305jobs/36.378mrows, failed0/blocked0;
FUTOI601/2192days/7.301m logical rows,282unresolved ticker-days/40gapdays.
Все три final manifests отсутствуют. Scope/services/token/Windows не менялись.
Full du не повторялся:5.198GB total/3.737GB AlgoPack — старый snapshot16:09UTC.

Следующий substantive результат этой ветки — full mapping и затем paired historical
screen после closure. Пока V89 работает, не повторять tests/audits и не строить ещё
один collector/ledger: продолжать другую разрешённую независимую гипотезу. Новая
broader AlgoPack economic authorization пока unanswered; download этим не блокируется.
Original PIT/full surface/live/goal admission false. Economic screens25 / Stage2=0.
