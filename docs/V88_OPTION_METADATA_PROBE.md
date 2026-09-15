# V88 — точная привязка опционов перед проверкой expiry pinning

Source-only protocol,2026-09-15T14:27:58Z. Не новый economic screen или доходность.
Гипотеза для последующей проверки: концентрация открытых позиций по страйкам может
создавать притяжение цены фьючерса перед исполнением опционов. Это не доказанная
позиция дилеров/gamma; знак хеджирования из общего OI неизвестен. Нужны точные
expiry, underlying и единицы, а не только совпадающие короткие коды.

V68 отложил pinning: у public weekly option source нет доказанной точной даты
экспирации. Старый calendar probe был анонимным и решал другую задачу — numeric
OPTION_SERIES_ID для curve coefficients. Теперь проверяется отдельный публичный
справочник по точным SECID и подписанный исторический календарь. Старые протоколы,
правила, данные и результаты не меняются. Не спасать V68 иной фильтрацией по outcome.

Документированный [security specification endpoint](https://iss.moex.com/iss/reference/193)
возвращает description/boards; запрос ограничен description. Public calendar path
зафиксирован старым metadata protocol со ссылкой на [руководство](https://fs.moex.com/files/26408).
В этой сессии PDF вернул transport timeout; перенос пути на apim является проверяемым
вариантом доступа, не заранее подтверждённой функцией подписки или гарантией схемы.
Новый запрос apim ограничен двумя точными датами до2026 и только options metadata.
Нет currentmarketdata, ордеров, цен исполнения или запросов защищённых исходов2026.

## Фиксированный минимальный sample

Существующий source подтверждён по manifest/parquet/audit hashes и только четырём
metadata columns:1327744rows,108104unique securities,2021-01-08…2025-12-30.
Для каждого SI/RI/BR/MIX в2021и2025берётся первый по алфавиту SECID на первом
сохранённом дне года:8description requests. Это не выбор по цене, страйку, OI или PnL.
Дополнительно2calendar queries на2021-01-08и2025-01-03, всего10logical requests,
до2transportattempts каждый. Никакого108104-request collector до понимания схемы.

Raw responses и actual clocks/SHA сохраняются внеGit в отдельном leaf
`/srv/trading_lab_data/source_evidence/v88_option_metadata_probe_v1`.
Существующая серверная CA проверяется по hash. Token только из service environment,
только к apim.moex.com, без redirects/логирования. Public ISS получает no credential.
Источник HTTP error/HTML/empty не считается наличием metadata. Не угадывать missing.

Читаются только whitelist static identity/type/expiry/unit fields и schema names.
Last trade date не выдавать за expiry; описательное имя — за точный underlying ID;
короткий код — за полную спецификацию. Возможная неоднородность settlement types
внутри logical asset требует проверки, а не автоматической агрегации контрактов.
Ни восемь примеров, ни calendar table не доказывают mapping всех108104securities.

Config/code/tests/этот документ запечатываются до HTTP. При доступной схеме следующий
шаг — отдельный фиксированный metadata join/coverage, затем один economic protocol
на старом futures execution. При отсутствии нужных полей — явный source blocker,
без фальшивого pinning PnL. AlgoPackarchive runs не трогаются.
