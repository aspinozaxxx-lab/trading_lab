"""Audit forward CNY relative-value snapshots and report sealed phase readiness."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from market_lab.futures import forward_option_readiness as phases
from market_lab.futures import moex_forward_cny_relative_value_source as source


def minimums(config: dict[str, Any]) -> dict[str, int]:
    sealed = config["future_economic_protocol_minimums"]
    return {
        "discovery_snapshots": int(sealed["discovery_unique_quote_dates"]),
        "calibration_snapshots": int(sealed["calibration_unique_quote_dates"]),
        "unseen_evaluation_snapshots": int(sealed["unseen_evaluation_unique_quote_dates"]),
    }


def assess(output_root: Path = source.DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
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
            dates = manifest["counts"]["quote_dates"]
            if not isinstance(dates, list) or len(dates) != 1:
                raise ValueError("manifest must contain exactly one quote date")
            checks = source.audit(snapshot)
            failed = sorted(name for name, passed in checks.items() if not passed)
            if failed:
                raise ValueError(f"replay audit failed: {', '.join(failed)}")
            quote_date = str(dates[0])
            item = {
                "quote_date": quote_date,
                "snapshot": snapshot.name,
                "quote_rows": int(manifest["counts"]["quote_rows"]),
                "funding_rows": int(manifest["counts"]["funding_rows"]),
                "retrieved_at_utc": str(manifest["retrieved_at_utc"]),
            }
            valid_snapshots.append(item)
            valid_by_date[quote_date].append(snapshot.name)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            invalid_snapshots.append({"snapshot": snapshot.name, "reason": str(error)})
    unique_dates = sorted(valid_by_date)
    duplicates = {
        date: names for date, names in sorted(valid_by_date.items()) if len(names) > 1
    }
    progress = phases.phase_progress(len(unique_dates), minimums(config))
    return {
        "protocol_id": config["protocol_id"],
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "output_root": str(root),
        "snapshot_count": len(snapshots),
        "valid_snapshot_count": len(valid_snapshots),
        "invalid_snapshot_count": len(invalid_snapshots),
        "valid_unique_quote_date_count": len(unique_dates),
        "first_valid_quote_date": unique_dates[0] if unique_dates else None,
        "last_valid_quote_date": unique_dates[-1] if unique_dates else None,
        "duplicate_valid_quote_dates": duplicates,
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
