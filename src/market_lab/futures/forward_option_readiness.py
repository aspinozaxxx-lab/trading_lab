"""Audit accumulated forward option snapshots and report protocol readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_forward_option_surface_source as source


def phase_progress(unique_date_count: int, minimums: dict[str, Any]) -> dict[str, Any]:
    """Translate valid unique source dates into the sealed 60/20/40 protocol phases."""
    discovery_required = int(minimums["discovery_snapshots"])
    calibration_required = int(minimums["calibration_snapshots"])
    evaluation_required = int(minimums["unseen_evaluation_snapshots"])
    discovery = min(unique_date_count, discovery_required)
    calibration = min(max(unique_date_count - discovery_required, 0), calibration_required)
    evaluation = min(
        max(unique_date_count - discovery_required - calibration_required, 0),
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
        "remaining_to_economic_protocol_seal": max(discovery_required - unique_date_count, 0),
        "remaining_to_calibration_complete": max(
            discovery_required + calibration_required - unique_date_count, 0
        ),
        "remaining_to_unseen_evaluation_complete": max(
            discovery_required
            + calibration_required
            + evaluation_required
            - unique_date_count,
            0,
        ),
        "economic_protocol_may_be_sealed": discovery == discovery_required,
        "calibration_complete": calibration == calibration_required,
        "unseen_evaluation_complete": evaluation == evaluation_required,
        "live_trading_allowed": False,
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    """Replay-audit every snapshot and count only valid unique trading dates."""
    config = source.load_config()
    root = output_root.resolve()
    snapshots = sorted(path for path in root.glob("snapshot_*") if path.is_dir())
    valid_by_date: dict[str, list[str]] = defaultdict(list)
    valid_snapshots: list[dict[str, Any]] = []
    invalid_snapshots: list[dict[str, str]] = []

    for snapshot in snapshots:
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            dates = manifest["counts"]["source_dates"]
            if not isinstance(dates, list) or len(dates) != 1:
                raise ValueError("manifest must contain exactly one source date")
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            source_date = str(dates[0])
            item = {
                "source_date": source_date,
                "snapshot": snapshot.name,
                "rows": int(manifest["counts"]["rows"]),
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
            }
            valid_snapshots.append(item)
            valid_by_date[source_date].append(snapshot.name)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid_snapshots.append({"snapshot": snapshot.name, "reason": str(error)})

    unique_dates = sorted(valid_by_date)
    duplicates = {
        date: names for date, names in sorted(valid_by_date.items()) if len(names) > 1
    }
    progress = phase_progress(
        len(unique_dates), config["future_economic_protocol_minimums"]
    )
    return {
        "protocol_id": config["protocol_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(snapshots),
        "valid_snapshot_count": len(valid_snapshots),
        "invalid_snapshot_count": len(invalid_snapshots),
        "valid_unique_source_date_count": len(unique_dates),
        "first_valid_source_date": unique_dates[0] if unique_dates else None,
        "last_valid_source_date": unique_dates[-1] if unique_dates else None,
        "duplicate_valid_source_dates": duplicates,
        "invalid_snapshots": invalid_snapshots,
        "valid_snapshots": valid_snapshots,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
