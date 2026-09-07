# Numerical forecast/source replay V1

2026-09-08. `src/market_lab/futures/algopack_paper_forecast_audit_v1.py`.
Full activation and own SHA required; F=null. No model refit or outcomes/labels.

Observe immutable forecast and validate identity, pinned model hashes, original F,
input cutoff/completion/durable clocks. Fixed source list: market packet plus optional
witnessed flow, in that order. Check source durable availability before saved original
observation and cutoff. Replay actual raw market packet and witnessed source, derive
plans/bars/flow versions. Source replay uses current actual audit clocks.

Separate immutable dataclass copies reconstruct original availability from the saved
durable observation evidence. They never replace live observations or rewrite source
records. Rebuild target-free features with original E/cutoff/F, load only pinned model
bytes, calculate both arms and reconstruct original completion mask. A late completed
forecast remains missed/None; it cannot become a new valid historical trade signal.

Compare entire canonical candidate, including features/provenance/contracts/statuses/
prediction values and timestamps, not only model name or output shape. Any difference
fails exact replay. No tolerance tuning, model selection or fallback source. Audit
returns actual audited_at and forecast_recomputed=true only on exact match.

## Remaining economic admission

FORECAST_RECOMPUTED does not prove profitable forecasts, independent exchange fills,
historical PIT training or full runtime coverage. Combine with execution-binding replay,
daily/report/evaluation provenance and official calendar; configure service and complete
pre-F publication before actual experiment. No actual production audit/run has occurred.
No live trading, target_income_verified=false. Original clock evidence relies on sealed
runtime/durable journal, not a third-party independent timestamp certificate.

7synthetic tests: no activation, price-only/price-flow reconstruction on later audit day,
hash-valid altered prediction or contract rejected, original late-completion mask,
corrupt raw flow rejection. Fake HTTP/model bytes with real source parsing/projection,
numeric inference, source hashes and durable Linux journal. No actual market values.
