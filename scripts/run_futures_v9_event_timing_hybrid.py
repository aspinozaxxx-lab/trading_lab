"""Run the byte-sealed frozen event/timing hybrid evaluation."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from market_lab.futures_v9_event_timing_hybrid import PROJECT_ROOT, run_hybrid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or (
        PROJECT_ROOT / "runs" / f"futures_v9_event_timing_hybrid_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    )
    run_hybrid(output_dir.resolve())
    print(output_dir.resolve())


if __name__ == "__main__":
    main()
