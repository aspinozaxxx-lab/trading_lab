# V80 — REJECT_STAGE1: GPR risk persistence did not earn money

2026-09-15. [Frozen protocol](V80_GPR_RISK.md). One new information set, one rule,
no model/grid/retune. Latest COMPLETE Russia GPR month relative to its prior12mean;
stress BR+/MIX-/SI+, reverse below average. Constant-stress control; full2022–2025.

## Economic result

| Arm / costs | CAGR | Sharpe | MDD | Closed asset episodes | Net RUB on initial1m |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPR /1x | -4.5783% | -0.4076 | 24.1416% | 99 | -170512 |
| GPR /2x | -4.7481% | -0.4252 | 24.6752% | 98 | -176386 |
| Constant stress /1x | -6.6661% | -0.6442 | 28.2978% | 75 | -240577 |
| Constant stress /2x | -6.7348% | -0.6505 | 28.3971% | 75 | -242805 |

| Year | GPR1x | GPR2x | Control1x | Control2x |
| --- | ---: | ---: | ---: | ---: |
| 2022 | -8.4008% | -8.7049% | -15.9177% | -16.0902% |
| 2023 | +3.6924% | +3.4968% | -1.1663% | -0.8210% |
| 2024 | -7.6553% | -7.8961% | +0.7071% | +0.5008% |
| 2025 | -5.4288% | -5.3607% | -9.2567% | -9.4672% |

Primary fails both CAGR>=5% and Sharpe>=0.5 gates, with only1/4positive years (<3).
Its CAGR excess over losing control is2.0878pp/1.9866pp; double costs fail the2pp gate
as well. Lower loss than control is not profitable alpha. MDD/trade count/worst-year
gates pass, but cannot compensate for failed income/stability gates. Stage2=0.

Primary gross VM -159513/-154865RUB before explicit10999/21521RUB costs, so the loss
is not only transaction costs. These are VM sums in each integer-sized cost scenario,
NOT an independently simulated zero-cost strategy. Filled legs310/305,turnover56.7049/
55.4633times initial capital. Control costs7485/14949RUB,legs193/192.
Maximum modeled participation0.60241% (<1%); primary maximum close gross0.91205/0.88844
(<portfolio cap1). All4executions complete,critical0,unresolved0,terminal flat,
no carried halts; each has1no-liquidity cancellation retained, not silently filled.

## Coverage and source

Before MOEX prices, separately persisted feasibility PASS:95.669291% source-ready,
3048asset decisions/1016dates per arm,46ready source dates.132feature-unavailable and
132stale-at-fill flags are overlapping, not264missing opportunities;17source-unavailable
plan/contract flags can also overlap. Each arm has2901nonzero targets/46used editions.
All early unavailable dates remain in the four-year cash/ledger period. Repeated daily
positions/99closed episodes do not mean99independent news shocks; only46editions.

Source V2 complete46first-commit DTA202203…202512,34298157raw bytes.562undated rows
retained and excluded from the dated feature window, no imputation. All46prior13windows
finite/in[0,100],invalid0. All46raw/history/commit/calendar replays passed before economics.
The2calendar-day delayed Git author/committer clock is still only an availability proxy,
not witnessed public push. No PIT/live admission. Historical candle/spec/fee/margin
proxies remain, no collateral interest or personal tax model.2026outcomes not read.

## Reproducibility

- Pre-outcome commit6299f8b pushed before GPR scalar and MOEX outcome loads.
- Config SHA8994ed63c232d5fc29740ebbba5e0d3a0980fb3636ae7a139944f567389c9824.
- Six-file transitive economic seal93b011ce775e9ea3af36674a2a143084e3f0616f68107e9d19ea06835d70d489.
- Source root /srv/trading_lab_data/source_evidence/v80_gpr_vintages_2022_2025_v2;
  final manifest ed716b9021067ec24be87e7a6b3707c82a12d9b93e567cbc14b415942c6c6338.
- Canonical /srv/trading_lab_data/runs/v80_gpr_risk_v1_93b011ce775e.
- Feasibility root same name with _feasibility suffix; JSON SHA
  fcbe2e842797c312ef323b3dcd08b8c507b83006aa95fcd5aad5b9da86a2f6ad.
- Metrics SHA7fe5d6c09f252ee779601ecd2970bb6e0f308d6507e6272d820a5535c980e391.
- One4arm/cost batch, economic runtime2.624094seconds, start09:59:37.542837UTC;
  batch and read-only audit completed09:59:41.468797UTC. No repeat simulation.
- Local113/server113synthetic/dependency tests PASS, Ruff clean. Initial global-Python
  invocation lacked the package; repo venv used. Two early synthetic-map tests omitted
  required roll field; fixture fixed before seal, never a market-data/execution defect.
- Audit19artifact hashes, raw DTA/commit -> features/states/targets,4saved-ledger
  metric/annual/count/cash replays PASS. Server pytest emitted an unwritable cache warning;
  audit emitted pandas2.3.3 None/NaN comparison future warnings for unavailable target
  fields. Missing states stay missing, not zero/imputed; frozen parent not rewritten.

## Decision

REJECT_STAGE1. Do not change sign/window/lag/TTL/weights/costs/years on these outcomes
or train a larger model to rescue this particular rule. This is not a rejection of
every conceivable news mechanism. V65–V80 now23economic screens=21rejected+
1incomplete(V73)+1invalid(V74),0Stage2; V75/V77 source-only counted separately.
The20–50%goal is NOT achieved. Select a genuinely different available information set
for the next cheap screen. AlgoPack archival downloads stay independent and active;
no new paper service, Windows task, broker trade, subscription or purchase was created.
