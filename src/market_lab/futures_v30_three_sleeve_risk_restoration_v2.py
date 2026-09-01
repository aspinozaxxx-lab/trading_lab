"""V30-D2: correct only the pre-execution holdout-proof boolean polarity."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v29_risk_first_roll as v29
from market_lab import futures_v30_three_sleeve_risk_restoration as v1

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v30_three_sleeve_risk_restoration_v2.yaml"
)
PARENT_CONFIG_RELATIVE: Final[str] = (
    "configs/futures_v30_three_sleeve_risk_restoration.yaml"
)
PARENT_CONFIG_SHA256: Final[str] = (
    "2e191a82f1a6145667f640d565541de49e69e5bee6081b06764074344c43ce8a"
)
PARENT_MODULE_SHA256: Final[str] = (
    "b642afe2cd7b112a2f69c6854fcf47e28bd566c065dd39b7412a0ba04df3c9e7"
)
V2_PROTOCOL_ID: Final[str] = "futures_v30_three_sleeve_risk_restoration_v2"


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"V30-D2 {label} must be a mapping")
    return value


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> v1.V30Protocol:
    """Verify the persistence-free gate correction and its immutable V1 parent."""
    path = config_path.resolve()
    actual_sha = v12.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("V30-D2 protocol SHA-256 mismatch")
    correction = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(correction, dict):
        raise TypeError("V30-D2 protocol must be a YAML object")
    parent_record = _mapping(correction.get("parent_V1"), "parent V1")
    failure = _mapping(correction.get("failed_V1_attempt"), "failed V1 attempt")
    changed = _mapping(correction.get("only_changed_behavior"), "changed behavior")
    if (
        correction.get("protocol_id") != V2_PROTOCOL_ID
        or correction.get("status")
        != "pre_execution_boolean_correction_before_canonical_development_run"
        or correction.get("research_only") is not True
        or correction.get("live_trading_allowed") is not False
        or str(parent_record.get("path")) != PARENT_CONFIG_RELATIVE
        or str(parent_record.get("sha256")) != PARENT_CONFIG_SHA256
        or str(parent_record.get("module_sha256")) != PARENT_MODULE_SHA256
        or failure.get("output_published") is not False
        or failure.get("ledger_execution_started") is not False
        or failure.get("strategy_outcomes_computed") is not False
        or failure.get("pre2012_prices_returns_or_pnl_read") is not False
        or int(failure.get("total_aggregated_checks", -1)) != 86
        or int(failure.get("true_checks", -1)) != 85
        or failure.get("only_false_key") != "pre2012_outcomes_read_by_V30"
        or failure.get("only_false_value") is not False
        or changed.get("old_non_assertion_fact")
        != "pre2012_outcomes_read_by_V30_equals_false"
        or changed.get("new_positive_proof")
        != "pre2012_outcomes_not_read_by_V30_equals_true"
        or changed.get("source_signal_target_risk_execution_costs_or_gates_changed")
        is not False
    ):
        raise ValueError("V30-D2 correction invariants drifted")
    parent_path = PROJECT_ROOT / str(parent_record["path"])
    if v12.sha256_file(parent_path) != PARENT_CONFIG_SHA256:
        raise ValueError("V30-D2 parent config bytes drifted")
    if (
        v12.sha256_file(
            PROJECT_ROOT / "src/market_lab/futures_v30_three_sleeve_risk_restoration.py"
        )
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("V30-D2 parent module bytes drifted")
    parent = v1.load_protocol(parent_path)
    dependencies = _mapping(
        correction.get("implementation_dependencies"), "dependencies"
    )
    dependency_hashes = dict(parent.dependency_hashes)
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v12.sha256_file(dependency_path) != digest:
            raise ValueError(f"V30-D2 implementation dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    payload = copy.deepcopy(parent.payload)
    payload.update(
        {
            "protocol_id": V2_PROTOCOL_ID,
            "status": correction["status"],
            "correction_lineage": {
                "parent_V1_config_sha256": PARENT_CONFIG_SHA256,
                "parent_V1_module_sha256": PARENT_MODULE_SHA256,
                "failed_V1_attempt": dict(failure),
                "only_changed_behavior": dict(changed),
            },
            "implementation_dependencies": dependency_hashes,
        }
    )
    payload["output"] = {
        **payload["output"],
        "run_prefix": "v30_three_sleeve_risk_v2",
    }
    return v1.V30Protocol(path, actual_sha, payload, parent.paths, dependency_hashes)


def corrected_pre_execution_checks(
    verified: v1.VerifiedInputs,
    signal: v1.SignalBuild,
    targets: v1.TargetBuild,
    *,
    predecessor: pd.Timestamp,
    execution_session_count: int,
    coverage_rows: int,
) -> dict[str, bool]:
    """Aggregate the same V1 proofs with a positive holdout-preservation assertion."""
    checks = {
        **verified.checks,
        **signal.checks,
        **targets.checks,
        "execution_predecessor_exact": predecessor == v1.EXPECTED_PREDECESSOR,
        "execution_sessions_exact": execution_session_count == 1225,
        "coverage_rows_match_nonzero_targets": coverage_rows
        == int(targets.restored_targets["target_weight"].abs().gt(1e-12).sum()),
        "pre2012_outcomes_not_read_by_V30": True,
    }
    if len(checks) != 86:
        raise ValueError(f"V30-D2 aggregated check count drifted: {len(checks)}")
    return checks


def run_experiment(
    output_root: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> Path:
    """Run one immutable V30-D2 development evaluation after the gate-only correction."""
    protocol = load_protocol(config_path)
    verified = v1.verify_inputs(protocol)
    inputs = protocol.payload["inputs"]
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
    signal = v1.build_three_sleeve_scores(panel)
    targets = v1.build_targets(panel, signal.scores, active)
    market = v12.build_execution_market(observations, specs)
    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v1.VALIDATION_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, v1.VALIDATION_END
        )
    ].copy()
    coverage = v12.execution_coverage(market, targets.restored_targets)
    checks = corrected_pre_execution_checks(
        verified,
        signal,
        targets,
        predecessor=predecessor,
        execution_session_count=execution_market["session_date"].nunique(),
        coverage_rows=len(coverage),
    )
    if not all(checks.values()):
        raise ValueError(f"V30-D2 pre-execution checks failed: {checks}")
    scenario_declarations = protocol.payload["execution"]["cost_scenarios"]
    run_specs = {
        "baseline_1x_primary": (
            targets.unscaled_targets,
            scenario_declarations["primary"],
        ),
        "primary": (targets.restored_targets, scenario_declarations["primary"]),
        "doubled": (targets.restored_targets, scenario_declarations["doubled"]),
        "stress": (targets.restored_targets, scenario_declarations["stress"]),
        "hard_2x_primary": (targets.hard_2x_targets, scenario_declarations["primary"]),
        "hard_2x_stress": (targets.hard_2x_targets, scenario_declarations["stress"]),
    }
    outputs: dict[str, Any] = {}
    metrics: dict[str, dict[str, Any]] = {}
    for name, (scenario_targets, settings) in run_specs.items():
        result = v29.run_risk_first_portfolio_ledger(
            execution_market,
            scenario_targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        outputs[name] = result
        metrics[name] = v1._scenario_metrics(result, execution_market, settings)
    robustness_summary, bootstrap, rolling, leave = v1._robustness_outputs(
        {name: outputs[name] for name in ("primary", "stress")}, protocol
    )
    nonzero = int(targets.restored_targets["target_weight"].abs().gt(1e-12).sum())
    counts = {
        **signal.counts,
        "source_panel_rows": len(panel),
        "weekly_decisions": targets.weekly_decisions,
        "roll_decisions": targets.roll_decisions,
        "mapped_target_rows": len(targets.restored_targets),
        "nonzero_targets": nonzero,
        "covered_nonzero_targets": int(
            coverage["execution_dependencies_complete"].sum()
        ),
        "mean_risk_multiplier": float(targets.risk_audit["risk_multiplier"].mean()),
        "maximum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].max()),
        "minimum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].min()),
    }
    assessment = v1.assess_candidate(metrics, robustness_summary, checks)
    correction = protocol.payload["correction_lineage"]
    identity = {
        "protocol_sha256": protocol.config_sha256,
        "parent_V1_config_sha256": PARENT_CONFIG_SHA256,
        "parent_V1_module_sha256": PARENT_MODULE_SHA256,
        "market_manifest_sha256": inputs["market_manifest"]["sha256"],
        "input_sha256": {name: value["sha256"] for name, value in inputs.items()},
        "implementation_sha256": protocol.dependency_hashes,
        "only_changed_behavior": correction["only_changed_behavior"],
        "development_period_outcomes_observed_before_formula_freeze": True,
        "pre2012_returns_or_pnl_observed": False,
        "contains_2018_or_later_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "development_selection": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
        "correction_lineage": correction,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": metrics,
        "robustness": robustness_summary,
        "assessment": assessment,
        "limitations": protocol.payload["limitations"],
    }
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v30_three_sleeve_risk_v2_{timestamp}_{protocol.config_sha256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V30-D2 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(protocol.config_path, temporary / "resolved_protocol.yaml")
        shutil.copyfile(
            PROJECT_ROOT / PARENT_CONFIG_RELATIVE,
            temporary / "parent_v1_protocol.yaml",
        )
        v1._write_parquet(temporary / "scores.parquet", signal.scores)
        v1._write_parquet(temporary / "signal_components.parquet", signal.components)
        v1._write_parquet(temporary / "weekly_weights.parquet", targets.weekly_weights)
        v1._write_parquet(temporary / "risk_restoration.parquet", targets.risk_audit)
        v1._write_parquet(temporary / "mapped_targets_1x.parquet", targets.unscaled_targets)
        v1._write_parquet(
            temporary / "mapped_targets_risk_restored.parquet",
            targets.restored_targets,
        )
        v1._write_parquet(
            temporary / "mapped_targets_hard_2x.parquet",
            targets.hard_2x_targets,
        )
        targets.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        v1._write_parquet(temporary / "bootstrap.parquet", bootstrap)
        v1._write_parquet(temporary / "rolling_252.parquet", rolling)
        leave.to_csv(
            temporary / "leave_one_year_out.csv", index=False, encoding="utf-8-sig"
        )
        for name, result in outputs.items():
            v1._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v1._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v1._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        (temporary / "report.md").write_text(
            v1._report_text(payload), encoding="utf-8-sig"
        )
        artifacts: dict[str, Any] = {}
        for artifact_path in sorted(temporary.iterdir()):
            if artifact_path.name in {"metrics.json", "identity.json"}:
                continue
            record: dict[str, Any] = {
                "bytes": artifact_path.stat().st_size,
                "sha256": v12.sha256_file(artifact_path),
            }
            if artifact_path.suffix == ".parquet":
                record["rows"] = pq.ParquetFile(artifact_path).metadata.num_rows
            artifacts[artifact_path.name] = record
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(
                v12._json_safe(payload),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
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
