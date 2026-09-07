# Calendar policy V1 — prospective version selection

2026-09-08. Fixed rule implemented before any actual forward outcomes, but not yet
included in an actual activation seal. F=null. No new strategy or model fitting.

One canonical key `calendar_YYYYMMDD` per weekday. Capture may begin only during
09:00:00 inclusive to09:05:00 exclusive Moscow time. Source STARTED makes even a
failed attempt immutable; no second attempt under the same key. No fallback to another
key or later revision. All page requests/receipts and completed capture durability
must be within that interval for report calendar eligibility. Late success is retained
but classified LATE_CALENDAR, not promoted to timely.

Build starts at the calendar date of F, never a caller-selected favorable start date,
and enumerates every date through an explicit matured end date (18:20:30 Moscow).
Weekends remain strategy-out-of-scope, not exchange-closed. For every weekday read
only its canonical source, fully replay raw/durable evidence, and retain OPEN/CLOSED/
UNRESOLVED status. Missing, late or unknown weekdays make expected_days=null for the
whole interval. Corrupt canonical bytes cause an error, not fallback or day removal.
Known closed days remain in the decision ledger even though excluded from expected_days.

Policy deliberately freezes the morning version. A later schedule amendment is not
retroactive evidence for deleting a failed day. Trading eligibility still requires
contemporaneous per-instrument intraday session evidence; morning OPEN is not permission
to trade through a later closure. Additional-source versions may be archived separately,
but cannot substitute this canonical denominator. Any policy change needs a new
prospective protocol, not selection against already observed PnL.

Digest binds protocol, activation, all decisions and canonical source hashes/replay
digests; reread observation clocks remain explicit but outside the stable digest.
calendar_source_verified means this fixed calendar-source policy resolved, NOT report
or economic admission. report_admitted=false and execution_admitted=false always.
Caller-supplied expected_days is not trusted merely because this helper exists.

## Required integration

Before passing expected_days into economic evaluation, a report wrapper must check
the full ledger for excluded dates: no economic activity or carried/unresolved exposure
may be hidden by an official closure or an out-of-scope weekend. An empty expected
calendar is not proof of profit. Missing calendar must block metrics rather than call
the evaluator with a shortened tuple. Bind the wrapper/policy/source/core in activation.
Runtime must schedule this canonical attempt before inference, without backfill.

11 tests: fixed key/window, pre-HTTP timing/closure gates, missing/timely/late source,
stable digest on later audit, no alternative-key fallback, closed day exclusion ledger,
complete period with unresolved weekdays and explicit weekends, immature period and
corrupt source rejection. Local3PASS/8Linux skips; server verification separately.
