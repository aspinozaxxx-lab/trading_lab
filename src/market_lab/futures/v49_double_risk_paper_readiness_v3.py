"""V49 paper readiness with causal official MOEX futures-calendar admission."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_forward_futures_calendar_readiness_v1 as calendar
from market_lab.futures import moex_forward_futures_calendar_source_v1 as calendar_source
from market_lab.futures import moex_forward_option_surface_source as option_source
from market_lab.futures import moex_v27_forward_component_source as component_source
from market_lab.futures import v49_double_risk_paper_readiness_v2 as parent

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/v49_double_risk_paper_calendar_admission_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "6b81c07c9faf43588ed940d639aaeb4d8792385c069e7af826366a802e50bb57"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    parent_config = config["parent_paper_arm"]
    calendar_config = config["calendar_source_admission"]
    contract = config["successor_readiness_contract"]
    frozen = config["frozen_economic_invariants"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "v49_double_risk_paper_calendar_admission_v1"
        or config.get("live_trading_allowed") is not False
        or parent_config["protocol_sha256"] != parent.parent.CONFIG_SHA256
        or parent_config["readiness_v2_sha256"] != _sha(Path(parent.__file__))
        or calendar_config["readiness_sha256"] != _sha(Path(calendar.__file__))
        or calendar_config["require_next_six_trading_sessions_known"] is not True
        or contract["combined_paper_economics_may_start_is_logical_AND"] is not True
        or contract["calendar_can_override_false_base_readiness"] is not False
        or contract["return_target_prediction_order_position_or_pnl_computed"] is not False
        or float(frozen["V49_multiplier"]) != 2.0
        or int(frozen["hard_fallback_sessions"]) != 5
        or frozen["signal_scale_cap_margin_capacity_cost_execution_or_gate_changed"]
        is not False
    ):
        raise ValueError("V49 paper calendar admission protocol drifted")
    if calendar_config["protocol_sha256"] != _sha(
        PROJECT_ROOT / calendar_config["protocol_path"]
    ):
        raise ValueError("V49 paper calendar source admission identity drifted")
    parent.load_config()
    calendar_source.load_config()
    return config


def assess(
    option_root: Path = option_source.DEFAULT_OUTPUT_ROOT,
    component_root: Path = component_source.DEFAULT_OUTPUT_ROOT,
    calendar_root: Path = calendar_source.DEFAULT_OUTPUT_ROOT,
    *,
    as_of_utc: str | datetime | pd.Timestamp | None = None,
) -> dict[str, Any]:
    config = load_config()
    base = parent.assess(option_root, component_root)
    calendar_report = calendar.assess(calendar_root, as_of_utc=as_of_utc)
    base_ready = bool(base["progress"]["paper_economics_may_start"])
    calendar_ready = bool(
        calendar_report["calendar_source_ready_for_five_session_fallback"]
    )
    combined_ready = base_ready and calendar_ready
    annualization = bool(base["progress"]["cagr_reporting_allowed"] and combined_ready)
    progress = {
        **base["progress"],
        "official_calendar_valid_snapshot_count": calendar_report[
            "valid_snapshot_count"
        ],
        "official_calendar_invalid_snapshot_count": calendar_report[
            "invalid_snapshot_count"
        ],
        "official_calendar_latest_causal_retrieved_at_utc": calendar_report[
            "latest_causal_retrieved_at_utc"
        ],
        "official_calendar_next_six_trading_sessions_known": calendar_report[
            "next_six_trading_sessions_known"
        ],
        "official_calendar_ready_for_five_session_fallback": calendar_ready,
        "paper_economics_may_start": combined_ready,
        "cagr_reporting_allowed": annualization,
        "live_trading_allowed": False,
    }
    if base_ready and not calendar_ready:
        progress["current_phase"] = "postseal_official_calendar_wait"
    return {
        **base,
        "readiness_version": 3,
        "calendar_admission_protocol_id": config["protocol_id"],
        "calendar_admission_protocol_sha256": CONFIG_SHA256,
        "calendar_root": str(calendar_root.resolve()),
        "calendar_readiness": calendar_report,
        "progress": progress,
        "contains_signal_return_target_prediction_order_position_or_pnl": False,
        "live_trading_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--option-root", type=Path, default=option_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--component-root", type=Path, default=component_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--calendar-root", type=Path, default=calendar_source.DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--as-of-utc")
    args = parser.parse_args()
    print(
        json.dumps(
            assess(
                args.option_root,
                args.component_root,
                args.calendar_root,
                as_of_utc=args.as_of_utc,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
