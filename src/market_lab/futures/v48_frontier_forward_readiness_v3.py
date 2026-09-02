"""Current V48 readiness with componentized data and dual official FRED routes."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import moex_v27_forward_fred_api_component_source as fred_api
from market_lab.futures import v27_forward_component_readiness_v2 as component_readiness
from market_lab.futures import v39_forward_validation_readiness as v39_readiness
from market_lab.futures import v48_frontier_forward_readiness as v48_v1
from market_lab.futures import v48_frontier_forward_readiness_v2 as v48_v2


def load_config() -> dict[str, Any]:
    config = component_readiness.load_config()
    v48_v2.load_config()
    if (
        config["parent_component_correction"]["protocol_sha256"] != v48_v2.CONFIG_SHA256
        or config["authenticated_FRED_component"]["protocol_sha256"]
        != fred_api.CONFIG_SHA256
        or config["live_trading_allowed"] is not False
    ):
        raise ValueError("V48 dual-FRED forward readiness drifted")
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    v39_config = v39_readiness.load_config()
    weekly_dates, invalid_option, option_report = v48_v2._option_weekly_dates(option_root)
    components = component_readiness.assess(component_root)
    decision_dates = sorted(
        {
            date.fromisoformat(str(item["source_dates"][0]))
            for item in components["valid_snapshots"]
            if item["component"] == "market_decision" and len(item["source_dates"]) == 1
        }
    )
    progress = v39_readiness.joint_progress(weekly_dates, decision_dates, v39_config)
    macro_ready = bool(components["progress"]["macro_state_ready"])
    execution_ready = components["valid_market_execution_dates"] > 0
    paper_ready = bool(progress["joint_warmup_complete"] and macro_ready and execution_ready)
    annualization = bool(progress["evaluation_complete"] and macro_ready and execution_ready)
    if not progress["joint_warmup_complete"]:
        phase = "joint_warmup"
    elif not macro_ready:
        phase = "macro_wait"
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
    fixed = v48_v1.load_config()["fixed_mode"]
    key_configured = bool(
        fred_api.API_KEY_PATTERN.fullmatch(os.environ.get("FRED_API_KEY", ""))
    )
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": component_readiness.CONFIG_SHA256,
        "parent_component_protocol_sha256": v48_v2.CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "option_root": str(option_root.resolve()),
        "component_root": str(component_root.resolve()),
        "fixed_mode": {
            "name": fixed["name"],
            "V39_mapped_target_multiplier": float(fixed["V39_mapped_target_multiplier"]),
            "maximum_gross_notional_multiple": float(
                fixed["maximum_gross_notional_multiple"]
            ),
            "initial_margin_buffer_multiplier": float(
                fixed["initial_margin_buffer_multiplier"]
            ),
            "maximum_prior_official_volume_participation": float(
                fixed["maximum_prior_official_volume_participation"]
            ),
        },
        "FRED_API_KEY_configured": key_configured,
        "FRED_route_if_collected_now": (
            "authenticated_official_API" if key_configured else "anonymous_fredgraph"
        ),
        "valid_option_weekly_levels": len(weekly_dates),
        "invalid_V39_option_snapshots": invalid_option,
        "option_source_invalid_snapshot_count": option_report["invalid_snapshot_count"],
        "component_source_invalid_snapshot_count": components["invalid_snapshot_count"],
        "valid_market_execution_dates": components["valid_market_execution_dates"],
        "valid_market_decision_dates": components["valid_market_decision_dates"],
        "valid_macro_FRED_snapshots": components["valid_macro_FRED_snapshots"],
        "valid_macro_FRED_anonymous_snapshots": components[
            "valid_macro_FRED_anonymous_snapshots"
        ],
        "valid_macro_FRED_authenticated_snapshots": components[
            "valid_macro_FRED_authenticated_snapshots"
        ],
        "valid_macro_CBR_snapshots": components["valid_macro_CBR_snapshots"],
        "progress": progress,
        "contains_signal_return_target_prediction_or_pnl": False,
        "live_trading_allowed": False,
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
