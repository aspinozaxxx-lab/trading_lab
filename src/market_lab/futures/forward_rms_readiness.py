"""Replay-audit forward MOEX RMS snapshots and report sequential readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_rms_source_v2 as source


def phase_progress(unique_dates: int, config: dict[str, Any]) -> dict[str, Any]:
    rules = config["sequential_research"]
    discovery_required = int(rules["discovery_unique_source_dates"])
    calibration_required = int(rules["calibration_unique_source_dates"])
    evaluation_required = int(rules["unseen_evaluation_unique_source_dates"])
    discovery = min(unique_dates, discovery_required)
    calibration = min(max(unique_dates - discovery_required, 0), calibration_required)
    evaluation = min(
        max(unique_dates - discovery_required - calibration_required, 0),
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
        "economic_protocol_may_be_designed": discovery == discovery_required,
        "evaluation_complete": evaluation == evaluation_required,
        "live_trading_allowed": False,
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = source.load_config()
    root = output_root.resolve()
    valid_by_date: dict[str, list[str]] = defaultdict(list)
    invalid: list[dict[str, str]] = []
    for snapshot in sorted(path for path in root.glob("snapshot_*") if path.is_dir()):
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            valid_by_date[str(manifest["risk_source_date"])].append(snapshot.name)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    duplicate = {
        date: names for date, names in sorted(valid_by_date.items()) if len(names) > 1
    }
    dates = sorted(valid_by_date)
    return {
        "protocol_id": config["protocol_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "valid_unique_risk_source_date_count": len(dates),
        "first_valid_risk_source_date": dates[0] if dates else None,
        "last_valid_risk_source_date": dates[-1] if dates else None,
        "invalid_snapshots": invalid,
        "duplicate_valid_risk_source_dates": duplicate,
        "contains_price_return_target_prediction_or_pnl": False,
        "progress": phase_progress(len(dates), config),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
