# AlgoPack FUTOI archive V1 — full-market historical supplement

2026-09-15. Source-only preservation under the [user authorization](
ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md). No economic experiment,
model, price-based universe, old canonical rerun,2026 observation or paper activation.

## Frozen collection rule

Official [all-market API](https://moexalgo.github.io/docs/api/get-all-futoi/),
[ticker API](https://moexalgo.github.io/docs/api/get-futoi-for-ticker/) and
[SDK implementation](https://github.com/moexalgo/moexalgo/blob/main/moexalgo/features/futoi.py)
(observed Git blob bbfaeca32e8dc24fb048576cd70a577e86d8b3a5) identify date-bounded
all-market and from/till ticker routes. The existing core4 source proved latest=1
daily-last responses and the1000-row cap; start offsets did not advance that route.
The SDK is documentation evidence only, not a newly installed dependency.

For all2192calendar days2020–2025: first2024-10-15,2020-05-04,2025-12-30, then descending
remaining days. Request all-market date=day,latest=1 to discover that day's tickers,
not today's surviving contracts. Require fewer than1000rows, exactly one FIZ/YUR
sequence pair per ticker, exact historical date and a safe path identifier. Empty
days are recorded, not silently removed. If date/latest semantics differ, stop
incomplete; no ad-hoc fallback to undated/latest2026 routes.

For each discovered ticker request one exact from=till day, without latest or offset.
Require fewer than1000rows, unique(session,sequence,time,group) keys, complete FIZ/YUR
pairs, same schema and final sequence/value pair equal to the day's discovery proof.
Only mutable SYSTIME is excluded from final-value comparison; it is retained raw.
Repeated wall-clock times with different sequence identities are not deduplicated.
Preserve every returned column and exact response bytes, lossless gzip and receipts.
Coverage means complete retrieval under these API/cap checks, not independent proof
of every vendor observation or original historical availability.

## Reuse, persistence and safety

The local core4 canonical bundle exists and was byte-verified; it was absent at the
assumed server processed path. Preserve a separate exact server copy (no movement or
replacement), manifest SHA cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed.
All four artifact hashes are verified before HTTP. Reuse only a covered ticker/day
whose complete12-column schema and current daily-last stable values match the old
proof. Otherwise retain the old vintage and archive a new response, explicitly
recording the mismatch/extra-schema case. No old values or availability flags change.
The archive's new compressed-byte/downloaded-row counters exclude reused core4 bytes.

New root /srv/trading_lab_data/data/algopack-archive/algopack_futoi_archive_v1_<seal12>.
Code/config/protocol/tests plus existing archive dependency closure sealed before HTTP.
Reuse transport and atomic page primitives without modifying the running14-family
collector. Token only server EnvironmentFile, apim HTTPS, no redirects, pinned CA,
UID999, serial1second spacing and bounded5/15/45 retries. No local collectors.
100GiB supplement ceiling and128GiB free-space reserve; reaching either stops
incomplete. No new purchase, fee, tariff, auto-renew or redistribution authorization.
Rights after subscription expiry are not independently established.

Each durable response directory has raw and compressed SHA, URL, receipt, schema,
date/sequence counts and stable proof hashes. A day manifest binds all discovered
tickers, downloaded pages and external core4 references. Single-writer lock; restart
replays committed pages and verifies manifests without HTTP for those pages. Partial
temporary directories remain untouched. No overwrite/reset of canonical bytes.
Missing/changed proof, cap hit, schema change or exhausted transport failure stops
the supplement with incomplete status, without changing the independent14-family run.

Runtime is a bounded server service, Restart=no. status.json is only an operational
checkpoint, not completeness evidence. Final manifest requires all2192days and exact
day identities, including empty days. Full-market ticker coverage cannot be asserted
before actual API discovery and terminal audit. CAGR/Sharpe/MDD are null/not applicable;
no new strategy has passed because an archive was saved.
