# V102 V2 — узкое исправление неиспользуемого заголовка

V1 source остановился 2026-09-16T22:45:17.276903UTC:18 parsed releases,18newGET,
1reused,19rawHTTP200. Economics не запускалась. Root и code/config seal V1 сохраняются:
`source_evidence/v102_tic_bank_funding/96238a5697f9`, manifest
`bb11c0ac8eda14f2b64efab679011fe19e3e1b38fc164d5a813395978994611e`.

В [17 June 2019 release](https://home.treasury.gov/news/press-releases/sm711)
два rolling12month headers ошибочно одинаковы: `Apr-19`, `Apr-19`; восемь колонок
`2017,2018,Apr-19,Apr-19,Jan,Feb,Mar,Apr`. Article дата17June2019, titleApril,
последний monthly value и current rollingApril2019 согласованы. Признак берётся
из последней месячной колонки, не из этих rolling totals.

Только для точных bytes SHA
`0a12dba5637e022d9e84f3c4d5b1011ea4fb4758b9a0cd990dc9eca138567760` и exact header
V2 заменяет в parser RAM первый, неиспользуемый `Apr-19` на `Apr-18`. Это явное
schema исправление prior-year label, не восстановление неизвестного значения.
Сохранённые raw/metadata, числовые данные и latest column не изменяются. Иные
неизвестные bytes/headers по этой дате отклоняются. Все прежние проверки остаются.

Новый source root,22rawreuse(19failed+3remainingprobes),74newGET,no retry/access
workaround. Во время V1 ни prices/targets/PnL новой гипотезы не читались. Новый
pre-outcome code/config seal пинит V1 seal и отдельный correction config.
SI sign/weight/TTL/control/calendar/costs/gates/targets/states/engine и scope из
[V1 protocol](V102_TIC_BANK_FUNDING.md) не меняются. V1/V2 = одна гипотеза.
Новый manifest/root/run; canonical V1 нельзя перезапускать или перезаписывать.
