# Latest completed witnessed-flow selection V1

2026-09-08. `src/market_lab/futures/algopack_paper_flow_selection_v1.py`.
Full activation and own SHA required. F=null. Selection inspects metadata, never prices,
predictions, returns or target labels. Fixed source root from predictor V1.

Freeze actual selection_cutoff. Enumerate canonical capture IDs only; skip incomplete,
pre-F, future-started and prior-Moscow-day names before manifest/artifact reads.
For current-day post-F candidates require exact name/start identity, protocol/seal,
ordinary files and available_at≥started_at. Choose maximal (available_at,capture_id,
manifest SHA) among available_at≤cutoff; deterministic identity tie-break. No ranking
by values/coverage/predictions/profit and no nearest profitable fallback.

This is selection by completed-source metadata, not a claim of original public
availability or that filesystem publication occurred by that timestamp. Actual
metadata observation and subsequent predictor replay/publication/consumption clocks
remain separate; only latter clocks can admit inference inputs. Current-day restriction
matches the intraday same-day feature window; absent sources remain explicit missing.

Malformed eligible metadata fails selection, not silently skip to older source.
Chosen capture goes through full predictor import replay. Replay failure cannot become
missing or choose another source. Existing imported key is observed/replayed, hash
checked against selected manifest and reused without overwrite. Partial import blocks.
Selector does not combine several archives to optimize completeness.

Missing selection returns reference=None. Scheduler must persist selection outcome
and pass it to slot runner; no CLI/scheduler or production HTTP is started here.
Unified runtime, offline economic audit/evaluation wiring and full pre-F publication
still needed. Source selection alone proves neither execution nor20–50% income.

9synthetic tests: activation, completion-vs-start ordering, future completion, pre-F/
incomplete skip, bad metadata/no fallback, missing reference, replay error/no fallback,
existing import/replay/no overwrite and partial import refusal. Import reuse fixture
stubs full predictor audit; parent predictor suite covers actual synthetic projection.
