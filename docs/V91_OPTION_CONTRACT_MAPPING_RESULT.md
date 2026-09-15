# V91 — sample binding COMPLETE, не экономический результат

Completed **2026-09-15T16:16:03.185461UTC**. [Протокол](V91_OPTION_CONTRACT_MAPPING.md).
Pre-sample commit `e010f20`, pushed. Five-file seal
`436c6a3f949df4d8e354e549493ca867af7bfe0cfa1a2827765de614751f8eff`
проверен на server; 59/59 server synthetic tests PASS за0.18s. Локально 59 новых /
126 combined V91/V90/V89/V88 tests PASS, Ruff clean. Tests не новые торговые гипотезы.

12 старых static catalog files, 255660bytes, скопированы один раз в отдельный
`/srv/trading_lab_data/source_evidence/v91_static_futures_catalogs_v1`.
228 alias rows / 220 canonical contracts, manifest/raw/Parquet replay совпал.
Catalog evidence SHA `ca7fb707635608c186685f8463977e64df36f3014826e90df5102bb9d0a5505e`.
Transfer archive266240bytes сохранён там как `transfer.tar`, SHA
`3d6a9e7732c6a310f9975f1bfa06ad91fca37468438a579aa00c0bfa819aa795`.
Локальный transfer находится вне Git, в `D:\Projects\trading_lab_data\tmp\v91_static_catalogs_20260915`.
Не удалять canonical static files; дальнейший full mapper ссылается на этот subset.

## Новый результат на восьми уже сохранённых описаниях

Raw bytes взяты из closed V88 manifest
`10ff109b609658ebd0ff4ae4bb7e8f0f17e0d1b5a1afe521ea113699e25d9d7f`, без новых HTTP.
Проверена именно новая exact-contract/strike-unit связь, а не повтор старого probe.

| Option SECID | Результат / exact underlying |
| --- | --- |
| Si100000BC1 | `Si:SiH1:2021-03-18` |
| Si100.5CA5B | `EXCLUDED_PREMIUM_CURRENCY`, не futures mapping |
| RI100000BA1 | `RTS:RIH1:2021-03-18` |
| RI100000BA5 | `RTS:RIH5:2025-03-20` |
| BR100BB1 | `BR:BRH1:2021-03-01` |
| BR100BA5 | `BR:BRG5:2025-02-03` |
| MX100000BC1 | `MIX:MXH1:2021-03-18` |
| MX145000BC5 | `MIX:MXH5:2025-03-20` |

Итого7 `EXACT_STATIC_BINDING` +1 positive currency exclusion, без unresolved среди
восьми. Все7 исходных weekly source dates внутри option lifecycle. Семь карточек
содержат explicit exercise-to-underlying price equality: quote_units_compatible=true
получен из raw условия исполнения, не присвоен вручную и не из premium UNIT.
SI future использует exact NAME/SERIES + independent catalog USD000UTSTOM agreement;
прочие шесть — согласованное exact NAME/SERIES/FUTURES_SECID.

Canonical derived report:
`/srv/trading_lab_data/source_evidence/v91_static_futures_catalogs_v1/sample_binding_result.json`
SHA **`1db69479b90d03cb1f89e20aec0f472523f6e58944ebf10728cba0122528b8e4`**.
Report записан UID999/GID989, exclusive create/fsync; старые canonical roots не менялись.

## Что это позволяет и чего не позволяет

Завершён новый bounded metadata adapter для V90. Не повторять восемь проверок как
новый прогресс. Они не доказывают mapping coverage всех40820 V89 descriptions и не
позволяют выбрать удобный partial BR subset. OI magnitudes/market values/targets/PnL
не читались; no HTTP/model fit/live/demo. Original PIT/economic/full V89 admission false.
Воронка25 economic screens /0 Stage2, цель20–50% по-прежнему не подтверждена.

Следующий полезный шаг, пока V89 writer работает: подготовить тонкий full-source
join и economic runner вокруг frozen V90 + V91 и существующего daily ledger,
проверяя сборку на synthetic inputs. Никакого ещё одного ledger/collector/audit этих8.
До реальных OI/price inputs требуются closed V89 manifest, один full mapping/coverage
pass и полный economic code/config/input seal с неизменяемыми gates. В source-calendar
261dates×4assets=1044groups сохранить missing/empty releases, не старый good fallback.

## Параллельные архивы и объём

Actual16:08:58UTC main/FUTOI/V89 units active/running с прежними PID/invocations.
Main2872/26305jobs,34.010mrows, failed0/blocked0; FUTOI531/2192days,6.637m logical rows,
237 unresolved ticker-days/31gapdays. V89 5896/40820 exact descriptions, unavailable0.
Все final manifests ещё отсутствовали. Никаких service/token/Windows changes.

Sequential du16:08:59UTC: весь server data+source_evidence **5198027449bytes (5.198GB)**,
из них AlgoPack two main roots **3737085922bytes (3.737GB)**; allocated6.049GB.
Models/runs/tmp исключены. Это snapshot **до** маленького V91 static subset transfer.
Local2.720GB — предыдущий15:09:20UTC замер копии; не складывать с server как unique corpus.
