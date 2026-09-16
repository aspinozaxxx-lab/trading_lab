# EIA consensus — bounded source feasibility, not a new economic result

Declared 2026-09-16 after V96 rejection, before archived calendar page fetches.
No V97 strategy/seal/run exists. V17 raw inventory changes remain closed; a fitted
normalization of those same observations is not an independent analyst consensus.

## What changed

The public [Forex Factory calendar for 2025-06-04](https://www.forexfactory.com/calendar?day=jun4.2025)
shows Actual / Forecast / Previous for Crude Oil Inventories. It is rendered today,
not proof of what the page displayed before the release. Some of these 2025
macroeconomic numbers were visible during source discovery; no new market returns,
strategy targets or PnL were computed. The interrupted earlier selection turn is
unfinished selection, not another experiment or result.

Wayback CDX read-only query at 2026-09-16T18:47:52.794186UTC returned 1262 day-collapsed
captures of `https://www.forexfactory.com/calendar` for 2021–2025, 143467 bytes,
SHA `e0afb5e411833d4aae08a204b90d3d6cc711bfdfc6ac85c543f109c81786b0e2`.
Range `20210101064631..20251228174814`. This initial response was not persisted;
the hash/count record alone is not a reproducible full source bundle. The analogous
`http://www.forexfactory.com/calendar.php` query returned a three-byte empty result.
Neither catalog count proves forecast coverage or pre-release availability.

## Bounded next check

`scripts/probe_eia_consensus_archive_20260916.py` fetches only the first two already
observed Monday/Sunday captures, `20210104164842` and `20210110095453`. These dates
were chosen from metadata, before forecast contents/outcomes, not by prediction
success. At most two requests, each 30 seconds and 8 MB, no redirects, retry,
authentication, cookies, JavaScript execution or current-page fallback. An access
refusal stops the check. Private raw responses, headers, retrieval clocks and SHA
remain in a new external server directory, never Git. This is a one-shot probe,
not a new scheduled collector or a trading engine.

To admit a future source: verify the *actual* archive timestamp, historical event
date/time/zone, forecast present while actual is absent, and capture strictly before
the corresponding official EIA release. Later revisions must not be backdated.
If the sample is empty/blocked/post-release, do not manufacture a forecast from
realized inventories or call the unchanged current website point-in-time evidence.
No bulk collection or economic run is authorized by this source-only note.

## Other checked routes and scope

[Trading Economics point-in-time documentation](https://docs.tradingeconomics.com/economic_calendar/point-in-time/)
describes historical calendar retrieval; its authentication documentation requires
an API key/plan. No such credentials were supplied, no account/purchase/API call
was made, and original forecast-version semantics remain unverified. A guessed
Nasdaq calendar route returned HTTP404 on a header-only check; that says nothing
about all Nasdaq offerings. No paid route is selected by default.

An optional question about expanding preliminary AlgoPack<=2025 screens beyond the
completed narrow V79 exception was re-issued once at about 18:48UTC, after the
previous day's unanswered question. The input panel accepted the question; that is
**not user approval**. No answer received at declaration time. Do not ask again on
every automatic continuation, and do not admit OrderStats/HI2 economics until an
actual answer permits it. Downloading remains separately authorized and running.

During earlier broad web discovery, incidental 2026 market-news snippets appeared.
They were quarantined: not imported, used to design a signal, evaluated or quoted
as evidence. Do not claim that exposure never occurred or use it to justify a
2026 backtest. Continue using dated <=2025 sources and known documentation URLs.

All historical research remains development selection. Goal20–50% unverified;
29 completed portfolio hypotheses, 0 Stage2 candidates. This check increments
neither count. No model training, market labels, trades, live or demo activation.

## Initial sample completed; bounded Tuesday follow-up declared

Initial source script SHA `1cfdb07071aeb5ca51e6f13748759e6bc6eca085cd720acd82ceb0e099939f3a`,
pre-fetch commit `6f5b23e`, Ruff PASS.
Both GETs returned200 at18:58:03/18:58:05UTC, and both Memento-Datetime headers
match the requested 2021 archive timestamps. First page288224bytes, SHA
`2730676156b0966b85accfb836e82d0949974778d382968c2cbd0d49b39fdaa3`:
calendar exists, oil row118695 has neither actual nor forecast yet. Its printed
timezone is GMT−5/DSToff. Second page17948bytes, SHA
`f4a36d4dd36521abe56ee53c6fd98c8182f5f17e6230de0b579a672a4d1dd44a`:
no title/calendar/oil label. Neither page yields an admitted forecast.
Private report `source_evidence/eia_consensus_probe_20260916_v1/report.json`, SHA
`06bbc5fc3c627b5d6649306d55b61f974bf86fdba2e81b958578f7ff8e82f712`.

The Monday forecast was not posted yet. One final bounded feasibility sample moves
closer to publication: earliest **Tuesday** capture in each calendar year2021–2025,
chosen from the same CDX metadata, before those page contents, without market
outcomes. No sample expansion after these five outcomes in this investigation.
This changes source sampling, not a rejected trading rule. It is not a bulk crawl.
Selected stamps:
`20210119074920`, `20220104193106`, `20230103091601`, `20240102181232`,
`20250225104806`. Some selected weeks include holidays; not swapped for convenient
normal weeks after inspection.

The CDX response was persisted at19:01:28.218437UTC under a separate
`source_evidence/eia_consensus_tuesday_probe_20260916_v1/cdx.json`, identical to the
initial143467byte SHA above. It has461 plain `/calendar`,800 trailing-slash URLs,
and1 empty-query URL. A preceding metadata-only assertion failed because it
expected only the plain path; it wrote no output and read no calendar values.
`scripts/probe_eia_consensus_tuesday_20260916.py` pins this exact catalog, preserves
each original URL and uses the same no-redirect/no-retry/access-refusal policy.
Its new `captures/` must not exist; no original sample files are changed.
Tuesday script SHA `70d3186760b2da01aaf758e1829744c896ab8337ac96b258db1e51c03f4c2461`,
Ruff PASS before page fetches. Neither script reads credentials or market bundles.

## Final outcome — limited source evidence; rights unresolved, no economic run

Pre-fetch commit `92a328d` was pushed, Tuesday script bytes were checked on the
server before execution. All five requests returned200 at19:04:03–19:04:11UTC,
with exact requested Memento-Datetime, without redirects, credentials or retries.
This does not make every HTTP200 response a valid calendar.

| Capture year | Inspected oil event | Forecast before event | Limitation |
| --- | --- | --- | --- |
| 2021 | January22,11:00, GMT−5 | Empty | Early holiday-week capture |
| 2022 | January5,10:30, America/New_York | Present; actual still empty | One example only |
| 2023 | January5,11:00, America/New_York | Empty | Early holiday-week capture |
| 2024 | January4,11:00, America/New_York | Empty | Changed HTML/embedded JSON |
| 2025 | No usable calendar in captured body | Unknown | Do not interpret as zero forecast |

The 2022 capture is `2022-01-04T19:31:06Z`, earlier than its displayed event
`2022-01-05T15:30:00Z`. It provides a genuine archived pre-event forecast example,
not verified multiyear coverage, a first-published consensus series, a checked join
to all official EIA releases or evidence of a profitable trade. No market outcomes
were computed. The simple HTML projection missed the changed2024 row class; direct
inspection of its already-stored event JSON/HTML confirms an empty forecast. Do not
treat that parser miss as evidence that the event did not exist.

Artifacts outside Git:

- Tuesday `captures/report.json` SHA
  `c8a396d434bcc0cecd0b4c951cf8bc2b1c53e474107fd353ca5f5f7603336500`.
- `calendar_projection.json` SHA
  `5847110dc2988989bf824b4952e847da91f2877bcd0731873f2b1829bd8acc1b`;
  this limited projection is not an economic input or a complete2024 parser.
- Raw/body/header hashes and receipt clocks are in the reports. Preserve the two
  distinct source roots; never rerun these once-only scripts into them.

The [owner's current notices](https://www.forexfactory.com/notices), inspected after
the bounded sample, restrict copying of its compiled economic-calendar database.
Public/Wayback access alone does not establish rights for a historical corpus.
**Do not bulk-download, redistribute, fit or backtest this source without an
appropriate rights basis.** Existing limited feasibility samples remain private,
unadmitted and outside Git. No new permission request, purchase or external message
was sent to the owner. This is a branch-level rights/source gate, not rejection of
the inventory-surprise mechanism and not a reason to halt the paid AlgoPack archive.

The [Bank of Canada2020-8 landing page](https://www.bankofcanada.ca/2020/03/staff-working-paper-2020-8/)
was checked for an openly supplied alternative: the inspected page links its paper,
not a downloadable consensus dataset. No PDF was opened or replication data
downloaded. This is not proof that no other permitted dataset exists. Its unrelated
current navigation/news snippets are excluded from research inputs and decisions,
as are earlier incidental2026 web snippets.

No further sampling/bulk collection/parser framework for this branch now. Resume
only on concrete new source/rights evidence; otherwise choose another independent
permitted information set. Broader AlgoPack approval remains unanswered. V96 stays
the last completed economic test;29portfolio/0Stage2 and goal status are unchanged.
