# V102 V3 — заголовки вне таблицы, без изменения чисел и economics

V2 source FAILED_SOURCE_NO_RETRY22:53:14.656403UTC:24parsed/25rawHTTP200,
6newGET+19reuse. Manifest
`1a1e68992ed1c12575494d6a625e6bec30a77bc8103de1246f45af0113b62eee` в
`source_evidence/v102_tic_bank_funding_v2/1a5b61175fb2`. V1/V2 files/root/seals
сохраняются; economic runs ещё не было.

В [16December2019](https://home.treasury.gov/news/press-releases/sm859) title/unit
находятся вне единственной таблицы; её header2017/2018/Oct-18/Oct-19/Jul/Aug/Sep/Oct
и bank row29 присутствуют. Raw SHA
`bc3b74fd51f8d953d70c6461acfba2778759ef3e9be627b5f42aeec07244850a`.
V3 требует ровно одну таблицу, по одному document TIC title/unit и одну row29,
после чего вставляет эти уже присутствующие title/unit в parser RAM. Никакие
существующие ячейки/числа/raw/metadata не меняются. Дальше все V1checks и узкая
[V2Juneheadercorrection](V102_TIC_BANK_FUNDING_V2.md) без ослабления.

28rawreuse(25V2+3remainingprobes),68newGET. Все economics из
[V1](V102_TIC_BANK_FUNDING.md) прежние; V1/V2/V3 = одна гипотеза, ещё не economic
contestant. Новый код/config seal до remaining source/targets/outcomes. Если
возникнет ещё один неизвестный формат, в этом turn сохранить source failure и
приостановить TIC вместо бесконечного развития parser; неполный корпус не тестировать.
