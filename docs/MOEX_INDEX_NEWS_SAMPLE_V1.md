# MOEX index news: fixed source sample before catalogue

2026-09-08. The user challenged timer-only work; research resumes with this bounded
source check while the existing AlgoPack startup remains autonomous and unchanged.
This protocol does not authorize prices, labels, model fitting or event returns.

## Question and scope

Can the documented anonymous ISS article API supply replayable historical publication
metadata and separate body fragments for the already documented index examples?
The complete intended event period remains2012–2025, with2011 publication lookback.
This nine-article sample tests format only; it is not a representative economic sample
or a claim that the complete archive, event universe or trading opportunity exists.

Fixed IDs:298,511,63504,63621,75276,75298,75466,78049,78230. These come from the prior
[source feasibility note](MOEX_INDEX_REBALANCE_SOURCE.md): old mixed-index/mixed-date
announcements, three repeated regular announcements and an extraordinary halt case.
IDs were selected before any associated market outcome; their returns are not read.

## Acquisition and evidence

Only `https://iss.moex.com/iss/sitenews/{id}.json`, two anonymous requests per fixed ID:
first `content.columns=id,published_at`, then `id,title,published_at,body`. Require
`2011-01-01 <= published_at < 2026-01-01` and matching ID BEFORE requesting any body.
Second response must retain that exact identity/date. Use `iss.only=content`, no site
HTML/current widgets, no API token/netrc/proxy environment, no redirects or retry.
Timeout30s, body limit1MiB, at least0.25s between request starts, maximum18requests.
Raw bytes stay on gpu-mlserver outside Git, with actual request/response receipt times,
SHA256/size/status/URL/schema evidence. Unknown timestamps, drift, unexpected schema,
access denial or budget exhaustion stop this attempt; failed directories are retained.

The source seal contains exactly config, implementation, their synthetic tests, this
protocol, both package initializers and pyproject.toml. Publish seal/commit before the
first persisted sample. Do not edit this byte closure after collection. The full
catalogue prototype is deliberately disabled; a full-corpus successor needs separate
review/seal, explicit missing periods and revision/dedup/instrument coverage.

## Pass means format feasibility only

All9articles/18responses must pass raw replay, identity, strict schemas, prior clock
binding and normalization equality. Preserve paragraphs; do not assign a single effective
date to an article or translate a waitlist/free-float mention into a confirmed inclusion.
`available_at=null`, timezone unverified, original version unverified; model/economic/live
admission allfalse. Current publisher timestamps do not prove original historical bytes.

No downloaded text is committed or republished. This limited internal source-format
inspection does not establish commercial/index-data rights. Full automated use and
economic admission remain separate from public API accessibility and sample PASS.

After collection: audit once, inspect these paragraphs for per-index action/date and
revision issues, then decide whether a full source corpus is feasible. Do not build a
neural model or backtest these convenient examples. Source counts are not trade counts.

## Commands (after push/deploy, GPU server only)

`python -m market_lab.stocks.moex_index_news_source_v1 --sample --storage-root
/srv/trading_lab_data --seal-sha <published-seal-sha>`

`python -m market_lab.stocks.moex_index_news_source_v1 --audit <exact-output>
--seal-sha <published-seal-sha> --manifest-sha <observed-manifest-sha>`

Run once under trading-lab without collector.env. A failed or existing output is never
overwritten or erased. No recurring service or change to the paper service is required.
