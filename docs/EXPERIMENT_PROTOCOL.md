# Шаблон протокола эксперимента

Новая гипотеза должна быть описана и byte-sealed до чтения её OOS outcomes. Скопируй этот
шаблон в описание задачи или новый config; не редактируй шаблон как замену реальному seal.

## 1. Идентичность

```yaml
protocol_id: <unique-name>
protocol_version: 1
declared_at_utc: <timestamp>
research_only: true
sealed_before_outcomes: true
protected_holdout_start: 2026-01-01
parent_protocol_sha256: <optional>
```

Нужно объяснить, является ли эксперимент независимой гипотезой, исправлением accounting,
execution follow-up или post-selection diagnostic.

## 2. Гипотеза и falsification rule

- **Hypothesis:** одно конкретное причинное утверждение.
- **Why it may work:** экономический механизм, не только architecture choice.
- **Primary comparison:** заранее выбранный baseline.
- **Reject if:** численный или структурный критерий провала.
- **Promote only if:** критерии signal, net execution, stability и coverage.
- **Forbidden follow-ups:** изменения, которые после результата считались бы tuning.

## 3. Источники

Для каждого input:

```yaml
role: <name>
path: <relative-to-external-root>
sha256: <64 hex>
bytes: <integer>
rows: <integer-or-null>
minimum_timestamp: <value>
maximum_timestamp: <must-be-before-2026>
manifest_path: <path>
manifest_sha256: <64 hex>
allowed_columns: [<exact list>]
```

Опиши transitive manifests, publication/revision semantics, universe membership и права на
использование. Не принимай filename как доказательство временной границы.

## 4. Information set

- decision timestamp и timezone;
- какие завершённые bars/releases доступны;
- causal feature formulas и lookbacks;
- train-only normalization/correlation/thresholds;
- missing/mask policy;
- явно запрещённые future columns;
- для LLM — exact accepted fact schema и forbidden market fields.

## 5. Targets и labels

- entry/exit definition;
- horizon и exact successor rules;
- same-contract requirement;
- target availability timestamp;
- treatment of gaps, rolls и terminal rows;
- same-bar precedence, если применимо.

Target не может определять feature availability или test-row eligibility до inference.

## 6. Validation

```yaml
train: <dates>
calibration: <dates-or-rule>
oos: <expanding years>
purge: <sessions/bars>
embargo: <sessions/bars>
seeds: [<fixed values>]
hyperparameter_search: false | <train-only design>
```

Зафиксируй, где обучаются scaler, early stopping, calibration и trade threshold. Ничто из
этого не должно читать outer-test labels.

## 7. Model и ablations

- exact model family/size/loss/optimizer;
- fixed seeds и ensemble rule без seed selection;
- заранее объявленные baselines/ablations;
- parameter count/runtime, если релевантно;
- что считается sleeping output.

## 8. Execution и portfolio

```yaml
decision: <completed information time>
entry: <factual next open/bar>
fill_rule: <adverse/exact/limit probability>
exit: <rule>
integer_quantity: true
participation_cap: <value>
asset_gross_cap: <value>
portfolio_gross_cap: <value>
initial_capital: <value>
costs: [base, double, stress]
margin_and_collateral: <rule>
missing_or_unprovable: unresolved
```

Если historical specs, borrow, fees или fill evidence отсутствуют, прямо определить,
блокирует ли это PnL или делает его research proxy.

## 9. Reporting

Обязательные outputs:

- protocol/config SHA и code/data identities;
- counts: source, decisions, predictions, trades;
- coverage и unresolved reasons;
- gross и net returns;
- CAGR, Sharpe, MDD, worst year и per-year metrics;
- turnover, costs, participation, gross/cap breaches;
- 1×/2× и заранее объявленные stress scenarios;
- baseline/ablation paired comparison;
- machine-readable metrics и human-readable verdict.

## 10. Pre-outcome seal checklist

- [ ] Config записан и SHA сохранён.
- [ ] Все source hashes проверены.
- [ ] Максимальная дата меньше `2026-01-01`.
- [ ] Feature/target schemas разделены.
- [ ] Train/calibration/OOS и purge зафиксированы.
- [ ] Execution и costs нельзя менять через CLI.
- [ ] Baselines, gates и promotion rule объявлены.
- [ ] Output directory новый и не совпадает с canonical run.
- [ ] Synthetic smoke test прошёл.

## 11. Итоговая запись

После run добавить в [EXPERIMENTS.md](EXPERIMENTS.md):

```text
Protocol/config SHA:
Canonical external run path:
Input/data identities:
OOS dates:
Decision/trade/coverage counts:
Primary and stress metrics:
Per-year stability:
Baseline comparison:
Known limitations:
Verdict: GO TO NEXT VALIDATION | NO-GO | BLOCKED
Next allowed action:
```

`GO TO NEXT VALIDATION` не означает `GO LIVE`. Live требует отдельного admission protocol
с broker/exchange exact data, operational risk и новым независимым holdout.

