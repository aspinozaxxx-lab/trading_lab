# V96 — один source-only повтор, экономика не меняется

2026-09-16. Original V96 economic run не запускался: нет новых SP500 values,
features, targets или PnL. Прежние код/config/seal и failed staging не изменяются.

1. Unit `trading-lab-v96-source-798bfda91f93` failed до HTTP: сервисному UID999
   недоступно создание root в root:root0755 source_evidence. Root не создан.
2. Unit `trading-lab-v96-source-access1-798bfda91f93`, invocation
   `e9199430428f49e2a1ec487d496edeb5`, получил временно право группы создать root;
   исходные owner/group/mode parent восстановлены 10:53:22.312560UTC.
   urllib GET завершился read timeout90s; root со started/calendar сохранён,
   source manifest отсутствует, numerical/economic run не состоялся.
3. HEAD обычного curl дал HTTP/2 stream error. HEAD HTTP/1.1 с уже известными
   anonymous research headers ответил200 в10:56:42UTC. Body/quotes не читались;
   HEAD сам по себе не доказывает успешную загрузку.

Retry1 меняет только транспорт: curl HTTP/1.1, те же endpoint/query/date bounds,
45s timeout, <=2MB body, exact200, TLS verification, no redirects/cookies/credentials.
Парсер, calendar, source clocks, signal, cohort windows, assets, costs, gates и
ledger — те же original V96 функции. Entry point явно устанавливает отдельные
config/seal; runtime equality-check допускает различия только protocol_id и
declared_at_utc. Original bytes включены в retry seal. Новый staging и новый run
получают retry seal suffix; old partial root не перезаписывать/не удалять.

Это тот же один экономический кандидат, не второй конкурс. Сначала synthetic
transport tests/push/seal, затем один retry fetch на gpu-mlserver. Если источник
снова недоступен, сохранить blocker и не превращать поиск стратегии в endless
HTTP retries. Никакого ослабления защиты2026 или смены underlying по результату.
