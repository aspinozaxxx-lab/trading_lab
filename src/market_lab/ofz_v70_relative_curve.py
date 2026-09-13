"""Small OFZ relative-curve screen on the existing coupon-aware bond ledger."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import futures_v52_ofz_carry_roll_down as engine
from market_lab import futures_v64_si_tax_calendar as base

CONFIG = base.PROJECT / "configs/v70_ofz_relative_curve_v1.json"
SEAL = base.PROJECT / "configs/v70_ofz_relative_curve_v1.seal.json"
ARMS = ("primary", "control")


def load(expected):
    base.require(base.sha(SEAL) == expected, "V70 seal mismatch")
    seal = json.loads(SEAL.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        base.require(base.sha(base.safe(base.PROJECT, name)) == digest, "V70 file drift")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    base.load_config(cfg["parent_helper_seal_sha256"])
    base.require(cfg["dates"]["protected_from"] == "2026-01-01", "boundary drift")
    base.require(not cfg["goal_verified"] and not cfg["live_trading_allowed"], "research only")
    return cfg


def preflight(cfg, storage):
    checks = {}
    for role, item in cfg["inputs"].items():
        path = base.safe(storage, item["path"])
        checks[role + "_sha"] = base.sha(path) == item["sha256"]
        base.require(checks[role + "_sha"], "input hash drift")
        if "rows" not in item:
            continue
        checks[role + "_bytes"] = path.stat().st_size == item["bytes"]
        pf = base.pq.ParquetFile(path)
        checks[role + "_rows"] = pf.metadata.num_rows == item["rows"]
        columns = engine.HISTORY_COLUMNS if role == "history" else engine.SCHEDULE_COLUMNS
        checks[role + "_schema"] = set(columns) <= set(pf.schema_arrow.names)
        col = "trade_date" if role == "history" else "event_date"
        dates = pd.to_datetime(pd.read_parquet(path, columns=[col])[col])
        checks[role + "_dates"] = bool(
            dates.notna().all()
            and dates.ge(cfg["dates"]["start"]).all()
            and dates.lt(base.BOUNDARY).all()
        )
    manifest = json.loads(
        base.safe(storage, cfg["inputs"]["manifest"]["path"]).read_text(encoding="utf-8-sig")
    )
    source_audit = json.loads(
        base.safe(storage, cfg["inputs"]["audit"]["path"]).read_text(encoding="utf-8-sig")
    )
    checks["source_audit_pass"] = source_audit["all_true"] is True
    checks["source_only"] = manifest["contains_return_label_target_prediction_or_pnl"] is False
    checks["accounting_only_schedule"] = (
        manifest["bondization_current_vintage_not_historical_predictor"] is True
    )
    for role in ("history", "bondization"):
        checks[role + "_manifest_link"] = all(
            manifest["processed"][role][k] == cfg["inputs"][role][k]
            for k in ("sha256", "bytes", "rows")
        )
    base.require(all(checks.values()), "OFZ preflight failed")
    return checks


def loo_residuals(years, yields, zero_tolerance=1e-10):
    """Current cross-section only; an issue's own yield cannot affect its fitted value."""
    x, y = np.asarray(years, dtype=float) - 4.5, np.asarray(yields, dtype=float)
    base.require(len(x) == len(y) and len(x) >= 4, "curve sample too small")
    base.require(np.isfinite(x).all() and np.isfinite(y).all(), "unknown curve values")
    design = np.column_stack([np.ones(len(x)), x, x * x])
    fitted = []
    for i in range(len(x)):
        keep = np.arange(len(x)) != i
        beta, _, rank, _ = np.linalg.lstsq(design[keep], y[keep], rcond=None)
        base.require(rank == 3, "rank-deficient curve")
        fitted.append(float(design[i] @ beta))
    residual = y - np.asarray(fitted)
    residual[np.abs(residual) <= zero_tolerance] = 0.0
    return np.asarray(fitted), residual


def decisions(history, cfg):
    p = cfg["selection"]
    base.require(history.trade_date.lt(base.BOUNDARY).all(), "protected history")
    days = pd.Series(sorted(history.trade_date.unique()))
    first = days.groupby(days.dt.to_period("M")).first()
    rows, score_rows = [], []
    for day in first:
        day = pd.Timestamp(day)
        clock = (
            day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        ).tz_convert("UTC")
        prior = days.loc[days.lt(day)]
        snapshot_date = prior.iloc[-1] if len(prior) else pd.NaT
        status, eligible, selected = "snapshot_unavailable", pd.DataFrame(), {}
        if pd.notna(snapshot_date) and (day - snapshot_date).days <= p["maximum_snapshot_age_days"]:
            cur = history.loc[history.trade_date.eq(snapshot_date)].copy()
            remaining = (cur.maturity_date - day).dt.days / 365.25
            mask = cur.security_id.str.startswith(p["universe_security_id_prefix"])
            mask &= cur.currency_id.eq(p["currency_id"]) & cur.face_unit.eq(p["face_unit"])
            mask &= remaining.between(
                p["minimum_remaining_maturity_years"], p["maximum_remaining_maturity_years"]
            )
            mask &= cur.trailing_median_value_rub.ge(p["minimum_trailing_median_value_rub"])
            mask &= np.isfinite(cur.yield_at_wap_pct) & cur.yield_at_wap_pct.gt(0)
            mask &= (
                np.isfinite(cur.dirty_open)
                & np.isfinite(cur.dirty_mark)
                & cur.available_at_utc.le(clock)
            )
            eligible = cur.loc[mask].copy().sort_values("security_id")
            eligible["remaining_maturity_years"] = remaining.loc[eligible.index]
            status = "insufficient_curve_issues"
            if len(eligible) >= p["minimum_curve_issues"]:
                try:
                    fitted, residual = loo_residuals(
                        eligible.remaining_maturity_years,
                        eligible.yield_at_wap_pct,
                        p["numerical_zero_residual_yield_pp"],
                    )
                except ValueError as error:
                    if "rank-deficient" not in str(error):
                        raise
                    status = "rank_deficient_curve"
                else:
                    eligible["fitted_yield_pct"] = fitted
                    eligible["residual_yield_pct"] = residual
                    eligible["abs_residual"] = np.abs(residual)
                    eligible["decision_date"] = day
                    eligible["decision_at_utc"] = clock
                    eligible["snapshot_date"] = snapshot_date
                    score_rows.append(
                        eligible[
                            [
                                "decision_date",
                                "decision_at_utc",
                                "snapshot_date",
                                "security_id",
                                "available_at_utc",
                                "remaining_maturity_years",
                                "yield_at_wap_pct",
                                "fitted_yield_pct",
                                "residual_yield_pct",
                            ]
                        ]
                    )
                    primary = (
                        eligible.loc[eligible.residual_yield_pct.gt(0)]
                        .sort_values(["residual_yield_pct", "security_id"], ascending=[False, True])
                        .head(p["selected_security_count"])
                    )
                    status = "insufficient_positive_residuals"
                    if len(primary) == p["selected_security_count"]:
                        status = "selected"
                        selected = {
                            "primary": primary,
                            "control": eligible.sort_values(["abs_residual", "security_id"]).head(
                                p["selected_security_count"]
                            ),
                        }
        for arm in ARMS:
            chosen = selected.get(arm)
            common = {
                "decision_date": day,
                "decision_at_utc": clock,
                "snapshot_date": snapshot_date,
                "arm": arm,
                "status": status,
                "eligible_count": len(eligible),
            }
            if chosen is None:
                rows.append(
                    {
                        **common,
                        "security_id": None,
                        "rank": None,
                        "target_weight": 0.0,
                        "available_at_utc": pd.NaT,
                        "residual_yield_pct": np.nan,
                    }
                )
            else:
                for rank, item in enumerate(chosen.itertuples(), start=1):
                    rows.append(
                        {
                            **common,
                            "security_id": item.security_id,
                            "rank": rank,
                            "target_weight": 1 / p["selected_security_count"],
                            "available_at_utc": item.available_at_utc,
                            "residual_yield_pct": item.residual_yield_pct,
                        }
                    )
    out = pd.DataFrame(rows)
    out["available_at_utc"] = pd.to_datetime(out.available_at_utc, utc=True)
    scores = (
        pd.concat(score_rows, ignore_index=True)
        if score_rows
        else pd.DataFrame(
            columns=[
                "decision_date",
                "decision_at_utc",
                "snapshot_date",
                "security_id",
                "available_at_utc",
                "remaining_maturity_years",
                "yield_at_wap_pct",
                "fitted_yield_pct",
                "residual_yield_pct",
            ]
        )
    )
    admitted = out.loc[out.status.eq("selected")]
    base.require(admitted.available_at_utc.le(admitted.decision_at_utc).all(), "future source")
    base.require(admitted.snapshot_date.lt(admitted.decision_date).all(), "same-day source")
    return out, scores


def position_counts(positions, dates):
    prior, entries, exits = set(), 0, 0
    by_day = {pd.Timestamp(day): set(frame.security_id) for day, frame in positions.groupby("date")}
    for day in dates:
        held = by_day.get(pd.Timestamp(day), set())
        entries += len(held - prior)
        exits += len(prior - held)
        prior = held
    return {"entries": entries, "closed_episodes": exits, "terminal_open_episodes": len(prior)}


def summarize(result, cfg, scenario):
    full = (
        result.mark_sessions == result.total_sessions
        and result.unresolved_cashflows == 0
        and result.unresolved_rebalances == 0
    )
    ledger = result.ledger.copy()
    reserve = None
    performance = None
    counts = None
    if full:
        base.require(
            len(ledger) == result.total_sessions and not ledger.date.duplicated().any(),
            "incomplete NAV",
        )
        last = result.positions.loc[
            result.positions.date.eq(ledger.date.max()), "market_value_rub"
        ].sum()
        reserve = float(last * cfg["cost_scenarios"][scenario]["one_way_bps"] / 10000)
        ledger["reported_nav"] = ledger.nav
        ledger.loc[ledger.index[-1], "reported_nav"] -= reserve
        performance = engine.metrics(ledger.reported_nav, ledger.date)
        counts = position_counts(result.positions, ledger.date)
    else:
        ledger["reported_nav"] = np.nan
    total_cost = float(result.trades.cost_rub.sum())
    coupons = float(ledger.cashflow_credit_rub.sum())
    return {
        "complete": full,
        "performance": performance,
        "position_counts": counts,
        "completed_rebalances": result.completed_rebalances,
        "unresolved_rebalances": result.unresolved_rebalances,
        "unresolved_cashflows": result.unresolved_cashflows,
        "marked_sessions": result.mark_sessions,
        "total_sessions": result.total_sessions,
        "trade_legs": len(result.trades),
        "turnover_rub": float(result.trades.notional_rub.sum()),
        "trading_cost_rub": total_cost,
        "coupon_and_amortization_credit_rub": coupons,
        "terminal_cost_reserve_rub": reserve,
        "ending_marked_nav_before_reserve": float(ledger.nav.iloc[-1]) if full else None,
        "net_pnl_after_reserve_rub": float(
            ledger.reported_nav.iloc[-1] - cfg["execution"]["initial_cash_rub"]
        )
        if full
        else None,
        "gross_price_pnl_rub": float(
            ledger.nav.iloc[-1] - cfg["execution"]["initial_cash_rub"] - coupons + total_cost
        )
        if full
        else None,
    }, ledger


def assess(metrics, counts, cfg):
    g = cfg["screen_gates"]
    base.require(set(metrics) == set(ARMS), "missing arm")
    for arm in ARMS:
        base.require(set(metrics[arm]) == set(cfg["cost_scenarios"]), "missing cost scenario")
    checks = {
        "months": counts["months"] == g["expected_months"],
        "selected_months": counts["selected_months"] >= g["minimum_selected_months"],
    }
    for arm in ARMS:
        for scenario, value in metrics[arm].items():
            checks[arm + "_" + scenario + "_complete"] = value["complete"]
    for scenario, value in metrics["primary"].items():
        perf = value["performance"]
        other = metrics["control"][scenario]["performance"]
        checks[scenario + "_rebalances"] = (
            value["completed_rebalances"] >= g["minimum_completed_rebalances_each_cost"]
        )
        checks[scenario + "_cagr"] = (
            perf is not None and perf["cagr"] >= g["minimum_cagr_each_cost"]
        )
        checks[scenario + "_excess"] = (
            perf is not None
            and other is not None
            and perf["cagr"] - other["cagr"] >= g["minimum_cagr_excess_over_control_each_cost"]
        )
        checks[scenario + "_sharpe"] = (
            perf is not None and perf["sharpe"] >= g["minimum_sharpe_each_cost"]
        )
        checks[scenario + "_drawdown"] = (
            perf is not None and perf["maximum_drawdown"] <= g["maximum_drawdown_each_cost"]
        )
        checks[scenario + "_positive_years"] = (
            perf is not None and perf["positive_years"] >= g["minimum_positive_years_each_cost"]
        )
        checks[scenario + "_worst_year"] = (
            perf is not None and perf["worst_year"] >= g["minimum_worst_year_each_cost"]
        )
        checks[scenario + "_years"] = (
            perf is not None and sorted(perf["annual_returns"]) == g["expected_years"]
        )
    complete = all(value for key, value in checks.items() if key.endswith("_complete"))
    return {
        "checks": checks,
        "verdict": "STAGE2_CANDIDATE"
        if all(checks.values())
        else ("REJECT_STAGE1" if complete else "INVALID_INCOMPLETE_ACCOUNTING"),
        "historical_20_percent_each_cost": complete
        and all(v["performance"]["cagr"] >= 0.2 for v in metrics["primary"].values()),
        "historical_50_percent_each_cost": complete
        and all(v["performance"]["cagr"] >= 0.5 for v in metrics["primary"].values()),
        "goal_verified": False,
    }


def run(cfg, storage, expected):
    base.require(os.name == "posix", "economic run must use gpu-mlserver")
    output = base.safe(storage, "runs/" + cfg["protocol_id"] + "_" + expected[:12])
    base.require(not output.exists(), "existing canonical run; no repeat")
    verified = preflight(cfg, storage)
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    base.write_json(output / "inputs.json", verified)
    raw = pd.read_parquet(
        base.safe(storage, cfg["inputs"]["history"]["path"]), columns=list(engine.HISTORY_COLUMNS)
    )
    history = engine.prepare_history(raw, cfg)
    chosen, scores = decisions(history, cfg)
    chosen.to_parquet(output / "decisions.parquet", index=False)
    scores.to_parquet(output / "curve_scores.parquet", index=False)
    # The predictor has already finished; schedule is loaded for accounting only.
    schedule = pd.read_parquet(
        base.safe(storage, cfg["inputs"]["bondization"]["path"]),
        columns=list(engine.SCHEDULE_COLUMNS),
    )
    months = chosen.loc[chosen.arm.eq("primary")].drop_duplicates("decision_date")
    counts = {
        "history_rows": len(history),
        "curve_issue_scores": len(scores),
        "months": len(months),
        "selected_months": int(months.status.eq("selected").sum()),
        "monthly_status_counts": months.status.value_counts().to_dict(),
    }
    metrics = {}
    for arm in ARMS:
        metrics[arm] = {}
        for scenario in cfg["cost_scenarios"]:
            result = engine.simulate(
                history, schedule, chosen.loc[chosen.arm.eq(arm)], cfg, scenario
            )
            metrics[arm][scenario], report_ledger = summarize(result, cfg, scenario)
            for kind in ("trades", "positions", "ledger"):
                getattr(result, kind).to_parquet(
                    output / f"{kind}_{arm}_{scenario}.parquet", index=False
                )
            report_ledger.to_parquet(output / f"valuation_{arm}_{scenario}.parquet", index=False)
            print(json.dumps({"completed": arm, "costs": scenario}), flush=True)
    payload = {
        "protocol_id": cfg["protocol_id"],
        "seal_sha256": expected,
        "metrics": metrics,
        "counts": counts,
        "assessment": assess(metrics, counts, cfg),
        "runtime_seconds": time.monotonic() - started,
        "numerics": {"numpy": np.__version__, "pandas": pd.__version__},
        "limitations": cfg["limitations"],
        "goal_verified": False,
    }
    base.write_json(output / "metrics.json", payload)
    base.write_json(
        output / "identity.json",
        {
            "seal_sha256": expected,
            "files": {p.name: base.sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        },
    )
    print(json.dumps({"output": str(output), "assessment": payload["assessment"]}), flush=True)
    return output


def audit(output, cfg):
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    for name, digest in identity["files"].items():
        base.require(base.sha(base.safe(output, name)) == digest, "artifact drift")
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    base.require(payload["seal_sha256"] == base.sha(SEAL), "run seal drift")
    chosen = pd.read_parquet(output / "decisions.parquet")
    admitted = chosen.loc[chosen.status.eq("selected")]
    base.require(admitted.available_at_utc.le(admitted.decision_at_utc).all(), "future source")
    base.require(admitted.snapshot_date.lt(admitted.decision_date).all(), "same-day source")
    replayed = 0
    for arm in ARMS:
        for scenario, value in payload["metrics"][arm].items():
            if not value["complete"]:
                base.require(value["performance"] is None, "incomplete metrics published")
                continue
            ledger = pd.read_parquet(output / f"valuation_{arm}_{scenario}.parquet")
            replay = engine.metrics(ledger.reported_nav, ledger.date)
            base.require(replay == value["performance"], "metric drift")
            positions = pd.read_parquet(output / f"positions_{arm}_{scenario}.parquet")
            base.require(
                position_counts(positions, ledger.date) == value["position_counts"], "episode drift"
            )
            last_value = positions.loc[
                positions.date.eq(ledger.date.max()), "market_value_rub"
            ].sum()
            reserve = last_value * cfg["cost_scenarios"][scenario]["one_way_bps"] / 10000
            expected_nav = ledger.nav.copy()
            expected_nav.iloc[-1] -= reserve
            base.require(
                np.allclose(ledger.reported_nav, expected_nav)
                and np.isclose(reserve, value["terminal_cost_reserve_rub"]),
                "terminal reserve drift",
            )
            trades = pd.read_parquet(output / f"trades_{arm}_{scenario}.parquet")
            base.require(trades.execution_date.gt(trades.decision_date).all(), "same-day fill")
            base.require(np.isclose(trades.cost_rub.sum(), value["trading_cost_rub"]), "cost drift")
            replayed += 1
    base.require(
        assess(payload["metrics"], payload["counts"], cfg) == payload["assessment"], "verdict drift"
    )
    return {
        "artifact_hashes": len(identity["files"]),
        "complete_metric_replays": replayed,
        "all_true": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha", required=True)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    cfg = load(args.seal_sha)
    if args.audit:
        print(json.dumps(audit(args.audit, cfg)))
    else:
        run(cfg, args.storage_root, args.seal_sha)


if __name__ == "__main__":
    main()
