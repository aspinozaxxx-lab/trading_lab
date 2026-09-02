"""Report source-only readiness for sealed forward cross-market BBO snapshots."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Final

import pandas as pd

from market_lab.futures import moex_forward_cross_market_bbo_source as source

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


def _root(config: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    return source._safe_output_root(str(config["output"]["root"])).resolve()


def readiness(root: Path | None = None) -> dict[str, Any]:
    config = source.load_config()
    source_root = _root(config, root)
    snapshots = sorted(source_root.glob("snapshot_*")) if source_root.exists() else []
    valid_manifests: list[dict[str, Any]] = []
    invalid: list[dict[str, str]] = []
    status_counts: Counter[str] = Counter()
    for snapshot in snapshots:
        try:
            checks = source.audit(snapshot)
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            audit_valid = all(checks.values())
            status = str(manifest.get("status", "missing"))
            status_counts[status] += 1
            if audit_valid:
                valid_manifests.append(manifest)
            else:
                invalid.append({"snapshot": snapshot.name, "reason": "audit_false"})
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": type(error).__name__})
    complete = [
        manifest
        for manifest in valid_manifests
        if manifest.get("status") == "complete_core_valid"
    ]
    per_session = Counter(str(manifest["source_date"]) for manifest in complete)
    minimum = int(config["readiness"]["minimum_complete_core_snapshots_per_session"])
    complete_sessions = sorted(
        source_date for source_date, count in per_session.items() if count >= minimum
    )
    discovery_required = int(config["readiness"]["discovery_sessions_source_only"])
    calibration_required = int(
        config["readiness"]["calibration_sessions_after_separate_economic_seal"]
    )
    evaluation_required = int(
        config["readiness"]["unseen_evaluation_sessions_after_calibration"]
    )
    discovery_complete = len(complete_sessions) >= discovery_required
    return {
        "protocol_id": config["protocol_id"],
        "protocol_sha256": source.CONFIG_SHA256,
        "source_root": str(source_root),
        "source_only": True,
        "market_outcomes_or_pnl_computed": False,
        "live_trading_allowed": False,
        "counts": {
            "snapshot_directories": len(snapshots),
            "audited_snapshots": len(valid_manifests),
            "complete_core_snapshots": len(complete),
            "invalid_or_unreadable_snapshots": len(invalid),
            "complete_sessions": len(complete_sessions),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "complete_snapshots_by_session": dict(sorted(per_session.items())),
        "complete_session_dates": complete_sessions,
        "first_complete_slot": min(
            (str(item["scheduled_slot_moscow"]) for item in complete), default=None
        ),
        "latest_complete_slot": max(
            (str(item["scheduled_slot_moscow"]) for item in complete), default=None
        ),
        "invalid": invalid,
        "gates": {
            "minimum_complete_snapshots_per_session": minimum,
            "discovery_sessions": {
                "complete": len(complete_sessions),
                "required": discovery_required,
                "ready": discovery_complete,
            },
            "separate_economic_protocol_sealed": False,
            "calibration_sessions": {
                "complete": 0,
                "required": calibration_required,
                "ready": False,
            },
            "unseen_evaluation_sessions": {
                "complete": 0,
                "required": evaluation_required,
                "ready": False,
            },
            "annualization_allowed": False,
            "live_allowed": False,
        },
        "next_action": (
            "seal_separate_economic_protocol_without_using_discovery_outcomes"
            if discovery_complete
            else "continue_immutable_ten_minute_source_collection"
        ),
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    payload = readiness(args.source_root)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output_json is None:
        print(text, end="")
    else:
        args.output_json.write_text(text, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
