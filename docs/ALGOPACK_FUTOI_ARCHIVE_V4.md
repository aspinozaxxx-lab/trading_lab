# FUTOI archive V4: preserve available history, explicitly report source gaps

2026-09-15, source-only correction under the existing archival authorization.
No new economic hypothesis, source/model admission, price/return/PnL calculation,
Windows collector, subscription change or broker operation.

## Evidence and bounded change

V3 stopped at2025-08-26 after129complete calendar days,7391ticker-days and2295881
intraday rows. The official daily discovery included AU, but the requested ticker
response passed schema checks and contained no rows: missing_planned_ticker_day.
V3 failed safely before persisting this empty response. Actual systemctl confirmed
failed/MainPID0/exit1; its stopped status timestamp is11:15:42.730848UTC.

For an archive, one unavailable ticker-day must not prevent saving the other dates.
V4 saves valid empty ticker responses, and both sides of valid daily/intraday
schema or final-point discrepancies, with UNRESOLVED_SOURCE_GAP and exact reasons.
They are not zero positions, proven absent trading, matched data or economic PASS.
The discovered universe and expected daily hash remain in the day manifest.
This policy applies to every requested day/ticker, not an AU-specific exception.

Malformed payloads, incorrect dates/tickers, duplicate keys, unsafe identifiers,
1000-row truncation risk, invalid sequence/group identities, changed stored bytes,
authentication and exhausted transport failures remain fail-closed. Daily discovery
must still contain one final common sequence point per ticker. No pagination guess,
extra retries, alternate dates or silent row dropping.

## Immutable reuse and controls

Verify pinned terminal V2 and V3 identity/status hashes and full page metadata
inventories:120V2+7404V3pages. Acquire both existing writer locks read-only and a
new V4 writer lock. Reuse each committed response by source_root/path/hash, replaying
raw gzip, date, schema and final-point identity without HTTP or copying raw bytes.
Do not restart, modify or delete either failed root. New canonical day manifests
belong only to V4. Partial V3's2025-08-26 pages are reusable too.

V4 no longer substitutes the separate old12-column core4 bundle for raw responses;
the expanded API13columns are retained. Keep core4 anyway for existing V3 references
and earlier research. A self-contained backup of this logical archive needs V4,
V3 and V2; retaining core4 keeps the older logical archives intact as well.

All2192calendar days2020-01-01…2025-12-31, same3pilot dates then descending remaining
dates; historical daily universe, all fields and original receipts. Same1second
request interval,5/15/45second bounded transport retries,16MiB response cap,
100GiB new-root ceiling,128GiB free-space reserve. Only apim.moex.com, existing
server EnvironmentFile token, verified source-scoped CA; no redirects/secret logs.
Server UID999 only; Restart=no transient service, no implied reboot auto-resume.

Code/config/tests/this protocol and transitive V3/V2/archive closures must be
sealed before the first new request. Parent modules and their frozen tests are
unchanged. Synthetic regression covers empty responses, genuine mismatch, continued
collection, unchanged fail-closed guards, old raw reuse, tampering and final totals.

## Terminal semantics

processed_days counts days with committed manifests, including explicit gaps;
it does not assert full source coverage. Report resolved/unresolved ticker-days,
days_with_gaps, actual intraday rows, reused pages and new-root bytes separately.
If every planned day is processed but any ticker-day remains unresolved, final
status is COMPLETE_WITH_SOURCE_GAPS, source_coverage_complete=false. COMPLETE is
reserved for no detected gaps; neither verdict proves original publication/vintage
or economic readiness. Missing returns and all economic metrics remain unknown.

Do not repeatedly download a persisted empty response. A future hole-recovery pass,
if useful, needs its own versioned plan; never overwrite this evidence. Runtime
checkpoint and precise unit/seal are recorded in ALGOPACK_FUTOI_ARCHIVE_STATUS.md.
