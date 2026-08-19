"""Run and persist the sealed futures-v9 corridor development experiment."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import pandas as pd

from market_lab.futures_v8.context_run import verify_main_session_manifest_tree
from market_lab.futures_v9_corridor.backtest import run_corridor_backtest
from market_lab.futures_v9_corridor.data import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONFIG_SHA256,
    PROJECT_ROOT,
    load_corridor_source_bundle,
    load_protocol,
    sha256_file,
    verify_protocol_sources,
)
from market_lab.futures_v9_corridor.label_dataset import build_competing_risk_labels
from market_lab.futures_v9_corridor.model import fit_expanding_corridor_models

DEFAULT_OUTPUT: Final[Path] = PROJECT_ROOT / "runs" / "futures-v9-corridor-development-v1"
CODE_FILES: Final[tuple[str, ...]] = (
    "src/market_lab/futures_v9_corridor/__init__.py",
    "src/market_lab/futures_v9_corridor/data.py",
    "src/market_lab/futures_v9_corridor/labels.py",
    "src/market_lab/futures_v9_corridor/label_dataset.py",
    "src/market_lab/futures_v9_corridor/model.py",
    "src/market_lab/futures_v9_corridor/backtest.py",
    "src/market_lab/futures_v9_corridor/run.py",
)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: object) -> None:
    content = "\ufeff" + json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
        default=lambda value: value.isoformat() if hasattr(value, "isoformat") else str(value),
    ) + "\n"
    _atomic_bytes(path, content.encode("utf-8"))


def _persist_parquet(path: Path, frame: pd.DataFrame) -> dict[str, object]:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)
    reloaded = pd.read_parquet(path)
    if len(reloaded) != len(frame) or list(reloaded.columns) != list(frame.columns):
        raise RuntimeError(f"persisted parquet failed reload verification: {path.name}")
    return {
        "path": path.name,
        "rows": len(frame),
        "columns": list(frame.columns),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _qa_against_v8(bundle: Any) -> dict[str, object]:
    context = pd.read_parquet(bundle.source_paths["v8_context_qa_only"])
    context["decision_at"] = pd.to_datetime(context["decision_at"], utc=True)
    joined = bundle.features.merge(
        context,
        on=["decision_at", "asset"],
        how="inner",
        validate="one_to_one",
        suffixes=("_v9", "_v8"),
    )
    comparisons = {
        "raw_close": "close",
        "atr_20_v9": "atr_20_v8",
        "daily_volatility_20_v9": "daily_volatility_20_v8",
        "momentum_20_v9": "momentum_20_v8",
        "range_position_20_v9": "range_position_20_v8",
        "volatility_ratio_20_v9": "volatility_ratio_20_v8",
        "volume_ratio_20_v9": "volume_ratio_20_v8",
        "carry_z": "carry_z_value",
        "cftc_z": "cftc_crowd_z_value",
        "usd_rub_return_z": "usd_rub_return_z_value",
    }
    differences: dict[str, object] = {}
    for left, right in comparisons.items():
        finite = joined[left].notna() & joined[right].notna()
        delta = (
            joined.loc[finite, left].astype(float)
            - joined.loc[finite, right].astype(float)
        ).abs()
        differences[f"{left}__{right}"] = {
            "compared": int(finite.sum()),
            "max_absolute_difference": None if delta.empty else float(delta.max()),
            "missingness_mismatch": int((joined[left].notna() != joined[right].notna()).sum()),
        }
    return {
        "joined_rows": len(joined),
        "expected_rows": len(context),
        "comparisons": differences,
    }


def run_experiment(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    """Execute the fixed experiment once and return the verified manifest."""
    output = output_dir.resolve()
    if not output.is_relative_to(PROJECT_ROOT):
        raise ValueError("corridor output must remain inside the project")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"corridor output already exists and is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    bundle = load_corridor_source_bundle()
    source_seconds = time.perf_counter() - started
    labels = build_competing_risk_labels(bundle)
    label_seconds = time.perf_counter() - started - source_seconds
    model_result = fit_expanding_corridor_models(bundle.features, labels)
    model_seconds = time.perf_counter() - started - source_seconds - label_seconds
    results = [
        run_corridor_backtest(
            bundle,
            model_result.predictions,
            corridor_id=corridor_id,
            cost_multiplier=cost,
        )
        for corridor_id in ("primary", "safer_diagnostic")
        for cost in (1.0, 2.0)
    ]
    backtest_seconds = (
        time.perf_counter() - started - source_seconds - label_seconds - model_seconds
    )
    feature_columns = [
        name
        for name in bundle.features.columns
        if not any(token in name.lower() for token in ("target", "label", "pnl", "future"))
    ]
    artifacts: dict[str, object] = {}
    artifacts["causal_features"] = _persist_parquet(
        output / "causal_features.parquet", bundle.features.loc[:, feature_columns]
    )
    artifacts["planned_contracts"] = _persist_parquet(
        output / "planned_contracts.parquet", bundle.planned_contracts
    )
    artifacts["competing_risk_labels"] = _persist_parquet(
        output / "competing_risk_labels.parquet", labels
    )
    artifacts["oos_predictions"] = _persist_parquet(
        output / "oos_predictions.parquet", model_result.predictions
    )
    for result in results:
        stem = f"{result.corridor_id}_{int(result.cost_multiplier)}x"
        artifacts[f"attempts_{stem}"] = _persist_parquet(
            output / f"attempts_{stem}.parquet", result.attempts
        )
        artifacts[f"trades_{stem}"] = _persist_parquet(
            output / f"trades_{stem}.parquet", result.trades
        )
        artifacts[f"equity_{stem}"] = _persist_parquet(
            output / f"equity_{stem}.parquet", result.equity_curve
        )
    fold_payload = [asdict(item) for item in model_result.folds]
    metrics = {
        "protocol_sha256": DEFAULT_CONFIG_SHA256,
        "development_only": True,
        "protected_holdout_accessed": False,
        "label_coverage": {
            "rows": len(labels),
            "resolved_rows": int(labels["label_resolved"].sum()),
            "unresolved_rows": int((~labels["label_resolved"].astype(bool)).sum()),
            "unresolved_reasons": {
                str(key): int(value)
                for key, value in labels.loc[
                    ~labels["label_resolved"].astype(bool), "unresolved_reason"
                ].value_counts().items()
            },
        },
        "folds": fold_payload,
        "results": [item.metrics for item in results],
    }
    _write_json(output / "metrics.json", metrics)
    artifacts["metrics"] = {
        "path": "metrics.json",
        "bytes": (output / "metrics.json").stat().st_size,
        "sha256": sha256_file(output / "metrics.json"),
    }
    qa = _qa_against_v8(bundle)
    code_records = [
        {
            "path": relative,
            "sha256": sha256_file(PROJECT_ROOT / relative),
            "bytes": (PROJECT_ROOT / relative).stat().st_size,
        }
        for relative in CODE_FILES
    ]
    source_records = [
        {
            "name": name,
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for name, path in sorted(bundle.source_paths.items())
    ]
    manifest: dict[str, object] = {
        "schema": "market-lab-futures-v9-corridor-development-v1",
        "created_at": datetime.now(UTC),
        "protocol": {
            "path": str(DEFAULT_CONFIG_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": DEFAULT_CONFIG_SHA256,
            "frozen_before_development_outcome_read": True,
        },
        "protected_holdout_start": "2026-01-01",
        "protected_holdout_accessed": False,
        "calendar": {
            "source_decisions": len(bundle.decisions),
            "first_decision": bundle.decisions[0],
            "last_decision": bundle.decisions[-1],
            "oos_years": [2021, 2022, 2023, 2024, 2025],
        },
        "raw_10m": {
            "rows_loaded": len(bundle.bar_store.bars),
            "parquet_children_used": len(bundle.bar_store.parquet_sha256s),
            "transitive_child_bundle_sha256": bundle.raw_tree_bundle_sha256,
        },
        "feature_names": list(model_result.feature_names),
        "qa_against_v8_context": qa,
        "source_files": source_records,
        "source_bundle_sha256": _canonical_sha256(source_records),
        "code_files": code_records,
        "code_bundle_sha256": _canonical_sha256(code_records),
        "artifacts": artifacts,
        "artifact_bundle_sha256": _canonical_sha256(artifacts),
        "timings_seconds": {
            "source": source_seconds,
            "labels": label_seconds,
            "model": model_seconds,
            "backtest": backtest_seconds,
            "total_before_persist": source_seconds
            + label_seconds
            + model_seconds
            + backtest_seconds,
        },
        "outcome_summary": metrics,
    }
    _write_json(output / "manifest.json", manifest)
    manifest_sha = sha256_file(output / "manifest.json")
    _atomic_bytes(
        output / "manifest.sha256",
        ("\ufeff" + f"{manifest_sha}  manifest.json\n").encode("utf-8"),
    )
    reloaded = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    if reloaded["protected_holdout_accessed"] is not False:
        raise RuntimeError("persisted manifest holdout flag drift")
    return reloaded


def finalize_existing_output(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    """Finalize a computed ledger set after a post-evaluation manifest-only failure.

    This recovery path never refits a model or changes a trade.  It verifies every
    existing artifact, reruns source and context QA, and records the recovery reason.
    """
    output = output_dir.resolve()
    if not output.is_relative_to(PROJECT_ROOT) or not output.is_dir():
        raise ValueError("existing corridor output is missing or outside project")
    if (output / "manifest.json").exists():
        raise FileExistsError("existing output is already finalized")
    expected = {
        "causal_features.parquet",
        "planned_contracts.parquet",
        "competing_risk_labels.parquet",
        "oos_predictions.parquet",
        "metrics.json",
        *{
            f"{kind}_{corridor}_{cost}x.parquet"
            for kind in ("attempts", "trades", "equity")
            for corridor in ("primary", "safer_diagnostic")
            for cost in (1, 2)
        },
    }
    present = {path.name for path in output.iterdir() if path.is_file()}
    if present != expected:
        raise ValueError(
            f"partial artifact set is not exact; missing={sorted(expected-present)}, "
            f"extra={sorted(present-expected)}"
        )
    protocol = load_protocol()
    source_paths = verify_protocol_sources(protocol)
    features = pd.read_parquet(output / "causal_features.parquet")

    class _QaBundle:
        def __init__(self) -> None:
            self.features = features
            self.source_paths = source_paths

    qa = _qa_against_v8(_QaBundle())
    tree = verify_main_session_manifest_tree(source_paths["raw_10m_manifest"])
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    artifacts: dict[str, object] = {}
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
            artifacts[path.stem] = {
                "path": path.name,
                "rows": len(frame),
                "columns": list(frame.columns),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        elif path.name == "metrics.json":
            artifacts["metrics"] = {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    code_records = [
        {
            "path": relative,
            "sha256": sha256_file(PROJECT_ROOT / relative),
            "bytes": (PROJECT_ROOT / relative).stat().st_size,
        }
        for relative in CODE_FILES
    ]
    source_records = [
        {
            "name": name,
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for name, path in sorted(source_paths.items())
    ]
    feature_times = pd.to_datetime(features["decision_at"], utc=True)
    manifest: dict[str, object] = {
        "schema": "market-lab-futures-v9-corridor-development-v1",
        "created_at": datetime.now(UTC),
        "protocol": {
            "path": str(DEFAULT_CONFIG_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": DEFAULT_CONFIG_SHA256,
            "frozen_before_development_outcome_read": True,
        },
        "protected_holdout_start": "2026-01-01",
        "protected_holdout_accessed": False,
        "calendar": {
            "source_decisions": int(feature_times.nunique()),
            "first_decision": feature_times.min(),
            "last_decision": feature_times.max(),
            "oos_years": [2021, 2022, 2023, 2024, 2025],
        },
        "raw_10m": {
            "verified_tree_rows": tree.parquet_rows,
            "verified_tree_parquet_children": tree.parquet_artifact_count,
            "transitive_child_bundle_sha256": tree.child_bundle_sha256,
        },
        "qa_against_v8_context": qa,
        "source_files": source_records,
        "source_bundle_sha256": _canonical_sha256(source_records),
        "code_files": code_records,
        "code_bundle_sha256": _canonical_sha256(code_records),
        "artifacts": artifacts,
        "artifact_bundle_sha256": _canonical_sha256(artifacts),
        "recovery_audit": {
            "reason": "post_evaluation_qa_column_alias_bug_before_manifest_write",
            "models_or_trades_recomputed": False,
            "existing_artifacts_byte_preserved": True,
        },
        "outcome_summary": metrics,
    }
    _write_json(output / "manifest.json", manifest)
    manifest_sha = sha256_file(output / "manifest.json")
    _atomic_bytes(
        output / "manifest.sha256",
        ("\ufeff" + f"{manifest_sha}  manifest.json\n").encode("utf-8"),
    )
    return json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))


def main() -> None:
    manifest = run_experiment()
    print(json.dumps(manifest["outcome_summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_OUTPUT", "finalize_existing_output", "run_experiment"]
