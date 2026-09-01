"""Sealed V29 post-V28 risk-first roll-capacity correction."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v28_pre2018_unseen_validation as v28
from market_lab.futures import portfolio_ledger as ledger_engine
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/futures_v29_risk_first_roll.yaml"
PARENT_V28_CONFIG_SHA256: Final[str] = (
    "4f9e66634803a7ac1c100ecdc998e1ca6e29558b704416003bff9331eac511b2"
)
PARENT_V28_METRICS_SHA256: Final[str] = (
    "73b614b8a63adaa77b4380bf77b8d8e5d9a92b2fe69272fe2b843583a41cfaed"
)
_BASE_CAPACITY_ADMISSION = ledger_engine._fit_capacity_admission


@dataclass(frozen=True, slots=True)
class V29Protocol:
    """Verified V29 protocol plus its immutable parent V28 identity."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    parent: v28.V28Protocol
    parent_metrics_path: Path
    dependency_hashes: dict[str, str]


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"V29 protocol sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"V29 {label} must be a mapping")
    return value


def _resolved_run_file(relative_value: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe V29 run path: {relative_value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError(f"V29 parent outcome is outside runs: {relative_value}")
    root = (PROJECT_ROOT / "runs").resolve()
    resolved = (PROJECT_ROOT / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"V29 parent outcome escapes external runs: {relative_value}")
    return resolved


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> V29Protocol:
    """Verify the post-V28 seal and the single risk-first execution correction."""
    path = config_path.resolve()
    actual_sha = v12.sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("V29 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("sealed V29 protocol must be a mapping")
    parent_record = _mapping(payload.get("parent_V28"), "parent V28")
    correction = _mapping(payload.get("only_changed_behavior"), "correction")
    execution = _mapping(payload.get("execution"), "execution")
    validation = _mapping(payload.get("validation"), "validation")
    if (
        payload.get("protocol_id") != "futures_v29_risk_first_roll_v1"
        or payload.get("status") != "predeclared_after_V28_before_V29_outcomes"
        or payload.get("sealed_before_outcomes") is not True
        or payload.get("live_trading_allowed") is not False
        or parent_record.get("protocol_sha256") != PARENT_V28_CONFIG_SHA256
        or parent_record.get("metrics_sha256") != PARENT_V28_METRICS_SHA256
        or parent_record.get("outcome_observed_before_V29") is not True
        or correction.get("id") != "risk_first_roll_exit_then_capacity_clipped_entry"
        or correction.get("old_leg_exit_requirement")
        != "full_exit_only_when_factual_open_and_one_percent_capacity_prove_execution"
        or correction.get("new_leg_policy")
        != "independent_clip_to_one_percent_capacity_or_cash"
        or correction.get("old_exit_capacity_insufficient")
        != "retain_old_position_flag_execution_invalid"
        or correction.get("maximum_participation_changed") is not False
        or correction.get("signal_governor_leverage_collateral_or_cost_changed") is not False
        or execution.get("unexecutable_target_policy") != "risk_first_roll_then_cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"])
        != v15.MARGIN_BUFFER_MULTIPLIER
        or validation.get("period_role") != "post_V28_adaptive_execution_correction"
        or validation.get("independent_confirmation") is not False
        or validation.get("target_gates_byte_identical_to_V28") is not True
    ):
        raise ValueError("sealed V29 invariants drifted")
    if v12._scenario_settings(payload) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("V29 cost scenarios drifted")
    parent = v28.load_protocol()
    if parent.config_sha256 != PARENT_V28_CONFIG_SHA256:
        raise ValueError("V29 parent V28 config identity drifted")
    parent_metrics_path = _resolved_run_file(str(parent_record["metrics_path"]))
    if (
        not parent_metrics_path.is_file()
        or parent_metrics_path.stat().st_size != int(parent_record["metrics_bytes"])
        or v12.sha256_file(parent_metrics_path) != PARENT_V28_METRICS_SHA256
    ):
        raise ValueError("V29 parent V28 metrics identity drifted")
    parent_metrics = json.loads(parent_metrics_path.read_text(encoding="utf-8-sig"))
    parent_diagnosis = _mapping(parent_record.get("sealed_diagnosis"), "parent diagnosis")
    primary = parent_metrics["scenarios"]["primary"]["futures_only"]
    if (
        parent_metrics["assessment"]["verdict"] != "FAIL_UNSEEN_20"
        or bool(primary["execution_complete"])
        or int(primary["critical_failure_count"])
        != int(parent_diagnosis["critical_failure_count"])
        or int(primary["target_cancel_roll_capacity_count"])
        != int(parent_diagnosis["capacity_cancelled_roll_count"])
        or int(primary["rejected_leg_count"])
        != int(parent_diagnosis["rejected_leg_count"])
    ):
        raise ValueError("V29 parent V28 diagnosis no longer matches canonical metrics")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v12.sha256_file(dependency_path) != digest:
            raise ValueError(f"V29 implementation dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return V29Protocol(
        path,
        actual_sha,
        payload,
        parent,
        parent_metrics_path,
        dependency_hashes,
    )


def _finite_positive(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(number) and number > 0.0)


def risk_first_capacity_admission(
    desired: dict[str, tuple[str | None, int, pd.Series | None]],
    positions: dict[str, Any],
    indexed: pd.DataFrame,
    session_date: pd.Timestamp,
    config: Any,
    counters: Any,
) -> tuple[
    dict[str, tuple[str | None, int, pd.Series | None]],
    set[str],
    set[str],
]:
    """Exit a provably executable old roll leg before clipping the independent entry."""
    transformed = dict(desired)
    pre_cancelled: set[str] = set()
    pre_clipped: set[str] = set()
    for asset, (desired_contract, desired_quantity, desired_row) in desired.items():
        position = positions[asset]
        old_contract = position.contract_id
        old_quantity = int(position.contracts)
        contract_switch = (
            old_contract is not None
            and old_quantity != 0
            and desired_contract is not None
            and desired_contract != old_contract
        )
        if not contract_switch:
            continue
        old_row = ledger_engine._market_row(indexed, session_date, asset, old_contract)
        if old_row is None or not _finite_positive(old_row["open"]):
            transformed[asset] = (old_contract, old_quantity, old_row)
            counters.target_cancel_no_open_count += 1
            pre_cancelled.add(asset)
            continue
        if not _finite_positive(old_row["lagged_volume"]):
            transformed[asset] = (old_contract, old_quantity, old_row)
            counters.target_cancel_no_liquidity_count += 1
            pre_cancelled.add(asset)
            continue
        old_capacity = int(
            np.floor(float(old_row["lagged_volume"]) * config.maximum_participation)
        )
        if abs(old_quantity) > old_capacity:
            transformed[asset] = (old_contract, old_quantity, old_row)
            counters.target_cancel_roll_capacity_count += 1
            pre_cancelled.add(asset)
            continue
        if desired_quantity == 0:
            transformed[asset] = (None, 0, None)
            continue
        new_entry_proved = (
            desired_row is not None
            and _finite_positive(desired_row["open"])
            and _finite_positive(desired_row["lagged_volume"])
        )
        new_capacity = (
            int(
                np.floor(
                    float(desired_row["lagged_volume"])
                    * config.maximum_participation
                )
            )
            if new_entry_proved
            else 0
        )
        admitted_absolute = min(abs(int(desired_quantity)), new_capacity)
        admitted_quantity = (
            (1 if int(desired_quantity) > 0 else -1) * admitted_absolute
            if admitted_absolute > 0
            else 0
        )
        transformed[asset] = (
            desired_contract if admitted_quantity != 0 else None,
            admitted_quantity,
            desired_row if admitted_quantity != 0 else None,
        )
        if admitted_quantity != int(desired_quantity):
            counters.participation_clip_count += 1
            pre_clipped.add(asset)
    fitted, cancelled, clipped = _BASE_CAPACITY_ADMISSION(
        transformed,
        positions,
        indexed,
        session_date,
        config,
        counters,
    )
    return fitted, pre_cancelled | cancelled, pre_clipped | clipped


def run_risk_first_portfolio_ledger(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    config: v26.CapacityAwareLeveredLedgerConfig,
) -> FuturesPortfolioLedgerResult:
    """Transactionally replace only V26 roll-capacity admission for one ledger run."""
    original = ledger_engine._fit_capacity_admission
    if original is not _BASE_CAPACITY_ADMISSION:
        raise RuntimeError("V29 refuses nested or externally replaced capacity admission")
    ledger_engine._fit_capacity_admission = risk_first_capacity_admission
    try:
        return v15.run_levered_portfolio_ledger(market, targets, config)
    finally:
        ledger_engine._fit_capacity_admission = original


def _assessment(
    results: Mapping[str, Mapping[str, Any]], checks: Mapping[str, bool]
) -> dict[str, Any]:
    inherited = v28._assessment(results, checks)
    support_20 = bool(inherited["support_20_percent"]["passed"])
    inherited["verdict"] = (
        "PASS_POST_V28_20_RESEARCH_ONLY" if support_20 else "FAIL_POST_V28_20"
    )
    inherited["unseen_market_period_external_validation"] = False
    inherited["post_V28_adaptive_execution_correction"] = True
    inherited["independent_confirmation"] = False
    return inherited


def _report_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "# V29 post-V28 risk-first roll-capacity correction",
        "",
        f"Verdict: **{payload['assessment']['verdict']}** (research-only; live forbidden).",
        "",
        "This version was designed after observing the V28 execution failure and is not "
        "an independent holdout.",
        "",
        "| Scenario | Combined return | CAGR | Sharpe | MDD | Critical | Roll cancels | Clips |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        combined = item["combined"]
        futures = item["futures_only"]
        lines.append(
            f"| {name} | {combined['total_return']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{futures['critical_failure_count']} | "
            f"{futures['target_cancel_roll_capacity_count']} | "
            f"{futures['participation_clip_count']} |"
        )
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["combined"][
        "annual_returns"
    ].items():
        lines.append(f"- {year}: {value:.4%}")
    primary = payload["scenarios"]["primary"]
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Execution and coverage",
            "",
            f"- V28 parent critical failures: {counts['parent_V28_critical_failures']}",
            f"- V29 critical failures: {primary['futures_only']['critical_failure_count']}",
            f"- Risk-first/ordinary capacity clips: "
            f"{primary['futures_only']['participation_clip_count']}",
            f"- Remaining roll-capacity cancellations: "
            f"{primary['futures_only']['target_cancel_roll_capacity_count']}",
            f"- Nonzero next-open coverage: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            f"- RUONIA recognized intervals: "
            f"{primary['collateral']['known_rate_intervals']}/"
            f"{primary['collateral']['accrual_intervals']}",
            "",
            "Old-leg liquidation and new-leg entry share the unchanged 1% per-leg capacity "
            "limit. A provable old exit executes first; the independent new entry is clipped "
            "to capacity or cash. Any unprovable old exit remains an execution failure.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path, config_path: Path = DEFAULT_CONFIG) -> Path:
    """Execute exactly one immutable post-V28 V29 run."""
    protocol = load_protocol(config_path)
    verified = v28.verify_inputs(protocol.parent)
    macro = v28.verify_macro_bundle(protocol.parent, verified)
    inputs = protocol.parent.payload["inputs"]
    panel = pd.read_parquet(
        verified.paths["market_panel"], columns=inputs["market_panel"]["read_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=inputs["active_contract_map"]["read_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=inputs["contract_observations"]["read_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"], columns=inputs["spec_proxy"]["read_columns"]
    )
    checks = {
        **verified.checks,
        **macro.checks,
        "parent_V28_protocol_seal": protocol.parent.config_sha256
        == PARENT_V28_CONFIG_SHA256,
        "parent_V28_metrics_seal": v12.sha256_file(protocol.parent_metrics_path)
        == PARENT_V28_METRICS_SHA256,
    }
    scores = v12.build_trend_scores(panel)
    weekly_v12 = v12.build_weekly_weights(panel, scores)
    governed = v28.apply_frozen_governors(weekly_v12, macro)
    checks.update(governed.checks)
    levered_weekly = v28.build_levered_weekly_weights(governed.weights)
    target_build = v28.build_levered_execution_targets(governed.weights, active)
    mapped_gross = target_build.targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    checks["mapped_target_gross_at_most_two"] = bool(
        mapped_gross.le(v15.MAXIMUM_GROSS + 1e-12).all()
    )
    market = v12.build_execution_market(observations, specs)
    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v28.VALIDATION_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, v28.VALIDATION_END
        )
    ].copy()
    checks["execution_predecessor_exact"] = predecessor == v28.EXPECTED_PREDECESSOR
    checks["execution_session_count_exact"] = (
        execution_market["session_date"].nunique()
        == v28.EXPECTED_COLLATERAL_CALENDAR["execution_sessions"]
    )
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero_targets = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    covered_nonzero_targets = int(coverage["execution_dependencies_complete"].sum())
    checks["execution_coverage_report_complete"] = len(coverage) == nonzero_targets
    if not all(checks.values()):
        raise ValueError(f"V29 pre-execution invariant failure: {checks}")

    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, v28.CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol.payload).items():
        result = run_risk_first_portfolio_ledger(
            execution_market,
            target_build.targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = v28._scenario_payload(
            result, execution_market, settings, macro.ruonia
        )
        checks.update(
            {
                f"{name}_{key}": value
                for key, value in collateral_outputs[name].checks.items()
            }
        )
    parent_metrics = json.loads(
        protocol.parent_metrics_path.read_text(encoding="utf-8-sig")
    )
    parent_primary = parent_metrics["scenarios"]["primary"]["futures_only"]
    counts = {
        "source_panel_rows": int(len(panel)),
        "validation_weekly_decisions": governed.validation_counts["weekly_decisions"],
        "validation_pass_both": governed.validation_counts["pass_both"],
        "mapped_weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
        "parent_V28_critical_failures": int(parent_primary["critical_failure_count"]),
        "parent_V28_rejected_legs": int(parent_primary["rejected_leg_count"]),
        "parent_V28_cancelled_rolls": int(
            parent_primary["target_cancel_roll_capacity_count"]
        ),
    }
    assessment = _assessment(scenario_results, checks)
    identity = {
        "protocol_sha256": protocol.config_sha256,
        "parent_V28_protocol_sha256": PARENT_V28_CONFIG_SHA256,
        "parent_V28_metrics_sha256": PARENT_V28_METRICS_SHA256,
        "inherited_input_sha256": {
            name: declaration["sha256"] for name, declaration in inputs.items()
        },
        "implementation_sha256": protocol.dependency_hashes,
        "protected_from": v28.PROTECTED_FROM.date().isoformat(),
        "contains_2018_or_later_market_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "post_V28_adaptive_execution_correction": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "assessment": assessment,
        "parent_V28_reference": protocol.payload["parent_V28"],
        "limitations": protocol.payload["limitations"],
    }
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v29_risk_first_roll_{timestamp}_{protocol.config_sha256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V29 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(protocol.config_path, temporary / "resolved_protocol.yaml")
        shutil.copyfile(
            protocol.parent.config_path, temporary / "parent_v28_protocol.yaml"
        )
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_v12)
        v12._write_parquet(
            temporary / "weekly_v29_governed_weights.parquet", governed.weights
        )
        v12._write_parquet(
            temporary / "weekly_v29_levered_weights.parquet", levered_weekly
        )
        governed.governor.to_csv(
            temporary / "combined_governor.csv", index=False, encoding="utf-8-sig"
        )
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"collateral_{name}.parquet", collateral_outputs[name].audit
            )
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet",
                collateral_outputs[name].combined_ledger,
            )
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for artifact_path in sorted(temporary.iterdir()):
            if artifact_path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": artifact_path.stat().st_size,
                "sha256": v12.sha256_file(artifact_path),
            }
            if artifact_path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(artifact_path).metadata.num_rows
            artifacts[artifact_path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps(
                v12._json_safe(
                    {**identity, "metrics_sha256": v12.sha256_file(metrics_path)}
                ),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    arguments = parser.parse_args(argv)
    print(run_experiment(arguments.output_root, arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
