"""Audit timestamped V2 intraday option snapshots without computing outcomes."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import forward_option_intraday_readiness as shared
from market_lab.futures import moex_forward_option_surface_source_v2 as source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_option_surface_intraday_admission_v2.yaml"
)
CONFIG_SHA256: Final[str] = "fb598938c62364be33e352ed6bdc2c68f7bf6b44020a1c77d42c03211b6d12ce"


def _sha(path: Path) -> str:
    return source._sha_file(path)


def _timestamp(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError("intraday option V2 timestamp must be timezone-aware")
    return result.tz_convert("UTC")


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("intraday option V2 config must be an object")
    parent = config["parent_source"]
    boundary = config["forward_boundary"]
    schedule = config["schedule"]
    admission = config["session_admission"]
    phases = config["sequential_phases"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_forward_option_surface_intraday_admission_v2"
        or config.get("status") != "sealed_before_first_timestamped_v2_snapshot_after_boundary"
        or config.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config_path"]) != parent["config_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation_path"]) != parent["implementation_sha256"]
        or int(parent["existing_v2_snapshot_count_at_declaration"]) != 0
        or int(parent["v1_complete_sessions_at_declaration"]) != 0
        or parent["v1_snapshots_counted_for_v2"] is not False
        or boundary["historical_or_v1_or_preboundary_backfill_counted"] is not False
        or schedule["single_authoritative_host"] != "gpu-mlserver"
        or schedule["local_windows_tasks_enabled"] is not False
        or int(schedule["maximum_expected_gap_minutes"]) != 16
        or int(admission["minimum_valid_snapshots"]) != 30
        or int(admission["minimum_retrieval_span_minutes"]) != 300
        or int(admission["maximum_gap_minutes"]) != 25
        or admission["required_v2_observations_complete"] is not True
        or int(phases["discovery_complete_sessions"]) != 20
        or int(phases["calibration_complete_sessions"]) != 20
        or int(phases["unseen_evaluation_complete_sessions"]) != 60
    ):
        raise ValueError("intraday option V2 admission protocol drifted")
    if _timestamp(boundary["earliest_eligible_retrieved_at_utc"]) != _timestamp(
        source.load_config()["temporal_semantics"]["earliest_eligible_retrieved_at_utc"]
    ):
        raise ValueError("intraday option V2 source and admission boundaries differ")
    return config


def _source_report(output_root: Path) -> dict[str, Any]:
    root = output_root.resolve()
    snapshots = sorted(path for path in root.glob("snapshot_*") if path.is_dir())
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    for snapshot in snapshots:
        try:
            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
            dates = manifest["counts"]["source_dates"]
            if not isinstance(dates, list) or len(dates) != 1:
                raise ValueError("manifest must contain exactly one source date")
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            valid.append(
                {
                    "source_date": str(dates[0]),
                    "snapshot": snapshot.name,
                    "rows": int(manifest["counts"]["rows"]),
                    "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
                }
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    return {"valid_snapshots": valid, "invalid_snapshots": invalid}


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = load_config()
    boundary = _timestamp(config["forward_boundary"]["earliest_eligible_retrieved_at_utc"])
    source_report = _source_report(output_root)
    eligible: list[dict[str, Any]] = []
    excluded_preboundary = 0
    for item in source_report["valid_snapshots"]:
        retrieved = _timestamp(item["retrieved_at_utc"])
        if retrieved < boundary:
            excluded_preboundary += 1
            continue
        eligible.append({**item, "retrieved": retrieved})
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        by_session[str(item["source_date"])].append(item)
    admission = config["session_admission"]
    sessions: list[dict[str, Any]] = []
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
        sessions.append(
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
    complete_count = sum(bool(item["complete"]) for item in sessions)
    progress = shared.phase_progress(complete_count, config["sequential_phases"])
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "eligibility_boundary_utc": boundary.isoformat(),
        "output_root": str(output_root.resolve()),
        "eligible_valid_snapshot_count": len(eligible),
        "excluded_preboundary_valid_snapshot_count": excluded_preboundary,
        "parent_invalid_snapshot_count": len(source_report["invalid_snapshots"]),
        "invalid_snapshots": source_report["invalid_snapshots"],
        "eligible_source_session_count": len(sessions),
        "complete_session_count": complete_count,
        "sessions": sessions,
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
