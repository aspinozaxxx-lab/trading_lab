# V84 — SBER measured component below target/cash; GAZP entry unresolved

2026-09-15, [sealed protocol](V84_STOCK_PERPETUAL_BASIS.md). Completed once on
gpu-mlserver at12:36:27.672148UTC, unit trading-lab-v84-basis-5891f2438653.service,
invocation9ca72894f03e4983a76512a0475d7b10. Observed12:37:17UTC terminal inactive/dead,
PID0,exit0/Result=success. No restart or canonical modification.

## Economic result

Fixed2024-10-01…2025-12-30,455calendar days, completed15:40bar→15:50open,
100shares plus short1perpetual,30%cash reserve. These are OHLC research endpoint
proxies, not actual fills or a proved feasible continuous position.

| Measured component | SBER/SBERF | GAZP/GAZPF |
| --- | ---: | --- |
| Initial capital, RUB | 34582.60 | unresolved whole comparison |
| Basis contribution, RUB | −44.00 | unresolved entry |
| Funding proxy, RUB | 7589.401 | 4195.036, separately observable only |
| Base turnover costs, RUB | 84.932 | null |
| Double turnover costs, RUB | 169.864 | null |
| Funding+basis−cost, base / double RUB | 7460.469 / 7375.537 | null |
| Component simple APR, base / double | 17.3176% / 17.1204% | null |
| Verdict | COMPONENT_HURDLES_NOT_MET | UNRESOLVED_ENDPOINT |

SBER prices RUB/share: entry stock266.02/future266.15; exit299.96/300.53.
The observed basis widened rather than converging: it did not close the funding
shortfall. At double costs the unmeasured additional contribution required to reach
20%simpleAPR is1240.524875RUB; to match the cash-rate proxy it is1994.035863RUB.
This is residual accounting, NOT a full economic rejection of all pair mechanisms.
No zero dividend liability, free financing or assumed collateral yield was credited.

GAZPF2024-10-01 has the15:40decision candle but NO15:50execution candle in the
returned70-bar day. Do not select another time or substitute settlement/next print
after this outcome. The other3leg endpoints are present. The independent funding
cashflow remains observable, but the basis/whole component/capital comparison is null.

## Cash-rate comparison

455calendar-day causal as-of records, original CBR available_at preserved. The
lagged RUONIA comparator accrues23.9815% without compounding, or27.0933153% with
daily ACT/365.25 compounding over the same455days. For like-for-like comparison,
the compounded terminal gain has21.7491%simple annual normalization; its annualized
growth is21.2228%. Do not compare SBER's simple APR to a differently normalized number.
Maximum publication age12.6597days, no post-outcome stale-date removal.

This comparator is NOT an official RUONIA index or guaranteed investable cash return.
In particular, it is not additional income on the pair's encumbered reserve. The
measured SBER component is below even this preliminary opportunity-cost comparison.

## Counts, unresolved inputs and temporal limits

Four public candle-day responses,322rows/28825raw bytes, all HTTP200/attempt1.
Exact required pair endpoints:2per candidate; valid leg proxies4/4SBER and3/4GAZP.
Actual decisions/trades/fills0. Funding319source payments per candidate, entry date
included and exit date excluded. This differs deliberately from V81's holding window.

| Funding cashflows only, RUB | Partial2024 | 2025 through29December |
| --- | ---: | ---: |
| SBERF | 1478.894 | 6110.507 |
| GAZPF | 835.097 | 3359.939 |

Monthly funding records are in metrics, NOT monthly portfolio returns. Full pair
PnL/CAGR/Sharpe/MDD/annual returns all remain null. Five unresolved groups per pair:
net stock dividends minus gross perpetual dividend adjustment and receipt timing;
historical margin/VMcash/liquidation; forced conversions and replacement trades;
actual fees/BBO/fill capacity; investable benchmark/collateral eligibility.
GAZP additionally has the explicit endpoint gap. Neither candidate admits Stage2/live.
This is a post-selection follow-up, not independent validation or two new alpha screens.
The23V65–V80 independent-screen counts are unchanged. Goal20–50% is NOT verified.

## Identity and verification

Pre-outcome push6357128. Thirteen-file seal
5891f243865384d6d0436551e2da09af16c880b0af1fff69c7ec63314434c921.
Configc9c7dbe4cc8134753a8127c390cc4d1423634fe0bd61293fa682b7fe00a20303;
code5c057153def3c41668dfddd6e5a6c5e1f62d07441381cf6946819b71396ce9ab.
Local75targeted tests PASS; final pre-seal11V84 and server11V84PASS, Ruff clean.
Parent canonical runs not rerun. All13closure files and3stock-subset inputs verified
on server before a single economic execution. No AlgoPack key/EnvFile needed for4public
ISS requests. Protected2026, archive units, Windows tasks and subscription unchanged.

Canonical root: /srv/trading_lab_data/runs/v84_stock_perpetual_basis_v1.
metrics.json SHA2cecd7147aafaa601f271a79cf14d1a0d65122f7f2fe8fde8c6c00745f65de5f.
candle_manifest.json SHA6ed0c1f962aa566a1d4217a05753bb61e7a7f53884b3ca62db1066e0a5f492fd.
Four raw+receipt SHA identities are in that manifest; original replies immutable.
Only two existing stocks and unchanged30-stock parent manifest transferred to
/srv/trading_lab_data/data/processed/v84_stock_pair_input_subset_v1;
this is an explicitly labeled PARTIAL subset, not all30stocks.

Independent verification:11raw/funding/capital checks, then16rate/scenario/flag checks
passed (4raw pages,638payment records,455rate days). An auxiliary audit first used
exact Decimal equality against binary-float rate/100;129records differ by at most3e-17.
That audit comparison was corrected to1e-12 tolerance; no source, production code,
protocol, result or economic run changed. RUB scenario agreement better than1e-8.
These are arithmetic/source checks, not evidence of investability or live performance.

## Download size and next work

Measured12:41:05.610159UTC: AlgoPack archive1375471252apparent bytes (1.375GB),
1706717184allocated bytes (1.707GB). Includes preserved oldcore4 78726995bytes;
reference-reused pages are not counted again as physical files. Server main data root
4080174365bytes (4.080GB). Local data folder, measured earlier this turn:
10841files/2719842747bytes (2.720GB), no reparse subdirectories. These roots overlap
in content; do not sum them as unique downloaded data. Models/runs/tmp are excluded.

Both archive units actually active/running: mainPID1663880,1583/26305jobs,
20095301rows/21175pages,failed0/blocked0; FUTOIV4PID2522946,185/2192processed days,
3073888logicalrows,9671resolved/47unresolved ticker-days,7524reference-reused pages.
Both final manifests absent. Download is still incomplete, and not an economic PASS.

Do not rerun this diagnostic, reduce reserve/costs or change the missing GAZP entry.
No basis headroom was demonstrated to justify a large full-pair engine now. Continue
the cheap contest with a different information set/mechanism; EQOrderStats/HI2 archive
coverage is a possible next source-only feasibility check, not a selected signal.
Do not retune the rejected three FO flow/depth rules from V79. A new rationale, fixed
contest and pre-outcome seal remain required; completion of the archive is not a
prerequisite to useful analysis on already admitted inputs.
