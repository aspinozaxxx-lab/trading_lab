"""Audit path stability of the frozen canonical V49 exact equity curves."""

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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v50_v49_robustness_audit_v1.yaml"
SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")
NAV_COLUMNS: Final[dict[str, str]] = {
    name: f"double_risk_{name}_combined_nav" for name in SCENARIOS
}


@dataclass(frozen=True, slots=True)
class VerifiedCurves:
    """Identity-checked normalized V49 curves and daily returns."""

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


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load the byte-sealed protocol and verify every code/parent identity."""

    config_path = config_path.resolve()
    actual = _sha(config_path)
    if actual != _sidecar(config_path.with_suffix(".sha256")):
        raise ValueError("V50 protocol SHA mismatch")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise ValueError("V50 protocol must be an object")
    implementation = protocol["implementation"]
    parent = protocol["parent_v49"]
    if (
        protocol.get("protocol_id") != "v50_v49_robustness_audit_v1"
        or protocol.get("status") != "sealed_before_any_v49_daily_curve_resampling"
        or protocol.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / implementation["path"]) != implementation["sha256"]
        or _sha(PROJECT_ROOT / implementation["reused_robustness_path"])
        != implementation["reused_robustness_sha256"]
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["protocol_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or protocol["analysis"]["strategy_parameter_search"] is not False
        or protocol["limitations"]["independent_holdout"] is not False
    ):
        raise ValueError("V50 robustness protocol drifted")
    return protocol


def _close(left: Any, right: Any, tolerance: float) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def verify_curves(protocol: dict[str, Any], runs_root: Path) -> VerifiedCurves:
    """Read only V49 dates and three combined NAV columns after byte checks."""

    input_spec = protocol["input"]
    parent = protocol["parent_v49"]
    run = (runs_root / input_spec["canonical_run_directory"]).resolve()
    if not run.is_dir():
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
        raise ValueError("V50 parent artifact identity failed")
    metrics_file = json.loads((run / "metrics.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8-sig"))
    checks.update(
        {
            "parent_protocol_exact": manifest["protocol_sha256"] == parent["protocol_sha256"],
            "parent_verdict_disclosed": metrics_file["verdict"] == "NO_GO",
            "parent_same_history_disclosed": metrics_file["adaptive_same_history"] is True,
            "parent_not_live": metrics_file["live_trading_allowed"] is False,
            "parent_runtime_audit_true": all(audit["checks"].values()),
        }
    )
    allowed = tuple(input_spec["allowed_columns"])
    expected = ("session_date", *(NAV_COLUMNS[name] for name in SCENARIOS))
    if allowed != expected:
        raise ValueError("V50 may read only dates and three V49 combined NAV columns")
    frame = pd.read_parquet(run / "combined_ledger.parquet", columns=list(allowed))
    dates = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
    checks.update(
        {
            "rows_exact": len(frame) == int(input_spec["expected_rows"]),
            "dates_unique": not dates.duplicated().any(),
            "dates_increasing": dates.is_monotonic_increasing,
            "minimum_session": dates.iloc[0]
            == pd.Timestamp(protocol["dates"]["expected_minimum_session"]),
            "maximum_session": dates.iloc[-1]
            == pd.Timestamp(protocol["dates"]["expected_maximum_session"]),
            "no_2026": not dates.ge(pd.Timestamp(protocol["dates"]["forbidden_from"])).any(),
        }
    )
    tolerance = float(protocol["analysis"]["metric_replay_absolute_tolerance"])
    levels: dict[str, pd.Series] = {}
    returns: dict[str, pd.Series] = {}
    observed: dict[str, dict[str, float]] = {}
    for scenario in SCENARIOS:
        nav = pd.to_numeric(frame[NAV_COLUMNS[scenario]], errors="raise").astype(float)
        nav.index = pd.DatetimeIndex(dates)
        checks[f"{scenario}_nav_finite_positive"] = bool(
            np.isfinite(nav.to_numpy()).all() and nav.gt(0.0).all()
        )
        replay = robust.performance_metrics(nav.reset_index(drop=True), dates, initial_cash=1.0)
        stored = metrics_file["scenarios"][scenario]["combined"]
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
        raise ValueError(f"V50 curve verification failed: {failed}")
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
            "contains_prices_targets_orders_or_positions": False,
            "contains_2026_prices_returns_targets_or_pnl": False,
        },
    )


def _assessment(
    protocol: dict[str, Any],
    bootstrap_summary: pd.DataFrame,
    rolling_summary: dict[str, dict[str, dict[str, float]]],
    leave: pd.DataFrame,
) -> dict[str, Any]:
    stress = bootstrap_summary.loc[bootstrap_summary["scenario"].eq("stress")]
    joint20 = float(stress["probability_cagr_ge_0_20_and_mdd_le_0_40"].min())
    joint50 = float(stress["probability_cagr_ge_0_50_and_mdd_le_0_40"].min())
    q05 = float(stress["cagr_q05"].min())
    rolling252 = rolling_summary["stress"]["252"]
    rolling504 = rolling_summary["stress"]["504"]
    leave_min = float(leave.loc[leave["scenario"].eq("stress"), "cagr"].min())
    gates = protocol["diagnostic_gates"]
    conditions = {
        "stress_joint_20_40_frequency": joint20
        >= float(gates["minimum_20"]["minimum_stress_joint_20_40_frequency"]),
        "stress_q05_cagr": q05 >= float(gates["minimum_20"]["minimum_stress_q05_cagr"]),
        "stress_252d_fraction_cagr_ge_20": rolling252["fraction_cagr_ge_0_20"]
        >= float(gates["minimum_20"]["stress_252d_fraction_cagr_ge_20"]),
        "stress_504d_fraction_cagr_ge_20": rolling504["fraction_cagr_ge_0_20"]
        >= float(gates["minimum_20"]["stress_504d_fraction_cagr_ge_20"]),
        "every_stress_leave_year_out_cagr_ge_20": leave_min
        >= float(gates["minimum_20"]["every_stress_leave_year_out_cagr_ge"]),
    }
    minimum20 = all(conditions.values())
    target50 = joint50 >= float(
        gates["aspirational_50"]["minimum_stress_joint_50_40_frequency"]
    ) and float(stress["cagr_q50"].min()) >= float(
        gates["aspirational_50"]["minimum_stress_median_cagr"]
    )
    return {
        "minimum_20_supported_internally": minimum20,
        "aspirational_50_supported_internally": target50,
        "minimum_20_conditions": conditions,
        "minimum_stress_joint_20_40_frequency": joint20,
        "minimum_stress_joint_50_40_frequency": joint50,
        "minimum_stress_q05_cagr": q05,
        "stress_252d_fraction_cagr_ge_20": rolling252["fraction_cagr_ge_0_20"],
        "stress_504d_fraction_cagr_ge_20": rolling504["fraction_cagr_ge_0_20"],
        "minimum_stress_leave_one_year_out_cagr": leave_min,
    }


def summarize_bootstrap_40(samples: pd.DataFrame, quantiles: tuple[float, ...]) -> dict[str, float]:
    """Summarize predeclared return thresholds with the V49 40% MDD ceiling."""

    result = robust.summarize_bootstrap(samples, quantiles=quantiles)
    result.update(
        {
            "probability_mdd_le_0_40": float(samples["maximum_drawdown"].le(0.40).mean()),
            "probability_cagr_ge_0_20_and_mdd_le_0_40": float(
                (samples["cagr"].ge(0.20) & samples["maximum_drawdown"].le(0.40)).mean()
            ),
            "probability_cagr_ge_0_50_and_mdd_le_0_40": float(
                (samples["cagr"].ge(0.50) & samples["maximum_drawdown"].le(0.40)).mean()
            ),
        }
    )
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


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


def _report(payload: dict[str, Any]) -> str:
    assessment = payload["target_assessment"]
    lines = [
        "# V50 robustness audit of canonical V49",
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
            f"Worst stress block frequency CAGR>=20% and MDD<=40%: "
            f"{assessment['minimum_stress_joint_20_40_frequency']:.2%}",
            f"Worst stress bootstrap CAGR q05: {assessment['minimum_stress_q05_cagr']:.2%}",
            "",
            "This is a same-history resampling diagnostic, not a calibrated forecast or",
            "independent validation. It cannot change V49 or authorize live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: dict[str, Any], output_root: Path) -> Path:
    """Run the sealed V50 audit once into a new immutable directory."""

    output_root = output_root.resolve()
    existing = sorted(output_root.glob("v50_v49_robustness_*"))
    if existing:
        raise FileExistsError(f"V50 robustness audit already exists: {existing[0]}")
    verified = verify_curves(protocol, output_root)
    analysis = protocol["analysis"]
    blocks = tuple(int(value) for value in analysis["block_sessions"])
    quantiles = tuple(float(value) for value in analysis["quantiles"])
    replications = int(analysis["bootstrap_replications_per_scenario_block"])
    elapsed_days = (
        pd.Timestamp(protocol["dates"]["expected_maximum_session"])
        - pd.Timestamp(protocol["dates"]["expected_minimum_session"])
    ).days
    elapsed_years = elapsed_days / 365.2425
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
                    **summarize_bootstrap_40(samples, quantiles),
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
        f"v50_v49_robustness_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{_sha(CONFIG_PATH)[:8]}"
    )
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
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
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            record: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
            if path.suffix == ".parquet":
                record["rows"] = pq.ParquetFile(path).metadata.num_rows
            elif path.suffix == ".csv":
                record["rows"] = len(pd.read_csv(path))
            artifacts[path.name] = record
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
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
        )
        identity = {
            "protocol_sha256": _sha(CONFIG_PATH),
            "implementation_sha256": _sha(Path(__file__).resolve()),
            "parent_v49_protocol_sha256": protocol["parent_v49"]["protocol_sha256"],
            "metrics_sha256": _sha(metrics_path),
            "manifest_sha256": _sha(manifest_path),
            "contains_2026_prices_returns_targets_or_pnl": False,
        }
        (temporary / "identity.json").write_text(
            json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig"
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit(output: Path) -> dict[str, Any]:
    """Replay artifact identities and all stored risk summaries without rerunning V49."""

    protocol = load_protocol()
    output = output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    identity = json.loads((output / "identity.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == _sha(CONFIG_PATH),
        "implementation_exact": manifest["implementation_sha256"] == _sha(Path(__file__).resolve()),
        "identity_protocol_exact": identity["protocol_sha256"] == _sha(CONFIG_PATH),
        "identity_metrics_exact": identity["metrics_sha256"] == _sha(output / "metrics.json"),
        "identity_manifest_exact": identity["manifest_sha256"] == _sha(output / "manifest.json"),
        "no_2026_disclosed": identity["contains_2026_prices_returns_targets_or_pnl"] is False,
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
                    **summarize_bootstrap_40(part, quantiles),
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
    stored = metrics["target_assessment"]
    checks["assessment_exact"] = _nested_close(replay, stored)
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
