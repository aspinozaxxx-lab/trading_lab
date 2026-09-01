"""Adaptive stress-cost-aware calendar-spread candidate after V3."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import calendar_spread_v2 as v2
from market_lab.futures import calendar_spread_v3 as v3
from market_lab.futures import moex_calendar_spread_source as source

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/calendar_spread_v4.yaml"
SELECTED_PRIMARY: Final[str] = "cross_sectional_extremes"
REQUIRED_COST_RATIO: Final[float] = 2.0
EXPECTED_V3_CONFIG_SHA: Final[str] = (
    "c38a7356385baeb75be7f0f206f757d49ff192284239630aed1aee72a79f8f57"
)
EXPECTED_V3_MODULE_SHA: Final[str] = (
    "fb9b4e1556ee848fa93f1173cf70e1ab92ac9b4cc628ee0956f793dcc6383f86"
)
EXPECTED_V3_MANIFEST_SHA: Final[str] = (
    "a7de7e04333eb24a16f4c6862503d9a20a09095abc547305476326c2bab91adc"
)
EXPECTED_V3_METRICS_SHA: Final[str] = (
    "665e13cb7cc04173cc4d29a3d8f1e3c55a0fdeef45d196a9b10f8b8824529eb0"
)
COST_COLUMNS: Final[tuple[str, ...]] = (
    "near_sizing_point_value",
    "far_sizing_point_value",
    "near_tick_size",
    "far_tick_size",
    "near_conservative_fee_per_side",
    "far_conservative_fee_per_side",
)


@dataclass(frozen=True, slots=True)
class CostAwareProtocol:
    """V4 overlay plus the inherited V1-compatible economic payload."""

    payload: dict[str, Any]
    config_sha256: str
    economic: v1.EconomicProtocol


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar spread V4 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"calendar spread V4 sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = CONFIG_PATH) -> CostAwareProtocol:
    """Verify V4, inherited code, and the exact V3 result without market reads."""
    path = config_path.resolve()
    config_sha = source.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("calendar spread V4 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar spread V4 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_V3"), "parent")
    diagnosis = _mapping(payload.get("observed_V3_diagnosis"), "diagnosis")
    primary = _mapping(payload.get("V4_primary"), "primary")
    admission = _mapping(payload.get("cost_aware_admission"), "admission")
    inheritance = _mapping(payload.get("inheritance_from_V3"), "inheritance")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "calendar_spread_economic_v4"
        or payload.get("status")
        != "post_V3_adaptive_cost_aware_candidate_predeclared_before_V4_outcomes"
        or payload.get("sealed_before_V4_outcomes") is not True
        or payload.get("post_selection_adaptive") is not True
        or payload.get("independent_confirmation") is not False
        or payload.get("live_trading_allowed") is not False
        or parent.get("config_sha256") != EXPECTED_V3_CONFIG_SHA
        or parent.get("implementation_sha256") != EXPECTED_V3_MODULE_SHA
        or parent.get("canonical_manifest_sha256") != EXPECTED_V3_MANIFEST_SHA
        or parent.get("canonical_metrics_sha256") != EXPECTED_V3_METRICS_SHA
        or diagnosis.get("selected_candidate") != SELECTED_PRIMARY
        or diagnosis.get("selection_is_post_outcome") is not True
        or primary.get("strategy_id") != SELECTED_PRIMARY
        or float(admission.get("required_opportunity_to_stress_round_trip_ratio", 0.0))
        != REQUIRED_COST_RATIO
        or admission.get("failure_policy")
        != "reject_entire_preplanned_interval_without_retry_or_threshold_change"
        or inheritance.get("exact_ten_strategy_definitions") is not True
        or inheritance.get("exact_numeric_promotion_gates") is not True
        or inheritance.get("no_leverage_increase") is not True
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar spread V4 invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"calendar spread V4 dependency drift: {relative}")
    v3_protocol = v3.load_protocol()
    if v3_protocol.config_sha256 != EXPECTED_V3_CONFIG_SHA:
        raise ValueError("calendar spread V4 parent V3 drifted")
    v3_output = v3_protocol.economic.output_directory
    if (
        source.sha256_file(v3_output / "manifest.json") != EXPECTED_V3_MANIFEST_SHA
        or source.sha256_file(v3_output / "metrics.json") != EXPECTED_V3_METRICS_SHA
    ):
        raise ValueError("calendar spread V4 canonical V3 result drifted")
    economic_payload = copy.deepcopy(v3_protocol.economic.payload)
    economic_payload["protocol_id"] = "calendar_spread_economic_v4"
    economic_payload["status"] = str(payload["status"])
    economic_payload["hypothesis"]["primary_strategy"] = SELECTED_PRIMARY
    economic_payload["hypothesis"]["post_selection_adaptive"] = True
    economic_payload["features"]["cost_aware_admission"] = copy.deepcopy(admission)
    economic_payload["output"] = {
        **economic_payload["output"],
        "directory": str(output["directory"]),
    }
    economic = v1.EconomicProtocol(
        payload=economic_payload,
        config_sha256=config_sha,
        output_directory=source._project_path(str(output["directory"]), "runs"),
        input_paths=v3_protocol.economic.input_paths,
    )
    return CostAwareProtocol(
        payload=payload,
        config_sha256=config_sha,
        economic=economic,
    )


def _strategy_exit_thresholds(payload: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(row["id"]): float(row["exit_abs"])
        for row in payload["strategies"]
    }


def build_cost_aware_trade_plans(
    features: pd.DataFrame, protocol_payload: Mapping[str, Any]
) -> pd.DataFrame:
    """Admit only intervals whose ex-ante move exceeds twice stress round-trip cost."""
    missing = set(COST_COLUMNS) - set(features.columns)
    if missing:
        raise ValueError(f"calendar spread V4 cost fields missing: {sorted(missing)}")
    candidates = v3.build_width_independent_trade_plans(features, protocol_payload)
    lookup_columns = (
        "trade_date",
        "logical_asset",
        "spread_id",
        *COST_COLUMNS,
    )
    lookup = features.loc[:, lookup_columns].rename(
        columns={"trade_date": "entry_decision_date", "logical_asset": "asset"}
    )
    if lookup.duplicated(["entry_decision_date", "asset", "spread_id"]).any():
        raise ValueError("calendar spread V4 cost lookup is duplicated")
    plans = candidates.merge(
        lookup,
        on=["entry_decision_date", "asset", "spread_id"],
        how="left",
        validate="many_to_one",
    )
    numeric = plans.loc[:, COST_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("calendar spread V4 cost dependency is missing or nonfinite")
    if (numeric <= 0.0).any().any():
        raise ValueError("calendar spread V4 cost dependency must be positive")
    exit_threshold = plans["strategy_id"].map(
        _strategy_exit_thresholds(protocol_payload)
    )
    remaining_points = (
        plans["entry_score"].abs() - exit_threshold
    ).clip(lower=0.0) * plans["entry_scale"]
    conservative_point_value = numeric[
        ["near_sizing_point_value", "far_sizing_point_value"]
    ].min(axis=1)
    expected_cash = remaining_points * conservative_point_value
    stress_one_way = 4.0 * (
        numeric["near_tick_size"] * numeric["near_sizing_point_value"]
        + numeric["far_tick_size"] * numeric["far_sizing_point_value"]
    ) + 2.0 * (
        numeric["near_conservative_fee_per_side"]
        + numeric["far_conservative_fee_per_side"]
    )
    stress_round_trip = 2.0 * stress_one_way
    ratio = expected_cash / stress_round_trip
    plans["expected_cash_opportunity_per_contract"] = expected_cash
    plans["stress_round_trip_cost_per_contract"] = stress_round_trip
    plans["opportunity_to_stress_cost_ratio"] = ratio
    plans["required_opportunity_to_stress_cost_ratio"] = REQUIRED_COST_RATIO
    admitted = plans.loc[
        ratio.notna() & np.isfinite(ratio) & ratio.ge(REQUIRED_COST_RATIO)
    ].copy()
    if admitted.empty:
        raise ValueError("calendar spread V4 cost hurdle admitted no plans")
    return admitted.sort_values(
        ["strategy_id", "asset", "entry_decision_date"],
        kind="mergesort",
        ignore_index=True,
    )


_PARENT_PROMOTION: Final = v1._promotion
_PARENT_REPORT_TEXT: Final = v1._report_text


def selected_candidate_promotion(
    metrics: Mapping[str, Any], validation: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply unchanged numeric gates to the explicitly post-selected candidate."""
    aliased = dict(metrics)
    aliased[v1.STRATEGY_IDS[0]] = metrics[SELECTED_PRIMARY]
    result = _PARENT_PROMOTION(aliased, validation)
    result["selected_primary_strategy"] = SELECTED_PRIMARY
    result["post_selection_adaptive"] = True
    result["independent_confirmation"] = False
    if result["passed"]:
        result["verdict"] = (
            "ADAPTIVE_LEAD_REQUIRES_NEW_UNSEEN_MULTILEG_VALIDATION"
        )
    return result


def adaptive_report_text(payload: Mapping[str, Any]) -> str:
    """Correct the inherited report's primary-status disclosure."""
    report = _PARENT_REPORT_TEXT(payload)
    return report.replace(
        "Primary strategy was fixed before outcomes. The best of ten is exploratory only.",
        "V4 primary cross_sectional_extremes was selected after V3 outcomes; even a pass "
        "is only an adaptive lead requiring new unseen multileg validation.",
    )


@contextlib.contextmanager
def _correction_context() -> Iterator[None]:
    original_metrics = v1._period_metrics
    original_features = v1.build_feature_frame
    original_plans = v1.build_trade_plans
    original_promotion = v1._promotion
    original_report = v1._report_text
    original_active_columns = v1.ACTIVE_COLUMNS
    original_config = v1.CONFIG_PATH
    v1._period_metrics = v2.corrected_period_metrics
    v1.build_feature_frame = v3.build_last_trade_feature_frame
    v1.build_trade_plans = build_cost_aware_trade_plans
    v1._promotion = selected_candidate_promotion
    v1._report_text = adaptive_report_text
    v1.ACTIVE_COLUMNS = (*original_active_columns, *COST_COLUMNS)
    v1.CONFIG_PATH = CONFIG_PATH
    try:
        yield
    finally:
        v1._period_metrics = original_metrics
        v1.build_feature_frame = original_features
        v1.build_trade_plans = original_plans
        v1._promotion = original_promotion
        v1._report_text = original_report
        v1.ACTIVE_COLUMNS = original_active_columns
        v1.CONFIG_PATH = original_config


def run_experiment(protocol: CostAwareProtocol | None = None) -> Path:
    """Run inherited V3 economics with only the sealed cost-aware admission."""
    protocol = protocol or load_protocol()
    with _correction_context():
        return v1.run_experiment(protocol.economic)


def audit_bundle(protocol: CostAwareProtocol | None = None) -> dict[str, bool]:
    """Audit inherited artifacts plus the exact V4 cost hurdle."""
    protocol = protocol or load_protocol()
    checks = v1.audit_bundle(protocol.economic)
    plans = pd.read_parquet(
        protocol.economic.output_directory / "plans.parquet",
        columns=(
            "opportunity_to_stress_cost_ratio",
            "required_opportunity_to_stress_cost_ratio",
        ),
    )
    checks["cost_aware_plans_nonempty"] = bool(len(plans) > 0)
    checks["cost_hurdle_exact"] = bool(
        plans["required_opportunity_to_stress_cost_ratio"]
        .eq(REQUIRED_COST_RATIO)
        .all()
        and plans["opportunity_to_stress_cost_ratio"]
        .ge(REQUIRED_COST_RATIO)
        .all()
    )
    if not all(checks.values()):
        raise ValueError(f"calendar spread V4 audit failed: {checks}")
    return checks


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.audit_only:
        print(json.dumps(audit_bundle(), ensure_ascii=False, indent=2))
    else:
        print(run_experiment())


if __name__ == "__main__":
    main()
