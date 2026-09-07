# Paper calendar core V1

2026-09-08. Pure primitives in `algopack_paper_calendar_core_v1.py`; no HTTP,
credentials, filesystem access, actual calendar, model or economic run.
Official schema rationale: [source discovery](ALGOPACK_PAPER_CALENDAR_DISCOVERY_20260908.md).

CalendarWindow requires exact dates within one year. Closed futures off_days URL
requests show_all_days=1 and five explicit columns. Raw replay requires ordered
pages with exact start offsets, serial request/receipt chronology, bounded bytes,
an explicit empty terminal page and exactly one row for every inclusive calendar date.
Vendor update may not follow receipt. Extra blocks, malformed flags, out-of-range
dates, duplicates and incomplete coverage fail rather than shorten the denominator.

OPEN requires integer1 and N/T/W reason; CLOSED requires integer0 and H reason.
Null or contradictory fields remain UNRESOLVED. A W row needs a later session date;
other rows with a different linked date are unresolved. This is conservative semantics,
not confirmation of the live vendor response. Calendar date is never replaced by the
linked session date. Weekends are explicitly strategy-out-of-scope, not exchange-closed.

Digest binds normalized rows, raw response hashes, URLs and request/receipt clocks.
Separate revisions produce separate digests. This pure function cannot prove that a
caller-supplied clock is an actual durable observation, nor authentic HTTP origin.
Accordingly RAW_CALENDAR_REPLAYED_NOT_ADMITTED and calendar_source_verified=false.
No expected_days tuple or selection policy is silently substituted into the evaluator.

21 synthetic tests cover request scope, flags/nulls/contradictions, weekday holidays,
weekend-to-Monday labels, missing/duplicate/reversed/out-of-scope dates, future updates,
pagination, chronology/cursor, revision identity and extra blocks/year boundaries.
Local core+evaluation38 PASS, Ruff check PASS. Server verification recorded separately.

Next: activation-gated HTTP/durable journal capture and raw replay; preregistered
calendar version/cutoff/amendment policy; report expected-days provenance binding.
Then report persistence/CLI, latency, complete config/seal and future activation.
No change to trained models, frozen parent seals, strategy economics or F=null.
