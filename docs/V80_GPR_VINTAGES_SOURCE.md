# V80 source feasibility — archived geopolitical-risk vintages

2026-09-15, до любых MOEX outcomes нового механизма. Это bounded source-only шаг,
не новый collector, model или economic PASS. Архивы AlgoPack продолжают отдельно.

## Почему этот источник

[Caldara/Iacoviello, Fed](https://www.federalreserve.gov/econres/ifdp/measuring-geopolitical-risk.htm)
описывают измерение geopolitical threats/acts по доле статей и связь с downside risk.
Это мотивирует, но не доказывает, новый последующий торговый тест: рост российского
геополитического риска может сопровождаться устойчивым удорожанием USD/RUB и нефти,
снижением российских акций. GDELT geopolitical channel был в раннем планеV6;
исполненного теста на country GPR archived vintages в реестре не найдено.

На [странице авторов](https://www.matteoiacoviello.com/gpr.htm) и
[country page](https://www.matteoiacoviello.com/gpr_country.htm) описаны monthly updates
в начале месяца (federal holiday переносит на следующий business day), weekly daily
updates, revisions и CC BY attribution. [Методология](
https://www.matteoiacoviello.com/gpr_files/gpr_methodology.htm) изменилась в2021;
не смешивать старую/new series без проверки.

## Проверенный каталог, а не numeric data

Официальная ссылка авторов ведёт в GitHub iacoviel/iacoviel.github.io/gpr_archive_files.
Tree2112f4d7887dde3bc8f571dd8fcb736c35b1355c, truncated=false:59monthly DTA editions,
50editions<=2025, earliest202110;202202 отсутствует. Запросы истории current DTA до
2021-10-01 и до2018-12-31 пустые. Edition202110 впервые добавлена в Git commit
b256af84d25b73b22440d24ad3e0261527cdd8f1 от2022-03-01T14:49:01Z.
Имя202110 не доказывает public availability в октябре2021. Авторский log отдельно
сообщает correction2024-02-07 о missing articles с2021. Numeric GPR ещё не читался.

Поэтому source plan заранее ограничен всем46monthly editions202203…202512,
не удобными годами после PnL. First3metadata pilots202203/202401/202512; затем остальные.
Это не покрытие2018–2025 original vintages. Возможный economic screen должен сохранить
весь2022–2025 (до первой доступной версии — unavailable/cash) и назвать короткий sample.
Не подставлять current2026 series вместо старых выпусков.

## Фиксированное получение

Только gpu-mlserver, новый external root из config. Stata выбран как native statistical
format, pandas2.3.3 уже установлен; spreadsheets/export artifacts не создаются.
Для каждого exact month один GitHub commits?path=...&per_page=100: require1…99entries,
взять oldest returned commit, затем raw DTA по exact40hex commit URL. Сохранить весь
commit response, raw DTA, SHA/size/actual receipt и first author/committer clocks.
Commit timestamps являются proxy, не независимо witnessed public push time.

Пилот читает ТОЛЬКО variable labels и month column: unique ordered months<2026,
maximum<=edition month, calendar coverage13previous complete months, Russia candidates.
Никаких GPR numeric values, market prices, returns, targets, PnL или model fit на этом шаге.
Data labels/filenames не заменяют date validation. Full mode уже входит в этот seal,
но запускается только после фактической проверки3metadata pilots. Успешные raw jobs
повторно не скачивать; verify pinned hashes, single-writer lock, atomic new directories.
Partial staging retained; completed manifest не overwrite. Нет live/demo/новой оплаты.

Anonymous HTTPS only api.github.com/raw.githubusercontent.com, no credentials,
no redirects;2MiB per response, bounded transport retries,0.5sec spacing. GitHub403
или missing source останавливает batch; rate limit не повод добавлять чужой token.
До сетевого получения — source code/config/tests/doc/dependency seal и push.

После source readiness нужен отдельный economic protocol/seal: конкретный показатель,
past-only transformation, publication allowance, masks, control, 1x/2x costs и gates.
Для всех источников/лет сохранить неудачи; отсутствие исходных vintages нельзя скрывать.
Цель20–50% не достигнута; source metadata не является доказательством прибыльности.

При поиске документации Brent/WTI поисковая выдача содержала нерелевантные current
snippets с котировками; они отброшены, не использованы в GPR design/числах и не открывались
как market dataset. Последующая документация ограничена primary author/Fed sources.
