"""Build the sealed development-only continuous timing tensor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from market_lab.futures_v9_intraday_timing.data import (
    ASSETS,
    FEATURE_NAMES,
    HORIZONS,
    build_timing_arrays,
    save_timing_arrays,
    sha256_file,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_dir = root / "data/processed/futures_v9_intraday_timing"
    tensor_path = output_dir / "development_2018_2025.npz"
    arrays = build_timing_arrays()
    save_timing_arrays(arrays, tensor_path)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "research_status": "development_only_holdout_untouched",
        "protected_from": "2026-01-01",
        "assets": list(ASSETS),
        "feature_names": list(FEATURE_NAMES),
        "horizons": list(HORIZONS),
        "timestamp_rows": int(len(arrays.timestamps_ns)),
        "first_timestamp_ns": int(arrays.timestamps_ns[0]),
        "last_timestamp_ns": int(arrays.timestamps_ns[-1]),
        "asset_bar_rows": int(arrays.asset_mask.sum()),
        "exact_next_execution_rows": int(arrays.execution_mask.sum()),
        "target_rows_by_horizon": [
            int(arrays.target_mask[:, :, index, 0].sum()) for index in range(len(HORIZONS))
        ],
        "sizing_rows": int(arrays.sizing_mask.sum()),
        "source_parquet_sha256s": list(arrays.source_hashes),
        "protocol": {
            "path": "configs/futures_v9_intraday_timing.yaml",
            "sha256": "fd6ee70086bc7056ca60c73a91490362aae37c4caf053091cc73e2e0924159cf",
        },
        "tensor": {
            "path": str(tensor_path.relative_to(root)).replace("\\", "/"),
            "bytes": tensor_path.stat().st_size,
            "sha256": sha256_file(tensor_path),
        },
        "positive_target_fraction": {
            f"{horizon}_{side}": float(
                np.mean(
                    arrays.target_values[:, :, horizon_index, side_index][
                        arrays.target_mask[:, :, horizon_index, side_index]
                    ]
                    > 0.0
                )
            )
            for horizon_index, horizon in enumerate(HORIZONS)
            for side_index, side in enumerate(("long", "short"))
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
