# Runtime readiness cost — actual traversal, synthetic activation

2026-09-08. Pushed3c6bb03 before exact test-only deployment to gpu-mlserver.
`test_algopack_paper_readiness_cost.py` builds an isolated2099 activation in pytest
temporary storage. Copies89 code/config/document dependencies, including actual frozen
training/witnessed parent closures. No production activation, models, prices, labels,
network, credentials or portfolio read. Only activation clock is substituted; runtime
ready traversal and full dependency hashing/stat checks execute unchanged.

Linux UID999 result:1PASS0.69s, process exit0. Three consecutive runtime.ready calls:

| Sample | Seconds | Full activation reloads |
| --- | ---: | ---: |
| 1 | 0.107874381 | 39 |
| 2 | 0.103963713 | 39 |
| 3 | 0.104133312 | 39 |

The test also mutates a dependency in its temporary copy and confirms next readiness
rejects it. No production file changed. Local test correctly skipped Linux-only runtime;
Ruff/diff PASS. Temporary root `/tmp/algopack_readiness_cost_3c6bb03_tests`, separate cache.

Interpretation: duplicate transitive readiness is real, but this warm-filesystem sample
does not by itself exhaust5s quote freshness or30s fill window. It is NOT total tick cost,
network latency, concurrent-worker load, cold-cache bound, tail percentile or SLA. The
0.1s polling sleep is additional, not an achieved0.1s service period. Actual activation
may have a larger closure. No timing assertion or weakened verifier was introduced.

Next measure integrated due/slot/source-observation/ledger work and process sandbox with
synthetic inputs. Avoid premature global readiness caching: current checks detect code
changes and time-bound admission, which an unchecked cache would bypass. Actual F=null,
no service start and no independent income result.
