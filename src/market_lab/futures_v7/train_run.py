"""Servernyi runner pyati outer-foldov i treh seed futures-v7 bez PnL."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from market_lab.futures_v7.assembly import (
    V7_ASSEMBLY_SCHEMA_VERSION,
    LoadedV7TrainingArrays,
    load_v7_training_arrays,
)
from market_lab.futures_v7.config import (
    DEFAULT_V7_CONFIG_SHA256,
    V7_ASSETS,
    V7_SEEDS,
    V7FoldConfig,
    V7ResearchConfig,
    byte_sha256,
    load_v7_research_config,
)
from market_lab.io_utils import write_json

V7_PROTECTED_FROM: Final[date] = date(2026, 1, 1)  # Pervaya zapreshchennaya data.
V7_ASSEMBLY_STATUS: Final[str] = (  # Razreshennyi do-train status manifesta.
    "development_only_no_pnl_no_training"
)
V7_RUN_FORMAT: Final[str] = (  # Versiya atomarnogo itogovogo manifesta runnera.
    "market-lab-futures-v7-training-run-v1"
)
V7_PROGRESS_FORMAT: Final[str] = (  # Versiya resume-progress bez model'nyh metrik.
    "market-lab-futures-v7-training-progress-v1"
)
V7_CHECKPOINT_MANIFEST_FORMAT: Final[str] = (  # Format sidecar iz training API.
    "market-lab-futures-v7-seed-manifest-v1"
)
V7_RESUME_SEMANTICS: Final[str] = (  # Razreshen tol'ko gotovyi seed-checkpoint.
    "completed_seed_checkpoint_only_no_mid_stage_resume"
)
V7_MODEL_ID_PREFIX: Final[str] = "futures_v7_three_seed_mean"  # Stabil'nyi model-id.
V7_PREDICTION_COLUMNS: Final[tuple[str, ...]] = (  # Minimal'naya OOS-skhema.
    "decision_date",
    "decision_at",
    "asset",
    "candidate_score",
    "model_id",
)
V7_SHA256_LENGTH: Final[int] = 64  # Dlina hex SHA-256 bez prefiksa.
V7_CODE_IDENTITY_RELATIVE_PATHS: Final[tuple[str, ...]] = (  # Train code seal.
    "src/market_lab/futures_v7/train_run.py",
    "src/market_lab/futures_v7/training.py",
    "src/market_lab/futures_v7/model.py",
    "src/market_lab/futures_v7/dataset.py",
    "src/market_lab/futures_v7/config.py",
    "src/market_lab/futures_v7/assembly.py",
    "src/market_lab/futures_v7/contracts.py",
)


@dataclass(frozen=True, slots=True)
class VerifiedV7AssemblyManifest:
    """Hranit proverennye puti i identity assembly do zagruzki NPZ."""

    manifest_path: Path
    manifest_sha256: str
    arrays_path: Path
    arrays_sha256: str
    execution_overlay_path: Path
    execution_overlay_sha256: str
    source_artifacts: tuple[dict[str, Any], ...]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedV7TrainingInputs:
    """Obedinyaet zapechatannyi config, manifest i proverennye arrays."""

    project_root: Path
    config_path: Path
    config_sha256: str
    config: V7ResearchConfig
    assembly: VerifiedV7AssemblyManifest
    loaded: LoadedV7TrainingArrays


@dataclass(frozen=True, slots=True)
class V7TrainingApi:
    """Pozvolyaet testirovat' orchestration bez real'nogo CUDA-obucheniya."""

    train_fold_ensemble: Callable[..., Sequence[Any]]
    predict_model: Callable[..., np.ndarray]
    ensemble_predictions: Callable[[Sequence[np.ndarray]], np.ndarray]
    architecture_sha256: Callable[[Any], str]
    build_training_scope: Callable[..., Any]
    device: Any
    runtime_identity: dict[str, Any]
    reset_peak_vram: Callable[[], None]
    peak_vram: Callable[[], dict[str, int]]
    release_fold: Callable[[], None]


@dataclass(frozen=True, slots=True)
class V7TrainingRunArtifacts:
    """Vozvrashchaet puti polnogo training-only server run."""

    output_directory: Path
    run_identity_path: Path
    predictions_path: Path
    progress_path: Path
    checkpoint_identities_path: Path
    training_summary_path: Path


def _file_sha256(path: Path) -> str:
    """Hashiruet fail potokovo, ne zagruzhaya checkpoint v pamyat'."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(payload: Any) -> str:
    """Hashiruet JSON-compatible payload s fiksirovannoi serializaciei."""
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def build_v7_code_identity(project_root: Path) -> dict[str, Any]:
    """Hashiruet fixed implementation files strogo vnutri project-root/src."""
    root = project_root.resolve()
    source_root = (root / "src").resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    files: list[dict[str, Any]] = []
    for relative_name in V7_CODE_IDENTITY_RELATIVE_PATHS:
        path = root.joinpath(*Path(relative_name).parts).resolve()
        try:
            path.relative_to(source_root)
        except ValueError as error:
            raise ValueError(f"Code identity path vyshel iz project-root/src: {path}") from error
        if not path.is_file():
            raise FileNotFoundError(path)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    aggregate_sha = _canonical_json_sha256(files)
    return {
        "files": files,
        "code_identity_sha256": aggregate_sha,
    }


def _is_sha256(value: Any) -> bool:
    """Proveryaet strogo lowercase/uppercase hex SHA-256."""
    text = str(value)
    return len(text) == V7_SHA256_LENGTH and all(
        symbol in "0123456789abcdefABCDEF" for symbol in text
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    """Chitaet BOM-sovmestimyi JSON i trebuet object verhnego urovnya."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya object: {path}")
    return payload


def _bounded_path(root: Path, value: str | Path, label: str) -> Path:
    """Razreshaet absolute ili relative path strogo vnutri project-root."""
    resolved_root = root.resolve()
    candidate = Path(value)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else resolved_root.joinpath(*candidate.parts).resolve()
    )
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{label} vyshel iz project-root: {target}") from error
    return target


def _bounded_data_record_path(data_root: Path, value: Any, label: str) -> Path:
    """Razreshaet tol'ko otnositel'nyi manifest path vnutri data-root."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} ne soderzhit path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} path dolzhen byt' otnositel'nym")
    resolved_root = data_root.resolve()
    target = resolved_root.joinpath(*relative.parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{label} path vyshel iz data-root: {target}") from error
    return target


def _verify_artifact_record(
    data_root: Path,
    record: Any,
    label: str,
    *,
    require_bytes: bool,
) -> dict[str, Any]:
    """Proveryaet path, razmer i SHA odnogo manifest-referenced faila."""
    if not isinstance(record, dict):
        raise ValueError(f"{label} ne yavlyaetsya object")
    path = _bounded_data_record_path(data_root, record.get("path"), label)
    if not path.is_file():
        raise FileNotFoundError(path)
    if require_bytes and "bytes" not in record:
        raise ValueError(f"{label} ne soderzhit bytes")
    if "bytes" in record:
        expected_bytes = int(record["bytes"])
        if expected_bytes < 0 or path.stat().st_size != expected_bytes:
            raise ValueError(f"{label} bytes mismatch: {path}")
    expected_sha = record.get("sha256")
    if not _is_sha256(expected_sha):
        raise ValueError(f"{label} ne soderzhit korrektnyi SHA-256")
    actual_sha = _file_sha256(path)
    if actual_sha != str(expected_sha).lower():
        raise ValueError(f"{label} SHA-256 mismatch: {path}")
    return {
        "label": label,
        "path": path,
        "bytes": path.stat().st_size,
        "sha256": actual_sha,
    }


def verify_v7_assembly_manifest(
    project_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str | None = None,
) -> VerifiedV7AssemblyManifest:
    """Fail-closed proveryaet assembly manifest i vse ego file references."""
    root = project_root.resolve()
    data_root = (root / "data").resolve()
    resolved_manifest = _bounded_path(root, manifest_path, "Assembly manifest")
    try:
        resolved_manifest.relative_to(data_root)
    except ValueError as error:
        raise ValueError("Assembly manifest dolzhen nahodit'sya v data-root") from error
    if not resolved_manifest.is_file():
        raise FileNotFoundError(resolved_manifest)
    manifest_sha = _file_sha256(resolved_manifest)
    if expected_manifest_sha256 is not None:
        if not _is_sha256(expected_manifest_sha256):
            raise ValueError("Expected assembly manifest SHA-256 nekorrekten")
        if manifest_sha != expected_manifest_sha256.lower():
            raise ValueError("Assembly manifest byte-seal mismatch")
    payload = _read_json_object(resolved_manifest)
    declared_payload_sha = payload.get("manifest_payload_sha256")
    if not _is_sha256(declared_payload_sha):
        raise ValueError("Assembly manifest ne soderzhit payload SHA-256")
    payload_without_sha = dict(payload)
    payload_without_sha.pop("manifest_payload_sha256")
    actual_payload_sha = _canonical_json_sha256(payload_without_sha)
    if actual_payload_sha != str(declared_payload_sha).lower():
        raise ValueError("Assembly manifest payload SHA-256 mismatch")
    if int(payload.get("schema_version", -1)) != V7_ASSEMBLY_SCHEMA_VERSION:
        raise ValueError("Assembly schema version mismatch")
    if payload.get("research_status") != V7_ASSEMBLY_STATUS:
        raise ValueError("Assembly research status ne razreshaet training")
    if payload.get("protected_from") != V7_PROTECTED_FROM.isoformat():
        raise ValueError("Assembly ne imeet zapechatannoi 2026 granicy")

    arrays_identity = _verify_artifact_record(
        data_root,
        payload.get("arrays"),
        "Assembly arrays",
        require_bytes=True,
    )
    overlay_identity = _verify_artifact_record(
        data_root,
        payload.get("execution_market_overlay"),
        "Execution overlay",
        require_bytes=True,
    )
    if arrays_identity["path"] == overlay_identity["path"]:
        raise ValueError("Assembly arrays i execution overlay ssylayutsya na odin fail")
    expected_bundle_sha = hashlib.sha256(
        f"{arrays_identity['sha256']}:{overlay_identity['sha256']}".encode("ascii")
    ).hexdigest()
    if payload.get("bundle_sha256") != expected_bundle_sha:
        raise ValueError("Assembly arrays/overlay bundle SHA-256 mismatch")

    sources = payload.get("source_artifacts", [])
    if not isinstance(sources, list):
        raise ValueError("Assembly source_artifacts dolzhen byt' spiskom")
    verified_sources: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for index, record in enumerate(sources):
        identity = _verify_artifact_record(
            data_root,
            record,
            f"Source artifact {index}",
            require_bytes=False,
        )
        path = identity["path"]
        if path in seen_paths:
            raise ValueError(f"Assembly source_artifacts soderzhit duplicate path: {path}")
        seen_paths.add(path)
        verified_sources.append(
            {
                "kind": str(record.get("kind", "unknown")),
                "path": path.relative_to(data_root).as_posix(),
                "bytes": identity["bytes"],
                "sha256": identity["sha256"],
            }
        )
    return VerifiedV7AssemblyManifest(
        manifest_path=resolved_manifest,
        manifest_sha256=manifest_sha,
        arrays_path=arrays_identity["path"],
        arrays_sha256=arrays_identity["sha256"],
        execution_overlay_path=overlay_identity["path"],
        execution_overlay_sha256=overlay_identity["sha256"],
        source_artifacts=tuple(verified_sources),
        payload=payload,
    )


def _protected_cutoff_utc(config: V7ResearchConfig) -> np.datetime64:
    """Perevodit lokal'noe nachalo holdout v naive UTC numpy timestamp."""
    local = datetime.combine(
        config.development.protected_holdout_start,
        datetime_time.min,
        tzinfo=ZoneInfo(config.development.decision_timezone),
    )
    utc_naive = local.astimezone(UTC).replace(tzinfo=None)
    return np.datetime64(utc_naive, "ns")


def _decision_local_dates(
    decision_times: np.ndarray,
    timezone_name: str,
) -> np.ndarray:
    """Poluchaet lokal'nye kalendarnye daty iz naive UTC decision timestamps."""
    decisions = np.asarray(decision_times).astype("datetime64[ns]")
    if decisions.ndim != 1 or np.isnat(decisions).any():
        raise ValueError("Decision timestamps dolzhny byt' odnomernymi bez NaT")
    localized = pd.DatetimeIndex(decisions).tz_localize("UTC").tz_convert(timezone_name)
    return localized.tz_localize(None).to_numpy(dtype="datetime64[D]")


def _guard_no_protected_holdout(
    loaded: LoadedV7TrainingArrays,
    config: V7ResearchConfig,
) -> None:
    """Zapreshchaet lyubye sample, bar ili factual open iz lokal'nogo 2026 holdout."""
    arrays = loaded.arrays
    cutoff = _protected_cutoff_utc(config)
    timing_values = {
        "bar_times": arrays.timing.bar_times,
        "decision_times": arrays.timing.decision_times,
        "entry_open_times": arrays.timing.entry_open_times,
        "exit_open_times": arrays.timing.exit_open_times,
    }
    for name, values in timing_values.items():
        timestamps = np.asarray(values).astype("datetime64[ns]")
        factual = timestamps[~np.isnat(timestamps)]
        if len(factual) and (factual >= cutoff).any():
            raise ValueError(f"Protected 2026 timestamp obnaruzhen v {name}")
    sample_dates = np.asarray(loaded.sample_trade_dates).astype("datetime64[D]")
    if np.isnat(sample_dates).any() or (
        sample_dates >= np.datetime64(V7_PROTECTED_FROM, "D")
    ).any():
        raise ValueError("Protected 2026 sample_trade_date obnaruzhen")


def _validate_loaded_arrays(
    loaded: LoadedV7TrainingArrays,
    config: V7ResearchConfig,
    assembly: VerifiedV7AssemblyManifest,
) -> None:
    """Sveryaet tol'ko input/shape/calendar, ne vetvitsya po target contents."""
    arrays = loaded.arrays
    arrays.validate_inputs(config.model)
    sample_count = int(arrays.intraday.shape[0])
    if arrays.intraday.shape[1] != len(V7_ASSETS):
        raise ValueError("Assembly asset-axis ne sovpadaet s V7_ASSETS")
    if np.asarray(loaded.log_price).shape != arrays.intraday.shape[:3]:
        raise ValueError("Assembly log_price shape mismatch")
    if np.asarray(loaded.sample_trade_dates).shape != (sample_count,):
        raise ValueError("Assembly sample_trade_dates shape mismatch")
    if np.asarray(loaded.asset_entry_open_times).shape != arrays.asset_valid.shape:
        raise ValueError("Assembly asset_entry_open_times shape mismatch")
    if np.asarray(loaded.asset_exit_open_times).shape != arrays.asset_valid.shape:
        raise ValueError("Assembly asset_exit_open_times shape mismatch")
    if np.asarray(arrays.supervised_target).shape != arrays.asset_valid.shape:
        raise ValueError("Assembly supervised_target shape mismatch")
    if np.asarray(arrays.supervised_valid).shape != arrays.asset_valid.shape:
        raise ValueError("Assembly supervised_valid shape mismatch")

    arrays_record = assembly.payload["arrays"]
    expected_shapes = {
        "intraday_shape": list(arrays.intraday.shape),
        "daily_context_shape": list(arrays.daily_context.shape),
        "log_price_shape": list(np.asarray(loaded.log_price).shape),
        "asset_execution_time_shape": list(
            np.asarray(loaded.asset_entry_open_times).shape
        ),
    }
    if int(arrays_record.get("sample_count", -1)) != sample_count:
        raise ValueError("Assembly manifest sample_count mismatch")
    for field_name, actual_shape in expected_shapes.items():
        if list(arrays_record.get(field_name, [])) != actual_shape:
            raise ValueError(f"Assembly manifest {field_name} mismatch")
    audit = assembly.payload.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("Assembly manifest ne soderzhit audit object")
    sealed_audit_fields = {
        "assets": list(config.development.assets),
        "bar_feature_names": list(config.model.bar_feature_names),
        "daily_feature_names": list(config.model.daily_feature_names),
        "sequence_bars": config.model.sequence_bars,
        "ssl_horizons": list(config.model.ssl_horizons),
        "sample_count": sample_count,
    }
    for field_name, expected_value in sealed_audit_fields.items():
        if audit.get(field_name) != expected_value:
            raise ValueError(f"Assembly audit/config mismatch: {field_name}")

    sample_dates = np.asarray(loaded.sample_trade_dates).astype("datetime64[D]")
    decisions = np.asarray(arrays.timing.decision_times).astype("datetime64[ns]")
    local_dates = _decision_local_dates(
        decisions,
        config.development.decision_timezone,
    )
    if not np.array_equal(sample_dates, local_dates):
        raise ValueError("sample_trade_dates ne sovpadayut s local decision dates")
    if len(np.unique(sample_dates)) != sample_count:
        raise ValueError("Assembly soderzhit duplicate sample_trade_dates")
    if len(np.unique(decisions)) != sample_count:
        raise ValueError("Assembly soderzhit duplicate decision timestamps")
    if sample_count > 1 and (np.diff(decisions) <= np.timedelta64(0, "ns")).any():
        raise ValueError("Decision timestamps dolzhny strogo vozrastat'")
    _guard_no_protected_holdout(loaded, config)


def load_verified_v7_training_inputs(
    project_root: Path,
    config_path: Path,
    assembly_manifest_path: Path,
    *,
    expected_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
    expected_assembly_manifest_sha256: str | None = None,
    array_loader: Callable[[Path], LoadedV7TrainingArrays] | None = None,
) -> LoadedV7TrainingInputs:
    """Proveryaet oba seal i vse file hashes pered pervym chteniem NPZ arrays."""
    root = project_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    resolved_config = _bounded_path(root, config_path, "V7 config")
    config = load_v7_research_config(resolved_config, expected_config_sha256)
    config_sha = byte_sha256(resolved_config)
    assembly = verify_v7_assembly_manifest(
        root,
        assembly_manifest_path,
        expected_assembly_manifest_sha256,
    )
    loaded = (
        array_loader(assembly.arrays_path)
        if array_loader is not None
        else load_v7_training_arrays(
            assembly.arrays_path,
            validate_supervised_timing=False,
        )
    )
    _validate_loaded_arrays(loaded, config, assembly)
    return LoadedV7TrainingInputs(
        project_root=root,
        config_path=resolved_config,
        config_sha256=config_sha,
        config=config,
        assembly=assembly,
        loaded=loaded,
    )


def build_v7_oos_sample_indices(
    sample_trade_dates: np.ndarray,
    decision_times: np.ndarray,
    fold: V7FoldConfig,
    timezone_name: str,
) -> np.ndarray:
    """Vyberaet OOS tol'ko po datam/timestamps i nikogda po target availability."""
    sample_dates = np.asarray(sample_trade_dates).astype("datetime64[D]")
    decisions = np.asarray(decision_times).astype("datetime64[ns]")
    if sample_dates.ndim != 1 or decisions.shape != sample_dates.shape:
        raise ValueError("OOS calendar arrays imeyut raznye formy")
    if np.isnat(sample_dates).any() or np.isnat(decisions).any():
        raise ValueError("OOS calendar ne dopuskaet NaT")
    local_dates = _decision_local_dates(decisions, timezone_name)
    if not np.array_equal(sample_dates, local_dates):
        raise ValueError("OOS trade dates ne sovpadayut s decision timestamps")
    if len(np.unique(sample_dates)) != len(sample_dates):
        raise ValueError("OOS calendar soderzhit duplicate trade dates")
    if len(np.unique(decisions)) != len(decisions):
        raise ValueError("OOS calendar soderzhit duplicate decisions")
    score_start = np.datetime64(fold.score_start, "D")
    score_end = np.datetime64(fold.score_end, "D")
    indices = np.flatnonzero((sample_dates >= score_start) & (sample_dates <= score_end))
    if not len(indices):
        raise ValueError(f"Fold {fold.name} ne imeet OOS decision samples")
    result = indices.astype(np.int64, copy=False)
    result.flags.writeable = False
    return result


def build_v7_oos_prediction_frame(
    sample_trade_dates: np.ndarray,
    decision_times: np.ndarray,
    asset_valid: np.ndarray,
    sample_indices: np.ndarray,
    predictions: np.ndarray,
    model_id: str,
) -> pd.DataFrame:
    """Maskiruet scores tol'ko causal asset_valid i stroit long OOS-table."""
    indices = np.asarray(sample_indices, dtype=np.int64)
    scores = np.asarray(predictions, dtype=np.float64)
    causal_valid = np.asarray(asset_valid, dtype=bool)
    sample_dates = np.asarray(sample_trade_dates).astype("datetime64[D]")
    decisions = np.asarray(decision_times).astype("datetime64[ns]")
    expected_shape = (len(indices), len(V7_ASSETS))
    if indices.ndim != 1 or not len(indices):
        raise ValueError("Prediction frame trebuet nepustye odnomernye indices")
    if len(np.unique(indices)) != len(indices):
        raise ValueError("Prediction frame indices soderzhat duplicate")
    if (indices < 0).any() or (indices >= len(sample_dates)).any():
        raise IndexError("Prediction frame index vyshel iz sample calendar")
    if scores.shape != expected_shape:
        raise ValueError(f"Prediction shape {scores.shape} != {expected_shape}")
    if causal_valid.shape != (len(sample_dates), len(V7_ASSETS)):
        raise ValueError("asset_valid shape mismatch")
    selected_valid = causal_valid[indices]
    if not np.isfinite(scores[selected_valid]).all():
        raise ValueError("Valid candidate scores dolzhny byt' konechnymi")
    masked_scores = np.where(selected_valid, scores, np.nan)
    selected_dates = sample_dates[indices]
    selected_decisions = pd.to_datetime(decisions[indices], utc=True)
    frame = pd.DataFrame(
        {
            "decision_date": np.repeat(selected_dates, len(V7_ASSETS)),
            "decision_at": np.repeat(selected_decisions.to_numpy(), len(V7_ASSETS)),
            "asset": np.tile(np.asarray(V7_ASSETS, dtype=object), len(indices)),
            "candidate_score": masked_scores.reshape(-1),
            "model_id": model_id,
        },
        columns=list(V7_PREDICTION_COLUMNS),
    )
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], utc=True)
    duplicate_key = ["decision_at", "asset", "model_id"]
    if frame.duplicated(duplicate_key).any():
        raise ValueError("OOS predictions soderzhat duplicate decision/asset/model")
    return frame


def validate_v7_fold_supervised_scope(
    loaded: LoadedV7TrainingArrays,
    scope: Any,
) -> None:
    """Proveryaet target i per-asset timing tol'ko v uzhe postroennom train-scope."""
    arrays = loaded.arrays
    indices = np.asarray(scope.sample_indices, dtype=np.int64)
    sample_count = int(arrays.intraday.shape[0])
    if indices.ndim != 1 or not len(indices):
        raise ValueError("Train fold scope dolzhen soderzhat' samples")
    if len(np.unique(indices)) != len(indices):
        raise ValueError("Train fold scope soderzhit duplicate indices")
    if (indices < 0).any() or (indices >= sample_count).any():
        raise IndexError("Train fold scope index vyshel iz assembly")
    targets = np.asarray(arrays.supervised_target)[indices]
    target_valid = np.asarray(arrays.supervised_valid, dtype=bool)[indices]
    causal_asset_valid = np.asarray(arrays.asset_valid, dtype=bool)[indices]
    valid = target_valid & causal_asset_valid
    if not valid.any():
        raise ValueError("Train fold ne soderzhit ni odnogo valid supervised target")
    if not np.isfinite(targets[valid]).all():
        raise ValueError("Train fold valid supervised target ne konechen")

    asset_entry = np.asarray(loaded.asset_entry_open_times).astype("datetime64[ns]")[
        indices
    ]
    asset_exit = np.asarray(loaded.asset_exit_open_times).astype("datetime64[ns]")[
        indices
    ]
    decisions = np.asarray(arrays.timing.decision_times).astype("datetime64[ns]")[
        indices
    ][:, None]
    if (
        np.isnat(asset_entry[valid]).any()
        or np.isnat(asset_exit[valid]).any()
        or (asset_entry[valid] <= np.broadcast_to(decisions, valid.shape)[valid]).any()
        or (asset_entry[valid] >= asset_exit[valid]).any()
    ):
        raise ValueError("Train fold valid target imeet nekorrektnyi per-asset timing")
    effective_end = np.datetime64(scope.effective_end_exclusive_utc, "ns")
    if (asset_exit[valid] >= effective_end).any():
        raise ValueError("Train fold target vyhodit za effective train boundary")


def _default_training_api() -> V7TrainingApi:
    """Lenivo zagruzhaet torch i finalized training API tol'ko posle data verify."""
    import torch

    from market_lab.futures_v7.training import (
        architecture_sha256,
        arithmetic_ensemble_predictions,
        build_fold_training_scope,
        predict_v7_model,
        require_v7_training_device,
        train_v7_fold_ensemble,
    )

    device = require_v7_training_device()
    properties = torch.cuda.get_device_properties(device)

    def reset_peak_vram() -> None:
        """Sbrosyvaet CUDA peak counters neposredstvenno pered pervym foldom."""
        torch.cuda.reset_peak_memory_stats(device)

    def peak_vram() -> dict[str, int]:
        """Vozvrashchaet peak allocated i reserved VRAM za ves' run."""
        return {
            "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
            "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
        }

    def release_fold() -> None:
        """Osvobozhdaet CUDA cache posle sohraneniya prognozov odnogo folda."""
        torch.cuda.empty_cache()

    runtime_identity = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "pid": os.getpid(),
        "torch_version": str(torch.__version__),
        "cuda_runtime_version": str(torch.version.cuda),
        "cuda_device_index": int(device.index or 0),
        "gpu_name": str(properties.name),
        "gpu_total_memory_bytes": int(properties.total_memory),
        "gpu_compute_capability": list(torch.cuda.get_device_capability(device)),
        "native_bfloat16": bool(torch.cuda.is_bf16_supported()),
    }
    return V7TrainingApi(
        train_fold_ensemble=train_v7_fold_ensemble,
        predict_model=predict_v7_model,
        ensemble_predictions=arithmetic_ensemble_predictions,
        architecture_sha256=architecture_sha256,
        build_training_scope=build_fold_training_scope,
        device=device,
        runtime_identity=runtime_identity,
        reset_peak_vram=reset_peak_vram,
        peak_vram=peak_vram,
        release_fold=release_fold,
    )


def _checkpoint_identity(
    outcome: Any,
    project_root: Path,
    expected_fold_name: str,
    expected_seed: int,
    architecture_sha256: str,
) -> dict[str, Any]:
    """Povtorno proveryaet checkpoint/sidecar i izvlekaet transport identity."""
    checkpoint_path = _bounded_path(
        project_root,
        Path(outcome.checkpoint_path),
        "Checkpoint",
    )
    manifest_path = _bounded_path(
        project_root,
        Path(outcome.manifest_path),
        "Checkpoint manifest",
    )
    if not checkpoint_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("Checkpoint bundle nepolon posle training")
    sidecar = _read_json_object(manifest_path)
    if sidecar.get("format") != V7_CHECKPOINT_MANIFEST_FORMAT:
        raise ValueError("Checkpoint sidecar format mismatch")
    if sidecar.get("checkpoint_file") != checkpoint_path.name:
        raise ValueError("Checkpoint sidecar ssylayetsya ne na tot fail")
    checkpoint_sha = _file_sha256(checkpoint_path)
    if sidecar.get("checkpoint_sha256") != checkpoint_sha:
        raise ValueError("Checkpoint sidecar SHA-256 mismatch")
    core = sidecar.get("manifest")
    if not isinstance(core, dict):
        raise ValueError("Checkpoint sidecar ne soderzhit internal manifest")
    internal_manifest_sha = _canonical_json_sha256(core)
    if sidecar.get("manifest_sha256") != internal_manifest_sha:
        raise ValueError("Checkpoint internal manifest SHA-256 mismatch")
    fold_payload = core.get("fold")
    if not isinstance(fold_payload, dict) or fold_payload.get("name") != expected_fold_name:
        raise ValueError("Checkpoint fold identity mismatch")
    if int(core.get("seed", -1)) != expected_seed or int(outcome.seed) != expected_seed:
        raise ValueError("Checkpoint seed identity mismatch")
    if core.get("resume_semantics") != V7_RESUME_SEMANTICS:
        raise ValueError("Checkpoint resume semantics mismatch")
    training_hashes = core.get("training_hashes")
    if not isinstance(training_hashes, dict):
        raise ValueError("Checkpoint ne soderzhit training hashes")
    if training_hashes.get("architecture_sha256") != architecture_sha256:
        raise ValueError("Checkpoint architecture SHA-256 mismatch")
    return {
        "fold_name": expected_fold_name,
        "seed": expected_seed,
        "resumed": bool(outcome.resumed),
        "checkpoint_path": checkpoint_path.relative_to(project_root).as_posix(),
        "checkpoint_bytes": checkpoint_path.stat().st_size,
        "checkpoint_sha256": checkpoint_sha,
        "sidecar_path": manifest_path.relative_to(project_root).as_posix(),
        "sidecar_bytes": manifest_path.stat().st_size,
        "sidecar_sha256": _file_sha256(manifest_path),
        "internal_manifest_sha256": internal_manifest_sha,
        "training_hashes": dict(training_hashes),
        "resume_semantics": V7_RESUME_SEMANTICS,
    }


def _validate_seed_outcomes(
    outcomes: Sequence[Any],
    expected_seeds: tuple[int, ...],
    fold_name: str,
) -> tuple[Any, ...]:
    """Trebuet odin i tol'ko odin outcome dlya kazhdogo fixed seed."""
    normalized = tuple(outcomes)
    actual_seeds = tuple(int(outcome.seed) for outcome in normalized)
    if len(normalized) != len(expected_seeds):
        raise ValueError(f"Fold {fold_name} ne vernul rovno tri seed outcomes")
    if actual_seeds != expected_seeds:
        raise ValueError(
            f"Fold {fold_name} seed order/identity mismatch: {actual_seeds}"
        )
    if len(set(actual_seeds)) != len(actual_seeds):
        raise ValueError(f"Fold {fold_name} soderzhit duplicate seed")
    return normalized


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno pishet Parquet i fsync-it gotovyi vremennyi fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _identity_payload(
    inputs: LoadedV7TrainingInputs,
    architecture_sha256: str,
    code_identity: dict[str, Any],
) -> dict[str, Any]:
    """Sobiraet compact config/data/model identity dlya resume i itoga."""
    source_sha = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in inputs.assembly.source_artifacts
    ]
    data_payload = {
        "assembly_manifest_sha256": inputs.assembly.manifest_sha256,
        "assembly_arrays_sha256": inputs.assembly.arrays_sha256,
        "execution_overlay_sha256": inputs.assembly.execution_overlay_sha256,
        "source_artifacts": source_sha,
    }
    return {
        "config_sha256": inputs.config_sha256,
        "architecture_sha256": architecture_sha256,
        "assembly_manifest_sha256": inputs.assembly.manifest_sha256,
        "assembly_arrays_sha256": inputs.assembly.arrays_sha256,
        "execution_overlay_sha256": inputs.assembly.execution_overlay_sha256,
        "data_identity_sha256": _canonical_json_sha256(data_payload),
        "code_identity_sha256": code_identity["code_identity_sha256"],
        "code_identity": code_identity,
    }


def _validate_existing_run_identity(path: Path, identity: dict[str, Any]) -> None:
    """Ne daet resume smeshat' output ot drugogo config ili assembly."""
    if not path.exists():
        return
    payload = _read_json_object(path)
    existing = payload.get("identity")
    if existing != identity:
        raise ValueError(f"Existing training artifact identity mismatch: {path}")


def _write_progress(
    path: Path,
    identity: dict[str, Any],
    completed_folds: Sequence[str],
    checkpoints: Sequence[dict[str, Any]],
) -> None:
    """Atomarno fiksiruet completed-fold progress bez OOS score values."""
    write_json(
        path,
        {
            "format": V7_PROGRESS_FORMAT,
            "research_status": "training_in_progress_no_pnl",
            "identity": identity,
            "completed_folds": list(completed_folds),
            "completed_seed_checkpoints": len(checkpoints),
            "checkpoint_keys": [
                f"{item['fold_name']}:{item['seed']}" for item in checkpoints
            ],
            "resume_semantics": V7_RESUME_SEMANTICS,
        },
    )


def run_v7_training(
    project_root: Path,
    config_path: Path,
    assembly_manifest_path: Path,
    output_directory: Path,
    *,
    expected_config_sha256: str = DEFAULT_V7_CONFIG_SHA256,
    expected_assembly_manifest_sha256: str | None = None,
    resume: bool = True,
    training_api: V7TrainingApi | None = None,
    array_loader: Callable[[Path], LoadedV7TrainingArrays] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> V7TrainingRunArtifacts:
    """Obuchaet 5x3 seed, strogo sobiraet OOS prediction i ne schitaet PnL."""
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    inputs = load_verified_v7_training_inputs(
        project_root,
        config_path,
        assembly_manifest_path,
        expected_config_sha256=expected_config_sha256,
        expected_assembly_manifest_sha256=expected_assembly_manifest_sha256,
        array_loader=array_loader,
    )
    root = inputs.project_root
    output = _bounded_path(root, output_directory, "Training output")
    api = training_api or _default_training_api()
    architecture_sha = api.architecture_sha256(inputs.config.model)
    if not _is_sha256(architecture_sha):
        raise ValueError("Training API vernul nekorrektnyi architecture SHA-256")
    code_identity = build_v7_code_identity(root)
    identity = _identity_payload(inputs, architecture_sha.lower(), code_identity)
    run_identity_path = output / "run_identity.json"
    progress_path = output / "training_progress.json"
    summary_path = output / "training_summary.json"
    checkpoint_directory = output / "checkpoints"
    if not run_identity_path.exists():
        orphaned_checkpoint = checkpoint_directory.exists() and any(
            path.is_file() for path in checkpoint_directory.rglob("*")
        )
        if resume and orphaned_checkpoint:
            raise ValueError("Resume checkpoint sushchestvuet bez pre-run identity commit")
        output.mkdir(parents=True, exist_ok=True)
        write_json(
            run_identity_path,
            {
                "format": V7_RUN_FORMAT,
                "research_status": "pre_training_identity_committed_no_pnl",
                "identity": identity,
            },
        )
    _validate_existing_run_identity(run_identity_path, identity)
    _validate_existing_run_identity(progress_path, identity)
    _validate_existing_run_identity(summary_path, identity)
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_directory.mkdir(parents=True, exist_ok=True)

    config = inputs.config
    loaded = inputs.loaded
    if len(config.development.folds) != 5 or tuple(config.training.seeds) != V7_SEEDS:
        raise ValueError("V7 runner trebuet rovno 5 folds x 3 fixed seeds")
    model_id = f"{V7_MODEL_ID_PREFIX}_{architecture_sha[:12]}"
    oos_frames: list[pd.DataFrame] = []
    checkpoint_identities: list[dict[str, Any]] = []
    completed_folds: list[str] = []
    used_oos_indices: set[int] = set()
    api.reset_peak_vram()

    for fold in config.development.folds:
        oos_indices = build_v7_oos_sample_indices(
            loaded.sample_trade_dates,
            loaded.arrays.timing.decision_times,
            fold,
            config.development.decision_timezone,
        )
        overlap = used_oos_indices.intersection(int(index) for index in oos_indices)
        if overlap:
            raise ValueError(f"Outer-fold OOS indices perekryvayutsya: {sorted(overlap)}")
        used_oos_indices.update(int(index) for index in oos_indices)
        train_scope = api.build_training_scope(
            loaded.arrays.timing,
            fold,
            config.development.decision_timezone,
            config.development.purge_sessions,
        )
        validate_v7_fold_supervised_scope(loaded, train_scope)
        outcomes = _validate_seed_outcomes(
            api.train_fold_ensemble(
                loaded.arrays,
                loaded.log_price,
                config,
                fold.name,
                checkpoint_directory,
                resume=resume,
            ),
            tuple(config.training.seeds),
            fold.name,
        )
        seed_predictions: list[np.ndarray] = []
        for expected_seed, outcome in zip(config.training.seeds, outcomes, strict=True):
            checkpoint_identities.append(
                _checkpoint_identity(
                    outcome,
                    root,
                    fold.name,
                    expected_seed,
                    architecture_sha.lower(),
                )
            )
            prediction = np.asarray(
                api.predict_model(
                    outcome.model,
                    loaded.arrays,
                    outcome.scaler,
                    oos_indices,
                    api.device,
                ),
                dtype=np.float64,
            )
            expected_shape = (len(oos_indices), len(V7_ASSETS))
            if prediction.shape != expected_shape:
                raise ValueError(
                    f"Fold {fold.name} seed {expected_seed} prediction shape mismatch"
                )
            seed_predictions.append(prediction)
        ensemble = np.asarray(
            api.ensemble_predictions(tuple(seed_predictions)),
            dtype=np.float64,
        )
        oos_frames.append(
            build_v7_oos_prediction_frame(
                loaded.sample_trade_dates,
                loaded.arrays.timing.decision_times,
                loaded.arrays.asset_valid,
                oos_indices,
                ensemble,
                model_id,
            )
        )
        completed_folds.append(fold.name)
        _write_progress(
            progress_path,
            identity,
            completed_folds,
            checkpoint_identities,
        )
        api.release_fold()
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "fold_complete",
                    "fold_name": fold.name,
                    "completed_folds": len(completed_folds),
                    "total_folds": len(config.development.folds),
                    "completed_seed_checkpoints": len(checkpoint_identities),
                }
            )

    predictions = pd.concat(oos_frames, ignore_index=True)
    predictions = predictions.sort_values(
        ["decision_at", "asset", "model_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if predictions.duplicated(["decision_at", "asset", "model_id"]).any():
        raise ValueError("Itogovye OOS predictions soderzhat duplicate")
    if pd.to_datetime(predictions["decision_at"], utc=True).ge(
        pd.Timestamp(_protected_cutoff_utc(config)).tz_localize("UTC")
    ).any():
        raise ValueError("Itogovye predictions pronikli v protected 2026")
    if len(checkpoint_identities) != 15:
        raise ValueError("V7 runner ne zavershil rovno 15 seed checkpoints")
    checkpoint_keys = [
        (item["fold_name"], int(item["seed"])) for item in checkpoint_identities
    ]
    if len(set(checkpoint_keys)) != len(checkpoint_keys):
        raise ValueError("Itogovyi checkpoint spisok soderzhit duplicate")

    predictions_path = output / "oos_predictions.parquet"
    _atomic_write_parquet(predictions_path, predictions)
    checkpoint_identities_path = output / "checkpoint_identities.json"
    write_json(
        checkpoint_identities_path,
        {
            "format": V7_RUN_FORMAT,
            "research_status": "training_complete_no_pnl",
            "identity": identity,
            "checkpoints": checkpoint_identities,
        },
    )
    finished_at = datetime.now(UTC)
    summary = {
        "format": V7_RUN_FORMAT,
        "research_status": "training_complete_no_pnl_no_holdout_access",
        "identity": identity,
        "protocol_name": config.protocol_name,
        "protocol_version": config.protocol_version,
        "model_id": model_id,
        "fold_names": [fold.name for fold in config.development.folds],
        "seeds": list(config.training.seeds),
        "expected_fold_count": 5,
        "expected_seed_count_per_fold": 3,
        "completed_seed_checkpoint_count": len(checkpoint_identities),
        "new_seed_checkpoint_count": sum(
            not item["resumed"] for item in checkpoint_identities
        ),
        "resumed_seed_checkpoint_count": sum(
            item["resumed"] for item in checkpoint_identities
        ),
        "prediction_artifact": {
            "path": predictions_path.relative_to(root).as_posix(),
            "bytes": predictions_path.stat().st_size,
            "sha256": _file_sha256(predictions_path),
            "rows": len(predictions),
            "valid_candidate_scores": int(predictions["candidate_score"].notna().sum()),
            "masked_candidate_scores": int(predictions["candidate_score"].isna().sum()),
            "columns": list(V7_PREDICTION_COLUMNS),
            "mask_semantics": "causal_asset_valid_only_never_supervised_valid",
        },
        "checkpoint_identity_artifact": {
            "path": checkpoint_identities_path.relative_to(root).as_posix(),
            "bytes": checkpoint_identities_path.stat().st_size,
            "sha256": _file_sha256(checkpoint_identities_path),
        },
        "run_identity_artifact": {
            "path": run_identity_path.relative_to(root).as_posix(),
            "bytes": run_identity_path.stat().st_size,
            "sha256": _file_sha256(run_identity_path),
        },
        "runtime": {
            **api.runtime_identity,
            **api.peak_vram(),
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "elapsed_seconds": time.perf_counter() - started_clock,
        },
        "resume_semantics": V7_RESUME_SEMANTICS,
        "oos_index_semantics": "trade_date_and_decision_timestamp_fold_bounds_only",
        "protected_holdout_start": V7_PROTECTED_FROM.isoformat(),
        "pnl_or_trading_metrics_computed": False,
    }
    write_json(summary_path, summary)
    return V7TrainingRunArtifacts(
        output_directory=output,
        run_identity_path=run_identity_path,
        predictions_path=predictions_path,
        progress_path=progress_path,
        checkpoint_identities_path=checkpoint_identities_path,
        training_summary_path=summary_path,
    )


def _cli_progress(payload: dict[str, Any]) -> None:
    """Pechataet odnu compact JSON-stroku posle zaversheniya kazhdogo folda."""
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def build_argument_parser() -> argparse.ArgumentParser:
    """Stroit server-oriented CLI bez zavisimosti ot osnovnogo Typer-prilozheniya."""
    parser = argparse.ArgumentParser(
        description="Train sealed futures-v7 5-fold x 3-seed ensemble without PnL.",
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/futures_v7_development_protocol.yaml"),
    )
    parser.add_argument("--config-sha256", default=DEFAULT_V7_CONFIG_SHA256)
    parser.add_argument("--assembly-manifest", type=Path, required=True)
    parser.add_argument("--assembly-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore completed-seed checkpoints and retrain all fixed seeds.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Zapuskaet CLI i vozvrashchaet nol' tol'ko posle atomarnogo summary."""
    arguments = build_argument_parser().parse_args(argv)
    artifacts = run_v7_training(
        arguments.project_root,
        arguments.config,
        arguments.assembly_manifest,
        arguments.output,
        expected_config_sha256=arguments.config_sha256,
        expected_assembly_manifest_sha256=arguments.assembly_manifest_sha256,
        resume=not arguments.no_resume,
        progress_callback=_cli_progress,
    )
    print(
        json.dumps(
            {
                "event": "training_complete",
                "output_directory": str(artifacts.output_directory),
                "run_identity": str(artifacts.run_identity_path),
                "predictions": str(artifacts.predictions_path),
                "summary": str(artifacts.training_summary_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LoadedV7TrainingInputs",
    "V7TrainingApi",
    "V7TrainingRunArtifacts",
    "VerifiedV7AssemblyManifest",
    "build_v7_code_identity",
    "build_argument_parser",
    "build_v7_oos_prediction_frame",
    "build_v7_oos_sample_indices",
    "load_verified_v7_training_inputs",
    "main",
    "run_v7_training",
    "validate_v7_fold_supervised_scope",
    "verify_v7_assembly_manifest",
]
