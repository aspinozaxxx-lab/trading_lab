# AlgoPack paper: official calendar discovery, 2026-09-08

Status: documentation/source discovery only; no calendar API request, token access,
market prices, forecasts or economic run. F remains null. This is not a sealed
calendar admission protocol or implementation. Existing evaluator/runtime unchanged.

## Confirmed official interface

[MOEX AlgoPack calendar documentation](https://moexalgo.github.io/docs/description/calendar-iss/)
was read on 2026-09-08 through public HTTPS documentation (browser fetch failed;
PowerShell Invoke-WebRequest succeeded). The futures daily calendar endpoint is
`https://apim.moex.com/iss/calendars/futures.json`, with `show_all_days=1` and
`iss.only=off_days`. Documented columns:

| Column | Meaning |
| --- | --- |
| tradedate | Calendar date, distinct from the linked session date |
| is_traded | Integer 0/1, or null when information is missing |
| trade_session_date | Session date for an additional weekend session; may be null |
| reason | H holiday, W additional weekend session, N normal, T transferred |
| updatetime | Vendor update time, not our observation/publication receipt |

The documentation supports `from`/`till` within one year and `start` pagination.
Default output must not be assumed to enumerate every calendar date: explicitly
request all days and verify complete inclusive date coverage, including closed days.
The actual authenticated response/schema/entitlement has NOT been observed.

`/iss/calendars/futures/session.json` is a different source: dated intraday intervals
and a type dictionary. Existing execution source uses it for individual entry/exit
eligibility. It does not establish a complete reporting-day denominator.

## Why a static weekday list or annual announcement is insufficient

MOEX's [2026-09-04 schedule revision](https://www.moex.com/n103931) changes weekend
trading from November 28–29 to December 5–6. Thus a later official calendar can differ
from an earlier official version. Do not overwrite original receipts or use a later
revision to silently remove an earlier expected reporting day.

The current experiment deliberately schedules weekdays only. Do not add weekend
trading or map a weekend observation onto Monday merely because the official
`trade_session_date` refers to Monday. Calendar dates, session labels, model slots
and the 18:20 Moscow reporting clock are separate concepts. Holiday weekday trading
may be an additional session, not an ordinary session; day-open status alone does
not override the execution adapter's intraday eligibility checks.

## Implementation requirements before calendar admission

1. Add a separate versioned calendar-source adapter with a closed route/column list,
   TLS checks, bounded terminal pagination, exact unique date coverage and raw receipt
   hashes. Split multi-year periods into separate requests. No price fields/endpoints.
2. Preserve actual request, receipt and durable observation clocks plus every version.
   Null, missing, contradictory or unknown flags remain unresolved; never infer closure
   from a missing row or replace null with false. Strict integer checks reject booleans.
3. Seal an explicit selection/cutoff rule before F. Define how initial expected days,
   prospective schedule amendments and late/missing calendar observations are handled.
   Later versions must not retrospectively improve coverage by deleting failed days.
   This discovery note intentionally does not claim that policy has been implemented.
4. Bind the report's expected-day tuple to replayed calendar evidence and its sealed
   selection policy, not a caller-supplied digest. Keep a complete exclusion/unresolved
   ledger and distinguish a strategy-out-of-scope weekend from an exchange closure.
5. Test holidays on weekdays, weekend-to-Monday session labels, transferred days,
   null flags, duplicate/missing dates, year boundaries, revisions before/after cutoff,
   incomplete pagination and caller-tampered expected days before enabling admission.

Next: implement and synthetically verify this source/policy binding, then immutable
report persistence/CLI, latency verification and complete pre-F activation/service.
`calendar_source_verified=false` remains correct in the existing combined report.
