"""Replay-audit V27 forward snapshots and report warmup/evaluation readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import moex_v27_forward_validation_source as source


def phase_progress(decision_dates: int, execution_dates: int, config: dict[str, Any]) -> dict:
    rules = config["sequential_validation"]
    warmup_required = int(rules["warmup_common_sessions"])
    evaluation_required = int(rules["evaluation_common_sessions_minimum"])
    warmup = min(decision_dates, warmup_required)
    evaluation = min(max(decision_dates - warmup_required, 0), evaluation_required)
    if warmup < warmup_required:
        phase = "signal_warmup"
    elif evaluation < evaluation_required:
        phase = "unseen_evaluation"
    else:
        phase = "independent_review"
    return {
        "current_phase": phase,
        "warmup": {"complete": warmup, "required": warmup_required},
        "unseen_evaluation": {"complete": evaluation, "required": evaluation_required},
        "execution_observation_unique_dates": execution_dates,
        "remaining_to_first_paper_decision": max(warmup_required - decision_dates, 0),
        "remaining_to_evaluation_complete": max(
            warmup_required + evaluation_required - decision_dates, 0
        ),
        "paper_economics_may_start": warmup == warmup_required,
        "evaluation_complete": evaluation == evaluation_required,
        "second_unseen_confirmation_still_required": True,
        "live_trading_allowed": False,
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = source.load_config()
    root = output_root.resolve()
    snapshots = sorted(path for path in root.glob("snapshot_*") if path.is_dir())
    valid_by_kind_date: dict[tuple[str, str], list[str]] = defaultdict(list)
    valid_snapshots: list[dict[str, Any]] = []
    invalid_snapshots: list[dict[str, str]] = []
    for snapshot in snapshots:
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            kind = str(manifest["snapshot_kind"])
            dates = manifest["counts"]["source_dates"]
            if kind not in source.SNAPSHOT_KINDS:
                raise ValueError("unknown snapshot kind")
            if not isinstance(dates, list) or len(dates) != 1:
                raise ValueError("manifest must contain exactly one source date")
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            source_date = str(dates[0])
            item = {
                "snapshot_kind": kind,
                "source_date": source_date,
                "snapshot": snapshot.name,
                "market_rows": int(manifest["counts"]["market_rows"]),
                "macro_rows": int(manifest["counts"]["macro_rows"]),
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
            }
            valid_snapshots.append(item)
            valid_by_kind_date[(kind, source_date)].append(snapshot.name)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid_snapshots.append({"snapshot": snapshot.name, "reason": str(error)})
    decision_dates = sorted(
        date for kind, date in valid_by_kind_date if kind == "decision_eod"
    )
    execution_dates = sorted(
        date for kind, date in valid_by_kind_date if kind == "execution_observation"
    )
    duplicate = {
        f"{kind}:{date}": names
        for (kind, date), names in sorted(valid_by_kind_date.items())
        if len(names) > 1
    }
    decision_set, execution_set = set(decision_dates), set(execution_dates)
    paired = sorted(decision_set & execution_set)
    return {
        "protocol_id": config["protocol_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(snapshots),
        "valid_snapshot_count": len(valid_snapshots),
        "invalid_snapshot_count": len(invalid_snapshots),
        "valid_unique_decision_date_count": len(decision_dates),
        "valid_unique_execution_date_count": len(execution_dates),
        "paired_same_date_count": len(paired),
        "first_valid_decision_date": decision_dates[0] if decision_dates else None,
        "last_valid_decision_date": decision_dates[-1] if decision_dates else None,
        "duplicate_valid_kind_dates": duplicate,
        "invalid_snapshots": invalid_snapshots,
        "valid_snapshots": valid_snapshots,
        "progress": phase_progress(len(decision_dates), len(execution_dates), config),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
