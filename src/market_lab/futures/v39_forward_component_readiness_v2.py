"""V39 readiness over componentized V27 data and all sealed FRED routes."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v27_forward_component_readiness_v3 as component_readiness
from market_lab.futures import v39_forward_validation_readiness as parent
from market_lab.futures import v48_frontier_forward_readiness_v2 as option_component


def load_config() -> dict[str, Any]:
    config = parent.load_config()
    correction = component_readiness.load_config()
    invariants = correction["economic_invariants"]
    if (
        correction["protocol_id"]
        != "v48_frontier_forward_fred_transport_v2_correction_v1"
        or invariants["V27_V39_V48_V49_signal_or_weight_changed"] is not False
        or invariants["macro_join_rule_changed"] is not False
        or invariants["warmup_evaluation_or_promotion_gates_changed"] is not False
        or correction["live_trading_allowed"] is not False
    ):
        raise ValueError("V39 component/FRED V2 readiness drifted")
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    weekly_dates, invalid_option, option_report = option_component._option_weekly_dates(
        option_root
    )
    components = component_readiness.assess(component_root)
    decision_dates = sorted(
        {
            date.fromisoformat(str(item["source_dates"][0]))
            for item in components["valid_snapshots"]
            if item["component"] == "market_decision" and len(item["source_dates"]) == 1
        }
    )
    progress = parent.joint_progress(weekly_dates, decision_dates, config)
    macro_ready = bool(components["progress"]["macro_state_ready"])
    execution_ready = components["valid_market_execution_dates"] > 0
    paper_ready = bool(progress["joint_warmup_complete"] and macro_ready and execution_ready)
    annualization = bool(progress["evaluation_complete"] and macro_ready and execution_ready)
    if not progress["joint_warmup_complete"]:
        phase = "joint_warmup"
    elif not macro_ready or not execution_ready:
        phase = "source_wait"
    elif not progress["evaluation_complete"]:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    progress = {
        **progress,
        "current_phase": phase,
        "FRED_component_available": components["progress"]["FRED_component_available"],
        "CBR_component_available": components["progress"]["CBR_component_available"],
        "execution_component_available": execution_ready,
        "causally_joinable_decision_dates": components[
            "causally_joinable_decision_dates"
        ],
        "paper_economics_may_start": paper_ready,
        "cagr_reporting_allowed": annualization,
        "live_trading_allowed": False,
    }
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": parent.CONFIG_SHA256,
        "readiness_version": 2,
        "FRED_transport_admission_protocol_sha256": component_readiness.CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "option_root": str(option_root.resolve()),
        "component_root": str(component_root.resolve()),
        "valid_option_weekly_levels": len(weekly_dates),
        "invalid_V39_option_snapshots": invalid_option,
        "option_source_invalid_snapshot_count": option_report["invalid_snapshot_count"],
        "component_source_invalid_snapshot_count": components["invalid_snapshot_count"],
        "valid_market_execution_dates": components["valid_market_execution_dates"],
        "valid_market_decision_dates": components["valid_market_decision_dates"],
        "valid_macro_FRED_snapshots": components["valid_macro_FRED_snapshots"],
        "valid_macro_FRED_anonymous_v1_snapshots": components[
            "valid_macro_FRED_anonymous_v1_snapshots"
        ],
        "valid_macro_FRED_anonymous_v2_snapshots": components[
            "valid_macro_FRED_anonymous_v2_snapshots"
        ],
        "valid_macro_FRED_authenticated_snapshots": components[
            "valid_macro_FRED_authenticated_snapshots"
        ],
        "valid_macro_CBR_snapshots": components["valid_macro_CBR_snapshots"],
        "contains_signal_return_target_prediction_or_pnl": False,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--component-root", type=Path, default=component_source.DEFAULT_OUTPUT_ROOT
    )
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.component_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
