# SLOOS source review, 17 September 2026

The proposed economic question was stated before reading the full numeric corpus:
joint tightening of business credit standards and weakening demand may reduce oil
demand. BR short/cash, not a reconstruction of the academic bank-level credit supply
shock. Original-report reconstruction is **PAUSED**. The later conditional machine
export route does not establish original availability or erase earlier failures.

## Original PDF/HTML route — preserved, no V3

Source: [Board SLOOS](https://www.federalreserve.gov/data/sloos.htm),
[announcements](https://www.federalreserve.gov/feeds/sloos.html),
[Board terms](https://www.federalreserve.gov/disclaimer.htm).
Public aggregate definitions differ by bank/borrower population and weighting.
Large-bank size cutoff changed in October2023; the proposed rule uses **all domestic
banks**, with large/middle-market **borrowers**, not the large-bank subgroup.
The announcements document revisions. Quarter labels are not publication dates.

Canonical parent `/srv/trading_lab_data/source_evidence/sloos_feasibility_20260917_v1`:

- Initial startup at03:43:36UTC, invocation `f4c17e9e88d44abf989aa7dfd6649bd3`,
  failed before HTTP because the dedicated directory had not been provisioned for
  service UID999. No source artifact/run was overwritten. Original script hash
  `8c0d710dd85d91e7217d549cfa56c045b33e2fbcd8b257dae18bbb25e1be2988`
  remains in server staging. Dedicated parent only was then created/chowned.
- `capture`, complete03:46:17.548085UTC, **FAILED_SOURCE_NO_RETRY**,
  invocation `385321edd3f2497f8d06a5820e00f3f2`: three successful GETs, then old
  201710 narrative route mismatch. No report table/PDF requested in this attempt.
  Manifest `0faf4de5f35477e81838307c98d1aaf51095891485d2d1f904adb6047640d9ed`.
- `capture_v2`, complete03:50:52.389666UTC, **FAILED_SOURCE_PAUSED**,
  invocation `bda84f9ed46f45a3b2064dc20799b1d3`: reused six index/terms/feed files,
  four successful new GETs, then201802 table alias mismatch. 201710 narrative/table/
  PDF and201802 narrative retained. No201802 table/PDF or202510 request in this run.
  Manifest `81db0740a8cd2f3037c0ab76578a7c28b37d6d62e407c274008f3932f4c5b5e2`.

Both failures concern explicit route matching, not inaccessible survey values.
201802 links use `table1` and a PDF named201801; do not invent dates from filenames.
No third HTML/PDF resolver or whole original-release reconstruction is authorized
by this note. Local backup checked7+15 artifact hashes, with manifests separately.
Archives43900/2015209bytes, SHA
`13be2754a968e2b5884338e24a409ff146c650dfbe741796a974aa9e2ccbe4e6` /
`c64313a728fe7981ba56278ecf19cf1ec2f6cad93126fe35708cd63ed30220f9`.
Raw/PDF remain outside Git in matching local `D:\Projects\trading_lab_data\source_evidence`.

PDF skill: text extraction and page1 visual inspection of the actual201710 cover
agree: release2pmET **November6,2017**, not October1. PDF SHA
`09a36af4af43d94c850c8cf7bb743353b98cad95c41a2089ddaddc0213db9004`.
Only the cover was rendered; other137-page contents were not used for feature design.
Local Poppler font-path warnings did not prevent a legible verified cover.

## FRED current-vintage route — timeout, no data obtained, no further retry

Official identities:
[DRTSCILM](https://fred.stlouisfed.org/series/DRTSCILM) net standards tightening,
[DRSDCILM](https://fred.stlouisfed.org/series/DRSDCILM) net stronger loan demand.
Quarterly percent, NSA, same large/middle-market borrowers, all domestic banks.
[FRED terms](https://fred.stlouisfed.org/legal/) read through web tool; personal
research copies only, no redistribution or commercial service license inferred.

Parent `/srv/trading_lab_data/source_evidence/sloos_fred_20260917_v1`:

- `capture`, invocation `d86698fe850c434ca7121a76be4325e5`, completed04:03:34.418538UTC.
  Legal page HTTP000/curl28/30sec timeout/zero bytes, **FAILED_SOURCE_NO_RETRY**.
  No CSV requests. Manifest
  `7a3290b2918e1ac582aff74fdef348daa0866564b205de1cd2f2ddcff74ccc60`.
- `csv`, invocation `9124be550a3e4920bba0d59385f23b76`, completed04:09:24.770131UTC.
  First-ever DRTSCILM CSV request failed with zero bytes; DRSDCILM not attempted.
  The legal-page request was not retried, credentials/challenge/access controls
  were not involved. Manifest
  `cf5563ea95916bfebdd3be3413bafed9f98b26a05747d12c703c1083933c48be`.

These failures are source attempts, **not portfolio entrants, economic rejects,
evidence of zero signal, or completed backtests**. No FRED observations were parsed.
The draft CSV adapter passed synthetic tests only; it is not a sealed run.

## Separate Board machine export

The already captured official index explicitly links
`https://www.federalreserve.gov/releases/sloos/data/FRB_SLOOS_xml.zip`.
One bounded request was declared:5MB wire/50MB expanded limit, no redirects/retries,
schema-only inventory. This is current-vintage data with a conditional clock, **not
resumption of the original PDF/HTML route**. Other series and>=2026 observations
must be excluded before value inspection/conversion. Status/admission must come
from its actual manifest, not this request declaration.

Actual result: **COMPLETE_SCHEMA_ONLY**, one successful GET,
completed04:11:43.600421UTC, invocation `028fcd1b70114233b611238480fa25af`.
Root `source_evidence/sloos_board_20260917_v1/capture`, manifest
`92b003b1c7f8d88bb7bcfdf2e4536e1d60088cb427a41b9f7d24866291158903`, raw ZIP
`9e043b31aea376d3198fb04a94a7f8cd46e6983e1b45aea65c0bd5801f1fd0be`.
Selected definitions verified by XML annotations and exact attributes, not numeric
ranking. Standards `SUBLPDCILS_N.Q`, demand `SUBLPDCILD_N.Q`, both ALL/DOM/CILG.
FREQ162=Quarterly; period labels are quarter ends, not publication timestamps.
33selected quarters per series,66statusA/lexical numeric cells; no missing calendar.
No new magnitudes/directions/targets/PnL read in this metadata check. Five-file
local copy passed manifest+4artifact SHA checks. [V110](V110_BANK_CREDIT_SQUEEZE.md)
uses the separately disclosed conditional current-vintage assumption.
