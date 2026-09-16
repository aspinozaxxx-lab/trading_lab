"""Fixed post-selection stress and dependence checks of the V99 candidate."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from market_lab import futures_v99_reserve_liquidity as candidate

base, engine, STORAGE = candidate.base, candidate.engine, candidate.STORAGE
CONFIG = base.PROJECT / "configs/v100_v99_robustness_v1.json"
SEAL = base.PROJECT / "configs/v100_v99_robustness_v1.seal.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_manifest(root, digest):
    base.require(base.sha(root / "manifest.json") == digest, "input manifest drift")
    manifest = read_json(root / "manifest.json")
    base.require(manifest["status"] == "COMPLETE", "incomplete input")
    for name, expected in manifest["files"].items():
        base.require(base.sha(base.safe(root, name)) == expected, "input artifact drift")
    return manifest


def delayed_states(releases, days, parent_cfg):
    base.require(days in (0, 1, 7), "unplanned delay")
    result = copy.deepcopy(candidate.states(releases, parent_cfg))
    for row in result:
        row["original_available_at_utc"] = row["available_at_utc"]
        row["available"] += pd.Timedelta(days=days)
        row["lag_available"] += pd.Timedelta(days=days)
        row["available_at_utc"] = row["available"].isoformat()
        base.require(row["available"] < base.BOUNDARY.tz_localize("UTC"), "protected delay")
    return result


def temporal(annual):
    base.require(sorted(annual) == [str(y) for y in range(2018, 2026)], "annual coverage")
    base.require(all(np.isfinite(x) and x > -1 for x in annual.values()), "invalid annual return")
    four = {f"{y}-{y + 3}": float(np.prod([1 + annual[str(j)] for j in range(y, y + 4)])
                                  ** .25 - 1) for y in range(2018, 2023)}
    leave = {year: float(np.prod([1 + v for k, v in annual.items() if k != year])
                         ** (1 / 7) - 1) for year in annual}
    return {"four_calendar_year_geometric_annual": four, "leave_one_year_out_annual": leave,
            "positive_years": sum(v > 0 for v in annual.values()),
            "rolling_blocks_overlap": True, "independent_holdout": False}


def monthly_dependence(candidate_ledger, reference, reference_column):
    def monthly(frame, column):
        dates = pd.to_datetime(frame.session_date)
        base.require(dates.notna().all() and dates.lt(base.BOUNDARY).all()
                     and not dates.duplicated().any() and dates.is_monotonic_increasing,
                     "protected or malformed NAV calendar")
        nav = pd.Series(frame[column].to_numpy(dtype=float), index=dates)
        base.require(np.isfinite(nav).all() and nav.gt(0).all(), "invalid NAV values")
        levels = nav.resample("ME").last().loc["2020-12-01":"2025-12-31"]
        base.require(len(levels) == 61 and levels.notna().all(), "missing monthly anchor")
        return levels.pct_change(fill_method=None).iloc[1:]

    left = monthly(candidate_ledger, "ending_cash")
    right = monthly(reference, reference_column)
    base.require(left.index.equals(right.index) and len(left) == 60, "monthly alignment")
    bad = right.lt(0)
    corr = left.corr(right) if left.std() > 0 and right.std() > 0 else np.nan
    rows = pd.DataFrame({"month": left.index, "v99_return": left.to_numpy(),
                         "v49_return": right.to_numpy(), "v49_negative": bad.to_numpy()})
    return {"months": 60, "monthly_correlation": float(corr) if np.isfinite(corr) else None,
            "v49_negative_months": int(bad.sum()),
            "v99_mean_in_v49_negative_months": float(left[bad].mean()) if bad.any() else None,
            "v99_positive_in_v49_negative_months": int(left[bad].gt(0).sum()),
            "v49_includes_modeled_cash_yield_and_different_risk": True,
            "conditional_sample_ex_post_not_live_rule": True}, rows


def audit_case(folder, case, signals):
    base.require(engine.target_counts(signals) == case["counts"], "target count drift")
    for arm, frame in signals.items():
        pd.testing.assert_frame_equal(frame, pd.read_parquet(folder / f"targets_{arm}.parquet"))
        used = frame.loc[frame.target_weight.ne(0)]
        base.require(frame.effective_date.lt(base.BOUNDARY).all()
                     and frame.decision_date.lt(frame.effective_date).all(), "target time boundary")
        base.require(used.available_at_utc.le(used.decision_at_utc).all()
                     and used.lag_available_at_utc.lt(used.available_at_utc).all(), "future source")
        for cost, value in case["metrics"][arm].items():
            ledger = pd.read_parquet(folder / f"ledger_{arm}_{cost}.parquet")
            orders = pd.read_parquet(folder / f"orders_{arm}_{cost}.parquet")
            positions = pd.read_parquet(folder / f"positions_{arm}_{cost}.parquet")
            dates = pd.to_datetime(ledger.session_date)
            base.require(dates.lt(base.BOUNDARY).all(), "protected ledger")
            base.require(np.isclose(ledger.starting_cash.iloc[0], base.CAPITAL)
                         and np.allclose(ledger.starting_cash.iloc[1:],
                                         ledger.ending_cash.iloc[:-1], rtol=1e-10, atol=1e-6),
                         "cash continuity drift")
            costs = ledger.commission_cost + ledger.slippage_cost
            base.require(np.allclose(ledger.ending_cash,
                                      ledger.starting_cash + ledger.variation_margin - costs,
                                      rtol=1e-10, atol=1e-6),
                         "daily cash identity drift")
            filled = orders.loc[orders.filled.eq(True)]  # noqa: E712
            order_costs = float(filled.commission_cost.sum() + filled.slippage_cost.sum())
            base.require(np.isclose(order_costs, value["total_cost"])
                         and np.isclose(costs.sum(), order_costs), "cost ledger drift")
            replay = base._performance_metrics(ledger.ending_cash, ledger.session_date,
                                                base.CAPITAL)
            base.require(all(np.isclose(value[k], v) for k, v in replay.items()), "metric drift")
            daily = ledger.ending_cash / ledger.starting_cash - 1
            for year, part in daily.groupby(dates.dt.year):
                base.require(np.isclose((1 + part).prod() - 1, value["annual_returns"][str(year)]),
                             "annual drift")
            counts = engine.shared.position_counts(positions)
            base.require(all(value[k] == v for k, v in counts.items()),
                         "position count drift")
    return {"source_target_replays": len(signals),
            "cash_cost_metric_annual_count_replays": sum(len(v) for v in case["metrics"].values())}


def assessment(baseline, stresses, cfg):
    base.require(set(stresses) == {s["id"] for s in cfg["scenarios"]}, "missing stress scenarios")
    for spec in cfg["scenarios"]:
        base.require(set(stresses[spec["id"]]["metrics"]) == {"primary", "control"},
                     "missing stress arm")
        for metrics in stresses[spec["id"]]["metrics"].values():
            base.require(set(metrics) == set(spec["costs"]), "missing stress cost")
    checks = {"all_stress_stage1_gates": all(
        c["assessment"]["verdict"] == "STAGE2_CANDIDATE" for c in stresses.values())}
    floor = cfg["diagnostic_gates"]["minimum_each_four_year_block_cagr"]
    for cost, metric in baseline["metrics"]["primary"].items():
        values = temporal(metric["annual_returns"])["four_calendar_year_geometric_annual"]
        checks[cost + "_all_four_year_blocks_ge_component_floor"] = all(
            x >= floor for x in values.values())
    execution_ok = all(v["execution_complete"] and v["critical_failure_count"] == 0
                       and v["unresolved_halt_count"] == 0 and not v["terminal_carried"]
                       for case in stresses.values() for arm in case["metrics"].values()
                       for v in arm.values())
    return {"checks": checks, "stress_execution_complete": execution_ok,
            "verdict": ("INVALID_STAGE2_EXECUTION" if not execution_ok else
                        "STAGE3_SOURCE_CHECK_CANDIDATE" if all(checks.values()) else
                        "REJECT_STAGE2_ROBUSTNESS"),
            "late_block_failure_known_before_new_stresses": True,
            "goal_verified": False, "live_trading_allowed": False}


def load(expected):
    base.require(base.sha(SEAL) == expected, "V100 seal drift")
    for name, digest in read_json(SEAL)["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V100 file drift")
    cfg = read_json(CONFIG)
    parent_cfg, market_parent = candidate.load(cfg["parent_seal_sha256"])
    base.require(cfg["stage"] == 2 and not cfg["goal_verified"]
                 and not cfg["live_trading_allowed"] and not cfg["parameter_search"], "scope drift")
    return cfg, parent_cfg, market_parent


def run(cfg, parent_cfg, market_parent, expected):
    source = base.safe(STORAGE, cfg["inputs"]["source"]["path"])
    canonical = base.safe(STORAGE, cfg["inputs"]["stage1"]["path"])
    source_manifest = verify_manifest(source, cfg["inputs"]["source"]["manifest_sha256"])
    run_manifest = verify_manifest(canonical, cfg["inputs"]["stage1"]["manifest_sha256"])
    base.require(source_manifest["seal_sha256"] == run_manifest["seal_sha256"]
                 == cfg["parent_seal_sha256"], "parent source/run identity")
    ref = cfg["inputs"]["v49"]
    reference_root = base.safe(STORAGE, ref["path"])
    base.require(base.sha(reference_root / "manifest.json") == ref["manifest_sha256"],
                 "V49 manifest drift")
    reference_file = reference_root / "combined_ledger.parquet"
    spec = ref["ledger"]
    base.require(base.sha(reference_file) == spec["sha256"]
                 and reference_file.stat().st_size == spec["bytes"], "V49 NAV drift")
    pf = pq.ParquetFile(reference_file)
    base.require(pf.metadata.num_rows == 1272
                 and set(spec["columns"]) <= set(pf.schema_arrow.names),
                 "V49 schema drift")
    dates = pd.to_datetime(pf.read(columns=["session_date"]).to_pandas().session_date)
    base.require(dates.notna().all() and dates.between("2020-12-30", "2025-12-30").all()
                 and dates.is_unique and dates.is_monotonic_increasing
                 and dates.iloc[0] == pd.Timestamp("2020-12-30")
                 and dates.iloc[-1] == pd.Timestamp("2025-12-30"), "V49 date admission")
    verified = base.preflight(market_parent, STORAGE)
    declared = base.declarations(market_parent)["recent"]
    active = pd.read_parquet(base.safe(STORAGE, declared["active_map"]["path"]),
                             columns=base.ACTIVE_COLS)
    releases = read_json(source / "releases.json")
    baseline = read_json(canonical / "metrics.json")["case"]
    original_signals = candidate.targets(active, delayed_states(releases, 0, parent_cfg),
                                         parent_cfg)
    baseline_audit = audit_case(canonical / "case", baseline, original_signals)
    base.require(baseline["assessment"]["verdict"] == "STAGE2_CANDIDATE", "not a Stage1 candidate")
    output = base.safe(STORAGE, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    output.mkdir(exist_ok=False)
    base.write_json(output / "inputs.json", {"seal_sha256": expected, "sources": cfg["inputs"],
                    "futures": verified, "baseline_audit": baseline_audit,
                    "started_at_utc": datetime.now(UTC).isoformat()})
    reference = pd.read_parquet(reference_file, columns=spec["columns"])
    dependencies = {}
    for cost, column in ref["cost_columns"].items():
        ledger = pd.read_parquet(canonical / "case" / f"ledger_primary_{cost}.parquet")
        dependencies[cost], rows = monthly_dependence(ledger, reference, column)
        rows.to_parquet(output / f"monthly_dependence_{cost}.parquet", index=False)
    market = engine.market_inputs(STORAGE, declared, parent_cfg)
    stresses, audits, periods = {}, {}, {"baseline": {
        arm: {cost: temporal(v["annual_returns"]) for cost, v in costs.items()}
        for arm, costs in baseline["metrics"].items()}}
    for scenario in cfg["scenarios"]:
        current = copy.deepcopy(parent_cfg)
        current["execution"]["costs"] = scenario["costs"]
        signals = candidate.targets(active, delayed_states(
            releases, scenario["additional_calendar_days"], parent_cfg), current)
        quality = {**baseline["source_quality"], "ready_asset_date_fraction": float(
            (~(signals["primary"].feature_unavailable | signals["primary"].stale_at_fill)).mean())}
        name = scenario["id"]
        stresses[name] = engine.simulate_case(output / name, signals, market, quality,
                                               current, name)
        audits[name] = audit_case(output / name, stresses[name], signals)
        periods[name] = {arm: {cost: temporal(v["annual_returns"]) for cost, v in costs.items()}
                         for arm, costs in stresses[name]["metrics"].items()}
    payload = {"status": "COMPLETE", "stage": 2, "protocol_id": cfg["protocol_id"],
               "seal_sha256": expected, "completed_at_utc": datetime.now(UTC).isoformat(),
               "baseline_metrics_reused_not_rerun": baseline, "stresses": stresses,
               "temporal": periods, "dependence": dependencies, "audits": audits,
               "assessment": assessment(baseline, stresses, cfg),
               "limitations": cfg["limitations"], "goal_verified": False}
    base.write_json(output / "metrics.json", payload)
    base.write_json(output / "manifest.json", {"status": "COMPLETE", "seal_sha256": expected,
                    "completed_at_utc": payload["completed_at_utc"], "files": {
                        p.relative_to(output).as_posix(): base.sha(p)
                        for p in sorted(output.rglob("*")) if p.is_file()}})
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--seal-sha", required=True)
    args = cli.parse_args()
    base.require(os.name == "posix" and os.getuid() == 999, "server service only")
    cfg, parent_cfg, market_parent = load(args.seal_sha)
    run(cfg, parent_cfg, market_parent, args.seal_sha)


if __name__ == "__main__":
    main()
