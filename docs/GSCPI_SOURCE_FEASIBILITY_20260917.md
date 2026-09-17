# NY Fed GSCPI — bounded source feasibility

2026-09-17, до V108 source magnitudes / targets / PnL. Проверены только header,
даты, lexical numeric/missing types и counts. Spreadsheet read-only workflow:
raw CSV не редактировался; protected columns/rows исключаются до numeric conversion.

## Capture и права

Четыре bounded GET, 1/sec, без auth, redirects, retries или vendor feeds:
[product](https://www.newyorkfed.org/research/policy/gscpi),
[terms](https://www.newyorkfed.org/privacy/termsofuse),
[description](https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/gscpi.json),
[vintage matrix](https://www.newyorkfed.org/medialibrary/research/interactives/data/gscpi/gscpi_interactive_data.csv).
Terms разрешают personal/business use с attribution и сохранением notices;
third-party content имеет отдельные ограничения. Это private derived-index research,
не скачивание лицензируемых BDI/Harpex/PMI feeds, endorsement или public redistribution.
Attribution: Federal Reserve Bank of New York, Global Supply Chain Pressure Index.
Индекс не является official estimate ФРБ Нью-Йорка, её президента, Fed System/FOMC.

Root `source_evidence/gscpi_probe_20260917_v1/capture`, completed
`2026-09-17T02:16:18.934940+00:00`, status `COMPLETE_FEASIBILITY_CAPTURE_ONLY`.
Unit `trading-lab-gscpi-feasibility-20260917-v1.service`, PID1816673,
invocation `4e2eef5575e6465f9ec5f89fde52c7e2`; observed running then terminal journal.
Manifest SHA `69b8f0daadb50fb512c7486fc8a6e23db19d5b3fbf93a8179111b1a96a879831`.
CSV 115873 bytes / SHA
`723e8dc81728176dea10e7d685478bfe888516ec68d1d2cc1b77d6fea8177c55`.
Nine artifacts plus manifest verified on both hosts, no economic admission implied.

Executed script SHA `54f791842cd3133a7b2b1124de2679e85ae3a5655ef51553d8daaf14acebd274`
preserved as `source_evidence/gscpi_probe_20260917_v1/executed_capture_script.py`
on both hosts. Local script only line-wrapped after two Ruff E501 warnings;
AST equality verified, formatted SHA
`380fb671a1c073440670d0caa63ef0d8dd25c92fb449e746365346029102090e`.
Capture pins actual executed bytes, not the later formatted file.

## Coverage and selection

58 columns = Date +57 monthly vintages Jan2022–Sep2026; 348 dated month-end rows
Sep1997–Aug2026 plus one empty footer. Forty-eight vintage labels precede2026.
Only `#N/A` is missing; zero is valid. Early nonblank checks mistakenly counted
`#N/A` and were discarded, not used for admission. Correct lexical checks establish
Jan2022's last observation Dec2021 and successive prior-month endpoints.

[Regular launch May2022](https://www.newyorkfed.org/newsevents/news/research/2022/20220518)
and [revisions/methodology](https://libertystreeteconomics.newyorkfed.org/2022/03/global-supply-chain-pressure-index-march-2022-update/)
exclude interpreting pre2022 back-history as information available then. V108 selects
43 vintages May2022–Nov2025, all43 have both current/prior-month cells. Numeric
counts296…338, endpointApr2022…Oct2025; this says nothing about signal direction.
Availability is conditional labelled-month end New York, not witnessed release or
immutable original-vintage proof. Dec2025 maps into Jan2026UTC and is excluded.
Raw later macro columns remain quarantined and never enter feature conversion.

## Backup recovery, no source rerun

Recursive SCP stalled on terms.html at98304/137938 bytes. Only the verified task-owned
local SCP25488/SSH24636 processes were cancelled. Partial copy preserved as
`partial_recursive_copy_v1`; main AlgoPack archive and source unit untouched.
Server-generated single archive `capture.tar.gz`: 68515 bytes, SHA
`cd251a594d2a71d9d9d9470fa3e6f7d9ecadaef810e3ed336ffc7bf9cb077975`.
Single-file transfer succeeded; ten safe regular members extracted into fresh local
canonical capture, all hashes verified. First local verification hit a BOM decoding
error after extraction; utf-8-sig verification succeeded without overwrite/re-extract.
Copies/raw remain outside Git; no extra HTTP or changed source evidence.

## Pre-economic checks

26 new /85 combined synthetic tests PASS, Ruff clean. Fifteen futures input
bytes/schema/date checks PASS, no market magnitudes loaded during preflight.
Next: [V108 protocol](V108_SUPPLY_CHAIN_PRESSURE.md), immutable code/config/input
seal and commit before new source values/targets/economics. Goal20–50 not verified.
