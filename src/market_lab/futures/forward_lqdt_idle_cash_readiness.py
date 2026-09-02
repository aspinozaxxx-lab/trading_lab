"""Replay-audit paired forward LQDT snapshots and report sealed readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.futures import forward_stock_futures_cash_carry_readiness as paired
from market_lab.futures import moex_forward_lqdt_idle_cash_source as source


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    config = source.load_config()
    root = output_root.resolve()
    snapshots = sorted(path for path in root.glob("snapshot_*") if path.is_dir())
    valid_by_date: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    invalid: list[dict[str, str]] = []
    duplicates: dict[str, list[str]] = defaultdict(list)
    for snapshot in snapshots:
        try:
            manifest = json.loads(
                (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
            )
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            if manifest["status"] != "complete_valid":
                raise ValueError(f"snapshot status is {manifest['status']}")
            source_date = str(manifest["source_date"])
            stage = str(manifest["stage"])
            if stage in valid_by_date[source_date]:
                duplicates[source_date].extend(
                    [valid_by_date[source_date][stage]["snapshot"], snapshot.name]
                )
            valid_by_date[source_date][stage] = {
                "snapshot": snapshot.name,
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
            }
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid.append({"snapshot": snapshot.name, "reason": str(error)})
    valid_pairs: list[dict[str, str]] = []
    ordering_failures: list[str] = []
    for source_date, stages in sorted(valid_by_date.items()):
        if set(stages) != {"decision", "fill"}:
            continue
        decision_at = pd.Timestamp(stages["decision"]["retrieved_at_utc"])
        fill_at = pd.Timestamp(stages["fill"]["retrieved_at_utc"])
        if fill_at <= decision_at:
            ordering_failures.append(source_date)
            continue
        valid_pairs.append(
            {
                "source_date": source_date,
                "decision_snapshot": stages["decision"]["snapshot"],
                "fill_snapshot": stages["fill"]["snapshot"],
            }
        )
    progress = paired.phase_progress(len(valid_pairs), config["readiness"])
    return {
        "protocol_id": config["protocol_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(snapshots),
        "complete_valid_pair_count": len(valid_pairs),
        "invalid_snapshot_count": len(invalid),
        "invalid_snapshots": invalid,
        "duplicate_stage_dates": {key: sorted(set(value)) for key, value in duplicates.items()},
        "fill_not_after_decision_dates": ordering_failures,
        "valid_pairs": valid_pairs,
        "paper_economics_allowed": False,
        "progress": progress,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=source.DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(assess(args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
