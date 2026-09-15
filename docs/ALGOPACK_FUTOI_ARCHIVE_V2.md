# FUTOI archive V2 — retain unpaired provider observations

2026-09-15. Source-only correction of [V1](ALGOPACK_FUTOI_ARCHIVE_V1.md), not a new
economic hypothesis. Same [user archival authorization](
ALGOPACK_RESEARCH_AND_ARCHIVE_AUTHORIZATION_20260915.md), no2026 observations/PnL/live.

## Observed V1 failure

Pre-request commit5af65e1, seal8cb976fa0276ed76cc704f2c5f104bdd0d7a307d7c44c9bf7edb1933cb9a7ff2.
Server62tests and core4 manifest/artifact verification passed. One service launched
2026-09-15T08:38:18UTC; first all-market2024-10-15 response failed unpaired_sequence.
Zero completed days/raw pages; status and failed service retained, no canonical reset.
This proves not every ticker/sequence in that response had a synchronized FIZ/YUR pair.
It does NOT yet identify affected tickers or whether a client group was wholly absent.
No malformed raw response or token was printed. Independent14-family archive unaffected.

V1 wrongly made feature-pair completeness a raw preservation prerequisite. V2 retains
unique dated group observations and explicitly counts paired versus unpaired sequence
points. For all-market latest discovery require one latest row per present ticker/group,
not synchronous sessions/sequence/time between groups. For a ticker's intraday history,
derive each group's last row independently and require the full set to match discovery.
Keep every group/sequence row, all columns and SYSTIME. Do not fabricate the other group,
align asynchronous rows, drop values, or claim economic feature readiness.

## Unchanged bounded workflow

Official [all-market](https://moexalgo.github.io/docs/api/get-all-futoi/) and
[ticker](https://moexalgo.github.io/docs/api/get-futoi-for-ticker/) routes only.
2192calendar days2020-01-01…2025-12-31, first2024-10-15,2020-05-04,2025-12-30,
then remaining dates descending. date+latest=1 discovery supplies historical tickers;
one from=till intraday request per ticker, no offsets or column projection. Strict
exact-date, valid identifier, row width, duplicate-key and <1000row-cap guards remain.
Unknown schema, cap hit or per-group final-proof mismatch stops incomplete, not a retry
under loosened source rules. Empty discovery days remain explicit.

Reuse core4 only if all12columns, covered date/ticker and current last values exactly
match preserved daily-last proof, excluding only mutable SYSTIME. The78.7MB exact copy
is already on server at /srv/trading_lab_data/data/algopack-archive/futoi_core4_preserved_20260831;
do not transfer/download it again. Manifest
cc432d5938e8b824339975e2d84b29fe3c24219c505c9dfefc4baeb3db46a1ed,
all4artifact hashes checked before HTTP. Otherwise retain old vintage and save new day.
V2 has independent code/config/seal/root; V1 bytes and its failed root remain unchanged.

Only gpu-mlserver UID999, new root
/srv/trading_lab_data/data/algopack-archive/algopack_futoi_archive_v2_<seal12>.
Existing sealed14-family transport/atomic-page functions reused unchanged. Secrets only
EnvironmentFile, apim HTTPS with pinned CA, no redirects/logged credentials. Serial1sec,
bounded5/15/45second transport retries,16MiB response cap,100GiB supplement ceiling and
128GiB free-space reserve. No Windows collectors, purchases, renew changes or brokerage.

Lossless raw gzip, compressed/raw SHA, URL/receipt/schema/date/group-quality evidence;
day manifests bind complete discovered ticker plan plus external core4 references.
Single writer, resume by verified committed pages without duplicate HTTP; partial temp
directories retained. Altered/missing committed source is not autohealed. Final manifest
only after2192complete/empty day manifests; status.json is not completeness proof.
Restart=no, manual same-identity resume only after actual terminal failure investigation.
No original-version/PIT/economic admission, no post-expiry usage-rights guarantee, no
redistribution. Archived rows are not strategy returns; CAGR/Sharpe/MDD not applicable.
