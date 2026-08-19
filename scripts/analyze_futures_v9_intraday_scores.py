"""Label-only score diagnostics; never selects or simulates a trading threshold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab.futures_v9_intraday_timing.data import ASSETS, load_timing_arrays

OUTPUTS = (
    "long_value_3",
    "short_value_3",
    "long_value_6",
    "short_value_6",
    "long_value_18",
    "short_value_18",
)


def _scalar(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _one_score_diagnostic(predicted: np.ndarray, realized: np.ndarray) -> dict[str, object]:
    valid = np.isfinite(predicted) & np.isfinite(realized)
    predicted = predicted[valid]
    realized = realized[valid]
    if len(predicted) < 10:
        return {"rows": int(len(predicted))}
    order = np.argsort(predicted, kind="stable")
    decile = max(len(order) // 10, 1)
    bottom = realized[order[:decile]]
    top = realized[order[-decile:]]
    predicted_sign = predicted > 0.0
    realized_sign = realized > 0.0
    return {
        "rows": int(len(predicted)),
        "pearson_ic": _scalar(np.corrcoef(predicted, realized)[0, 1]),
        "spearman_ic": _scalar(pd.Series(predicted).corr(pd.Series(realized), method="spearman")),
        "sign_accuracy": float(np.mean(predicted_sign == realized_sign)),
        "predicted_positive_fraction": float(np.mean(predicted_sign)),
        "realized_positive_fraction": float(np.mean(realized_sign)),
        "positive_recall": (
            float(np.mean(predicted_sign[realized_sign])) if realized_sign.any() else None
        ),
        "top_decile_realized_mean": float(np.mean(top)),
        "bottom_decile_realized_mean": float(np.mean(bottom)),
        "decile_spread": float(np.mean(top) - np.mean(bottom)),
        "top_decile_positive_fraction": float(np.mean(top > 0.0)),
    }


def analyze(tensor_path: Path, predictions_path: Path) -> dict[str, object]:
    arrays = load_timing_arrays(tensor_path)
    predictions = pd.read_parquet(predictions_path)
    timestamp_ns = predictions["timestamp"].astype("int64").to_numpy()
    indices = np.searchsorted(arrays.timestamps_ns, timestamp_ns)
    if not np.array_equal(arrays.timestamps_ns[indices], timestamp_ns):
        raise ValueError("prediction timestamps do not map exactly to sealed tensor")
    asset_lookup = {asset: index for index, asset in enumerate(ASSETS)}
    asset_indices = predictions["asset"].map(asset_lookup).to_numpy(dtype=int)
    target = arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6)[indices, asset_indices]
    mask = arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6)[indices, asset_indices]
    years = pd.to_datetime(predictions["timestamp"], utc=True).dt.year.to_numpy()
    result: dict[str, object] = {
        "status": "score_diagnostic_only_no_threshold_or_pnl_selection",
        "variants": {},
    }
    for variant, labels in predictions.groupby("variant", sort=True).groups.items():
        row_indices = np.asarray(labels, dtype=int)
        variant_result: dict[str, object] = {"overall": {}, "by_year": {}}
        for output_index, output in enumerate(OUTPUTS):
            predicted = predictions.loc[row_indices, output].to_numpy(float)
            realized = target[row_indices, output_index].astype(float)
            realized[~mask[row_indices, output_index]] = np.nan
            variant_result["overall"][output] = _one_score_diagnostic(predicted, realized)
        for year in sorted(set(years[row_indices])):
            year_rows = row_indices[years[row_indices] == year]
            year_result: dict[str, object] = {"outputs": {}}
            score_matrix = predictions.loc[year_rows, list(OUTPUTS)].to_numpy(float)
            sigma_matrix = predictions.loc[
                year_rows, [f"{name}_uncertainty" for name in OUTPUTS]
            ].to_numpy(float)
            maximum_score = np.nanmax(score_matrix, axis=1)
            maximum_snr = np.nanmax(score_matrix / sigma_matrix, axis=1)
            year_result["maximum_score_distribution"] = {
                key: _scalar(value)
                for key, value in zip(
                    ("p50", "p90", "p99", "p999", "max"),
                    [*np.nanquantile(maximum_score, [0.5, 0.9, 0.99, 0.999]), np.nanmax(maximum_score)],
                    strict=True,
                )
            }
            year_result["maximum_snr_distribution"] = {
                key: _scalar(value)
                for key, value in zip(
                    ("p50", "p90", "p99", "p999", "max"),
                    [*np.nanquantile(maximum_snr, [0.5, 0.9, 0.99, 0.999]), np.nanmax(maximum_snr)],
                    strict=True,
                )
            }
            year_result["score_counts"] = {
                "rows": int(len(year_rows)),
                "maximum_score_positive": int(np.sum(maximum_score > 0.0)),
                "maximum_snr_over_0_50": int(np.sum(maximum_snr > 0.5)),
                "maximum_snr_over_0_75": int(np.sum(maximum_snr > 0.75)),
            }
            for output_index, output in enumerate(OUTPUTS):
                predicted = predictions.loc[year_rows, output].to_numpy(float)
                realized = target[year_rows, output_index].astype(float)
                realized[~mask[year_rows, output_index]] = np.nan
                year_result["outputs"][output] = _one_score_diagnostic(predicted, realized)
            variant_result["by_year"][str(year)] = year_result
        result["variants"][str(variant)] = variant_result
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tensor", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.tensor, args.predictions)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
