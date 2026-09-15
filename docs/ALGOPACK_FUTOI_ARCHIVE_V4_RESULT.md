# FUTOI V4: загрузка возобновлена, неполнота сохраняется явно

Checkpoint2026-09-15T11:59:43.059880UTC. V4 actual active/running,
PID2522946, invocation2e561d202042490d81ddc8aefa3cd543,
unit trading-lab-algopack-futoi-archive-v4-f47d4cd22039.service.
Старт11:55:54.375041UTC, Restart=no. Это не завершённый архив и не economic PASS.

## Исправление первоначального диагноза

В pre-request тексте [V4](ALGOPACK_FUTOI_ARCHIVE_V4.md) ошибочно указан AU как
тикер пустого ответа. Старое поле status.current_ticker обновляется ПОСЛЕ успешной
обработки, поэтому AU был последним успешно сохранённым тикером, а следующим по
зафиксированному universe шёл BM. В V3 AU имеет committed page с352rows, SHA
8ceed0a55fdea5745416b5623eaa12c154beb4d526093e974d8c262866453ea7;
для BM её нет. Проверка stopped status SHA
5250411517831b343cf9bd829d0f366b5f29471a1fead4a146d8a60b9037ce07
совпала с pre-request snapshot, completed_count3 и порядок universe подтверждены.
Это уточнение получено после запуска V4. Замороженный протокол не переписывается;
данная dated note является явной поправкой к его описанию причины остановки.

Само исправление V4 изначально общее: сохранять valid empty/schema/tail discrepancies
с явным UNRESOLVED_SOURCE_GAP. Ни правила, ни tickers, ни источник после запроса
не менялись. Нет AU/BM-specific исключения. Failure timestamp/остальные counts V3
подтвердились; его root и status не изменялись.

## Что проверено

- До новых HTTP проверены transitive code/config seals и7524page metadata inventory:
  120из V2,7404из V3. Оба старых unit подтверждены terminal/PID0. Точные source_root
  references заменяют копирование и повторное скачивание уже сохранённого raw.
- Local93/server93targeted synthetic tests PASS, Ruff clean. Начальная локальная
  попытка имела ошибки setup на автоматически сформированных длинных byte-payload
  test ids; до seal им присвоены короткие ids, текущий прогон прошёл полностью.
- После возобновления отдельно проверены все59pages проблемного дня2025-08-26:
  raw/gzip/page SHA и размеры, строки/схема/дата, exact final-point proofs и все
  resolved/unresolved reasons.59/59PASS, без нового HTTP и без редактирования данных.
- Day manifest SHA:
  00ae45dfb486cdd1dba9180afda02f5054cab2304dcc3e6ca8aad08feb91e44b.
  58ticker-days,47matched/11unresolved,16312intraday rows,
  15256new-root rows,4reused pages,308551new-root bytes.
- Все11gaps данного дня — HTTP200/schema-valid пустые ответы:
  BM,CE,DX,FF,HS,IB,KC,MY,NA,NR,OJ. Каждый имеет собственный request URL,
  фактический receipt иpage SHA. Это не нулевые позиции и не доказанное отсутствие
  торгов; не объявлять историю полной и не наполнять этими нулями будущие признаки.
  Одинаковые empty raw bytes SHA
  58e2026f17628387dee24af88a57b91f72396c62618e9547c83b7c48bf01168f
  не заменяют отдельную request identity каждого тикера.

## Текущие счётчики

131/2192processed days,7507attempted ticker-days,7478resolved/29unresolved,
days_with_gaps2.2328426intraday rows всего в logical V4 archive,
31489new-root rows,7524prior pages reused;651209new-root bytes completed days.
Current2025-08-24,22/47tickers завершены. Final manifest ещё отсутствует.
processed означает сохранённый отчёт дня, не полное покрытие исходных данных.
При завершении плана с gaps final должен быть COMPLETE_WITH_SOURCE_GAPS, не COMPLETE.

Root /srv/trading_lab_data/data/algopack-archive/algopack_futoi_archive_v4_f47d4cd22039.
Pre-request push1b44b19. Seal:
f47d4cd22039c56c5647a36087b4ee37fac96db8df62b87b6366d9a9ac7e947e.
Config SHA0be82abb8934c53501e1b9a3c289b086ec5bf4f8528ffc6b4f1e8ad5e2eff63f.
Transfer algopack_futoi_archive_v4_f47d4cd22039.tar,
SHA8ad45bc9adbe31a02e5b080c551b3b3148b01645cdbde240a0a092ee93129439,
local external transfers иserver/tmp совпали. Распакованы только6новых code/config/
test/protocol files с keep-old-files; старые файлы не заменялись.
Server synthetic basetemp /tmp/algopack_futoi_v4_tests_f47d4cd22039 сохранён.

14-family archive независимо продолжает работу:PID1663880,1348/26305jobs,
17154756rows/18067pages,1024787666stored bytes completedjobs,failed0/blocked0;
final manifest отсутствует. Свободно898792579072bytes в момент checkpoint.
Данные/модели вне Git, полного Windows зеркала новых архивов пока нет. Для backup
сохранить V4+V3+V2 и старыйcore4; только новый V4root не содержит всего архива.
Новых collectors на Windows, payments/subscription changes, broker/paper/live нет.
