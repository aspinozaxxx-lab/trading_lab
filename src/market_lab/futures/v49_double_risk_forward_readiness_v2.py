"""V49 post-seal readiness admitting all sealed FRED transport routes."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v27_forward_component_readiness_v3 as component_readiness
from market_lab.futures import v39_forward_validation_readiness as v39_readiness
from market_lab.futures import v48_frontier_forward_readiness_v4 as v48_readiness
from market_lab.futures import v49_double_risk_forward_readiness as parent


def load_config() -> dict[str, Any]:
    config = parent.load_config()
    correction = component_readiness.load_config()
    v48_readiness.load_config()
    invariants = correction["economic_invariants"]
    if (
        correction["protocol_id"]
        != "v48_frontier_forward_fred_transport_v2_correction_v1"
        or invariants["V27_V39_V48_V49_signal_or_weight_changed"] is not False
        or invariants["execution_cost_margin_capacity_or_quote_mark_changed"] is not False
        or invariants["warmup_evaluation_or_promotion_gates_changed"] is not False
        or correction["live_trading_allowed"] is not False
    ):
        raise ValueError("V49 FRED transport V2 readiness drifted")
    return config


def _assess_sources(
    config: dict[str, Any],
    boundary: Any,
    option_root: Path,
    component_root: Path,
    *,
    protocol_id: str,
    protocol_sha256: str,
) -> dict[str, Any]:
    option_dates, option_invalid, option_report, preseal_options = (
        parent._postseal_option_weeks(option_root, boundary)
    )
    component_report = component_readiness.assess(component_root)
    components, preseal_components = parent._postseal_components(
        component_report, boundary
    )
    decisions = sorted(
        {
            date.fromisoformat(str(item["source_dates"][0]))
            for item in components
            if item["component"] == "market_decision" and len(item["source_dates"]) == 1
        }
    )
    executions = {
        str(item["source_dates"][0])
        for item in components
        if item["component"] == "market_execution" and len(item["source_dates"]) == 1
    }
    fred = [item for item in components if item["component"] == "macro_fred"]
    cbr = [item for item in components if item["component"] == "macro_cbr"]
    fred_times = [parent._timestamp(item["retrieved_at_utc"]) for item in fred]
    cbr_times = [parent._timestamp(item["retrieved_at_utc"]) for item in cbr]
    decision_items = [item for item in components if item["component"] == "market_decision"]
    joinable = [
        str(item["source_dates"][0])
        for item in decision_items
        if any(value <= parent._timestamp(item["retrieved_at_utc"]) for value in fred_times)
        and any(value <= parent._timestamp(item["retrieved_at_utc"]) for value in cbr_times)
    ]
    progress = v39_readiness.joint_progress(
        option_dates, decisions, v39_readiness.load_config()
    )
    macro_ready = bool(fred and cbr)
    execution_ready = bool(executions)
    paper_ready = bool(progress["joint_warmup_complete"] and macro_ready and execution_ready)
    annualization = bool(progress["evaluation_complete"] and paper_ready)
    if not progress["joint_warmup_complete"]:
        phase = "postseal_joint_warmup"
    elif not macro_ready or not execution_ready:
        phase = "postseal_source_wait"
    elif not progress["evaluation_complete"]:
        phase = "postseal_unseen_evaluation"
    else:
        phase = "independent_review"
    progress = {
        **progress,
        "current_phase": phase,
        "postseal_FRED_component_available": bool(fred),
        "postseal_CBR_component_available": bool(cbr),
        "postseal_execution_component_available": execution_ready,
        "postseal_causally_joinable_decision_dates": len(set(joinable)),
        "paper_economics_may_start": paper_ready,
        "cagr_reporting_allowed": annualization,
        "live_trading_allowed": False,
    }
    arm = config["fixed_arm"]
    return {
        "protocol_id": protocol_id,
        "protocol_sha256": protocol_sha256,
        "readiness_version": 2,
        "FRED_transport_admission_protocol_sha256": component_readiness.CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "eligibility_boundary_utc": boundary.isoformat(),
        "option_root": str(option_root.resolve()),
        "component_root": str(component_root.resolve()),
        "fixed_arm": {
            "name": arm["name"],
            "V39_mapped_target_multiplier": float(arm["V39_mapped_target_multiplier"]),
            "maximum_gross_notional_multiple": float(
                arm["maximum_gross_notional_multiple"]
            ),
            "initial_margin_buffer_multiplier": float(
                arm["initial_margin_buffer_multiplier"]
            ),
            "maximum_prior_official_volume_participation": float(
                arm["maximum_prior_official_volume_participation"]
            ),
        },
        "postseal_valid_option_weekly_levels": len(option_dates),
        "postseal_valid_market_decision_dates": len(decisions),
        "postseal_valid_market_execution_dates": len(executions),
        "postseal_valid_macro_FRED_snapshots": len(fred),
        "postseal_valid_macro_CBR_snapshots": len(cbr),
        "excluded_preseal_option_snapshots": preseal_options,
        "excluded_preseal_component_snapshots": preseal_components,
        "invalid_postseal_V39_option_snapshots": option_invalid,
        "option_source_invalid_snapshot_count": option_report["invalid_snapshot_count"],
        "component_source_invalid_snapshot_count": component_report["invalid_snapshot_count"],
        "progress": progress,
        "contains_signal_return_target_prediction_or_pnl": False,
        "live_trading_allowed": False,
    }


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    boundary = parent._timestamp(
        config["forward_boundary"]["earliest_eligible_retrieved_at_utc"]
    )
    return _assess_sources(
        config,
        boundary,
        option_root,
        component_root,
        protocol_id=config["protocol_id"],
        protocol_sha256=parent.CONFIG_SHA256,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--component-root", type=Path, default=component_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.component_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
