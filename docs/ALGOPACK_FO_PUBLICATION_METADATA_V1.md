# AlgoPack FO publication metadata V1

## Основание и единственная задача

[Ответ MOEX](ALGOPACK_VENDOR_REPLY_20260907.md) определяет SYSTIME как время
публикации. Отдельный source-only diagnostic выясняет, какие именно publication
timestamps стоят в текущей версии истории2020–2025. Это не модель/экономический
эксперимент, не подбор lag и не восстановление отсутствующих original vintages.

Protocol `algopack_fo_publication_metadata_v1`. Config SHA
`6fcd794a5d71ff54274a8fcaef76a2652fd43f307eabc91da3b543252cebe62b`;
34-file closure `b07f521403456484656a1de2b62801665d1449cd941aa781af0d5f8c9f7b5db5`.
Parent quality closure `b57b9b226d63842dd0a3c09bafcd98746bcd48f383324f53e0b1bb4558f260ba`;
history source manifest `f50fa60a6986070d45f6a69555076df1f5748d09b70407131591740e77425fb4`.
Vendor reply summary включён в closure: после этого run его bytes frozen, новые
уточнения оформлять отдельной dated note, не переписывать прежнее свидетельство.

## Предварительно фиксированная методика

1. Проверить code/config closure; exact source manifest; полный parent raw replay.
2. Использовать294jobs/147contracts/2067949rows/2198pages, без новой выгрузки.
3. Arrow читает только строки dataset/requested_asset_code/secid/tradedate/tradetime/
   SYSTIME. Numeric fields не materialize-ятся. Hash проверяется до и после projection.
4. Группы ALL, dataset, dataset/label_year и dataset/asset/label_year; отдельные jobs.
5. Min/max SYSTIME, publication-year counts, same/earlier/later calendar-date counts,
   число publication timestamps>=2026-01-01. Рыночные label dates остаются<2026.
6. Разность двух naive vendor clocks: SYSTIME минус tradedate+tradetime. Bins(seconds):
   negative,[0,60),[60,300),[300,600),[600,3600),[3600,86400),>=86400; min/max.
   Это **не measured delivery latency**: timezone и bucket semantics не подтверждены.
   Parent parser уже требует SYSTIME>=label; 0 negative будет следствием parent guard,
   а не независимым свидетельством о всех данных поставщика.
7. Проверить counts/source SHA/closure повторно; записать audit/report/manifest в
   новый immutable directory, проверить bytes перед atomic publication.

Нет чтения prices/returns/labels/targets/PnL после2025. Используемый здесь `label`
означает только vendor date/time label, не финансовую прогнозную цель.
Нет сделок, train/OOS, CAGR или promotion. historical_model_eligible,
original_version_verified и live_trading_allowed остаются false при любом результате.

## Runtime и проверки

Новые synthetic tests31/31, Ruff/closure PASS до source run. Обязательны commit/push
и Linux tests. Runtime только gpu-mlserver: PrivateNetwork=yes, без env/API key,
source tree read-only; writable только отдельный output parent и exact parent
history audit lock. Существующие16timers не меняются.

```text
/opt/trading_lab/.venv/bin/python -m market_lab.futures.algopack_fo_publication_metadata_v1 --storage-root /srv/trading_lab_data --seal-sha256 b07f521403456484656a1de2b62801665d1449cd941aa781af0d5f8c9f7b5db5
```

Output parent `/srv/trading_lab_data/data/processed/algopack_quality`, canonical
`algopack_fo_publication_metadata_v1_b07f52140345`. Run один раз; нельзя повторять
для подбора новой source interpretation или превращать поздние публикации в ранние.

## Результат

Pre-run commit/push `47b2c5e`. Local389passed/4 Windows symlink skips, Linux391/391,
Ruff/closure PASS. Run запущен на gpu-mlserver около12:35UTC 2026-09-07:
`trading-lab-algopack-fo-publication-v1-b07f52140345.service`, handle57424.
Наблюдать именно этот unit/handle; observation timeout не разрешает новый запуск.
После completion записать actual metadata findings и hashes. Любое решение о model
admission требует отдельного обоснования; отдельный report не изменяет old canonical.

### Завершённый результат 2026-09-07

Unit terminal success/exit0, runtime2min2.625s, peak255.9MiB. Handle57424 завершён;
invocation `2be39d5c185d4f0ebc5fe1b4e664bc53`, PID2079332 завершён.
Report created12:37:53.233854UTC. Canonical:
`/srv/trading_lab_data/data/processed/algopack_quality/algopack_fo_publication_metadata_v1_b07f52140345`.
Manifest SHA `1bff6855218cceba6d815d137047458a089f3deec184f9325a99d3f2ed6afeda`;
publication JSON172511bytes, SHA `6d47ba3d6aa579ad69c8aa9b5cd0aa191698caceca7b9d4aa19666d24901d7d5`;
audit363bytes SHA `7c4de421746d0a3feca83ba891c1f69e93f076a391832a02c06d34ac4b9e4c18`.
Full raw replay PASS. Независимая report-only сверка hashes, всех294jobs, групп,
publication years и histogram/calendar sums PASS. Code/config не менялись после run.

| Dataset | Rows | Same calendar date | Later calendar date | SYSTIME>=2026 |
| --- | ---: | ---: | ---: | ---: |
| TradeStats | 1007214 | 132953 | 874261 | 1056 |
| OBStats | 1060735 | 132238 | 928497 | 0 |
| Total | 2067949 | 265191 | 1802758 | 1056 |

87,1761% записей текущего полученного vintage имеют SYSTIME на более позднюю
календарную дату, чем vendor tradedate. Общий минимум SYSTIME2024-04-11 12:45:04,
максимум2026-03-16 13:23:35. Publication-year counts2024=193581,2025=1873312,
2026=1056. Все1348066строк с label dates2020–2023 имеют более позднюю дату публикации.
Для label2020/2021 обе группы полностью имеют SYSTIME2025. Это не утверждение,
что сами сделки или исходные сообщения биржи не существовали раньше.

| Label year | TS same-day / total | OB same-day / total |
| --- | ---: | ---: |
| 2020 | 0 /159932 | 0 /171204 |
| 2021 | 0 /173949 | 0 /176756 |
| 2022 | 0 /143109 | 0 /173329 |
| 2023 | 0 /175967 | 0 /173820 |
| 2024 | 6531 /171302 | 5572 /177724 |
| 2025 | 126422 /182955 | 126666 /187902 |

1056 post2025 publication rows — только TradeStats:704 с label2023 и352 с label2025.
Ни одной price/return/target/PnL строки2026 при этом не читалось: речь о metadata
публикации исторических source rows. Same-day тоже не означает известность до
любого решения дня: остаются intraday clock, bucket и revision semantics.

Naive label-gap bins: negative0;[0,60)=261829;[60,300)=240;[300,600)=82;
[600,3600)=569;[3600,86400)=3387;>=86400=1801842. Максимум172220714секунд,
но называть этот интервал задержкой доставки запрещено. Это могут быть backfill,
перепубликации или исправления; различить причины по одному timestamp нельзя.

### Вывод и следующий шаг

Дата рыночной записи не является датой доступности её текущей версии. Нельзя
просто сдвинуть все feature rows2020–2025 на5/10минут и объявить такой backtest
исторически исполнимым. Отдельный metadata audit больше не нужен для установления
этого факта; canonical не перезапускать и bins не tune-ить.

Архив не объявляется бесполезным: **обучение сегодня** и **решение в прошлом**
требуют разных временных проверок. Возможный следующий bounded дизайн — отдельный
current-time training / prospective-only forecast protocol: обучение использует
действительно полученный сейчас архив, первые прогнозы только после нового seal,
без ретроспективного PnL и без чтения protected2026 outcomes. Сначала нужна явная
admission-модель training_cutoff vs decision_at, label-independent inference и
проверка bucket/time semantics; это пока дизайн, не разрешение запускать обучение.
Предложенный exploratory historical exception всё ещё не подтверждён пользователем.
