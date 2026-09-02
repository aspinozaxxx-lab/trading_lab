"""Measure displayed capacity and BBO crossing friction for Type B verticals."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_type_b_vertical_execution_diagnostics_v1.yaml"
)
CONFIG_SHA256: Final[str] = "cd32510e506b038546ced9a499f7b696d143d881529c2bb6e88bbde5ee0df26c"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-type-b-vertical-execution-diagnostics-2024-10-01-v1"
)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _root(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


def load_config() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("Type B vertical execution diagnostic config must be an object")
    fixed = config["fixed_diagnostics"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or config.get("protocol_id") != "moex_type_b_vertical_execution_diagnostics_v1"
        or config.get("status") != "sealed_after_parent_counts_before_depth_or_friction_values"
        or config.get("live_trading_allowed") is not False
        or int(config["parent"]["opportunities_rows"]) != 1_949
        or config["parent"]["structural_only"] is not True
        or [int(value) for value in fixed["freshness_seconds"]] != [1, 5, 15, 60]
        or [int(value) for value in config["predeclared_capacity_thresholds_contracts"]]
        != [1, 5, 10, 25]
        or [float(value) for value in config["predeclared_crossing_cost_fraction_thresholds"]]
        != [0.01, 0.02, 0.05, 0.10, 0.25]
        or [float(value) for value in config["predeclared_quantiles"]]
        != [0.10, 0.25, 0.50, 0.75, 0.90]
        or fixed["no_atomic_two_leg_fill_assumption"] is not True
        or config["limitations"][0]
        != "One sample date measures displayed structure, never expected return or stability."
    ):
        raise ValueError("Type B vertical execution diagnostic protocol drifted")
    return config


def verify_parent(config: dict[str, Any]) -> Path:
    spec = config["parent"]
    root = _root(spec["root"])
    manifest_path = root / "manifest.json"
    audit_path = root / "audit.json"
    opportunity_path = root / "vertical_opportunities.parquet"
    if (
        _sha_file(manifest_path) != spec["manifest_sha256"]
        or _sha_file(audit_path) != spec["audit_sha256"]
        or _sha_file(opportunity_path) != spec["opportunities_sha256"]
        or pq.ParquetFile(opportunity_path).metadata.num_rows != int(spec["opportunities_rows"])
    ):
        raise ValueError("Type B vertical execution diagnostic parent artifact drift")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    if (
        manifest["protocol_sha256"] != spec["protocol_sha256"]
        or manifest["implementation_sha256"] != spec["implementation_sha256"]
        or manifest["contains_return_label_target_prediction_trade_position_equity_or_pnl"]
        is not False
        or audit.get("all_true") is not True
    ):
        raise ValueError("Type B vertical execution diagnostic parent protocol drift")
    return root


def enrich(opportunities: pd.DataFrame) -> pd.DataFrame:
    required = {
        "grid_at_moscow",
        "freshness_seconds",
        "pair_id",
        "logical_asset",
        "option_type",
        "strike_width",
        "entry_debit",
        "long_bid_price",
        "long_bid_volume",
        "long_offer_price",
        "long_offer_volume",
        "short_bid_price",
        "short_bid_volume",
        "short_offer_price",
        "short_offer_volume",
    }
    missing = sorted(required - set(opportunities.columns))
    if missing:
        raise ValueError(f"Type B vertical diagnostic missing columns: {missing}")
    output = opportunities.loc[:, sorted(required)].copy()
    numeric = [
        "strike_width",
        "entry_debit",
        "long_bid_price",
        "long_bid_volume",
        "long_offer_price",
        "long_offer_volume",
        "short_bid_price",
        "short_bid_volume",
        "short_offer_price",
        "short_offer_volume",
    ]
    values = output[numeric].astype(float)
    if (
        not np.isfinite(values.to_numpy()).all()
        or values.le(0.0).any(axis=None)
        or output["entry_debit"].ge(output["strike_width"]).any()
    ):
        raise ValueError("Type B vertical diagnostic requires finite positive BBO inputs")
    if (
        output["long_bid_price"].ge(output["long_offer_price"]).any()
        or output["short_bid_price"].ge(output["short_offer_price"]).any()
    ):
        raise ValueError("Type B vertical diagnostic requires non-crossed leg BBO")
    expected_debit = output["long_offer_price"] - output["short_bid_price"]
    if not np.allclose(
        output["entry_debit"].astype(float),
        expected_debit.astype(float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("Type B vertical diagnostic entry debit drift")
    output["displayed_entry_capacity_contracts"] = (
        output[["long_offer_volume", "short_bid_volume"]].min(axis=1).astype("int64")
    )
    output["displayed_exit_capacity_contracts"] = (
        output[["long_bid_volume", "short_offer_volume"]].min(axis=1).astype("int64")
    )
    output["contemporaneous_exit_credit"] = output["long_bid_price"] - output["short_offer_price"]
    output["four_side_crossing_cost"] = (
        output["entry_debit"] - output["contemporaneous_exit_credit"]
    )
    tolerance = 1e-9
    if output["four_side_crossing_cost"].lt(-tolerance).any():
        raise ValueError("Type B vertical diagnostic found negative four-side crossing cost")
    output["four_side_crossing_cost"] = output["four_side_crossing_cost"].clip(lower=0.0)
    output["crossing_cost_fraction_of_strike_width"] = (
        output["four_side_crossing_cost"] / output["strike_width"]
    )
    output["entry_debit_fraction_of_strike_width"] = output["entry_debit"] / output["strike_width"]
    derived = output[
        [
            "contemporaneous_exit_credit",
            "four_side_crossing_cost",
            "crossing_cost_fraction_of_strike_width",
            "entry_debit_fraction_of_strike_width",
        ]
    ].astype(float)
    if not np.isfinite(derived.to_numpy()).all():
        raise ValueError("Type B vertical diagnostic produced nonfinite metrics")
    return output.sort_values(
        ["freshness_seconds", "grid_at_moscow", "pair_id"],
        kind="stable",
        ignore_index=True,
    )


def summarize(diagnostics: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    quantiles: dict[str, dict[str, float]] = {}
    capacity_thresholds = [
        int(value) for value in config["predeclared_capacity_thresholds_contracts"]
    ]
    friction_thresholds = [
        float(value) for value in config["predeclared_crossing_cost_fraction_thresholds"]
    ]
    quantile_grid = [float(value) for value in config["predeclared_quantiles"]]
    metric_columns = [
        "displayed_entry_capacity_contracts",
        "displayed_exit_capacity_contracts",
        "crossing_cost_fraction_of_strike_width",
        "entry_debit_fraction_of_strike_width",
    ]
    for freshness, subset in diagnostics.groupby("freshness_seconds", observed=True):
        age = int(freshness)
        counts[f"rows:{age}s"] = len(subset)
        for key, value in subset.groupby(["logical_asset", "option_type"]).size().items():
            counts[f"rows:{age}s:{key[0]}:{key[1]}"] = int(value)
        for threshold in capacity_thresholds:
            entry = subset["displayed_entry_capacity_contracts"].ge(threshold)
            exit_ = subset["displayed_exit_capacity_contracts"].ge(threshold)
            counts[f"entry_capacity_ge:{age}s:{threshold}"] = int(entry.sum())
            counts[f"exit_capacity_ge:{age}s:{threshold}"] = int(exit_.sum())
            counts[f"both_capacity_ge:{age}s:{threshold}"] = int((entry & exit_).sum())
        for threshold in friction_thresholds:
            label = f"{threshold:.2f}"
            counts[f"crossing_fraction_le:{age}s:{label}"] = int(
                subset["crossing_cost_fraction_of_strike_width"].le(threshold).sum()
            )
        for column in metric_columns:
            values = subset[column].quantile(quantile_grid, interpolation="linear")
            quantiles[f"{age}s:{column}"] = {
                f"q{int(round(q * 100)):02d}": float(values.loc[q]) for q in quantile_grid
            }
    forbidden = {str(value).lower() for value in config["forbidden_columns"]}
    if forbidden & {str(column).lower() for column in diagnostics.columns}:
        raise ValueError("Type B vertical diagnostic contains a forbidden economic column")
    return {
        "rows": len(diagnostics),
        "freshness_seconds": sorted(
            int(value) for value in diagnostics["freshness_seconds"].unique()
        ),
        "counts": dict(sorted(counts.items())),
        "quantiles": dict(sorted(quantiles.items())),
        "contains_return_label_target_prediction_signal_trade_position_equity_or_pnl": False,
        "single_sample_day_not_performance_evidence": True,
        "live_trading_allowed": False,
    }


def build(config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    root = verify_parent(config)
    opportunities = pd.read_parquet(root / "vertical_opportunities.parquet")
    if len(opportunities) != int(config["parent"]["opportunities_rows"]):
        raise ValueError("Type B vertical diagnostic parent row count drift")
    diagnostics = enrich(opportunities)
    return diagnostics, summarize(diagnostics, config)


def _sha_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(len(frame).to_bytes(8, "little", signed=False))
    values = pd.util.hash_pandas_object(frame, index=False, categorize=False)
    digest.update(values.to_numpy(dtype="uint64", copy=False).tobytes())
    return digest.hexdigest()


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha_file(path),
        "rows": rows,
    }


def audit(directory: Path) -> dict[str, Any]:
    config = load_config()
    verify_parent(config)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    artifacts_exact = True
    rows_exact = True
    for item in manifest["artifacts"]:
        path = directory / item["path"]
        artifacts_exact &= bool(
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
        if item["rows"] is not None and path.suffix == ".parquet":
            rows_exact &= pq.ParquetFile(path).metadata.num_rows == int(item["rows"])
    diagnostics, metrics = build(config)
    checks = {
        "config_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parent_exact_and_audited": True,
        "artifacts_exact": artifacts_exact,
        "parquet_rows_exact": rows_exact,
        "metrics_replay_exact": metrics == manifest["structural_metrics"],
        "diagnostics_replay_exact": (
            _sha_frame(diagnostics) == manifest["diagnostics_frame_sha256"]
        ),
        "crossing_cost_nonnegative": bool(diagnostics["four_side_crossing_cost"].ge(0.0).all()),
        "capacity_positive": bool(
            diagnostics[
                [
                    "displayed_entry_capacity_contracts",
                    "displayed_exit_capacity_contracts",
                ]
            ]
            .ge(1)
            .all(axis=None)
        ),
        "contains_no_economic_outputs": metrics[
            "contains_return_label_target_prediction_signal_trade_position_equity_or_pnl"
        ]
        is False,
        "live_trading_disabled": manifest["live_trading_allowed"] is False,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def run(output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    config = load_config()
    verify_parent(config)
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable Type B vertical diagnostic exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.parent / f".{output_root.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        diagnostics, metrics = build(config)
        diagnostics_path = temporary / config["outputs"]["diagnostics"]
        metrics_path = temporary / config["outputs"]["metrics"]
        diagnostics.to_parquet(diagnostics_path, index=False, compression="zstd")
        _write_json(metrics_path, metrics)
        manifest = {
            "protocol_id": config["protocol_id"],
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "parent_manifest_sha256": config["parent"]["manifest_sha256"],
            "diagnostics_frame_sha256": _sha_frame(diagnostics),
            "structural_metrics": metrics,
            "artifacts": [
                _artifact(diagnostics_path, len(diagnostics)),
                _artifact(metrics_path),
            ],
            "contains_return_label_target_prediction_signal_trade_position_equity_or_pnl": False,
            "live_trading_allowed": False,
        }
        _write_json(temporary / config["outputs"]["manifest"], manifest)
        report = audit(temporary)
        if report["all_true"] is not True:
            raise ValueError(f"Type B vertical diagnostic audit failed: {report['checks']}")
        _write_json(temporary / config["outputs"]["audit"], report)
        temporary.replace(output_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory is not None:
        report = audit(args.audit_directory)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["all_true"] is not True:
            raise SystemExit(1)
        return
    print(run(args.output_root))


if __name__ == "__main__":
    main()
