# Calendar source V1

2026-09-08. `algopack_paper_calendar_source_v1.py` adds current-calendar-day capture
and durable raw replay, using existing activation, pinned CA and journal primitives.
No CLI, scheduling, production activation, token loading or actual HTTP run.

Before any HTTP verify full activation, execution-source dependency closure and own
calendar-source/core hashes. Request only the current Moscow day after F, on the
closed futures off_days route. No historical/year-wide request is exposed here.
This scope suffices for daily prospective observations; the pure core supports wider
single-year intervals but that does not authorize those requests through this adapter.

Transport rejects ambient auth/proxies, redirects, non200, responses above2MiB,
10second deadline, empty/secret-reflecting content and day-boundary crossing. Uses the
existing pinned application CA. Returned steps contain raw base64/hash, exact URL,
actual request/receipt/validation times and independently replayable normalized rows;
never credentials, headers or provider error bodies. Failures expose only phase labels.

Collect records STARTED, exactly one data page plus explicit empty terminal page,
each durable RESPONSE, then COMPLETE after full date/pagination replay. FAILED retains
any existing responses. Duplicate/partial attempt keys block overwrite and new HTTP.
Each successful capture has a separate key; no automatic retry or revision selection.

Observe validates activation/root references, COMPLETE scope, exact child keys,
original response-to-durable chronology, all raw hashes/schema/normalization and the
combined digest. Its observation time is actual reread time, not original availability.
The original durable timestamp remains separately exposed. Raw source replay does not
select expected report days: calendar_source_verified=false and execution_admitted=false.
No later revision silently replaces an earlier capture.

14 tests: fake HTTP TLS/secret behavior, changed normalization/raw hash/URL/day/time,
bad response sanitization, closure/ambient auth before HTTP, plus4real Linux journal
tests for full replay/no overwrite, retained partial failure, corrupt saved bytes and
hash-valid forged normalization. Local10PASS/4Linux skips; server result separately.

Next: pre-F sealed version-selection/cutoff/amendment policy and report integration,
then report persistence/CLI, latency, full activation config/seal and server service.
Source/calendar collection remains unactivated. Models and strategy economics unchanged.
