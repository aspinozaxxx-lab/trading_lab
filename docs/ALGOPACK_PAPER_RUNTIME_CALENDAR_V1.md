# Runtime calendar integration V1, 2026-09-08

Unactivated runtime V1 now requires the calendar-policy/source/core closure and a
dedicated private `calendar` component under the activation root. Explicit initialization
creates it once; normal startup never creates or repairs missing components.

Each tick still pumps due exits/entries first. On weekdays during09:00–09:05Moscow,
scheduler reserves canonical calendar_YYYYMMDD work and invokes policy.capture with
the same server-only session/token. Returned durable reference is saved in scheduler
FINISHED; its status is RECORDED_CALENDAR_NOT_REPORT_ADMITTED. Actual timeliness and
eligibility are checked by the calendar policy when building the economic report.

Scheduler STARTED, even partial or failed, suppresses duplicate collection after
reopen. Failure invalidates runtime and retains sanitized FAILED_REOPEN_REQUIRED.
No calendar backfill outside the fixed window, no weekend job. Existing forecast,
daily snapshot and due pump semantics unchanged. Calendar does not replace current
instrument/session execution checks. The startup lifetime-lock correction is retained.

8 new synthetic tests: component requirement, pump-first/once/restart, both timing
boundaries, weekend, failed capture/reopen, pump uncertainty and missing-root refusal.
Local runtime/calendar/startup suite4PASS/13Linux skips; server verification separately.

This changes unactivated runtime bytes only. Before server replacement verify old
runtime SHA, absent activation and no running --serve process; retain old file explicitly.
Future activation must pin the current runtime hash. No actual --initialize/--serve
run, systemd service or calendar HTTP is authorized by file deployment alone. F=null.
Next: immutable economic-report persistence/CLI, latency and complete activation/service.
