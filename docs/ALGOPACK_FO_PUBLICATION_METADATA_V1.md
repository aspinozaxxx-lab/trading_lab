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

Не запущено. После run записать actual metadata findings, hashes и разрешённый
следующий шаг. Любое решение о model admission требует отдельного обоснования.
