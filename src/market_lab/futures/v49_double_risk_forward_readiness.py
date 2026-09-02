"""Source-only readiness for the post-seal V49 double-risk paper arm."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab import futures_v49_v39_double_risk_exact_execution as v49
from market_lab.futures import forward_option_readiness as option_readiness
from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v27_forward_component_readiness_v2 as component_readiness
from market_lab.futures import v39_forward_validation_readiness as v39_readiness
from market_lab.futures import v48_frontier_forward_readiness_v3 as v48_readiness

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v49_double_risk_forward_validation_v1.yaml"
CONFIG_SHA256: Final[str] = "520bd3d4bc5d920d3c624b4e9ca95f28dd87320f84a5e04cd9c7872e2f36cd64"
ASSETS: Final[set[str]] = {"SI", "RI", "BR", "MIX"}


def _sha(path: Path) -> str:
    return component_source._sha(path)


def _timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("V49 forward timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("V49 forward config must be an object")
    historical = config["historical_identity"]
    parent = config["forward_source_parent"]
    arm = config["fixed_arm"]
    boundary = config["forward_boundary"]
    state = config["current_state_at_seal"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "v49_double_risk_forward_validation_v1"
        or config.get("status")
        != "sealed_before_any_V49_forward_decision_target_order_position_or_PnL"
        or config.get("live_trading_allowed") is not False
        or historical["protocol_sha256"] != v49.CONFIG_SHA256
        or historical["implementation_sha256"]
        != _sha(PROJECT_ROOT / historical["implementation_path"])
        or historical["manifest_sha256"]
        != _sha(PROJECT_ROOT / historical["canonical_run"] / "manifest.json")
        or historical["metrics_sha256"]
        != _sha(PROJECT_ROOT / historical["canonical_run"] / "metrics.json")
        or historical["audit_sha256"]
        != _sha(PROJECT_ROOT / historical["canonical_run"] / "audit.json")
        or historical["development_verdict"] != "NO_GO"
        or parent["current_V48_readiness_sha256"]
        != _sha(PROJECT_ROOT / parent["current_V48_readiness_path"])
        or parent["admission_protocol_sha256"]
        != _sha(PROJECT_ROOT / parent["admission_protocol_path"])
        or parent["V39_readiness_sha256"] != _sha(PROJECT_ROOT / parent["V39_readiness_path"])
        or arm["name"] != "double_risk"
        or float(arm["V39_mapped_target_multiplier"]) != 2.0
        or float(arm["maximum_gross_notional_multiple"]) != 4.0
        or float(arm["initial_margin_buffer_multiplier"]) != 2.0
        or float(arm["maximum_prior_official_volume_participation"]) != 0.01
        or float(arm["broad_carry_cash_fraction"]) != 0.0
        or arm["comparison_or_selection_against_V48_after_forward_outcome"] != "forbidden"
        or boundary["preseal_option_market_macro_or_execution_snapshot_counted"] is not False
        or boundary["historical_2026_backfill_counted"] is not False
        or state["V49_eligible_counts_reset_to_zero"] is not True
        or state["V49_forward_decision_target_order_position_or_PnL_computed"] is not False
    ):
        raise ValueError("V49 double-risk forward protocol drifted")
    if _timestamp(boundary["earliest_eligible_retrieved_at_utc"]) != _timestamp(
        config["declared_at_utc"]
    ):
        raise ValueError("V49 forward eligibility boundary differs from seal")
    v48_readiness.load_config()
    return config


def _postseal_option_weeks(
    root: Path, boundary: pd.Timestamp
) -> tuple[list[date], list[dict[str, str]], dict[str, Any], int]:
    report = option_readiness.assess(root)
    dates: list[date] = []
    invalid: list[dict[str, str]] = []
    excluded_preseal = 0
    for item in report["valid_snapshots"]:
        snapshot = root.resolve() / item["snapshot"]
        try:
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
            if _timestamp(manifest["retrieved_at_utc"]) < boundary:
                excluded_preseal += 1
                continue
            frame = pd.read_parquet(
                snapshot / manifest["processed"]["path"],
                columns=["source_date", "asset_code", "option_type", "open_interest"],
            )
            frame["open_interest"] = pd.to_numeric(frame["open_interest"], errors="coerce")
            source_dates = pd.to_datetime(frame["source_date"], errors="raise").dt.date.unique()
            if len(source_dates) != 1 or source_dates[0].isoformat() != item["source_date"]:
                raise ValueError("processed option source date mismatch")
            if set(frame["asset_code"]) != ASSETS:
                raise ValueError("four-asset option universe incomplete")
            totals = frame.groupby(["asset_code", "option_type"])["open_interest"].sum(min_count=1)
            for asset in ASSETS:
                if (
                    float(totals.get((asset, "C"), 0.0)) <= 0.0
                    or float(totals.get((asset, "P"), 0.0)) <= 0.0
                ):
                    raise ValueError(f"nonpositive call/put OI for {asset}")
            dates.append(source_dates[0])
        except (KeyError, OSError, TypeError, ValueError) as error:
            invalid.append({"snapshot": item["snapshot"], "reason": str(error)})
    weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
    for value in sorted(set(dates)):
        iso = value.isocalendar()
        weeks[(iso.year, iso.week)].append(value)
    return sorted(max(values) for values in weeks.values()), invalid, report, excluded_preseal


def _postseal_components(
    report: dict[str, Any], boundary: pd.Timestamp
) -> tuple[list[dict[str, Any]], int]:
    duplicate_market = set(report["duplicate_market_component_dates"])
    eligible: list[dict[str, Any]] = []
    excluded_preseal = 0
    for item in report["valid_snapshots"]:
        if _timestamp(item["retrieved_at_utc"]) < boundary:
            excluded_preseal += 1
            continue
        label = (
            f"{item['component']}:{item['source_dates'][0]}"
            if item["component"].startswith("market_") and len(item["source_dates"]) == 1
            else None
        )
        if label in duplicate_market:
            continue
        eligible.append(item)
    return eligible, excluded_preseal


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    boundary = _timestamp(config["forward_boundary"]["earliest_eligible_retrieved_at_utc"])
    option_dates, option_invalid, option_report, preseal_options = _postseal_option_weeks(
        option_root, boundary
    )
    component_report = component_readiness.assess(component_root)
    components, preseal_components = _postseal_components(component_report, boundary)
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
