"""Frozen post-selection robustness audit for the canonical V27 equity curves."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs/futures_v27_robustness.yaml"
SCENARIOS = ("primary", "doubled", "stress")
EQUITY_COLUMNS = ("session_date", "combined_ending_equity")


@dataclass(frozen=True)
class VerifiedV27Curves:
    """Identity-checked V27 levels and returns used by the audit."""

    levels: dict[str, pd.DataFrame]
    returns: dict[str, pd.Series]
    canonical_metrics: dict[str, dict[str, float]]
    checks: dict[str, bool]
    input_identity: dict[str, Any]


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _sidecar_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig").strip()
    parts = text.split()
    if len(parts) < 1 or len(parts[0]) != 64:
        raise ValueError(f"Invalid SHA sidecar: {path}")
    return parts[0].lower()


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load a byte-sealed audit protocol and verify its implementation identity."""
    config_path = config_path.resolve()
    sidecar = config_path.with_suffix(".sha256")
    expected = _sidecar_hash(sidecar)
    actual = sha256_file(config_path)
    if actual != expected:
        raise ValueError(f"V27 robustness protocol SHA mismatch: {actual} != {expected}")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise ValueError("V27 robustness protocol must be a mapping")
    if protocol.get("protocol_id") != "futures_v27_robustness_audit_v1":
        raise ValueError("Unexpected V27 robustness protocol id")
    implementation = protocol["implementation"]
    implementation_path = PROJECT_ROOT / implementation["path"]
    implementation_hash = sha256_file(implementation_path)
    if implementation_hash != implementation["sha256"]:
        raise ValueError("V27 robustness implementation SHA mismatch")
    parent_path = PROJECT_ROOT / protocol["parent_v27"]["config_path"]
    if sha256_file(parent_path) != protocol["parent_v27"]["protocol_sha256"]:
        raise ValueError("Frozen V27 parent protocol SHA mismatch")
    return protocol


def performance_metrics(
    levels: pd.Series,
    dates: pd.Series,
    *,
    initial_cash: float,
) -> dict[str, float]:
    """Replay the canonical V27 level-based metric convention exactly."""
    values = np.r_[float(initial_cash), levels.to_numpy(dtype=float)]
    returns = pd.Series(values).pct_change().dropna()
    total_return = float(values[-1] / initial_cash - 1.0)
    elapsed_days = max((pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(dates.iloc[0])).days, 1)
    years = elapsed_days / 365.2425
    cagr = float((values[-1] / initial_cash) ** (1.0 / years) - 1.0)
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.sqrt(252.0) * returns.mean() / deviation) if deviation > 0.0 else 0.0
    peaks = np.maximum.accumulate(values)
    maximum_drawdown = float(np.max(1.0 - values / peaks))
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": maximum_drawdown,
    }


def _return_metrics_observation_clock(values: np.ndarray) -> dict[str, float]:
    returns = np.asarray(values, dtype=float)
    if returns.ndim != 1 or returns.size < 2:
        raise ValueError("At least two one-dimensional returns are required")
    if not np.isfinite(returns).all() or np.any(returns <= -1.0):
        raise ValueError("Returns must be finite and greater than -100 percent")
    equity = np.cumprod(1.0 + returns)
    years = returns.size / 252.0
    deviation = float(returns.std(ddof=1))
    peaks = np.maximum.accumulate(np.maximum(equity, 1.0))
    return {
        "observations": int(returns.size),
        "total_return": float(equity[-1] - 1.0),
        "cagr": float(equity[-1] ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / deviation * np.sqrt(252.0)) if deviation > 0.0 else 0.0,
        "maximum_drawdown": float(np.max(1.0 - equity / peaks)),
    }


def _require_exact_numeric(
    observed: dict[str, Any],
    expected: dict[str, Any],
    fields: tuple[str, ...],
    *,
    tolerance: float,
) -> None:
    for field in fields:
        difference = abs(float(observed[field]) - float(expected[field]))
        if difference > tolerance:
            raise ValueError(f"Canonical metric mismatch for {field}: {difference}")


def verify_v27_curves(
    protocol: dict[str, Any],
    *,
    runs_root: Path,
) -> VerifiedV27Curves:
    """Verify parent bytes before loading the two explicitly allowed columns."""
    input_spec = protocol["input"]
    run_directory = (runs_root / input_spec["canonical_run_directory"]).resolve()
    if not run_directory.is_dir():
        raise FileNotFoundError(f"Canonical V27 run not found: {run_directory}")

    checks: dict[str, bool] = {}
    for name, declaration in input_spec["artifacts"].items():
        path = run_directory / name
        checks[f"artifact_exists_{name}"] = path.is_file()
        if not path.is_file():
            raise FileNotFoundError(path)
        checks[f"artifact_bytes_{name}"] = path.stat().st_size == int(declaration["bytes"])
        checks[f"artifact_sha256_{name}"] = sha256_file(path) == declaration["sha256"]
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"Canonical V27 artifact identity mismatch: {failed}")

    metrics_path = run_directory / "metrics.json"
    identity_path = run_directory / "identity.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8-sig"))
    identity = json.loads(identity_path.read_text(encoding="utf-8-sig"))
    checks["parent_protocol_sha"] = (
        metrics["protocol_sha256"] == protocol["parent_v27"]["protocol_sha256"]
    )
    checks["parent_metrics_sha"] = (
        sha256_file(metrics_path) == protocol["parent_v27"]["metrics_sha256"]
        and identity["metrics_sha256"] == protocol["parent_v27"]["metrics_sha256"]
    )
    checks["parent_checks_all_true"] = all(bool(value) for value in metrics["checks"].values())
    checks["parent_not_live"] = metrics["live_trading_allowed"] is False
    checks["parent_not_independent_holdout"] = metrics["independent_holdout_confirmation"] is False
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"Canonical V27 parent checks failed: {failed}")

    initial_cash = float(protocol["analysis"]["initial_cash_rub"])
    tolerance = float(protocol["analysis"]["metric_replay_absolute_tolerance"])
    forbidden = pd.Timestamp(protocol["dates"]["forbidden_from"])
    expected_minimum = pd.Timestamp(protocol["dates"]["expected_minimum_session"])
    expected_maximum = pd.Timestamp(protocol["dates"]["expected_maximum_session"])
    expected_rows = int(protocol["input"]["expected_rows_per_scenario"])
    allowed_columns = tuple(protocol["input"]["allowed_columns"])
    if allowed_columns != EQUITY_COLUMNS:
        raise ValueError("Audit may read only session_date and combined_ending_equity")

    levels: dict[str, pd.DataFrame] = {}
    returns: dict[str, pd.Series] = {}
    canonical_metrics: dict[str, dict[str, float]] = {}
    reference_dates: pd.Series | None = None
    for scenario in SCENARIOS:
        filename = f"combined_ledger_{scenario}.parquet"
        frame = pd.read_parquet(run_directory / filename, columns=list(allowed_columns))
        dates = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
        equity = pd.to_numeric(frame["combined_ending_equity"], errors="raise").astype(float)
        checks[f"{scenario}_row_count"] = len(frame) == expected_rows
        checks[f"{scenario}_dates_unique"] = not dates.duplicated().any()
        checks[f"{scenario}_dates_increasing"] = dates.is_monotonic_increasing
        checks[f"{scenario}_minimum_session"] = dates.iloc[0] == expected_minimum
        checks[f"{scenario}_maximum_session"] = dates.iloc[-1] == expected_maximum
        checks[f"{scenario}_no_2026"] = not dates.ge(forbidden).any()
        checks[f"{scenario}_equity_finite_positive"] = bool(
            np.isfinite(equity.to_numpy()).all() and equity.gt(0.0).all()
        )
        if reference_dates is None:
            reference_dates = dates
        else:
            checks[f"{scenario}_calendar_matches_primary"] = dates.equals(reference_dates)
        normalized = pd.DataFrame({"session_date": dates, "combined_ending_equity": equity})
        observed = performance_metrics(equity, dates, initial_cash=initial_cash)
        parent = metrics["scenarios"][scenario]["combined"]
        configured = protocol["parent_v27"]["expected_combined_metrics"][scenario]
        metric_fields = ("total_return", "cagr", "sharpe", "maximum_drawdown")
        _require_exact_numeric(observed, parent, metric_fields, tolerance=tolerance)
        _require_exact_numeric(parent, configured, metric_fields, tolerance=tolerance)
        checks[f"{scenario}_canonical_metrics_replayed"] = True
        values = np.r_[initial_cash, equity.to_numpy(dtype=float)]
        daily_returns = pd.Series(
            values[1:] / values[:-1] - 1.0,
            index=pd.DatetimeIndex(dates),
            name="combined_return",
        )
        checks[f"{scenario}_returns_finite_above_minus_one"] = bool(
            np.isfinite(daily_returns.to_numpy()).all() and daily_returns.gt(-1.0).all()
        )
        levels[scenario] = normalized
        returns[scenario] = daily_returns
        canonical_metrics[scenario] = observed
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"V27 curve validation failed: {failed}")

    input_identity = {
        "canonical_run": str(run_directory),
        "parent_protocol_sha256": protocol["parent_v27"]["protocol_sha256"],
        "parent_metrics_sha256": protocol["parent_v27"]["metrics_sha256"],
        "artifacts": input_spec["artifacts"],
        "allowed_columns": list(allowed_columns),
        "contains_prices_targets_or_positions": False,
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    return VerifiedV27Curves(
        levels=levels,
        returns=returns,
        canonical_metrics=canonical_metrics,
        checks=checks,
        input_identity=input_identity,
    )


def circular_block_bootstrap(
    returns: np.ndarray,
    *,
    replications: int,
    block_sessions: int,
    seed: int,
    elapsed_years: float,
    batch_size: int = 250,
) -> pd.DataFrame:
    """Resample circular contiguous blocks and recompute path-dependent metrics."""
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < block_sessions:
        raise ValueError("Bootstrap input must be one-dimensional and longer than a block")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("Bootstrap returns must be finite and greater than -100 percent")
    if replications < 1 or block_sessions < 1 or elapsed_years <= 0.0:
        raise ValueError("Invalid bootstrap settings")
    n = values.size
    blocks = int(math.ceil(n / block_sessions))
    offsets = np.arange(block_sessions, dtype=np.int64)
    rng = np.random.default_rng(seed)
    rows: list[pd.DataFrame] = []
    completed = 0
    while completed < replications:
        size = min(batch_size, replications - completed)
        starts = rng.integers(0, n, size=(size, blocks, 1), dtype=np.int64)
        indices = (starts + offsets.reshape(1, 1, -1)) % n
        samples = values[indices.reshape(size, -1)[:, :n]]
        equity = np.cumprod(1.0 + samples, axis=1)
        peaks = np.maximum.accumulate(np.maximum(equity, 1.0), axis=1)
        drawdowns = np.max(1.0 - equity / peaks, axis=1)
        cagr = np.power(equity[:, -1], 1.0 / elapsed_years) - 1.0
        deviation = samples.std(axis=1, ddof=1)
        sharpe = np.divide(
            samples.mean(axis=1) * np.sqrt(252.0),
            deviation,
            out=np.zeros(size, dtype=float),
            where=deviation > 0.0,
        )
        rows.append(
            pd.DataFrame(
                {
                    "replication": np.arange(completed, completed + size, dtype=np.int64),
                    "cagr": cagr,
                    "sharpe": sharpe,
                    "maximum_drawdown": drawdowns,
                }
            )
        )
        completed += size
    return pd.concat(rows, ignore_index=True)


def summarize_bootstrap(
    samples: pd.DataFrame,
    *,
    quantiles: tuple[float, ...],
) -> dict[str, float]:
    """Summarize fixed threshold frequencies and predeclared quantiles."""
    output: dict[str, float] = {
        "replications": float(len(samples)),
        "probability_cagr_ge_0": float(samples["cagr"].ge(0.0).mean()),
        "probability_cagr_ge_0_20": float(samples["cagr"].ge(0.20).mean()),
        "probability_cagr_ge_0_50": float(samples["cagr"].ge(0.50).mean()),
        "probability_mdd_le_0_30": float(samples["maximum_drawdown"].le(0.30).mean()),
        "probability_cagr_ge_0_20_and_mdd_le_0_30": float(
            (samples["cagr"].ge(0.20) & samples["maximum_drawdown"].le(0.30)).mean()
        ),
        "probability_cagr_ge_0_50_and_mdd_le_0_30": float(
            (samples["cagr"].ge(0.50) & samples["maximum_drawdown"].le(0.30)).mean()
        ),
    }
    for column in ("cagr", "sharpe", "maximum_drawdown"):
        for quantile in quantiles:
            label = f"q{int(round(quantile * 100)):02d}"
            output[f"{column}_{label}"] = float(samples[column].quantile(quantile))
    return output


def rolling_windows(returns: pd.Series, *, window_sessions: int) -> pd.DataFrame:
    """Compute overlapping one-year-like path diagnostics without treating them as IID."""
    if len(returns) < window_sessions:
        raise ValueError("Rolling window is longer than the return history")
    rows: list[dict[str, Any]] = []
    values = returns.to_numpy(dtype=float)
    for end_index in range(window_sessions - 1, len(returns)):
        start_index = end_index - window_sessions + 1
        window = values[start_index : end_index + 1]
        metrics = _return_metrics_observation_clock(window)
        rows.append(
            {
                "start_session": returns.index[start_index],
                "end_session": returns.index[end_index],
                **metrics,
            }
        )
    return pd.DataFrame(rows)


def summarize_rolling(frame: pd.DataFrame) -> dict[str, float]:
    """Summarize overlapping windows as descriptive frequencies only."""
    return {
        "windows": float(len(frame)),
        "minimum_cagr": float(frame["cagr"].min()),
        "cagr_q05": float(frame["cagr"].quantile(0.05)),
        "median_cagr": float(frame["cagr"].median()),
        "cagr_q95": float(frame["cagr"].quantile(0.95)),
        "maximum_cagr": float(frame["cagr"].max()),
        "positive_fraction": float(frame["cagr"].gt(0.0).mean()),
        "fraction_cagr_ge_0_20": float(frame["cagr"].ge(0.20).mean()),
        "fraction_cagr_ge_0_50": float(frame["cagr"].ge(0.50).mean()),
        "maximum_window_drawdown": float(frame["maximum_drawdown"].max()),
        "fraction_mdd_le_0_30": float(frame["maximum_drawdown"].le(0.30).mean()),
    }


def leave_one_year_out(returns: pd.Series, *, years: tuple[int, ...]) -> pd.DataFrame:
    """Measure dependence on each calendar year using a 252-session observation clock."""
    rows: list[dict[str, Any]] = []
    for year in years:
        kept = returns.loc[returns.index.year != year].to_numpy(dtype=float)
        rows.append({"excluded_year": year, **_return_metrics_observation_clock(kept)})
    return pd.DataFrame(rows)


def deflated_sharpe_probability(returns: pd.Series, *, trials: int) -> dict[str, float]:
    """Return the Bailey-Lopez de Prado trial-count sensitivity diagnostic."""
    values = returns.to_numpy(dtype=float)
    n = len(values)
    daily_sharpe = float(values.mean() / values.std(ddof=1))
    normal = NormalDist()
    euler_gamma = 0.5772156649015329
    expected_max_z = (1.0 - euler_gamma) * normal.inv_cdf(1.0 - 1.0 / trials) + (
        euler_gamma * normal.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )
    benchmark = expected_max_z / math.sqrt(n - 1.0)
    skewness = float(pd.Series(values).skew())
    pearson_kurtosis = float(pd.Series(values).kurt()) + 3.0
    denominator = math.sqrt(
        max(
            1.0 - skewness * daily_sharpe + ((pearson_kurtosis - 1.0) / 4.0) * daily_sharpe**2,
            1e-12,
        )
    )
    z_score = (daily_sharpe - benchmark) * math.sqrt(n - 1.0) / denominator
    return {
        "trials": float(trials),
        "expected_max_null_sharpe_annualized": benchmark * math.sqrt(252.0),
        "deflated_sharpe_probability": normal.cdf(z_score),
        "deflated_sharpe_z": z_score,
    }


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


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V27 frozen robustness audit",
        "",
        f"Verdict: **{payload['verdict']}**.",
        "",
        "This is a post-selection resampling diagnostic on the already observed 2021-2025",
        "V27 curve. It is neither an independent holdout nor a calibrated forecast.",
        "",
        "| Scenario | Observed CAGR | Observed Sharpe | Observed MDD |",
        "|---|---:|---:|---:|",
    ]
    for scenario in SCENARIOS:
        metrics = payload["observed"][scenario]
        lines.append(
            f"| {scenario} | {metrics['cagr']:.4%} | {metrics['sharpe']:.3f} | "
            f"{metrics['maximum_drawdown']:.4%} |"
        )
    lines.extend(
        [
            "",
            "## Predeclared target assessment",
            "",
            f"- Minimum 20% target supported internally: "
            f"`{payload['target_assessment']['minimum_20_supported']}`.",
            f"- Aspirational 50% target supported internally: "
            f"`{payload['target_assessment']['aspirational_50_supported']}`.",
            f"- Worst stress joint 20%/30% bootstrap frequency: "
            f"{payload['target_assessment']['minimum_stress_joint_20_30_frequency']:.2%}.",
            f"- Worst stress joint 50%/30% bootstrap frequency: "
            f"{payload['target_assessment']['minimum_stress_joint_50_30_frequency']:.2%}.",
            "",
            "Passing this audit can only support a new unseen/PIT validation. It cannot",
            "authorize live trading or parameter changes on the same history.",
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(
    *,
    config_path: Path = CONFIG_PATH,
    output_root: Path,
) -> Path:
    """Run one immutable robustness audit from the sealed protocol."""
    protocol = load_protocol(config_path)
    output_root = output_root.resolve()
    verified = verify_v27_curves(protocol, runs_root=output_root)
    analysis = protocol["analysis"]
    block_sessions = tuple(int(value) for value in analysis["block_sessions"])
    quantiles = tuple(float(value) for value in analysis["quantiles"])
    replications = int(analysis["bootstrap_replications_per_scenario_block"])
    seed_base = int(analysis["seed_base"])
    rolling_sessions = int(analysis["rolling_window_sessions"])
    years = tuple(int(value) for value in analysis["calendar_years"])
    elapsed_days = (
        pd.Timestamp(protocol["dates"]["expected_maximum_session"])
        - pd.Timestamp(protocol["dates"]["expected_minimum_session"])
    ).days
    elapsed_years = elapsed_days / 365.2425

    bootstrap_frames: list[pd.DataFrame] = []
    bootstrap_summary_rows: list[dict[str, Any]] = []
    rolling_frames: list[pd.DataFrame] = []
    rolling_summary: dict[str, dict[str, float]] = {}
    leave_frames: list[pd.DataFrame] = []
    deflated_rows: list[dict[str, float | str]] = []
    for scenario_index, scenario in enumerate(SCENARIOS):
        scenario_returns = verified.returns[scenario]
        for block in block_sessions:
            seed = seed_base + scenario_index * 10_000 + block
            samples = circular_block_bootstrap(
                scenario_returns.to_numpy(dtype=float),
                replications=replications,
                block_sessions=block,
                seed=seed,
                elapsed_years=elapsed_years,
                batch_size=int(analysis["bootstrap_batch_size"]),
            )
            samples.insert(0, "seed", seed)
            samples.insert(0, "block_sessions", block)
            samples.insert(0, "scenario", scenario)
            bootstrap_frames.append(samples)
            bootstrap_summary_rows.append(
                {
                    "scenario": scenario,
                    "block_sessions": block,
                    "seed": seed,
                    **summarize_bootstrap(samples, quantiles=quantiles),
                }
            )
        rolling = rolling_windows(scenario_returns, window_sessions=rolling_sessions)
        rolling.insert(0, "scenario", scenario)
        rolling_frames.append(rolling)
        rolling_summary[scenario] = summarize_rolling(rolling)
        leave = leave_one_year_out(scenario_returns, years=years)
        leave.insert(0, "scenario", scenario)
        leave_frames.append(leave)
        for trials in analysis["deflated_sharpe_trial_counts"]:
            deflated_rows.append(
                {
                    "scenario": scenario,
                    **deflated_sharpe_probability(scenario_returns, trials=int(trials)),
                }
            )

    bootstrap_samples = pd.concat(bootstrap_frames, ignore_index=True)
    bootstrap_summary = pd.DataFrame(bootstrap_summary_rows)
    rolling = pd.concat(rolling_frames, ignore_index=True)
    leave = pd.concat(leave_frames, ignore_index=True)
    deflated = pd.DataFrame(deflated_rows)

    stress_bootstrap = bootstrap_summary.loc[bootstrap_summary["scenario"].eq("stress")]
    minimum_joint_20_30 = float(stress_bootstrap["probability_cagr_ge_0_20_and_mdd_le_0_30"].min())
    minimum_joint_50_30 = float(stress_bootstrap["probability_cagr_ge_0_50_and_mdd_le_0_30"].min())
    minimum_stress_q05_cagr = float(stress_bootstrap["cagr_q05"].min())
    minimum_leave_out_stress_cagr = float(leave.loc[leave["scenario"].eq("stress"), "cagr"].min())
    gates = protocol["diagnostic_gates"]
    minimum_conditions = {
        "minimum_stress_joint_20_30_frequency": minimum_joint_20_30
        >= float(gates["minimum_20"]["minimum_stress_joint_20_30_frequency"]),
        "minimum_stress_q05_cagr": minimum_stress_q05_cagr
        >= float(gates["minimum_20"]["minimum_stress_q05_cagr"]),
        "stress_rolling_positive_fraction": rolling_summary["stress"]["positive_fraction"]
        >= float(gates["minimum_20"]["stress_rolling_positive_fraction"]),
        "every_stress_leave_one_year_out_cagr": minimum_leave_out_stress_cagr
        > float(gates["minimum_20"]["every_stress_leave_one_year_out_cagr_above"]),
    }
    minimum_supported = all(minimum_conditions.values())
    fifty_supported = minimum_joint_50_30 >= float(
        gates["aspirational_50"]["minimum_stress_joint_50_30_frequency"]
    )
    target_assessment = {
        "minimum_20_supported": minimum_supported,
        "aspirational_50_supported": fifty_supported,
        "minimum_conditions": minimum_conditions,
        "minimum_stress_joint_20_30_frequency": minimum_joint_20_30,
        "minimum_stress_joint_50_30_frequency": minimum_joint_50_30,
        "minimum_stress_q05_cagr": minimum_stress_q05_cagr,
        "stress_rolling_positive_fraction": rolling_summary["stress"]["positive_fraction"],
        "minimum_stress_leave_one_year_out_cagr": minimum_leave_out_stress_cagr,
    }
    verdict = (
        "INTERNAL_ROBUSTNESS_SUPPORTS_UNSEEN_VALIDATION"
        if minimum_supported
        else "INTERNAL_ROBUSTNESS_WEAKENS_V27"
    )
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256_file(config_path),
        "research_only": True,
        "post_selection_diagnostic": True,
        "independent_holdout_confirmation": False,
        "probabilities_are_calibrated_forward_forecasts": False,
        "live_trading_allowed": False,
        "verdict": verdict,
        "checks": verified.checks,
        "input_identity": verified.input_identity,
        "observed": verified.canonical_metrics,
        "bootstrap_summary": bootstrap_summary.to_dict("records"),
        "rolling_summary": rolling_summary,
        "leave_one_year_out": leave.to_dict("records"),
        "deflated_sharpe_trial_sensitivity": deflated.to_dict("records"),
        "target_assessment": target_assessment,
        "limitations": protocol["limitations"],
    }

    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config_hash = sha256_file(config_path)
    run_name = f"v27_robustness_{timestamp}_{config_hash[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V27 robustness run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(config_path, temporary / "resolved_protocol.yaml")
        shutil.copyfile(config_path.with_suffix(".sha256"), temporary / "protocol.sha256")
        bootstrap_samples.to_parquet(
            temporary / "bootstrap_samples.parquet", index=False, compression="zstd"
        )
        bootstrap_summary.to_csv(
            temporary / "bootstrap_summary.csv", index=False, encoding="utf-8-sig"
        )
        rolling.to_parquet(temporary / "rolling_windows.parquet", index=False, compression="zstd")
        leave.to_csv(temporary / "leave_one_year_out.csv", index=False, encoding="utf-8-sig")
        deflated.to_csv(temporary / "deflated_sharpe.csv", index=False, encoding="utf-8-sig")
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            elif path.suffix == ".csv":
                entry["rows"] = int(len(pd.read_csv(path)))
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        identity = {
            "protocol_sha256": config_hash,
            "implementation_sha256": sha256_file(Path(__file__).resolve()),
            "parent_v27_protocol_sha256": protocol["parent_v27"]["protocol_sha256"],
            "parent_v27_metrics_sha256": protocol["parent_v27"]["metrics_sha256"],
            "metrics_sha256": sha256_file(metrics_path),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
            "contains_2026_prices_returns_targets_or_pnl": False,
        }
        (temporary / "identity.json").write_text(
            json.dumps(identity, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Byte-sealed robustness protocol.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root containing the canonical V27 parent.",
    )
    arguments = parser.parse_args()
    result = run_audit(config_path=arguments.config, output_root=arguments.output_root)
    print(result)


if __name__ == "__main__":
    main()
