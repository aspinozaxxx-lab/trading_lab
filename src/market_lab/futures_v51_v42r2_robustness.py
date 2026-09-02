"""Audit temporal robustness of all nine frozen V42R2 stability curves."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v27_robustness as robust

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v51_v42r2_robustness_audit_v1.yaml"
MARKET_SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")
COST_SCENARIOS: Final[tuple[str, ...]] = (
    "lqdt_contractual_max",
    "high_cost_tmon_contractual_max",
    "zero_idle_yield_with_switching",
)
SCENARIOS: Final[tuple[str, ...]] = tuple(
    f"{market}__{cost}" for market in MARKET_SCENARIOS for cost in COST_SCENARIOS
)
NAV_COLUMNS: Final[dict[str, str]] = {
    scenario: f"{scenario}__combined_nav" for scenario in SCENARIOS
}


@dataclass(frozen=True, slots=True)
class VerifiedCurves:
    """Identity-checked normalized V42R2 curves and session returns."""

    levels: dict[str, pd.Series]
    returns: dict[str, pd.Series]
    metrics: dict[str, dict[str, float]]
    checks: dict[str, bool]
    identity: dict[str, Any]


def _sha(path: Path) -> str:
    return robust.sha256_file(path)


def _sidecar(path: Path) -> str:
    value = path.read_text(encoding="utf-8-sig").split()[0].lower()
    if len(value) != 64:
        raise ValueError(f"invalid SHA sidecar: {path}")
    return value


def _close(left: Any, right: Any, tolerance: float) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _nested_close(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _nested_close(left[key], right[key], tolerance) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _nested_close(a, b, tolerance) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return bool(np.isclose(float(left), float(right), rtol=tolerance, atol=tolerance))
    return left == right


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _performance_metrics(nav: pd.Series) -> dict[str, float]:
    """Replay the exact V42R2 365.25-day metric clock."""

    values = nav.astype(float)
    returns = values.pct_change().fillna(0.0)
    total_return = float(values.iloc[-1] / values.iloc[0] - 1.0)
    elapsed_days = max((values.index[-1] - values.index[0]).days, 1)
    elapsed_years = elapsed_days / 365.25
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (1.0 / elapsed_years) - 1.0)
    deviation = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / deviation * np.sqrt(252.0)) if deviation > 0.0 else 0.0
    drawdown = 1.0 - values / values.cummax()
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.max()),
    }


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load the sealed V51 protocol and verify its code and parent identities."""

    config_path = config_path.resolve()
    actual = _sha(config_path)
    if actual != _sidecar(config_path.with_suffix(".sha256")):
        raise ValueError("V51 protocol SHA mismatch")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise ValueError("V51 protocol must be an object")
    implementation = protocol["implementation"]
    parent = protocol["parent_v42r2"]
    if (
        protocol.get("protocol_id") != "v51_v42r2_robustness_audit_v1"
        or protocol.get("status") != "sealed_before_any_v42r2_curve_resampling"
        or protocol.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / implementation["path"]) != implementation["sha256"]
        or _sha(PROJECT_ROOT / implementation["reused_robustness_path"])
        != implementation["reused_robustness_sha256"]
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or _sha(PROJECT_ROOT / parent["shared_engine_path"]) != parent["shared_engine_sha256"]
        or protocol["analysis"]["strategy_parameter_search"] is not False
        or protocol["analysis"]["all_nine_scenarios_required"] is not True
        or protocol["limitations"]["independent_holdout"] is not False
    ):
        raise ValueError("V51 robustness protocol drifted")
    if tuple(protocol["scenario_order"]) != SCENARIOS:
        raise ValueError("V51 scenario order drifted")
    return protocol


def verify_curves(protocol: dict[str, Any], runs_root: Path) -> VerifiedCurves:
    """Read only the nine V42R2 NAV columns on frozen V39 session dates."""

    input_spec = protocol["input"]
    parent = protocol["parent_v42r2"]
    runs_root = runs_root.resolve()
    run = (runs_root / input_spec["canonical_run_directory"]).resolve()
    if run.parent != runs_root or not run.is_dir():
        raise FileNotFoundError(run)
    checks: dict[str, bool] = {}
    for name, declaration in input_spec["artifacts"].items():
        path = run / name
        checks[f"artifact_exists_{name}"] = path.is_file()
        checks[f"artifact_bytes_{name}"] = path.is_file() and path.stat().st_size == int(
            declaration["bytes"]
        )
        checks[f"artifact_sha_{name}"] = path.is_file() and _sha(path) == declaration["sha256"]
    if not all(checks.values()):
        raise ValueError("V51 parent artifact identity failed")
    metrics_file = json.loads((run / "metrics.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8-sig"))
    checks.update(
        {
            "parent_protocol_exact": manifest["protocol_sha256"] == parent["protocol_sha256"],
            "parent_implementation_exact": manifest["implementation_sha256"]
            == parent["implementation_sha256"],
            "parent_shared_engine_exact": manifest["shared_engine_sha256"]
            == parent["shared_engine_sha256"],
            "parent_verdict_disclosed": metrics_file["verdict"]
            == "ROBUST_TO_DECLARED_IDLE_COST_STRESSES",
            "parent_same_history_disclosed": metrics_file["same_history_post_result_diagnostic"]
            is True,
            "parent_selection_forbidden": metrics_file["fund_selection_allowed"] is False,
            "parent_not_live": metrics_file["live_trading_allowed"] is False,
            "parent_runtime_audit_true": all(audit["checks"].values()),
        }
    )
    allowed = tuple(input_spec["allowed_columns"])
    expected = ("date", "is_v39_session", *(NAV_COLUMNS[name] for name in SCENARIOS))
    if allowed != expected:
        raise ValueError("V51 may read only date, V39 mask and nine combined NAV columns")
    frame = pd.read_parquet(run / "daily_ledger.parquet", columns=list(allowed))
    dates = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    mask = frame["is_v39_session"]
    selected = frame.loc[mask.eq(True)].copy()  # noqa: E712
    selected_dates = dates.loc[mask.eq(True)].reset_index(drop=True)  # noqa: E712
    checks.update(
        {
            "full_rows_exact": len(frame) == int(input_spec["expected_full_rows"]),
            "selected_rows_exact": len(selected) == int(input_spec["expected_rows"]),
            "dates_unique": not dates.duplicated().any(),
            "dates_increasing": dates.is_monotonic_increasing,
            "mask_boolean_complete": bool(mask.notna().all() and mask.isin([True, False]).all()),
            "minimum_session": selected_dates.iloc[0]
            == pd.Timestamp(protocol["dates"]["expected_minimum_session"]),
            "maximum_session": selected_dates.iloc[-1]
            == pd.Timestamp(protocol["dates"]["expected_maximum_session"]),
            "no_2026": not dates.ge(pd.Timestamp(protocol["dates"]["forbidden_from"])).any(),
        }
    )
    tolerance = float(protocol["analysis"]["metric_replay_absolute_tolerance"])
    levels: dict[str, pd.Series] = {}
    returns: dict[str, pd.Series] = {}
    observed: dict[str, dict[str, float]] = {}
    for scenario in SCENARIOS:
        nav = pd.to_numeric(selected[NAV_COLUMNS[scenario]], errors="raise").astype(float)
        nav.index = pd.DatetimeIndex(selected_dates)
        checks[f"{scenario}_nav_finite_positive"] = bool(
            np.isfinite(nav.to_numpy()).all() and nav.gt(0.0).all()
        )
        replay = _performance_metrics(nav)
        stored = metrics_file["combinations"][scenario]["combined"]
        configured = parent["expected_combined_metrics"][scenario]
        for field in ("total_return", "cagr", "sharpe", "maximum_drawdown"):
            checks[f"{scenario}_{field}_stored_replay"] = _close(
                replay[field], stored[field], tolerance
            )
            checks[f"{scenario}_{field}_configured_exact"] = _close(
                stored[field], configured[field], tolerance
            )
        daily = nav.pct_change().fillna(0.0)
        daily.name = "combined_return"
        checks[f"{scenario}_returns_valid"] = bool(
            np.isfinite(daily.to_numpy()).all() and daily.gt(-1.0).all()
        )
        levels[scenario] = nav
        returns[scenario] = daily
        observed[scenario] = replay
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"V51 curve verification failed: {failed}")
    return VerifiedCurves(
        levels=levels,
        returns=returns,
        metrics=observed,
        checks=checks,
        identity={
            "canonical_run": str(run),
            "parent_protocol_sha256": parent["protocol_sha256"],
            "parent_metrics_sha256": parent["metrics_sha256"],
            "allowed_columns": list(allowed),
            "selected_v39_sessions": len(selected),
            "contains_prices_targets_orders_or_positions": False,
            "contains_2026_prices_returns_targets_or_pnl": False,
        },
    )


def _minimum_record(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    row = frame.loc[frame[column].idxmin()]
    return {
        "scenario": str(row["scenario"]),
        "block_sessions": int(row["block_sessions"]),
        "value": float(row[column]),
    }


def _assessment(
    protocol: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    rolling_summary: dict[str, dict[str, dict[str, float]]],
    leave: pd.DataFrame,
) -> dict[str, Any]:
    joint20 = _minimum_record(bootstrap_summary, "probability_cagr_ge_0_20_and_mdd_le_0_30")
    joint50 = _minimum_record(bootstrap_summary, "probability_cagr_ge_0_50_and_mdd_le_0_30")
    q05 = _minimum_record(bootstrap_summary, "cagr_q05")
    median = _minimum_record(bootstrap_summary, "cagr_q50")
    rolling252 = min(
        (
            {
                "scenario": scenario,
                "value": float(rolling_summary[scenario]["252"]["fraction_cagr_ge_0_20"]),
            }
            for scenario in SCENARIOS
        ),
        key=lambda item: item["value"],
    )
    rolling504 = min(
        (
            {
                "scenario": scenario,
                "value": float(rolling_summary[scenario]["504"]["fraction_cagr_ge_0_20"]),
            }
            for scenario in SCENARIOS
        ),
        key=lambda item: item["value"],
    )
    leave_row = leave.loc[leave["cagr"].idxmin()]
    leave_min = {
        "scenario": str(leave_row["scenario"]),
        "excluded_year": int(leave_row["excluded_year"]),
        "value": float(leave_row["cagr"]),
    }
    gates = protocol["diagnostic_gates"]
    minimum = gates["minimum_20"]
    conditions = {
        "all_scenarios_joint_20_30_frequency": joint20["value"]
        >= float(minimum["minimum_joint_20_30_frequency"]),
        "all_scenarios_q05_cagr": q05["value"] >= float(minimum["minimum_q05_cagr"]),
        "all_scenarios_252d_fraction_cagr_ge_20": rolling252["value"]
        >= float(minimum["minimum_252d_fraction_cagr_ge_20"]),
        "all_scenarios_504d_fraction_cagr_ge_20": rolling504["value"]
        >= float(minimum["minimum_504d_fraction_cagr_ge_20"]),
        "every_scenario_leave_year_out_cagr_ge_20": leave_min["value"]
        >= float(minimum["every_leave_year_out_cagr_ge"]),
    }
    aspirational = gates["aspirational_50"]
    target50 = joint50["value"] >= float(aspirational["minimum_joint_50_30_frequency"]) and median[
        "value"
    ] >= float(aspirational["minimum_median_cagr"])
    return {
        "minimum_20_supported_internally": all(conditions.values()),
        "aspirational_50_supported_internally": target50,
        "minimum_20_conditions": conditions,
        "worst_joint_20_30": joint20,
        "worst_joint_50_30": joint50,
        "worst_bootstrap_q05_cagr": q05,
        "worst_bootstrap_median_cagr": median,
        "worst_252d_fraction_cagr_ge_20": rolling252,
        "worst_504d_fraction_cagr_ge_20": rolling504,
        "worst_leave_one_year_out_cagr": leave_min,
    }


def _report(payload: dict[str, Any]) -> str:
    assessment = payload["target_assessment"]
    lines = [
        "# V51 robustness audit of all canonical V42R2 stability curves",
        "",
        f"Verdict: **{payload['verdict']}**",
        "",
        "| Scenario | Observed CAGR | Sharpe | MDD |",
        "|---|---:|---:|---:|",
    ]
    for scenario in SCENARIOS:
        item = payload["observed"][scenario]
        lines.append(
            f"| {scenario} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
            f"{item['maximum_drawdown']:.4%} |"
        )
    lines.extend(
        [
            "",
            f"Minimum 20% internally supported: "
            f"**{assessment['minimum_20_supported_internally']}**",
            f"Aspirational 50% internally supported: "
            f"**{assessment['aspirational_50_supported_internally']}**",
            f"Worst joint CAGR>=20% and MDD<=30% frequency: "
            f"{assessment['worst_joint_20_30']['value']:.2%}",
            f"Worst bootstrap CAGR q05: {assessment['worst_bootstrap_q05_cagr']['value']:.2%}",
            "",
            "This is a same-history resampling diagnostic, not a calibrated forecast or",
            "independent validation. It cannot select a fund or authorize live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    if path.suffix == ".parquet":
        record["rows"] = pq.ParquetFile(path).metadata.num_rows
    elif path.suffix == ".csv":
        record["rows"] = len(pd.read_csv(path))
    return record


def run(protocol: dict[str, Any], output_root: Path) -> Path:
    """Run the sealed V51 audit once into a new immutable directory."""

    output_root = output_root.resolve()
    existing = sorted(output_root.glob("v51_v42r2_robustness_*"))
    if existing:
        raise FileExistsError(f"V51 robustness audit already exists: {existing[0]}")
    verified = verify_curves(protocol, output_root)
    analysis = protocol["analysis"]
    blocks = tuple(int(value) for value in analysis["block_sessions"])
    quantiles = tuple(float(value) for value in analysis["quantiles"])
    replications = int(analysis["bootstrap_replications_per_scenario_block"])
    elapsed_days = (
        pd.Timestamp(protocol["dates"]["expected_maximum_session"])
        - pd.Timestamp(protocol["dates"]["expected_minimum_session"])
    ).days
    elapsed_years = elapsed_days / float(analysis["bootstrap_calendar_year_days"])
    samples_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    rolling_frames: list[pd.DataFrame] = []
    rolling_summary: dict[str, dict[str, dict[str, float]]] = {}
    leave_frames: list[pd.DataFrame] = []
    deflated_rows: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        values = verified.returns[scenario]
        for block in blocks:
            seed = int(analysis["seed_base"]) + scenario_index * 10_000 + block
            samples = robust.circular_block_bootstrap(
                values.to_numpy(),
                replications=replications,
                block_sessions=block,
                seed=seed,
                elapsed_years=elapsed_years,
                batch_size=int(analysis["bootstrap_batch_size"]),
            )
            samples.insert(0, "seed", seed)
            samples.insert(0, "block_sessions", block)
            samples.insert(0, "scenario", scenario)
            samples_frames.append(samples)
            summary_rows.append(
                {
                    "scenario": scenario,
                    "block_sessions": block,
                    "seed": seed,
                    **robust.summarize_bootstrap(samples, quantiles=quantiles),
                }
            )
        rolling_summary[scenario] = {}
        for window in analysis["rolling_window_sessions"]:
            frame = robust.rolling_windows(values, window_sessions=int(window))
            frame.insert(0, "window_sessions", int(window))
            frame.insert(0, "scenario", scenario)
            rolling_frames.append(frame)
            rolling_summary[scenario][str(window)] = robust.summarize_rolling(frame)
        leave = robust.leave_one_year_out(
            values, years=tuple(int(value) for value in analysis["calendar_years"])
        )
        leave.insert(0, "scenario", scenario)
        leave_frames.append(leave)
        for trials in analysis["deflated_sharpe_trial_counts"]:
            deflated_rows.append(
                {
                    "scenario": scenario,
                    **robust.deflated_sharpe_probability(values, trials=int(trials)),
                }
            )
    samples = pd.concat(samples_frames, ignore_index=True)
    summary = pd.DataFrame(summary_rows)
    rolling = pd.concat(rolling_frames, ignore_index=True)
    leave = pd.concat(leave_frames, ignore_index=True)
    deflated = pd.DataFrame(deflated_rows)
    assessment = _assessment(protocol, summary, rolling_summary, leave)
    verdict = (
        "INTERNAL_ROBUSTNESS_SUPPORTS_20_FORWARD_TEST"
        if assessment["minimum_20_supported_internally"]
        else "INTERNAL_ROBUSTNESS_DOES_NOT_SUPPORT_20"
    )
    payload = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": _sha(CONFIG_PATH),
        "verdict": verdict,
        "post_selection_diagnostic": True,
        "independent_holdout_confirmation": False,
        "probabilities_are_calibrated_forward_forecasts": False,
        "fund_selection_allowed": False,
        "live_trading_allowed": False,
        "checks": verified.checks,
        "input_identity": verified.identity,
        "observed": verified.metrics,
        "bootstrap_summary": summary.to_dict("records"),
        "rolling_summary": rolling_summary,
        "leave_one_year_out": leave.to_dict("records"),
        "deflated_sharpe_trial_sensitivity": deflated.to_dict("records"),
        "target_assessment": assessment,
        "limitations": protocol["limitations"],
    }
    name = (
        f"v51_v42r2_robustness_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{_sha(CONFIG_PATH)[:8]}"
    )
    final = output_root / name
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        shutil.copyfile(CONFIG_PATH.with_suffix(".sha256"), temporary / "protocol.sha256")
        samples.to_parquet(temporary / "bootstrap_samples.parquet", index=False, compression="zstd")
        summary.to_csv(temporary / "bootstrap_summary.csv", index=False, encoding="utf-8-sig")
        rolling.to_parquet(temporary / "rolling_windows.parquet", index=False, compression="zstd")
        leave.to_csv(temporary / "leave_one_year_out.csv", index=False, encoding="utf-8-sig")
        deflated.to_csv(temporary / "deflated_sharpe.csv", index=False, encoding="utf-8-sig")
        (temporary / "report.md").write_text(_report(payload), encoding="utf-8-sig")
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        artifacts = {path.name: _artifact(path) for path in sorted(temporary.iterdir())}
        manifest = {
            "run_id": name,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": _sha(CONFIG_PATH),
            "implementation_sha256": _sha(Path(__file__).resolve()),
            "verdict": verdict,
            "artifacts": artifacts,
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8-sig",
        )
        identity = {
            "protocol_sha256": _sha(CONFIG_PATH),
            "implementation_sha256": _sha(Path(__file__).resolve()),
            "parent_v42r2_protocol_sha256": protocol["parent_v42r2"]["protocol_sha256"],
            "metrics_sha256": _sha(metrics_path),
            "manifest_sha256": _sha(manifest_path),
            "contains_2026_prices_returns_targets_or_pnl": False,
        }
        (temporary / "identity.json").write_text(
            json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit(output: Path) -> dict[str, Any]:
    """Replay artifact identities and all stored summaries without resampling."""

    protocol = load_protocol()
    output = output.resolve()
    verified = verify_curves(protocol, output.parent)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == _sha(CONFIG_PATH),
        "implementation_exact": manifest["implementation_sha256"] == _sha(Path(__file__).resolve()),
        "identity_protocol_exact": identity["protocol_sha256"] == _sha(CONFIG_PATH),
        "identity_parent_exact": identity["parent_v42r2_protocol_sha256"]
        == protocol["parent_v42r2"]["protocol_sha256"],
        "identity_metrics_exact": identity["metrics_sha256"] == _sha(output / "metrics.json"),
        "identity_manifest_exact": identity["manifest_sha256"] == _sha(output / "manifest.json"),
        "parent_reverified": all(verified.checks.values()),
        "no_2026_disclosed": identity["contains_2026_prices_returns_targets_or_pnl"] is False,
        "fund_selection_forbidden": metrics["fund_selection_allowed"] is False,
        "not_live": metrics["live_trading_allowed"] is False,
        "not_independent": metrics["independent_holdout_confirmation"] is False,
    }
    for name, declaration in manifest["artifacts"].items():
        path = output / name
        checks[f"artifact_{name}_sha"] = path.is_file() and _sha(path) == declaration["sha256"]
        checks[f"artifact_{name}_bytes"] = path.is_file() and path.stat().st_size == int(
            declaration["bytes"]
        )
        if "rows" in declaration and path.suffix == ".parquet":
            checks[f"artifact_{name}_rows"] = pq.ParquetFile(path).metadata.num_rows == int(
                declaration["rows"]
            )
        elif "rows" in declaration and path.suffix == ".csv":
            checks[f"artifact_{name}_rows"] = len(pd.read_csv(path)) == int(declaration["rows"])
    samples = pd.read_parquet(output / "bootstrap_samples.parquet")
    summary = pd.read_csv(output / "bootstrap_summary.csv")
    rolling = pd.read_parquet(output / "rolling_windows.parquet")
    leave = pd.read_csv(output / "leave_one_year_out.csv")
    quantiles = tuple(float(value) for value in protocol["analysis"]["quantiles"])
    replay_rows: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        for block in protocol["analysis"]["block_sessions"]:
            part = samples.loc[
                samples["scenario"].eq(scenario) & samples["block_sessions"].eq(int(block))
            ]
            seed = int(protocol["analysis"]["seed_base"]) + scenario_index * 10_000 + int(block)
            replay_rows.append(
                {
                    "scenario": scenario,
                    "block_sessions": int(block),
                    "seed": seed,
                    **robust.summarize_bootstrap(part, quantiles=quantiles),
                }
            )
    replay_summary = pd.DataFrame(replay_rows)
    checks["bootstrap_summary_replay"] = _nested_close(
        replay_summary.to_dict("records"), summary.to_dict("records")
    )
    rolling_summary: dict[str, dict[str, dict[str, float]]] = {}
    for scenario in SCENARIOS:
        rolling_summary[scenario] = {}
        for window in protocol["analysis"]["rolling_window_sessions"]:
            part = rolling.loc[
                rolling["scenario"].eq(scenario) & rolling["window_sessions"].eq(int(window))
            ]
            rolling_summary[scenario][str(window)] = robust.summarize_rolling(part)
    checks["rolling_summary_replay"] = _nested_close(rolling_summary, metrics["rolling_summary"])
    replay = _assessment(protocol, summary, rolling_summary, leave)
    checks["assessment_exact"] = _nested_close(replay, metrics["target_assessment"])
    checks["verdict_exact"] = replay["minimum_20_supported_internally"] == (
        metrics["verdict"] == "INTERNAL_ROBUSTNESS_SUPPORTS_20_FORWARD_TEST"
    )
    return {"checks": checks, "all_true": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        result = audit(args.audit_directory)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["all_true"] else 1
    output = run(load_protocol(), args.output_root)
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONFIG_PATH",
    "NAV_COLUMNS",
    "SCENARIOS",
    "audit",
    "load_protocol",
    "main",
    "run",
    "verify_curves",
]
