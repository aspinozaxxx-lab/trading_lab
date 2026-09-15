# FUTOI archive V3 — exact final sequence proof, preserved V2 raw pages

2026-09-15. Source-only preservation under the [user's permission](
ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md), no strategy/fit/PnL/live.

## Specific source evidence before this correction

V1 stopped on unpaired VI source observations, without saved raw. V2 correctly kept
those observations but incorrectly compared the latest observation of EACH client
group with the official latest snapshot. Two complete days2024-10-15/2020-05-04 passed
85page raw/hash/date/proof audit,26949intraday rows,46/37tickers. Third day2025-12-30
stopped at MY: all-market latest contains only FIZ at(session7471,seq58,23:50), while
the intraday endpoint also retains YUR's earlier(session7470,seq93,11:55) observation.
FIZ's entire stable row matches exactly; no stable value discrepancy in that row.
V2's comparison wrongly appended the older YUR observation, causing hash mismatch.

V3 compares the rows at the final common(session,sequence,time) point, allowing one
or two client groups, with the exact all-market latest snapshot. All intraday rows,
including the older YUR observation, are preserved. Missing groups are not fabricated,
shifted or silently turned into zeros. All-market discovery still requires one final
sequence point per ticker. Real final-point discrepancies remain fail-closed.

The API returns13columns including trade_session_date, absent from the old12-column
core4 bundle. This extra information is retained, so those responses are not replaced
by the old bundle. MY's2025-12-30 evening observation has trade_session_date=2026-01-05:
that is a future assigned session label, NOT a2026 observation, price, return or PnL.
All request and tradedate bounds remain2020–2025; no2026 trading values are requested.

## Reuse rather than re-download

V2 is terminal failed, PID0. Keep its code, status, two day manifests and partial
third day untouched. Before V3 network, verify pinned V2 identity/status and the
120page metadata SHA inventory (config). Each referenced raw gzip is hash/date/schema
replayed before use; new day manifests include source_root plus original page identity.
No V2 bytes are copied or overwritten, no committed V2 request is sent again. Hold
V2's existing writer lock read-only plus V3's new writer lock for the whole run.
The resulting logical archive depends on BOTH V2 and V3 roots; future backup must
retain those roots and any referenced core4 bundle, not V3 alone.

V2's parser/transport/page primitives are reused unchanged. V3 adds final-point
proofs to referencing manifests without rewriting the older page's per-group metadata.
Code/config/tests/protocol and transitive V2/archive closures sealed before HTTP.

## Scope and operational controls

Official [all-market](https://moexalgo.github.io/docs/api/get-all-futoi/) date+latest=1
and [ticker](https://moexalgo.github.io/docs/api/get-futoi-for-ticker/) from=till routes.
2192calendar days2020-01-01…2025-12-31, pilots2024-10-15/2020-05-04/2025-12-30 then
remaining dates descending. Universe comes from each historical day, not current
survivors or numeric ranking. All fields, exact date, safe identifiers, unique
sequence/group keys, correct row widths, fewer than1000rows and exact final proof.
No offset pagination. Empty discovery days are explicit, not omitted.

Server-only UID999, separate algopack_futoi_archive_v3_<seal12> root under
/srv/trading_lab_data/data/algopack-archive. One-second request interval, bounded
5/15/45second transport retries,16MiB response cap,100GiB new-root ceiling and128GiB
free-space reserve. Token only existing EnvironmentFile, apim HTTPS/pinned CA,
no redirects, secret logs, Windows collectors, new payment or subscription changes.

Atomic lossless gzip pages with raw/compressed hashes and actual receipts. Resume
verifies committed pages without HTTP; existing manifests cannot be replaced.
Partial temporary paths remain. Restart=no, manual same-identity resume only after
failure investigation. status.json is operational, not full coverage evidence.
Final manifest requires all2192days and discovered ticker-day proofs; no economic,
PIT/original-vintage, redistribution or post-expiry-rights admission is implied.
Source download is not a20–50% income result; CAGR/Sharpe/MDD remain inapplicable.
