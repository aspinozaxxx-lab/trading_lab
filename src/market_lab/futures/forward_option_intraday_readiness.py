"""Audit high-frequency forward option snapshots without computing outcomes."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import forward_option_readiness as parent_readiness
from market_lab.futures import moex_forward_option_surface_source as source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_option_surface_intraday_admission_v1.yaml"
)
CONFIG_SHA256: Final[str] = "b325dc263639ffa97e0c25ac95340b7bae339ca64f0f6b7fd6ba5de441cbed44"


def _sha(path: Path) -> str:
    return source._sha_file(path)


def _timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("intraday option timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("intraday option config must be an object")
    parent = config["parent_source"]
    boundary = config["forward_boundary"]
    schedule = config["schedule"]
    admission = config["session_admission"]
    phases = config["sequential_phases"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_forward_option_surface_intraday_admission_v1"
        or config.get("status") != "sealed_before_first_high_frequency_snapshot_after_boundary"
        or config.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["config_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or int(parent["existing_snapshot_count_at_declaration"]) != 1
        or parent["existing_snapshots_counted_for_intraday_admission"] is not False
        or boundary["historical_or_2026_backfill_counted"] is not False
        or schedule["single_authoritative_host"] != "gpu-mlserver"
        or schedule["local_windows_tasks_enabled"] is not False
        or int(schedule["maximum_expected_gap_minutes"]) != 16
        or int(admission["minimum_valid_snapshots"]) != 30
        or int(admission["minimum_retrieval_span_minutes"]) != 300
        or int(admission["maximum_gap_minutes"]) != 25
        or int(phases["discovery_complete_sessions"]) != 20
        or int(phases["calibration_complete_sessions"]) != 20
        or int(phases["unseen_evaluation_complete_sessions"]) != 60
    ):
        raise ValueError("intraday option admission protocol drifted")
    if _timestamp(boundary["earliest_eligible_retrieved_at_utc"]) != _timestamp(
        config["declared_at_utc"]
    ):
        raise ValueError("intraday option boundary differs from declaration")
    source.load_config()
    return config


def phase_progress(complete_sessions: int, phases: dict[str, Any]) -> dict[str, Any]:
    discovery_required = int(phases["discovery_complete_sessions"])
    calibration_required = int(phases["calibration_complete_sessions"])
    evaluation_required = int(phases["unseen_evaluation_complete_sessions"])
    discovery = min(complete_sessions, discovery_required)
    calibration = min(max(complete_sessions - discovery_required, 0), calibration_required)
    evaluation = min(
        max(complete_sessions - discovery_required - calibration_required, 0),
        evaluation_required,
    )
    if discovery < discovery_required:
        phase = "discovery"
    elif calibration < calibration_required:
        phase = "calibration"
    elif evaluation < evaluation_required:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    return {
        "current_phase": phase,
        "discovery": {"complete": discovery, "required": discovery_required},
        "calibration": {"complete": calibration, "required": calibration_required},
        "unseen_evaluation": {"complete": evaluation, "required": evaluation_required},
        "economic_protocol_may_be_sealed": discovery == discovery_required,
        "calibration_complete": calibration == calibration_required,
        "unseen_evaluation_complete": evaluation == evaluation_required,
        "live_trading_allowed": False,
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = load_config()
    boundary = _timestamp(config["forward_boundary"]["earliest_eligible_retrieved_at_utc"])
    report = parent_readiness.assess(output_root)
    eligible: list[dict[str, Any]] = []
    excluded_preboundary = 0
    for item in report["valid_snapshots"]:
        retrieved = _timestamp(item["retrieved_at_utc"])
        if retrieved < boundary:
            excluded_preboundary += 1
            continue
        eligible.append({**item, "retrieved": retrieved})
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        by_session[str(item["source_date"])].append(item)
    admission = config["session_admission"]
    session_rows: list[dict[str, Any]] = []
    for source_date, items in sorted(by_session.items()):
        times = sorted({item["retrieved"] for item in items})
        gaps = [
            (later - earlier).total_seconds() / 60.0
            for earlier, later in zip(times, times[1:], strict=False)
        ]
        span = (times[-1] - times[0]).total_seconds() / 60.0 if len(times) > 1 else 0.0
        complete = bool(
            len(times) >= int(admission["minimum_valid_snapshots"])
            and span >= float(admission["minimum_retrieval_span_minutes"])
            and (not gaps or max(gaps) <= float(admission["maximum_gap_minutes"]))
        )
        session_rows.append(
            {
                "source_date": source_date,
                "valid_snapshot_count": len(times),
                "first_retrieved_at_utc": times[0].isoformat(),
                "last_retrieved_at_utc": times[-1].isoformat(),
                "retrieval_span_minutes": span,
                "maximum_gap_minutes": max(gaps) if gaps else None,
                "complete": complete,
            }
        )
    complete_count = sum(bool(item["complete"]) for item in session_rows)
    progress = phase_progress(complete_count, config["sequential_phases"])
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "eligibility_boundary_utc": boundary.isoformat(),
        "output_root": str(output_root.resolve()),
        "eligible_valid_snapshot_count": len(eligible),
        "excluded_preboundary_valid_snapshot_count": excluded_preboundary,
        "parent_invalid_snapshot_count": report["invalid_snapshot_count"],
        "eligible_source_session_count": len(session_rows),
        "complete_session_count": complete_count,
        "sessions": session_rows,
        "progress": progress,
        "contains_signal_return_target_prediction_trade_position_equity_or_pnl": False,
        "live_trading_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
