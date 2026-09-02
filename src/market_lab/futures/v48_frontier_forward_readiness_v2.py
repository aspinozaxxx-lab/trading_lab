"""V48 frontier readiness over independent V27 market/FRED/CBR components."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import forward_option_readiness as option_readiness
from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v27_forward_component_readiness as component_readiness
from market_lab.futures import v39_forward_validation_readiness as v39_readiness
from market_lab.futures import v48_frontier_forward_readiness as v48_v1

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/v48_frontier_forward_component_correction_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "019f970e53b4ab3227824fba417222efa6847476b7882fb2012ab57a99e1e1c2"
)


def _sha(path: Path) -> str:
    return component_source._sha(path)


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent = config["parent_forward"]
    component = config["component_source"]
    option = config["option_source"]
    correction = config["source_correction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id")
        != "v48_frontier_forward_component_correction_v1"
        or config.get("live_trading_allowed") is not False
        or parent["protocol_sha256"] != v48_v1.CONFIG_SHA256
        or component["protocol_sha256"] != component_source.CONFIG_SHA256
        or component["implementation_sha256"]
        != _sha(PROJECT_ROOT / component["implementation_path"])
        or component["readiness_sha256"]
        != _sha(PROJECT_ROOT / component["readiness_path"])
        or option["protocol_sha256"] != option_source.CONFIG_SHA256
        or correction["economic_hypothesis_changed"] is not False
        or correction["V48_mode_or_parameter_changed"] is not False
        or correction["V39_signal_or_option_state_changed"] is not False
        or correction["endpoint_query_normalization_or_schema_changed"] is not False
        or correction["execution_mark_or_cost_changed"] is not False
        or correction["forward_outcomes_inspected_before_seal"] is not False
    ):
        raise ValueError("V48 component forward correction drifted")
    v48_v1.load_config()
    component_source.load_config()
    return config


def _option_weekly_dates(option_root: Path) -> tuple[list[date], list[dict[str, str]], dict]:
    report = option_readiness.assess(option_root)
    valid_dates: dict[str, list[str]] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    for item in report["valid_snapshots"]:
        snapshot = option_root.resolve() / item["snapshot"]
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            frame = pd.read_parquet(
                snapshot / manifest["processed"]["path"],
                columns=["source_date", "asset_code", "option_type", "open_interest"],
            )
            frame["open_interest"] = pd.to_numeric(frame["open_interest"], errors="coerce")
            dates = pd.to_datetime(frame["source_date"], errors="raise").dt.date.unique()
            if len(dates) != 1 or dates[0].isoformat() != item["source_date"]:
                raise ValueError("processed option source date mismatch")
            if set(frame["asset_code"]) != {"SI", "RI", "BR", "MIX"}:
                raise ValueError("four-asset option universe incomplete")
            totals = frame.groupby(["asset_code", "option_type"])["open_interest"].sum(
                min_count=1
            )
            for asset in ("SI", "RI", "BR", "MIX"):
                if (
                    float(totals.get((asset, "C"), 0.0)) <= 0.0
                    or float(totals.get((asset, "P"), 0.0)) <= 0.0
                ):
                    raise ValueError(f"nonpositive call/put OI for {asset}")
            valid_dates[item["source_date"]].append(item["snapshot"])
        except (KeyError, OSError, TypeError, ValueError) as error:
            invalid.append({"snapshot": item["snapshot"], "reason": str(error)})
    weeks: dict[tuple[int, int], list[date]] = defaultdict(list)
    for value in sorted(date.fromisoformat(item) for item in valid_dates):
        iso = value.isocalendar()
        weeks[(iso.year, iso.week)].append(value)
    return sorted(max(values) for values in weeks.values()), invalid, report


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    config = load_config()
    parent_config = v39_readiness.load_config()
    weekly_dates, invalid_option, option_report = _option_weekly_dates(option_root)
    components = component_readiness.assess(component_root)
    decision_dates = sorted(
        {
            date.fromisoformat(str(item["source_dates"][0]))
            for item in components["valid_snapshots"]
            if item["component"] == "market_decision" and len(item["source_dates"]) == 1
        }
    )
    progress = v39_readiness.joint_progress(weekly_dates, decision_dates, parent_config)
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
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "parent_V48_protocol_sha256": v48_v1.CONFIG_SHA256,
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
        "valid_option_weekly_levels": len(weekly_dates),
        "invalid_V39_option_snapshots": invalid_option,
        "option_source_invalid_snapshot_count": option_report["invalid_snapshot_count"],
        "component_source_invalid_snapshot_count": components["invalid_snapshot_count"],
        "valid_market_execution_dates": components["valid_market_execution_dates"],
        "valid_market_decision_dates": components["valid_market_decision_dates"],
        "valid_macro_FRED_snapshots": components["valid_macro_FRED_snapshots"],
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

