"""Source-only readiness for the independently sealed V49 paper arm."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v27_forward_component_readiness_v2 as component_readiness
from market_lab.futures import v39_forward_validation_readiness as v39_readiness
from market_lab.futures import v49_double_risk_forward_readiness as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v49_double_risk_paper_arm_v1.yaml"
CONFIG_SHA256: Final[str] = "56822e1ea112bf795cebdda598539f737ee77c55a8e91d37b30e9684453520b3"


def _sha(path: Path) -> str:
    return component_source._sha(path)


def _timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("V49 paper timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("V49 paper config must be an object")
    parent_config = config["parent_forward_protocol"]
    arm = config["fixed_arm"]
    boundary = config["paper_boundary"]
    counts = boundary["eligible_counts_at_seal"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "v49_double_risk_paper_arm_v1"
        or config.get("status")
        != "sealed_before_first_eligible_V49_paper_decision_target_order_position_or_PnL"
        or config.get("live_trading_allowed") is not False
        or parent_config["sha256"] != parent.CONFIG_SHA256
        or parent_config["readiness_sha256"] != _sha(PROJECT_ROOT / parent_config["readiness_path"])
        or arm["name"] != "double_risk"
        or float(arm["V39_mapped_target_multiplier"]) != 2.0
        or float(arm["maximum_gross_notional_multiple"]) != 4.0
        or float(arm["initial_margin_buffer_multiplier"]) != 2.0
        or float(arm["maximum_prior_official_volume_participation"]) != 0.01
        or float(arm["broad_carry_cash_fraction"]) != 0.0
        or arm["V39_signs_zeros_windows_and_quantiles_unchanged"] is not True
        or arm["comparison_or_selection_against_V48_after_forward_outcome"] != "forbidden"
        or boundary["observations_retrieved_before_this_seal_counted"] is not False
        or boundary["historical_2026_backfill_counted"] is not False
        or any(int(value) != 0 for value in counts.values())
    ):
        raise ValueError("V49 double-risk paper protocol drifted")
    if _timestamp(boundary["earliest_eligible_retrieved_at_utc"]) != _timestamp(
        config["declared_at_utc"]
    ):
        raise ValueError("V49 paper eligibility boundary differs from seal")
    parent.load_config()
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    boundary = _timestamp(config["paper_boundary"]["earliest_eligible_retrieved_at_utc"])
    option_dates, option_invalid, option_report, preseal_options = parent._postseal_option_weeks(
        option_root, boundary
    )
    component_report = component_readiness.assess(component_root)
    components, preseal_components = parent._postseal_components(component_report, boundary)
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
    fred_times = [_timestamp(item["retrieved_at_utc"]) for item in fred]
    cbr_times = [_timestamp(item["retrieved_at_utc"]) for item in cbr]
    decision_items = [item for item in components if item["component"] == "market_decision"]
    joinable = [
        str(item["source_dates"][0])
        for item in decision_items
        if any(value <= _timestamp(item["retrieved_at_utc"]) for value in fred_times)
        and any(value <= _timestamp(item["retrieved_at_utc"]) for value in cbr_times)
    ]
    progress = v39_readiness.joint_progress(option_dates, decisions, v39_readiness.load_config())
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
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "eligibility_boundary_utc": boundary.isoformat(),
        "option_root": str(option_root.resolve()),
        "component_root": str(component_root.resolve()),
        "fixed_arm": {
            "name": arm["name"],
            "V39_mapped_target_multiplier": float(arm["V39_mapped_target_multiplier"]),
            "maximum_gross_notional_multiple": float(arm["maximum_gross_notional_multiple"]),
            "initial_margin_buffer_multiplier": float(arm["initial_margin_buffer_multiplier"]),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--component-root", type=Path, default=component_source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.option_root, args.component_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
