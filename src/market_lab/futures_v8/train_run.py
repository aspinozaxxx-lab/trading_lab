"""Fail-closed servernyi orchestration runner futures-v8 bez PnL."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import platform
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures_v8.assembly import (
    V8_ASSEMBLY_SCHEMA_VERSION,
    V8_CAUSAL_V7_KEYS,
    V8_PROTECTED_HOLDOUT_START,
    V8AssemblyResult,
    V8CausalInputs,
    V8FoldScope,
    V8TargetArrays,
    assert_v8_pre_io_date_range,
    build_v8_fold_scope,
    build_v8_ssl_valid_mask,
    validate_v8_fold_scope,
)
from market_lab.futures_v8.config import (
    DEFAULT_V8_CONFIG_SHA256,
    V8_ASSETS,
    V8_SEEDS,
    V8_SSL_HORIZONS,
    V8FoldConfig,
    V8ResearchConfig,
    byte_sha256,
    load_v8_research_config,
)
from market_lab.io_utils import atomic_write_bytes, write_json

V8_RUN_FORMAT: Final[str] = "market-lab-futures-v8-training-run-v1"
V8_PROGRESS_FORMAT: Final[str] = "market-lab-futures-v8-training-progress-v1"
V8_CHECKPOINT_FORMAT: Final[str] = "market-lab-futures-v8-completed-seed-v1"
V8_RESUME_SEMANTICS: Final[str] = "completed_seed_only_no_midstage_resume"
V8_ASSEMBLY_STATUS: Final[str] = "assembly_only_no_train_no_pnl_no_holdout_access"
V8_MODEL_ID_PREFIX: Final[str] = "futures_v8_three_seed_moment_ensemble"
V8_SHA256_LENGTH: Final[int] = 64
V8_SSL_EPOCHS: Final[int] = 48
V8_SUPERVISED_EPOCHS: Final[int] = 32
V8_PRECISION: Final[str] = "bfloat16"
V8_TORCH_BACKEND_FORMAT: Final[str] = "market-lab-futures-v8-torch-backend-v1"
V8_TORCH_CHECKPOINT_FORMAT: Final[str] = "market-lab-futures-v8-torch-state-v1"
V8_TORCH_SSL_BATCH_SIZE: Final[int] = 64
V8_TORCH_SUPERVISED_BATCH_SIZE: Final[int] = 64
V8_TORCH_INFERENCE_BATCH_SIZE: Final[int] = 256
V8_CODE_ROOTS: Final[tuple[str, ...]] = (
    "src/market_lab/futures_v8/train_run.py",
    "src/market_lab/futures_v8/assembly.py",
    "src/market_lab/futures_v8/config.py",
    "src/market_lab/futures_v8/model.py",
    "src/market_lab/futures_v8/training.py",
)
V8_REQUIRED_ARRAY_KEYS: Final[tuple[str, ...]] = (
    "intraday",
    "intraday_valid",
    "daily_context",
    "daily_valid",
    "asset_valid",
    "log_price",
    "bar_times",
    "sample_trade_dates",
    "decision_times",
    "target_raw",
    "target_normalized",
    "target_valid",
    "target_ex_ante_daily_volatility_20",
    "target_entry_window_open_times",
    "target_entry_window_close_times",
    "target_exit_window_open_times",
    "target_exit_window_close_times",
    "target_availability_times",
    "target_entry_contract_ids",
    "target_exit_contract_ids",
    "target_entry_capacity_open_times",
    "target_exit_capacity_open_times",
    "target_entry_capacity_volumes",
    "target_exit_capacity_volumes",
)
V8_FORBIDDEN_LEGACY_KEYS: Final[frozenset[str]] = frozenset(
    {"supervised_target", "supervised_valid"}
)
V8_PREDICTION_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "factor_location",
    "factor_scale",
    "factor_score",
    "residual_location",
    "residual_scale",
    "residual_decision_score",
    "direction_logit",
    "model_id",
)


@dataclass(frozen=True, slots=True)
class VerifiedV8AssemblyManifest:
    """Hranit byte-proverennyi assembly i ego source provenance."""

    manifest_path: Path
    manifest_sha256: str
    arrays_path: Path
    arrays_sha256: str
    source_identities: tuple[dict[str, Any], ...]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedV8SpecProxy:
    """Hranit externally sealed authoritative spec-proxy table i identity."""

    manifest_path: Path
    manifest_sha256: str
    parquet_path: Path
    parquet_sha256: str
    frame: pd.DataFrame
    identity: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedV8TrainingInputs:
    """Obedinyaet proverennye config, assembly manifest i arrays."""

    project_root: Path
    config_path: Path
    config_sha256: str
    config: V8ResearchConfig
    assembly: VerifiedV8AssemblyManifest
    result: V8AssemblyResult


@dataclass(frozen=True, slots=True)
class V8FoldStatistics:
    """Hranit robust scaler i target IQR, fitted tol'ko v purged train fold."""

    intraday_median: tuple[float, ...]
    intraday_iqr: tuple[float, ...]
    intraday_observations: tuple[int, ...]
    daily_median: tuple[float, ...]
    daily_iqr: tuple[float, ...]
    daily_observations: tuple[int, ...]
    train_target_iqr: float
    train_target_observations: int
    sample_indices_sha256: str
    effective_cutoff: str

    def as_dict(self) -> dict[str, Any]:
        """Serializuet train-only statistiki bez tensorov ili OOS znachenii."""
        return {
            "intraday_median": list(self.intraday_median),
            "intraday_iqr": list(self.intraday_iqr),
            "intraday_observations": list(self.intraday_observations),
            "daily_median": list(self.daily_median),
            "daily_iqr": list(self.daily_iqr),
            "daily_observations": list(self.daily_observations),
            "train_target_iqr": self.train_target_iqr,
            "train_target_observations": self.train_target_observations,
            "sample_indices_sha256": self.sample_indices_sha256,
            "effective_cutoff": self.effective_cutoff,
        }


@dataclass(frozen=True, slots=True)
class V8FoldTrainingView:
    """Ogranichivaet training API tol'ko tekushchim purged train fold."""

    intraday: np.ndarray
    intraday_valid: np.ndarray
    daily_context: np.ndarray
    daily_valid: np.ndarray
    asset_valid: np.ndarray
    log_price: np.ndarray
    bar_times: np.ndarray
    decision_times: np.ndarray
    sample_trade_dates: np.ndarray
    normalized_target: np.ndarray
    target_valid: np.ndarray
    target_availability_times: np.ndarray
    ex_ante_daily_volatility_20: np.ndarray
    entry_effective_dates: np.ndarray
    entry_contract_ids: np.ndarray
    entry_capacity_open_times: np.ndarray
    exit_capacity_open_times: np.ndarray
    entry_capacity_volumes: np.ndarray
    exit_capacity_volumes: np.ndarray
    ssl_valid_mask: np.ndarray
    global_sample_indices: np.ndarray
    effective_cutoff: np.datetime64


@dataclass(frozen=True, slots=True)
class V8InferenceView:
    """Soderzhit tol'ko causal OOS input; target fields konstruktivno otsutstvuyut."""

    intraday: np.ndarray
    intraday_valid: np.ndarray
    daily_context: np.ndarray
    daily_valid: np.ndarray
    asset_valid: np.ndarray
    bar_times: np.ndarray
    decision_times: np.ndarray
    sample_trade_dates: np.ndarray
    global_sample_indices: np.ndarray


@dataclass(frozen=True, slots=True)
class V8CostScale:
    """Hranit D-known one-way cost proxy i ego explicit availability mask."""

    values_in_target_iqr: np.ndarray
    valid: np.ndarray
    method: str
    source_identity: dict[str, Any]


@dataclass(frozen=True, slots=True)
class V8SeedTrainingRequest:
    """Fiksiruet fresh SSL48 plus frozen-supervised32 kontrakt odnogo seed."""

    fold_name: str
    seed: int
    training_view: V8FoldTrainingView
    statistics: V8FoldStatistics
    cost_scale: V8CostScale
    ssl_epochs: int
    supervised_epochs: int
    ssl_learning_rate: float
    supervised_learning_rate: float
    weight_decay: float
    gradient_clip_norm: float
    precision: str
    deterministic_algorithms: bool
    fresh_ssl_initialization_required: bool
    freeze_encoder_before_supervised_required: bool


@dataclass(frozen=True, slots=True)
class V8SeedTrainingOutcome:
    """Vozvrashchaet tol'ko polnost'yu zavershennyi seed i checkpoint bytes."""

    seed: int
    state: Any
    checkpoint_bytes: bytes
    ssl_history: tuple[dict[str, Any], ...]
    supervised_history: tuple[dict[str, Any], ...]
    fresh_ssl_initialization: bool
    encoder_frozen_before_supervised: bool


@dataclass(frozen=True, slots=True)
class V8SeedPrediction:
    """Razdelyaet factor/residual location, uncertainty, score i direction."""

    factor_location: np.ndarray
    factor_scale: np.ndarray
    factor_score: np.ndarray
    residual_location: np.ndarray
    residual_scale: np.ndarray
    residual_decision_score: np.ndarray
    direction_logit: np.ndarray


@dataclass(frozen=True, slots=True)
class V8TrainingApi:
    """In'ekciya real CUDA ili synthetic test backend bez target access v predict."""

    fit_cost_scale: Callable[[V8FoldTrainingView, V8FoldStatistics], V8CostScale]
    train_completed_seed: Callable[[V8SeedTrainingRequest], V8SeedTrainingOutcome]
    restore_completed_seed: Callable[[bytes, V8SeedTrainingRequest], Any]
    predict_seed: Callable[[Any, V8InferenceView, V8FoldStatistics], V8SeedPrediction]
    runtime_identity: dict[str, Any]
    reset_peak_vram: Callable[[], None]
    peak_vram: Callable[[], dict[str, int]]
    release_fold: Callable[[], None]


@dataclass(frozen=True, slots=True)
class V8TrainingRunArtifacts:
    """Vozvrashchaet atomic training-only artefakty bez PnL."""

    output_directory: Path
    run_identity_path: Path
    predictions_path: Path
    progress_path: Path
    checkpoint_identities_path: Path
    training_summary_path: Path


def _file_sha256(path: Path) -> str:
    """Hashiruet file potokovo bez text normalization."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _bytes_sha256(content: bytes) -> str:
    """Hashiruet immutable binary payload."""
    return hashlib.sha256(content).hexdigest()


def _canonical_json_sha256(payload: Any) -> str:
    """Hashiruet JSON payload s odnoznachnoi serializaciei."""
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return _bytes_sha256(content)


def _array_sha256(values: np.ndarray) -> str:
    """Hashiruet dtype, shape i contiguous bytes odnogo numpy massiva."""
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    """Proveryaet exact 64-symbolnyi hexadecimal SHA-256."""
    text = str(value)
    return len(text) == V8_SHA256_LENGTH and all(
        symbol in "0123456789abcdefABCDEF" for symbol in text
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    """Chitaet BOM-compatible JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya object: {path}")
    return payload


def _bounded_path(root: Path, value: str | Path, label: str) -> Path:
    """Razreshaet path strogo vnutri project root."""
    resolved_root = root.resolve()
    candidate = Path(value)
    target = (
        candidate.resolve()
        if candidate.is_absolute()
        else (resolved_root / candidate).resolve()
    )
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"{label} vyshel iz project root: {target}") from error
    return target


def _bounded_data_path(data_root: Path, value: Any, label: str) -> Path:
    """Razreshaet manifest-relative path tol'ko vnutri data root."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} ne soderzhit path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{label} path dolzhen byt' otnositel'nym")
    target = (data_root.resolve() / relative).resolve()
    try:
        target.relative_to(data_root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} vyshel iz data root") from error
    return target


def _module_file(source_root: Path, module_name: str) -> Path | None:
    """Nahodit local market_lab module ili package init bez importa."""
    if not module_name.startswith("market_lab"):
        return None
    parts = module_name.split(".")
    module_path = source_root.joinpath(*parts).with_suffix(".py")
    if module_path.is_file():
        return module_path.resolve()
    package_path = source_root.joinpath(*parts, "__init__.py")
    if package_path.is_file():
        return package_path.resolve()
    return None


def _local_imports(path: Path, source_root: Path) -> tuple[Path, ...]:
    """Izvlekaet static local import closure iz odnogo Python source."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    discovered: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
        for module in modules:
            resolved = _module_file(source_root, module)
            if resolved is not None:
                discovered.add(resolved)
                parent = resolved.parent / "__init__.py"
                while parent.is_file() and parent.resolve().is_relative_to(source_root.resolve()):
                    discovered.add(parent.resolve())
                    if parent.parent == source_root:
                        break
                    parent = parent.parent.parent / "__init__.py"
    return tuple(sorted(discovered))


def build_v8_code_identity(project_root: Path) -> dict[str, Any]:
    """Hashiruet polnuyu static local runtime closure do CUDA initialization."""
    root = project_root.resolve()
    source_root = (root / "src").resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    pending = [_bounded_path(root, relative, "Code root") for relative in V8_CODE_ROOTS]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        try:
            path.relative_to(source_root)
        except ValueError as error:
            raise ValueError(f"Runtime code vyshel iz source root: {path}") from error
        if not path.is_file():
            raise FileNotFoundError(path)
        visited.add(path)
        pending.extend(item for item in _local_imports(path, source_root) if item not in visited)
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path in sorted(visited)
    ]
    return {"files": files, "code_identity_sha256": _canonical_json_sha256(files)}


def verify_v8_assembly_manifest(
    project_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> VerifiedV8AssemblyManifest:
    """Proveryaet external byte seal, payload, arrays i available source bytes."""
    root = project_root.resolve()
    data_root = (root / "data").resolve()
    manifest = _bounded_path(root, manifest_path, "V8 assembly manifest")
    try:
        manifest.relative_to(data_root)
    except ValueError as error:
        raise ValueError("V8 assembly manifest dolzhen byt' v data root") from error
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    if not _is_sha256(expected_manifest_sha256):
        raise ValueError("Expected V8 assembly manifest SHA-256 nekorrekten")
    manifest_sha = _file_sha256(manifest)
    if manifest_sha != expected_manifest_sha256.lower():
        raise ValueError("V8 assembly manifest byte seal mismatch")
    payload = _read_json_object(manifest)
    declared_payload_sha = payload.get("manifest_payload_sha256")
    payload_without_sha = dict(payload)
    payload_without_sha.pop("manifest_payload_sha256", None)
    if not _is_sha256(declared_payload_sha) or _canonical_json_sha256(
        payload_without_sha
    ) != str(declared_payload_sha).lower():
        raise ValueError("V8 assembly manifest payload SHA-256 mismatch")
    if int(payload.get("schema_version", -1)) != V8_ASSEMBLY_SCHEMA_VERSION:
        raise ValueError("V8 assembly schema mismatch")
    if payload.get("research_status") != V8_ASSEMBLY_STATUS:
        raise ValueError("V8 assembly research status ne razreshaet training")
    if payload.get("protected_holdout_start") != V8_PROTECTED_HOLDOUT_START.isoformat():
        raise ValueError("V8 assembly ne imeet sealed 2026 boundary")
    arrays_record = payload.get("arrays")
    if not isinstance(arrays_record, dict):
        raise ValueError("V8 assembly arrays record otsutstvuet")
    arrays_path = _bounded_data_path(data_root, arrays_record.get("path"), "V8 arrays")
    if not arrays_path.is_file():
        raise FileNotFoundError(arrays_path)
    if arrays_path.stat().st_size != int(arrays_record.get("bytes", -1)):
        raise ValueError("V8 assembly arrays bytes mismatch")
    arrays_sha = _file_sha256(arrays_path)
    if not _is_sha256(arrays_record.get("sha256")) or arrays_sha != str(
        arrays_record["sha256"]
    ).lower():
        raise ValueError("V8 assembly arrays SHA-256 mismatch")

    source_hashes = payload.get("source_hashes")
    sources = payload.get("source_artifacts")
    if not isinstance(source_hashes, dict) or not isinstance(sources, list) or not sources:
        raise ValueError("V8 assembly source provenance nepolon")
    identities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(sources):
        if not isinstance(record, dict):
            raise ValueError(f"V8 source artifact {index} ne object")
        source_id = str(record.get("id", ""))
        kind = str(record.get("kind", ""))
        stated_sha = str(record.get("sha256", "")).lower()
        if (
            not source_id
            or source_id in seen_ids
            or not kind
            or not _is_sha256(stated_sha)
        ):
            raise ValueError("V8 source id/kind/SHA invalid ili duplicate")
        seen_ids.add(source_id)
        if source_hashes.get(source_id) != stated_sha:
            raise ValueError(f"V8 source_hashes mismatch: {source_id}")
        identity: dict[str, Any] = {
            "id": source_id,
            "kind": kind,
            "sha256": stated_sha,
        }
        if "path" in record:
            source_path = _bounded_data_path(
                data_root,
                record["path"],
                f"V8 source {source_id}",
            )
            relative_path = source_path.relative_to(data_root).as_posix()
            expected_id = f"{kind}:{relative_path}"
            if source_id != expected_id:
                raise ValueError(f"V8 source stable id mismatch: {source_id}")
            stated_bytes = record.get("bytes")
            if (
                isinstance(stated_bytes, bool)
                or not isinstance(stated_bytes, int)
                or stated_bytes < 0
            ):
                raise ValueError(f"V8 source bytes invalid: {source_id}")
            if not source_path.is_file() or source_path.stat().st_size != stated_bytes:
                raise ValueError(f"V8 source byte count mismatch: {source_id}")
            if _file_sha256(source_path) != stated_sha:
                raise ValueError(f"V8 source byte SHA mismatch: {source_id}")
            stated_rows = record.get("rows")
            if stated_rows is not None and (
                isinstance(stated_rows, bool)
                or not isinstance(stated_rows, int)
                or stated_rows < 0
            ):
                raise ValueError(f"V8 source rows invalid: {source_id}")
            identity.update(
                {
                    "path": relative_path,
                    "bytes": stated_bytes,
                    "rows": stated_rows,
                    "verification": "byte_rehashed",
                }
            )
        else:
            stated_rows = record.get("rows")
            if (
                isinstance(stated_rows, bool)
                or not isinstance(stated_rows, int)
                or stated_rows <= 0
            ):
                raise ValueError(f"V8 source {source_id} bez proveriaemogo path/rows")
            identity.update(
                {
                    "rows": stated_rows,
                    "verification": "digest_bound_by_external_manifest_byte_seal",
                }
            )
        identities.append(identity)
    if set(source_hashes) != seen_ids:
        raise ValueError("V8 source_hashes keys ne ravny stable source ids")
    v7_record = payload.get("v7_source")
    if not isinstance(v7_record, dict):
        raise ValueError("V8 v7_source record otsutstvuet")
    if tuple(v7_record.get("keys_read", ())) != V8_CAUSAL_V7_KEYS:
        raise ValueError("V8 assembly causal v7 key whitelist mismatch")
    if v7_record.get("legacy_supervised_keys_read") != []:
        raise ValueError("V8 assembly prochital legacy supervised key")
    v7_identities = [item for item in identities if item["kind"] == "v7_causal_npz"]
    if len(v7_identities) != 1 or v7_identities[0]["sha256"] != v7_record.get("sha256"):
        raise ValueError("V8 v7 source SHA records mismatch")
    provenance = payload.get("source_provenance")
    if isinstance(provenance, dict) and provenance.get("status") == (
        "cryptographically_verified_real_sources"
    ):
        file_identities = [item for item in identities if item.get("path") is not None]
        official_count = sum(
            item["kind"] == "official_moex_10m_parquet" for item in file_identities
        )
        if (
            len(file_identities) != 222
            or official_count != 219
            or provenance.get("verified_file_count") != 222
            or provenance.get("verified_all_contract_parquet_count") != 219
        ):
            raise ValueError("V8 real source provenance file counts mismatch")
    return VerifiedV8AssemblyManifest(
        manifest_path=manifest,
        manifest_sha256=manifest_sha,
        arrays_path=arrays_path,
        arrays_sha256=arrays_sha,
        source_identities=tuple(identities),
        payload=payload,
    )


def _load_time(values: np.ndarray) -> np.ndarray:
    """Vosstanavlivaet datetime64[ns] iz int64 ili datetime archive field."""
    return np.asarray(values).astype("datetime64[ns]")


def load_v8_assembly_arrays(
    path: Path,
    assembly: VerifiedV8AssemblyManifest,
) -> V8AssemblyResult:
    """Chitaet current public v8 schema bez legacy supervised aliases."""
    with np.load(path, allow_pickle=False) as archive:
        names = set(archive.files)
        missing = set(V8_REQUIRED_ARRAY_KEYS) - names
        if missing:
            raise ValueError(f"V8 arrays ne soderzhat keys: {sorted(missing)}")
        if names & V8_FORBIDDEN_LEGACY_KEYS:
            raise ValueError("V8 arrays soderzhat forbidden legacy supervised keys")
        values = {name: archive[name] for name in V8_REQUIRED_ARRAY_KEYS}
    v7_record = assembly.payload["v7_source"]
    inputs = V8CausalInputs(
        intraday=np.asarray(values["intraday"], dtype=np.float32),
        intraday_valid=np.asarray(values["intraday_valid"], dtype=bool),
        daily_context=np.asarray(values["daily_context"], dtype=np.float32),
        daily_valid=np.asarray(values["daily_valid"], dtype=bool),
        asset_valid=np.asarray(values["asset_valid"], dtype=bool),
        log_price=np.asarray(values["log_price"], dtype=np.float64),
        bar_times=_load_time(values["bar_times"]),
        sample_trade_dates=_load_time(values["sample_trade_dates"]),
        decision_times=_load_time(values["decision_times"]),
        source_path=Path(str(v7_record["path"])).resolve(),
        source_sha256=str(v7_record["sha256"]),
        keys_read=tuple(v7_record["keys_read"]),
    )
    targets = V8TargetArrays(
        raw_target=np.asarray(values["target_raw"], dtype=np.float32),
        normalized_target=np.asarray(values["target_normalized"], dtype=np.float32),
        valid=np.asarray(values["target_valid"], dtype=bool),
        ex_ante_daily_volatility_20=np.asarray(
            values["target_ex_ante_daily_volatility_20"], dtype=np.float32
        ),
        entry_window_open_times=_load_time(values["target_entry_window_open_times"]),
        entry_window_close_times=_load_time(values["target_entry_window_close_times"]),
        exit_window_open_times=_load_time(values["target_exit_window_open_times"]),
        exit_window_close_times=_load_time(values["target_exit_window_close_times"]),
        availability_times=_load_time(values["target_availability_times"]),
        entry_contract_ids=np.asarray(values["target_entry_contract_ids"]),
        exit_contract_ids=np.asarray(values["target_exit_contract_ids"]),
        entry_capacity_open_times=_load_time(values["target_entry_capacity_open_times"]),
        exit_capacity_open_times=_load_time(values["target_exit_capacity_open_times"]),
        entry_capacity_volumes=np.asarray(
            values["target_entry_capacity_volumes"], dtype=np.float32
        ),
        exit_capacity_volumes=np.asarray(
            values["target_exit_capacity_volumes"], dtype=np.float32
        ),
    )
    return V8AssemblyResult(
        inputs=inputs,
        targets=targets,
        audit=dict(assembly.payload.get("audit", {})),
        source_artifacts=tuple(assembly.payload.get("source_artifacts", [])),
    )


def _guard_loaded_no_2026(result: V8AssemblyResult) -> None:
    """Zapreshchaet 2026 tol'ko v causal input calendar, ne chitaia OOS target timing."""
    protected = np.datetime64(V8_PROTECTED_HOLDOUT_START, "ns")
    timing = {
        "bar_times": result.inputs.bar_times,
        "sample_trade_dates": result.inputs.sample_trade_dates,
        "decision_times": result.inputs.decision_times,
    }
    for label, values in timing.items():
        timestamps = _load_time(values)
        factual = timestamps[~np.isnat(timestamps)]
        if len(factual) and (factual >= protected).any():
            raise ValueError(f"Protected 2026 timestamp obnaruzhen v {label}")


def _validate_loaded_arrays(
    result: V8AssemblyResult,
    config: V8ResearchConfig,
    assembly: VerifiedV8AssemblyManifest,
) -> None:
    """Sveryaet shapes/schema/calendar bez target-dependent OOS admission."""
    inputs = result.inputs
    targets = result.targets
    expected_intraday = (
        inputs.sample_count,
        len(V8_ASSETS),
        config.model.sequence_bars,
        len(config.model.bar_feature_names),
    )
    if inputs.intraday.shape != expected_intraday:
        raise ValueError(f"V8 intraday shape {inputs.intraday.shape} != {expected_intraday}")
    if inputs.intraday_valid.shape != inputs.intraday.shape[:3]:
        raise ValueError("V8 intraday_valid shape mismatch")
    expected_daily = (
        inputs.sample_count,
        len(V8_ASSETS),
        len(config.model.daily_feature_names),
    )
    if inputs.daily_context.shape != expected_daily or inputs.daily_valid.shape != expected_daily:
        raise ValueError("V8 daily shape mismatch")
    if inputs.asset_valid.shape != inputs.intraday.shape[:2]:
        raise ValueError("V8 asset_valid shape mismatch")
    if inputs.log_price.shape != inputs.intraday.shape[:3]:
        raise ValueError("V8 log_price shape mismatch")
    if inputs.bar_times.shape != (inputs.sample_count, config.model.sequence_bars):
        raise ValueError("V8 bar_times shape mismatch")
    if inputs.decision_times.shape != (inputs.sample_count,):
        raise ValueError("V8 decision_times shape mismatch")
    target_shape = inputs.asset_valid.shape
    target_arrays = (
        targets.raw_target,
        targets.normalized_target,
        targets.valid,
        targets.ex_ante_daily_volatility_20,
        targets.entry_window_open_times,
        targets.entry_window_close_times,
        targets.exit_window_open_times,
        targets.exit_window_close_times,
        targets.availability_times,
        targets.entry_contract_ids,
        targets.exit_contract_ids,
        targets.entry_capacity_open_times,
        targets.exit_capacity_open_times,
        targets.entry_capacity_volumes,
        targets.exit_capacity_volumes,
    )
    if any(np.asarray(values).shape != target_shape for values in target_arrays):
        raise ValueError("V8 target array shape mismatch")
    arrays_record = assembly.payload["arrays"]
    if int(arrays_record.get("sample_count", -1)) != inputs.sample_count:
        raise ValueError("V8 manifest sample_count mismatch")
    if list(arrays_record.get("intraday_shape", [])) != list(inputs.intraday.shape):
        raise ValueError("V8 manifest intraday_shape mismatch")
    if list(arrays_record.get("target_shape", [])) != list(target_shape):
        raise ValueError("V8 manifest target_shape mismatch")
    decisions = _load_time(inputs.decision_times)
    dates = _load_time(inputs.sample_trade_dates)
    if np.isnat(decisions).any() or np.isnat(dates).any():
        raise ValueError("V8 sample calendar ne dopuskaet NaT")
    if len(decisions) > 1 and (np.diff(decisions) <= np.timedelta64(0, "ns")).any():
        raise ValueError("V8 decisions dolzhny strogo vozrastat'")
    local = pd.DatetimeIndex(decisions).tz_localize("UTC").tz_convert(
        config.development.decision_timezone
    )
    if not np.all(local.strftime("%H:%M:%S") == config.development.decision_local_time):
        raise ValueError("V8 decision local time mismatch")
    local_dates = local.tz_localize(None).normalize().to_numpy(dtype="datetime64[ns]")
    if not np.array_equal(local_dates, dates):
        raise ValueError("V8 sample dates ne sovpadayut s decision timestamps")
    audit = assembly.payload.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("V8 assembly audit object otsutstvuet")
    if audit.get("legacy_v7_supervised_keys_read") != []:
        raise ValueError("V8 assembly audit pokazal legacy target read")
    target_audit = audit.get("target")
    if not isinstance(target_audit, dict) or int(
        target_audit.get("horizon_common_sessions", -1)
    ) != config.supervised_target.horizon_common_sessions:
        raise ValueError("V8 assembly target horizon audit mismatch")
    _guard_loaded_no_2026(result)
    for fold in config.development.folds:
        scope = build_v8_fold_scope(
            inputs,
            targets,
            train_start=fold.train_start,
            train_end=fold.train_end,
            purge_sessions=config.development.purge_sessions,
        )
        validate_v8_fold_scope(inputs, targets, scope)


def load_verified_v8_training_inputs(
    project_root: Path,
    config_path: Path,
    assembly_manifest_path: Path,
    *,
    expected_config_sha256: str = DEFAULT_V8_CONFIG_SHA256,
    expected_assembly_manifest_sha256: str,
    array_loader: Callable[[Path, VerifiedV8AssemblyManifest], V8AssemblyResult] | None = None,
) -> LoadedV8TrainingInputs:
    """Proveryaet vse byte seals i pre-I/O date guard do CUDA backend."""
    root = project_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    resolved_config = _bounded_path(root, config_path, "V8 config")
    config = load_v8_research_config(resolved_config, expected_config_sha256)
    assert_v8_pre_io_date_range(
        config.development.development_start,
        config.development.development_end,
    )
    assembly = verify_v8_assembly_manifest(
        root,
        assembly_manifest_path,
        expected_assembly_manifest_sha256,
    )
    result = (
        array_loader(assembly.arrays_path, assembly)
        if array_loader is not None
        else load_v8_assembly_arrays(assembly.arrays_path, assembly)
    )
    _validate_loaded_arrays(result, config, assembly)
    return LoadedV8TrainingInputs(
        project_root=root,
        config_path=resolved_config,
        config_sha256=byte_sha256(resolved_config),
        config=config,
        assembly=assembly,
        result=result,
    )


def build_v8_oos_sample_indices(
    sample_trade_dates: np.ndarray,
    decision_times: np.ndarray,
    fold: V8FoldConfig,
    timezone_name: str,
) -> np.ndarray:
    """Vyberaet OOS tol'ko po causal calendar, nikogda po target ili valid label."""
    dates = _load_time(sample_trade_dates)
    decisions = _load_time(decision_times)
    if dates.ndim != 1 or decisions.shape != dates.shape:
        raise ValueError("V8 OOS calendar shape mismatch")
    if np.isnat(dates).any() or np.isnat(decisions).any():
        raise ValueError("V8 OOS calendar ne dopuskaet NaT")
    local = pd.DatetimeIndex(decisions).tz_localize("UTC").tz_convert(timezone_name)
    local_dates = local.tz_localize(None).normalize().to_numpy(dtype="datetime64[ns]")
    if not np.array_equal(local_dates, dates):
        raise ValueError("V8 OOS dates/decision mismatch")
    start = np.datetime64(fold.score_start, "ns")
    end = np.datetime64(fold.score_end + pd.Timedelta(days=1), "ns")
    indices = np.flatnonzero((dates >= start) & (dates < end)).astype(np.int64)
    if not len(indices):
        raise ValueError(f"V8 fold {fold.name} ne imeet OOS decision samples")
    indices.flags.writeable = False
    return indices


def _robust_stats(values: np.ndarray) -> tuple[float, float, int]:
    """Schitaet median/IQR; constantnyi input poluchaet fail-safe scale 1."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.0, 1.0, 0
    lower, median, upper = np.quantile(finite, (0.25, 0.5, 0.75))
    scale = float(upper - lower)
    if not np.isfinite(scale) or scale <= np.finfo(np.float32).eps:
        scale = 1.0
    return float(median), scale, int(len(finite))


def fit_v8_fold_statistics(
    result: V8AssemblyResult,
    scope: V8FoldScope,
    config: V8ResearchConfig,
) -> V8FoldStatistics:
    """Fitit scaler i target IQR tol'ko na selected purged train indices."""
    validate_v8_fold_scope(result.inputs, result.targets, scope)
    indices = np.asarray(scope.sample_indices, dtype=np.int64)
    intraday = result.inputs.intraday[indices]
    asset_valid = result.inputs.asset_valid[indices]
    target_valid_asset = np.asarray(result.targets.valid, dtype=bool)[indices]
    scaler_asset_valid = asset_valid & target_valid_asset
    bar_times = _load_time(result.inputs.bar_times[indices])
    temporal = bar_times < scope.effective_cutoff
    bar_valid = result.inputs.intraday_valid[indices] & scaler_asset_valid[..., None]
    bar_valid &= temporal[:, None, :]
    intraday_stats = [
        _robust_stats(intraday[..., feature][bar_valid])
        for feature in range(intraday.shape[-1])
    ]
    daily = result.inputs.daily_context[indices]
    daily_valid = result.inputs.daily_valid[indices] & scaler_asset_valid[..., None]
    daily_stats = [
        _robust_stats(daily[..., feature][daily_valid[..., feature]])
        for feature in range(daily.shape[-1])
    ]
    targets = np.asarray(result.targets.normalized_target, dtype=np.float64)[indices]
    target_valid = (
        np.asarray(result.targets.valid, dtype=bool)[indices]
        & asset_valid
        & np.isfinite(targets)
    )
    target_values = targets[target_valid]
    if not len(target_values):
        raise ValueError("V8 fold ne imeet valid train target")
    lower, upper = np.quantile(target_values, (0.25, 0.75))
    target_iqr = float(upper - lower)
    if not np.isfinite(target_iqr) or target_iqr <= np.finfo(np.float32).eps:
        raise ValueError("V8 train target IQR ne polozhitelen")
    return V8FoldStatistics(
        intraday_median=tuple(item[0] for item in intraday_stats),
        intraday_iqr=tuple(item[1] for item in intraday_stats),
        intraday_observations=tuple(item[2] for item in intraday_stats),
        daily_median=tuple(item[0] for item in daily_stats),
        daily_iqr=tuple(item[1] for item in daily_stats),
        daily_observations=tuple(item[2] for item in daily_stats),
        train_target_iqr=target_iqr,
        train_target_observations=int(len(target_values)),
        sample_indices_sha256=_array_sha256(indices),
        effective_cutoff=str(np.datetime64(scope.effective_cutoff, "ns")),
    )


def build_v8_fold_training_view(
    result: V8AssemblyResult,
    scope: V8FoldScope,
) -> V8FoldTrainingView:
    """Materializuet tol'ko purged train rows i strict fold-local SSL mask."""
    validate_v8_fold_scope(result.inputs, result.targets, scope)
    indices = np.asarray(scope.sample_indices, dtype=np.int64)
    if (indices + 1 >= result.inputs.sample_count).any():
        raise ValueError("V8 train row ne imeet entry effective common session i+1")
    selected_bars = _load_time(result.inputs.bar_times[indices])
    if (selected_bars >= scope.effective_cutoff).any():
        raise ValueError("V8 training input bar dostig effective cutoff")
    ssl_mask = build_v8_ssl_valid_mask(result.inputs, scope, horizons=V8_SSL_HORIZONS)[indices]
    if ssl_mask.any():
        bars = _load_time(result.inputs.bar_times[indices])
        for horizon_index, horizon in enumerate(V8_SSL_HORIZONS):
            usable = bars.shape[1] - horizon
            if usable <= 0:
                continue
            valid = ssl_mask[:, :, :usable, horizon_index]
            origins = np.broadcast_to(bars[:, None, :usable], valid.shape)
            ends = np.broadcast_to(bars[:, None, horizon:], valid.shape)
            if (origins[valid] >= scope.effective_cutoff).any() or (
                ends[valid] >= scope.effective_cutoff
            ).any():
                raise ValueError("V8 fold-local SSL boundary leak")
    return V8FoldTrainingView(
        intraday=result.inputs.intraday[indices],
        intraday_valid=result.inputs.intraday_valid[indices],
        daily_context=result.inputs.daily_context[indices],
        daily_valid=result.inputs.daily_valid[indices],
        asset_valid=result.inputs.asset_valid[indices],
        log_price=result.inputs.log_price[indices],
        bar_times=result.inputs.bar_times[indices],
        decision_times=result.inputs.decision_times[indices],
        sample_trade_dates=result.inputs.sample_trade_dates[indices],
        normalized_target=result.targets.normalized_target[indices],
        target_valid=result.targets.valid[indices],
        target_availability_times=result.targets.availability_times[indices],
        ex_ante_daily_volatility_20=result.targets.ex_ante_daily_volatility_20[indices],
        entry_effective_dates=result.inputs.sample_trade_dates[indices + 1],
        entry_contract_ids=result.targets.entry_contract_ids[indices],
        entry_capacity_open_times=result.targets.entry_capacity_open_times[indices],
        exit_capacity_open_times=result.targets.exit_capacity_open_times[indices],
        entry_capacity_volumes=result.targets.entry_capacity_volumes[indices],
        exit_capacity_volumes=result.targets.exit_capacity_volumes[indices],
        ssl_valid_mask=ssl_mask,
        global_sample_indices=indices,
        effective_cutoff=np.datetime64(scope.effective_cutoff, "ns"),
    )


def build_v8_inference_view(
    result: V8AssemblyResult,
    sample_indices: np.ndarray,
) -> V8InferenceView:
    """Kopiruet tol'ko causal arrays OOS folda bez ssylki na target container."""
    indices = np.asarray(sample_indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices) or len(np.unique(indices)) != len(indices):
        raise ValueError("V8 inference indices invalid")
    factual_asset = result.inputs.intraday_valid[indices].any(axis=-1)
    effective_asset = result.inputs.asset_valid[indices] & factual_asset
    return V8InferenceView(
        intraday=result.inputs.intraday[indices].copy(),
        intraday_valid=result.inputs.intraday_valid[indices].copy(),
        daily_context=result.inputs.daily_context[indices].copy(),
        daily_valid=result.inputs.daily_valid[indices].copy(),
        asset_valid=effective_asset.copy(),
        bar_times=result.inputs.bar_times[indices].copy(),
        decision_times=result.inputs.decision_times[indices].copy(),
        sample_trade_dates=result.inputs.sample_trade_dates[indices].copy(),
        global_sample_indices=indices.copy(),
    )


def verify_authoritative_v8_spec_proxy(
    project_root: Path,
    manifest_path: Path,
    expected_manifest_sha256: str,
) -> VerifiedV8SpecProxy:
    """Proveryaet external manifest/parquet SHA i development-only spec dates."""
    root = project_root.resolve()
    data_root = (root / "data").resolve()
    manifest = _bounded_path(root, manifest_path, "V8 cost spec manifest")
    try:
        manifest.relative_to(data_root)
    except ValueError as error:
        raise ValueError("V8 cost spec manifest dolzhen byt' v data root") from error
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    if not _is_sha256(expected_manifest_sha256) or _file_sha256(
        manifest
    ) != expected_manifest_sha256.lower():
        raise ValueError("V8 cost spec manifest byte seal mismatch")
    payload = _read_json_object(manifest)
    expected_version = "futures-conservative-spec-proxy-v1"
    if (
        int(payload.get("schema_version", -1)) != 1
        or payload.get("spec_proxy_version") != expected_version
        or payload.get("requested_end") != "2025-12-31"
        or payload.get("protected_from") != "2026-01-01"
    ):
        raise ValueError("V8 authoritative spec manifest semantic seal mismatch")
    output = payload.get("output")
    parquet_record = output.get("parquet") if isinstance(output, dict) else None
    if not isinstance(parquet_record, dict):
        raise ValueError("V8 authoritative spec parquet record otsutstvuet")
    parquet_path = _bounded_data_path(
        data_root,
        parquet_record.get("path"),
        "V8 authoritative spec parquet",
    )
    if not parquet_path.is_file() or parquet_path.stat().st_size != int(
        parquet_record.get("bytes", -1)
    ):
        raise ValueError("V8 authoritative spec parquet bytes mismatch")
    parquet_sha = _file_sha256(parquet_path)
    if not _is_sha256(parquet_record.get("sha256")) or parquet_sha != str(
        parquet_record["sha256"]
    ).lower():
        raise ValueError("V8 authoritative spec parquet SHA mismatch")
    required_columns = (
        "session_date",
        "contract_id",
        "asset_symbol",
        "sizing_observed_session_date",
        "sizing_notional",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "sizing_usable",
        "spec_proxy_version",
        "research_only",
    )
    frame = pd.read_parquet(parquet_path, columns=list(required_columns))
    if len(frame) != int(parquet_record.get("rows", -1)):
        raise ValueError("V8 authoritative spec parquet row count mismatch")
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise").dt.normalize()
    frame["sizing_observed_session_date"] = pd.to_datetime(
        frame["sizing_observed_session_date"], errors="coerce"
    ).dt.normalize()
    if frame["session_date"].ge(pd.Timestamp("2026-01-01")).any():
        raise ValueError("V8 authoritative spec soderzhit protected 2026 session")
    observed = frame["sizing_observed_session_date"].dropna()
    if observed.ge(pd.Timestamp("2026-01-01")).any():
        raise ValueError("V8 authoritative spec observed date pronikla v 2026")
    if frame["spec_proxy_version"].ne(expected_version).any() or not frame[
        "research_only"
    ].fillna(False).all():
        raise ValueError("V8 authoritative spec version/research flag mismatch")
    key = ["session_date", "contract_id", "asset_symbol"]
    if frame.duplicated(key).any():
        raise ValueError("V8 authoritative spec imeet duplicate join key")
    identity = {
        "provider": "authoritative_spec_proxy_v1",
        "manifest_path": manifest.relative_to(root).as_posix(),
        "manifest_sha256": _file_sha256(manifest),
        "parquet_path": parquet_path.relative_to(root).as_posix(),
        "parquet_sha256": parquet_sha,
        "rows": len(frame),
        "spec_proxy_version": expected_version,
    }
    return VerifiedV8SpecProxy(
        manifest_path=manifest,
        manifest_sha256=identity["manifest_sha256"],
        parquet_path=parquet_path,
        parquet_sha256=parquet_sha,
        frame=frame,
        identity=identity,
    )


def build_authoritative_v8_cost_scale(
    view: V8FoldTrainingView,
    statistics: V8FoldStatistics,
    spec_proxy: VerifiedV8SpecProxy,
) -> V8CostScale:
    """Stroit exact D-known one-way fee+one-tick cost v target-IQR units."""
    target_cells = np.asarray(view.target_valid, dtype=bool) & np.asarray(
        view.asset_valid, dtype=bool
    )
    residual_required = target_cells & (target_cells.sum(axis=1, keepdims=True) >= 2)
    values = np.zeros(target_cells.shape, dtype=np.float32)
    valid = np.zeros(target_cells.shape, dtype=bool)
    lookup = spec_proxy.frame.set_index(["session_date", "contract_id", "asset_symbol"])
    entry_dates = pd.to_datetime(view.entry_effective_dates).normalize()
    decision_dates = pd.to_datetime(view.sample_trade_dates).normalize()
    if len(entry_dates) != target_cells.shape[0] or len(decision_dates) != len(entry_dates):
        raise ValueError("V8 cost date arrays shape mismatch")
    if statistics.train_target_iqr <= 0.0 or not np.isfinite(statistics.train_target_iqr):
        raise ValueError("V8 cost provider trebuet finite positive train target IQR")
    for sample_index, asset_index in zip(*np.nonzero(residual_required), strict=True):
        asset = V8_ASSETS[asset_index]
        contract = str(view.entry_contract_ids[sample_index, asset_index])
        key = (entry_dates[sample_index], contract, asset)
        if key not in lookup.index:
            raise ValueError(f"V8 authoritative cost spec join missing: {key}")
        row = lookup.loc[key]
        if isinstance(row, pd.DataFrame):
            raise ValueError(f"V8 authoritative cost spec join duplicate: {key}")
        observed = pd.Timestamp(row["sizing_observed_session_date"]).normalize()
        if pd.isna(observed) or observed != decision_dates[sample_index]:
            raise ValueError("V8 cost sizing_observed_session_date ne raven decision D")
        numbers = np.asarray(
            [
                row["sizing_notional"],
                row["sizing_tick_cash_value"],
                row["conservative_fee_per_side"],
            ],
            dtype=np.float64,
        )
        volatility = float(view.ex_ante_daily_volatility_20[sample_index, asset_index])
        if (
            not bool(row["sizing_usable"])
            or not np.isfinite(numbers).all()
            or (numbers <= 0.0).any()
            or not np.isfinite(volatility)
            or volatility < 0.0
        ):
            raise ValueError("V8 authoritative cost input unknown ili nonpositive")
        one_way_rate = (numbers[2] + numbers[1]) / numbers[0]
        denominator = (
            max(volatility, 0.01)
            * np.sqrt(5.0)
            * statistics.train_target_iqr
        )
        cost = one_way_rate / denominator
        if not np.isfinite(cost) or cost <= 0.0:
            raise ValueError("V8 authoritative cost result ne finite/positive")
        values[sample_index, asset_index] = np.float32(cost)
        valid[sample_index, asset_index] = True
    source_identity = {
        **spec_proxy.identity,
        "formula": (
            "((conservative_fee_per_side+1*sizing_tick_cash_value)/sizing_notional)"
            "/(max(d_known_daily_volatility_20,0.01)*sqrt(5)*train_target_iqr)"
        ),
        "join": "entry_effective_date_same_contract_asset_spec_proxy_row",
        "asof_rule": "sizing_observed_session_date_equals_decision_d",
        "fee_side_multiplier": 1,
        "slippage_ticks": 1,
    }
    return V8CostScale(
        values_in_target_iqr=values,
        valid=valid,
        method="authoritative_spec_proxy_v1_d_known_one_way_fee_plus_one_tick",
        source_identity=source_identity,
    )


def _validate_cost_scale(cost: V8CostScale, view: V8FoldTrainingView) -> dict[str, Any]:
    """Trebuet explicit known positive cost dlia kazhdoi supervised train cell."""
    values = np.asarray(cost.values_in_target_iqr, dtype=np.float64)
    valid = np.asarray(cost.valid, dtype=bool)
    expected = view.target_valid.shape
    if values.shape != expected or valid.shape != expected:
        raise ValueError("V8 cost scale shape mismatch")
    target_cells = view.target_valid & view.asset_valid
    required = target_cells & (target_cells.sum(axis=1, keepdims=True) >= 2)
    if not valid[required].all():
        raise ValueError("V8 cost provider ne dokazal cost dlia valid train target")
    if not np.isfinite(values[required]).all() or (values[required] <= 0.0).any():
        raise ValueError("V8 train one-way cost dolzhen byt' known, finite i positive")
    if not cost.method.strip() or not isinstance(cost.source_identity, dict):
        raise ValueError("V8 cost provider identity nepolon")
    return {
        "method": cost.method,
        "values_sha256": _array_sha256(values),
        "valid_sha256": _array_sha256(valid),
        "source_identity": cost.source_identity,
        "source_identity_sha256": _canonical_json_sha256(cost.source_identity),
    }


def _validate_history(
    history: Sequence[dict[str, Any]],
    expected_epochs: int,
    stage: str,
) -> tuple[dict[str, Any], ...]:
    """Trebuet exact fixed epoch history bez early stopping ili propuska."""
    normalized = tuple(dict(item) for item in history)
    if len(normalized) != expected_epochs:
        raise ValueError(f"V8 {stage} history dolzhna imet' {expected_epochs} epochs")
    epochs = [int(item.get("epoch", -1)) for item in normalized]
    if epochs != list(range(1, expected_epochs + 1)):
        raise ValueError(f"V8 {stage} epoch sequence mismatch")
    for item in normalized:
        if "loss" not in item or not np.isfinite(float(item["loss"])):
            raise ValueError(f"V8 {stage} history trebuet finite loss")
    return normalized


def _validate_seed_prediction(
    prediction: V8SeedPrediction,
    inference: V8InferenceView,
) -> None:
    """Proveryaet factor/residual shapes i uncertainty bez target masks."""
    samples = len(inference.decision_times)
    asset_shape = (samples, len(V8_ASSETS))
    factor_shape = (samples,)
    factor_fields = (
        np.asarray(prediction.factor_location),
        np.asarray(prediction.factor_scale),
        np.asarray(prediction.factor_score),
    )
    residual_fields = (
        np.asarray(prediction.residual_location),
        np.asarray(prediction.residual_scale),
        np.asarray(prediction.residual_decision_score),
        np.asarray(prediction.direction_logit),
    )
    if any(values.shape != factor_shape for values in factor_fields):
        raise ValueError("V8 factor prediction shape mismatch")
    if any(values.shape != asset_shape for values in residual_fields):
        raise ValueError("V8 residual prediction shape mismatch")
    sample_valid = inference.asset_valid.any(axis=1)
    if any(not np.isfinite(values[sample_valid]).all() for values in factor_fields):
        raise ValueError("V8 valid factor prediction ne finite")
    if (np.asarray(prediction.factor_scale)[sample_valid] <= 0.0).any():
        raise ValueError("V8 factor scale dolzhen byt' positive")
    valid = inference.asset_valid
    if any(not np.isfinite(values[valid]).all() for values in residual_fields):
        raise ValueError("V8 valid residual prediction ne finite")
    if (np.asarray(prediction.residual_scale)[valid] <= 0.0).any():
        raise ValueError("V8 residual scale dolzhen byt' positive")


def ensemble_v8_seed_predictions(
    predictions: Sequence[V8SeedPrediction],
    inference: V8InferenceView,
) -> V8SeedPrediction:
    """Usrednyaet tri seed i moment-matchit location/scale bez seed selection."""
    if len(predictions) != len(V8_SEEDS):
        raise ValueError("V8 ensemble trebuet rovno tri seed predictions")
    for prediction in predictions:
        _validate_seed_prediction(prediction, inference)
    factor_locations = np.stack([item.factor_location for item in predictions]).astype(np.float64)
    factor_scales = np.stack([item.factor_scale for item in predictions]).astype(np.float64)
    factor_location = factor_locations.mean(axis=0)
    factor_variance = np.mean(factor_scales**2 + factor_locations**2, axis=0) - factor_location**2
    residual_locations = np.stack([item.residual_location for item in predictions]).astype(
        np.float64
    )
    residual_scales = np.stack([item.residual_scale for item in predictions]).astype(np.float64)
    residual_location = residual_locations.mean(axis=0)
    residual_variance = np.mean(
        residual_scales**2 + residual_locations**2,
        axis=0,
    ) - residual_location**2
    return V8SeedPrediction(
        factor_location=factor_location,
        factor_scale=np.sqrt(np.maximum(factor_variance, np.finfo(np.float64).eps)),
        factor_score=np.mean([item.factor_score for item in predictions], axis=0),
        residual_location=residual_location,
        residual_scale=np.sqrt(np.maximum(residual_variance, np.finfo(np.float64).eps)),
        residual_decision_score=np.mean(
            [item.residual_decision_score for item in predictions], axis=0
        ),
        direction_logit=np.mean([item.direction_logit for item in predictions], axis=0),
    )


def build_v8_oos_prediction_frame(
    inference: V8InferenceView,
    prediction: V8SeedPrediction,
    model_id: str,
) -> pd.DataFrame:
    """Stroit long target-free predictions s exact D18:50/19:00/19:20 timing."""
    _validate_seed_prediction(prediction, inference)
    decisions = pd.DatetimeIndex(_load_time(inference.decision_times)).tz_localize("UTC")
    local = decisions.tz_convert("Europe/Moscow")
    if not np.all(local.strftime("%H:%M:%S") == "18:50:00"):
        raise ValueError("V8 prediction decision timing drift")
    local_day = local.normalize()
    capacity_open = local_day + pd.Timedelta(hours=19)
    capacity_close = capacity_open + pd.Timedelta(minutes=10)
    execution_open = local_day + pd.Timedelta(hours=19, minutes=20)
    execution_close = execution_open + pd.Timedelta(minutes=10)
    assets = len(V8_ASSETS)
    valid = inference.asset_valid
    factor_location = np.repeat(prediction.factor_location, assets)
    factor_scale = np.repeat(prediction.factor_scale, assets)
    factor_score = np.repeat(prediction.factor_score, assets)
    sample_valid = inference.asset_valid.any(axis=1)
    repeated_sample_valid = np.repeat(sample_valid, assets)
    frame = pd.DataFrame(
        {
            "decision_date": np.repeat(
                np.asarray(inference.sample_trade_dates).astype("datetime64[D]"), assets
            ),
            "decision_at": np.repeat(decisions.to_numpy(), assets),
            "capacity_window_open_at": np.repeat(
                capacity_open.tz_convert("UTC").to_numpy(), assets
            ),
            "capacity_window_close_at": np.repeat(
                capacity_close.tz_convert("UTC").to_numpy(), assets
            ),
            "execution_window_open_at": np.repeat(
                execution_open.tz_convert("UTC").to_numpy(), assets
            ),
            "execution_window_close_at": np.repeat(
                execution_close.tz_convert("UTC").to_numpy(), assets
            ),
            "asset": np.tile(np.asarray(V8_ASSETS, dtype=object), len(decisions)),
            "asset_valid": valid.reshape(-1),
            "factor_location": np.where(repeated_sample_valid, factor_location, np.nan),
            "factor_scale": np.where(repeated_sample_valid, factor_scale, np.nan),
            "factor_score": np.where(repeated_sample_valid, factor_score, np.nan),
            "residual_location": np.where(
                valid, prediction.residual_location, np.nan
            ).reshape(-1),
            "residual_scale": np.where(valid, prediction.residual_scale, np.nan).reshape(-1),
            "residual_decision_score": np.where(
                valid, prediction.residual_decision_score, np.nan
            ).reshape(-1),
            "direction_logit": np.where(valid, prediction.direction_logit, np.nan).reshape(-1),
            "model_id": model_id,
        },
        columns=list(V8_PREDICTION_COLUMNS),
    )
    return frame


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno pishet Parquet s fsync pered replace."""
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
    inputs: LoadedV8TrainingInputs,
    code_identity: dict[str, Any],
    cost_source_identity: dict[str, Any],
) -> dict[str, Any]:
    """Sobiraet immutable config/data/code identity do backend/CUDA."""
    architecture_payload = {
        "model": inputs.config.model.model_dump(mode="json"),
        "model_source_sha256": next(
            item["sha256"]
            for item in code_identity["files"]
            if item["path"].endswith("futures_v8/model.py")
        ),
        "training_source_sha256": next(
            item["sha256"]
            for item in code_identity["files"]
            if item["path"].endswith("futures_v8/training.py")
        ),
    }
    data_payload = {
        "manifest_sha256": inputs.assembly.manifest_sha256,
        "arrays_sha256": inputs.assembly.arrays_sha256,
        "sources": list(inputs.assembly.source_identities),
    }
    return {
        "config_sha256": inputs.config_sha256,
        "assembly_manifest_sha256": inputs.assembly.manifest_sha256,
        "assembly_arrays_sha256": inputs.assembly.arrays_sha256,
        "data_identity_sha256": _canonical_json_sha256(data_payload),
        "architecture_sha256": _canonical_json_sha256(architecture_payload),
        "code_identity_sha256": code_identity["code_identity_sha256"],
        "code_identity": code_identity,
        "cost_source_identity": cost_source_identity,
        "cost_source_identity_sha256": _canonical_json_sha256(cost_source_identity),
    }


def _validate_existing_identity(path: Path, identity: dict[str, Any]) -> None:
    """Ne daet resume smeshat' output ot drugogo seal ili code closure."""
    if not path.exists():
        return
    payload = _read_json_object(path)
    if payload.get("identity") != identity:
        raise ValueError(f"V8 existing artifact identity mismatch: {path}")


def _assert_code_unchanged(root: Path, expected: dict[str, Any]) -> None:
    """Otkazyvaet checkpoint commit pri drift runtime source vo vremya train."""
    current = build_v8_code_identity(root)
    if current != expected:
        raise ValueError("V8 runtime code closure drift posle run identity commit")


def _checkpoint_paths(directory: Path, fold_name: str, seed: int) -> tuple[Path, Path]:
    """Vozvrashchaet completed checkpoint i sidecar commit-marker."""
    checkpoint = directory / fold_name / f"seed-{seed}.pt"
    return checkpoint, checkpoint.with_suffix(".pt.manifest.json")


def _checkpoint_core(
    identity: dict[str, Any],
    backend_runtime_identity: dict[str, Any],
    request: V8SeedTrainingRequest,
    statistics_sha: str,
    cost_identity: dict[str, Any],
    outcome: V8SeedTrainingOutcome,
) -> dict[str, Any]:
    """Stroit completed-only sidecar core bez PnL i OOS metric."""
    return {
        "format": V8_CHECKPOINT_FORMAT,
        "research_status": "completed_seed_training_no_pnl",
        "identity": identity,
        "backend_runtime_identity": backend_runtime_identity,
        "fold_name": request.fold_name,
        "seed": request.seed,
        "ssl": {
            "fresh_initialization": outcome.fresh_ssl_initialization,
            "epochs": request.ssl_epochs,
            "history": list(outcome.ssl_history),
            "all_inputs_and_horizon_ends_strictly_before_cutoff": True,
        },
        "supervised": {
            "encoder_frozen_before_stage": outcome.encoder_frozen_before_supervised,
            "epochs": request.supervised_epochs,
            "history": list(outcome.supervised_history),
        },
        "precision": request.precision,
        "deterministic_algorithms": request.deterministic_algorithms,
        "optimizer": {
            "name": "adamw",
            "ssl_learning_rate": request.ssl_learning_rate,
            "supervised_learning_rate": request.supervised_learning_rate,
            "weight_decay": request.weight_decay,
            "gradient_clip_norm": request.gradient_clip_norm,
        },
        "statistics_sha256": statistics_sha,
        "cost_scale": cost_identity,
        "resume_semantics": V8_RESUME_SEMANTICS,
        "completed": True,
    }


def _write_completed_checkpoint_bundle(
    checkpoint_path: Path,
    sidecar_path: Path,
    checkpoint_bytes: bytes,
    core: dict[str, Any],
) -> dict[str, Any]:
    """Atomarno pishet checkpoint, zatem sidecar kak poslednii commit-marker."""
    if not checkpoint_bytes:
        raise ValueError("V8 completed checkpoint bytes pusty")
    checkpoint_sha = _bytes_sha256(checkpoint_bytes)
    outer = {
        "format": V8_CHECKPOINT_FORMAT,
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": checkpoint_sha,
        "manifest": core,
        "manifest_sha256": _canonical_json_sha256(core),
    }
    atomic_write_bytes(checkpoint_path, checkpoint_bytes)
    write_json(sidecar_path, outer)
    return outer


def _load_completed_checkpoint_bundle(
    checkpoint_path: Path,
    sidecar_path: Path,
    identity: dict[str, Any],
    backend_runtime_identity: dict[str, Any],
    request: V8SeedTrainingRequest,
    statistics_sha: str,
    cost_identity: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    """Resume-it tol'ko polnyi completed seed bundle s exact identity."""
    if not checkpoint_path.is_file() or not sidecar_path.is_file():
        raise ValueError("V8 resume zapreshchaet orphan ili midstage checkpoint")
    outer = _read_json_object(sidecar_path)
    if outer.get("format") != V8_CHECKPOINT_FORMAT:
        raise ValueError("V8 checkpoint sidecar format mismatch")
    content = checkpoint_path.read_bytes()
    if outer.get("checkpoint_file") != checkpoint_path.name or outer.get(
        "checkpoint_sha256"
    ) != _bytes_sha256(content):
        raise ValueError("V8 checkpoint byte SHA mismatch")
    core = outer.get("manifest")
    if not isinstance(core, dict) or outer.get("manifest_sha256") != _canonical_json_sha256(core):
        raise ValueError("V8 checkpoint internal manifest mismatch")
    expected = {
        "identity": identity,
        "backend_runtime_identity": backend_runtime_identity,
        "fold_name": request.fold_name,
        "seed": request.seed,
        "precision": request.precision,
        "deterministic_algorithms": request.deterministic_algorithms,
        "statistics_sha256": statistics_sha,
        "cost_scale": cost_identity,
        "resume_semantics": V8_RESUME_SEMANTICS,
        "completed": True,
    }
    for key, value in expected.items():
        if core.get(key) != value:
            raise ValueError(f"V8 checkpoint resume identity mismatch: {key}")
    ssl = core.get("ssl")
    supervised = core.get("supervised")
    if not isinstance(ssl, dict) or not isinstance(supervised, dict):
        raise ValueError("V8 checkpoint stage manifests otsutstvuyut")
    if (
        ssl.get("fresh_initialization") is not True
        or int(ssl.get("epochs", -1)) != V8_SSL_EPOCHS
        or supervised.get("encoder_frozen_before_stage") is not True
        or int(supervised.get("epochs", -1)) != V8_SUPERVISED_EPOCHS
    ):
        raise ValueError("V8 checkpoint stage seal mismatch")
    expected_optimizer = {
        "name": "adamw",
        "ssl_learning_rate": request.ssl_learning_rate,
        "supervised_learning_rate": request.supervised_learning_rate,
        "weight_decay": request.weight_decay,
        "gradient_clip_norm": request.gradient_clip_norm,
    }
    if core.get("optimizer") != expected_optimizer:
        raise ValueError("V8 checkpoint optimizer seal mismatch")
    _validate_history(tuple(ssl.get("history", ())), V8_SSL_EPOCHS, "SSL resume")
    _validate_history(
        tuple(supervised.get("history", ())),
        V8_SUPERVISED_EPOCHS,
        "supervised resume",
    )
    return content, outer


def _checkpoint_identity(
    root: Path,
    checkpoint_path: Path,
    sidecar_path: Path,
    outer: dict[str, Any],
    resumed: bool,
) -> dict[str, Any]:
    """Fiksiruet proverennyi transport identity odnogo completed seed."""
    core = outer["manifest"]
    return {
        "fold_name": core["fold_name"],
        "seed": int(core["seed"]),
        "resumed": resumed,
        "checkpoint_path": checkpoint_path.relative_to(root).as_posix(),
        "checkpoint_bytes": checkpoint_path.stat().st_size,
        "checkpoint_sha256": outer["checkpoint_sha256"],
        "sidecar_path": sidecar_path.relative_to(root).as_posix(),
        "sidecar_bytes": sidecar_path.stat().st_size,
        "sidecar_sha256": _file_sha256(sidecar_path),
        "manifest_sha256": outer["manifest_sha256"],
    }


def _write_progress(
    path: Path,
    identity: dict[str, Any],
    checkpoints: Sequence[dict[str, Any]],
) -> None:
    """Atomarno fiksiruet tol'ko polnost'yu completed seed keys."""
    write_json(
        path,
        {
            "format": V8_PROGRESS_FORMAT,
            "research_status": "training_in_progress_no_pnl",
            "identity": identity,
            "completed_seed_keys": [
                f"{item['fold_name']}:{item['seed']}" for item in checkpoints
            ],
            "completed_seed_checkpoint_count": len(checkpoints),
            "resume_semantics": V8_RESUME_SEMANTICS,
        },
    )


def _scaled_feature_array(
    values: np.ndarray,
    valid: np.ndarray,
    median: Sequence[float],
    iqr: Sequence[float],
    label: str,
) -> np.ndarray:
    """Primeniayet tol'ko fold-train median/IQR i zanuliaet masked observations."""
    source = np.asarray(values, dtype=np.float32)
    mask = np.asarray(valid, dtype=bool)
    if source.ndim == mask.ndim + 1:
        mask = np.broadcast_to(mask[..., None], source.shape)
    if mask.shape != source.shape:
        raise ValueError(f"V8 {label} scaler mask shape mismatch")
    center = np.asarray(median, dtype=np.float32)
    scale = np.asarray(iqr, dtype=np.float32)
    if center.shape != source.shape[-1:] or scale.shape != center.shape:
        raise ValueError(f"V8 {label} scaler statistics shape mismatch")
    if not np.isfinite(center).all() or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError(f"V8 {label} scaler statistics invalid")
    if not np.isfinite(source[mask]).all():
        raise ValueError(f"V8 {label} factual input ne finite")
    normalized = (source - center) / scale
    return np.where(mask, normalized, np.float32(0.0)).astype(np.float32, copy=False)


def _build_ssl_patch_supervision(
    view: V8FoldTrainingView,
    patch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Stroit patch-end SSL labels iz log-price tol'ko po fold-local valid mask."""
    log_price = np.asarray(view.log_price, dtype=np.float64)
    ssl_valid = np.asarray(view.ssl_valid_mask, dtype=bool)
    intraday_valid = np.asarray(view.intraday_valid, dtype=bool)
    bar_times = _load_time(view.bar_times)
    if log_price.ndim != 3 or intraday_valid.shape != log_price.shape:
        raise ValueError("V8 SSL log-price/intraday mask shape mismatch")
    samples, assets, bars = log_price.shape
    expected_ssl_shape = (samples, assets, bars, len(V8_SSL_HORIZONS))
    if ssl_valid.shape != expected_ssl_shape or bar_times.shape != (samples, bars):
        raise ValueError("V8 SSL mask/time shape mismatch")
    if bars % patch_size or patch_size <= 0:
        raise ValueError("V8 SSL patch size ne delimit bar count")
    origins = np.arange(patch_size - 1, bars, patch_size, dtype=np.int64)
    patch_count = len(origins)
    targets = np.zeros(
        (samples, assets, patch_count, len(V8_SSL_HORIZONS), 2),
        dtype=np.float32,
    )
    target_mask = ssl_valid[:, :, origins, :].copy()
    horizon_end = np.full(
        (samples, assets, patch_count, len(V8_SSL_HORIZONS)),
        np.datetime64("NaT", "ns"),
        dtype="datetime64[ns]",
    )
    one_bar = np.diff(log_price, axis=2)
    squared = np.where(np.isfinite(one_bar), np.square(one_bar), 0.0)
    prefix = np.concatenate(
        (np.zeros((samples, assets, 1), dtype=np.float64), np.cumsum(squared, axis=2)),
        axis=2,
    )
    for horizon_index, horizon in enumerate(V8_SSL_HORIZONS):
        eligible = origins + horizon < bars
        selected_origins = origins[eligible]
        selected_ends = selected_origins + horizon
        if not len(selected_origins):
            target_mask[..., horizon_index] = False
            continue
        returns = log_price[:, :, selected_ends] - log_price[:, :, selected_origins]
        realized = np.sqrt(
            np.maximum(
                prefix[:, :, selected_ends] - prefix[:, :, selected_origins],
                0.0,
            )
        )
        targets[:, :, eligible, horizon_index, 0] = returns.astype(np.float32)
        targets[:, :, eligible, horizon_index, 1] = realized.astype(np.float32)
        end_times = bar_times[:, selected_ends]
        horizon_end[:, :, eligible, horizon_index] = np.broadcast_to(
            end_times[:, None, :],
            (samples, assets, len(selected_origins)),
        )
        target_mask[:, :, ~eligible, horizon_index] = False
    patch_valid = intraday_valid.reshape(
        samples,
        assets,
        patch_count,
        patch_size,
    ).any(axis=-1)
    input_end = np.broadcast_to(
        bar_times[:, None, origins],
        (samples, assets, patch_count),
    ).copy()
    input_end[~patch_valid] = np.datetime64("NaT", "ns")
    finite_targets = np.isfinite(targets).all(axis=-1)
    target_mask &= finite_targets
    targets[~target_mask] = 0.0
    return targets, target_mask, input_end, horizon_end


@dataclass(frozen=True, slots=True)
class _V8TorchSeedState:
    """Hranit odin completed model na device dlia target-free predict."""

    model: Any
    fold_name: str
    seed: int


class _V8TorchBackend:
    """Real deterministic single-RTX5090 backend dlia SSL48 plus supervised32."""

    def __init__(
        self,
        config: V8ResearchConfig,
        *,
        device: str,
        ssl_batch_size: int,
        supervised_batch_size: int,
        inference_batch_size: int,
        test_only_allow_epoch_override: bool,
        test_only_allow_non_5090: bool,
    ) -> None:
        """Importiruet torch i inicializiruet CUDA tol'ko posle runner seals."""
        workspace = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
        if workspace not in (None, ":4096:8"):
            raise RuntimeError("CUBLAS_WORKSPACE_CONFIG dolzhen byt' :4096:8")
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        import torch

        from market_lab.futures_v8.model import (
            CausalPatchStateSpaceRegimeAlphaModel,
            configure_v8_supervised_finetuning,
            model_architecture_manifest,
            set_v8_determinism,
        )
        from market_lab.futures_v8.training import (
            FiveSessionTargetBatch,
            FoldLocalSslBoundary,
            OrderedDecisionBatch,
            causal_patch_contrastive_loss,
            masked_dynamic_ssl_loss,
            v8_supervised_loss,
        )

        self.torch = torch
        self.model_class = CausalPatchStateSpaceRegimeAlphaModel
        self.configure_supervised = configure_v8_supervised_finetuning
        self.architecture_manifest = model_architecture_manifest
        self.set_determinism = set_v8_determinism
        self.target_batch_class = FiveSessionTargetBatch
        self.ssl_boundary_class = FoldLocalSslBoundary
        self.ordered_batch_class = OrderedDecisionBatch
        self.contrastive_loss = causal_patch_contrastive_loss
        self.dynamic_ssl_loss = masked_dynamic_ssl_loss
        self.supervised_loss = v8_supervised_loss
        self.config = config
        self.device = torch.device(device)
        self.test_only_allow_epoch_override = test_only_allow_epoch_override
        self.test_only_allow_non_5090 = test_only_allow_non_5090
        batch_sizes = (ssl_batch_size, supervised_batch_size, inference_batch_size)
        if any(isinstance(value, bool) or value <= 0 for value in batch_sizes):
            raise ValueError("V8 torch batch sizes dolzhny byt' positive int")
        self.ssl_batch_size = int(ssl_batch_size)
        self.supervised_batch_size = int(supervised_batch_size)
        self.inference_batch_size = int(inference_batch_size)
        if self.device.type != "cuda" and not test_only_allow_non_5090:
            raise RuntimeError("V8 real backend trebuet CUDA RTX 5090")
        if self.device.type == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("V8 CUDA backend nedostupen")
            torch.cuda.set_device(self.device)
            device_name = torch.cuda.get_device_name(self.device)
            if "RTX 5090" not in device_name and not test_only_allow_non_5090:
                raise RuntimeError(f"V8 accelerator ne RTX 5090: {device_name}")
            if not torch.cuda.is_bf16_supported():
                raise RuntimeError("V8 RTX backend ne podderzhivaet bfloat16")
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = False
        else:
            device_name = "cpu-test-only"
        torch.use_deterministic_algorithms(True)
        if torch.backends.cudnn.is_available():
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        self.runtime_identity = {
            "backend_format": V8_TORCH_BACKEND_FORMAT,
            "backend": "pytorch_single_device_adamw",
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "torch_cuda": str(torch.version.cuda),
            "cudnn": int(torch.backends.cudnn.version() or 0),
            "device": str(self.device),
            "device_name": device_name,
            "precision": "bfloat16" if self.device.type == "cuda" else "float32_test_only",
            "deterministic_algorithms": True,
            "cublas_workspace_config": ":4096:8",
            "tf32": False,
            "ssl_batch_size": self.ssl_batch_size,
            "supervised_batch_size": self.supervised_batch_size,
            "inference_batch_size": self.inference_batch_size,
            "ssl_loss": "mean_two_view_dynamic_nll_plus_unit_weight_infonce",
            "supervised_order": "chronological_contiguous_with_detached_prior_carry",
            "test_only_epoch_override": self.test_only_allow_epoch_override,
        }

    def api(self) -> V8TrainingApi:
        """Vozvrashchaet callbacks, sovmestimye s target-isolated runnerom."""
        return V8TrainingApi(
            fit_cost_scale=self._cost_provider_must_be_external,
            train_completed_seed=self.train_completed_seed,
            restore_completed_seed=self.restore_completed_seed,
            predict_seed=self.predict_seed,
            runtime_identity=dict(self.runtime_identity),
            reset_peak_vram=self.reset_peak_vram,
            peak_vram=self.peak_vram,
            release_fold=self.release_fold,
        )

    @staticmethod
    def _cost_provider_must_be_external(
        view: V8FoldTrainingView,
        statistics: V8FoldStatistics,
    ) -> V8CostScale:
        """Zapreshchaet real train bez runner-verified authoritative spec proxy."""
        del view, statistics
        raise RuntimeError("V8 torch backend trebuet external authoritative cost provider")

    def _autocast(self) -> Any:
        """Vkluchaet sealed BF16 tol'ko na CUDA; CPU razreshen lish' testam."""
        return self.torch.autocast(
            device_type=self.device.type,
            dtype=self.torch.bfloat16,
            enabled=self.device.type == "cuda",
        )

    def _check_request(self, request: V8SeedTrainingRequest) -> None:
        """Proveryaet fixed optimizer/stages do model allocation."""
        expected = self.config.training
        if (
            request.precision != V8_PRECISION
            or not request.deterministic_algorithms
            or not request.fresh_ssl_initialization_required
            or not request.freeze_encoder_before_supervised_required
            or request.ssl_learning_rate != expected.ssl_learning_rate
            or request.supervised_learning_rate != expected.supervised_learning_rate
            or request.weight_decay != expected.weight_decay
            or request.gradient_clip_norm != expected.gradient_clip_norm
        ):
            raise ValueError("V8 torch request optimizer/stage seal mismatch")
        epochs = (request.ssl_epochs, request.supervised_epochs)
        if any(isinstance(value, bool) or value <= 0 for value in epochs):
            raise ValueError("V8 torch epochs dolzhny byt' positive int")
        if not self.test_only_allow_epoch_override and epochs != (
            V8_SSL_EPOCHS,
            V8_SUPERVISED_EPOCHS,
        ):
            raise ValueError("V8 real torch backend trebuet exact SSL48/supervised32")
        indices = np.asarray(request.training_view.global_sample_indices)
        if indices.ndim != 1 or not len(indices) or (
            len(indices) > 1 and not np.all(np.diff(indices.astype(np.int64)) == 1)
        ):
            raise ValueError("V8 supervised train trebuet contiguous ordered samples")

    def _new_model(self, seed: int) -> Any:
        """Sozdaet fresh seed model i proveriaet exact architecture parameter seal."""
        self.set_determinism(seed)
        model = self.model_class(self.config.model).to(self.device)
        manifest = self.architecture_manifest(model)
        if manifest["parameter_count"] != self.config.model.expected_parameter_count:
            raise RuntimeError("V8 torch model parameter count drift")
        return model

    def _training_tensors(
        self,
        view: V8FoldTrainingView,
        statistics: V8FoldStatistics,
    ) -> dict[str, Any]:
        """Kopiruet odin purged fold na device posle train-only scaling."""
        torch = self.torch
        intraday = _scaled_feature_array(
            view.intraday,
            view.intraday_valid,
            statistics.intraday_median,
            statistics.intraday_iqr,
            "intraday",
        )
        daily = _scaled_feature_array(
            view.daily_context,
            view.daily_valid,
            statistics.daily_median,
            statistics.daily_iqr,
            "daily",
        )
        ssl_targets, ssl_mask, input_end, horizon_end = _build_ssl_patch_supervision(
            view,
            self.config.model.patch_size_bars,
        )
        if not ssl_mask.any():
            raise ValueError("V8 fold ne imeet valid SSL patch targets")
        effective_asset = np.asarray(view.asset_valid, dtype=bool) & np.asarray(
            view.intraday_valid,
            dtype=bool,
        ).any(axis=-1)
        if (~effective_asset).all(axis=1).any():
            raise ValueError("V8 fold sample bez factual asset")

        def tensor(values: np.ndarray, *, dtype: Any | None = None) -> Any:
            """Perenosit contiguous numpy array na odin fixed device."""
            source = np.ascontiguousarray(values)
            result = torch.from_numpy(source)
            if dtype is not None:
                result = result.to(dtype=dtype)
            return result.to(self.device, non_blocking=False)

        return {
            "intraday": tensor(intraday),
            "intraday_valid": tensor(np.asarray(view.intraday_valid, dtype=bool)),
            "daily": tensor(daily),
            "daily_valid": tensor(np.asarray(view.daily_valid, dtype=bool)),
            "asset_valid": tensor(effective_asset),
            "ssl_targets": tensor(ssl_targets),
            "ssl_mask": tensor(ssl_mask),
            "ssl_input_end": input_end,
            "ssl_horizon_end": horizon_end,
            "targets": tensor(np.asarray(view.normalized_target, dtype=np.float32)),
            "target_valid": tensor(np.asarray(view.target_valid, dtype=bool)),
        }

    @staticmethod
    def _ranges(count: int, batch_size: int) -> Sequence[tuple[int, int]]:
        """Vozvrashchaet deterministic contiguous batch ranges bez shuffle."""
        return tuple(
            (start, min(start + batch_size, count))
            for start in range(0, count, batch_size)
        )

    def _ssl_history(
        self,
        model: Any,
        request: V8SeedTrainingRequest,
        tensors: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Vypolniaet fresh fold-local SSL s dynamic targets i two-view InfoNCE."""
        torch = self.torch
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=request.ssl_learning_rate,
            weight_decay=request.weight_decay,
        )
        count = len(request.training_view.global_sample_indices)
        history: list[dict[str, Any]] = []
        for epoch in range(1, request.ssl_epochs + 1):
            model.train()
            total_sum = 0.0
            dynamic_sum = 0.0
            contrastive_sum = 0.0
            observations = 0
            for start, stop in self._ranges(count, self.ssl_batch_size):
                optimizer.zero_grad(set_to_none=True)
                boundary = self.ssl_boundary_class(
                    input_bar_end_times=tensors["ssl_input_end"][start:stop],
                    horizon_end_times=tensors["ssl_horizon_end"][start:stop],
                    purged_train_cutoff=request.training_view.effective_cutoff,
                )
                intraday = tensors["intraday"][start:stop]
                intraday_valid = tensors["intraday_valid"][start:stop]
                daily = tensors["daily"][start:stop]
                daily_valid = tensors["daily_valid"][start:stop]
                asset_valid = tensors["asset_valid"][start:stop]
                target = tensors["ssl_targets"][start:stop]
                target_mask = tensors["ssl_mask"][start:stop]
                with self._autocast():
                    first = model(
                        intraday,
                        intraday_valid,
                        daily,
                        daily_valid,
                        asset_valid,
                    )
                    second = model(
                        intraday,
                        intraday_valid,
                        daily,
                        daily_valid,
                        asset_valid,
                    )
                first_dynamic = self.dynamic_ssl_loss(
                    first.ssl_forecasts.float(),
                    target,
                    target_mask,
                    boundary,
                )
                second_dynamic = self.dynamic_ssl_loss(
                    second.ssl_forecasts.float(),
                    target,
                    target_mask,
                    boundary,
                )
                dynamic = 0.5 * (first_dynamic + second_dynamic)
                contrastive = self.contrastive_loss(
                    first.contrastive_embedding.float(),
                    second.contrastive_embedding.float(),
                    asset_valid,
                    boundary,
                )
                loss = dynamic + contrastive
                if not torch.isfinite(loss):
                    raise FloatingPointError("V8 SSL loss ne finite")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    model.parameters(),
                    request.gradient_clip_norm,
                    error_if_nonfinite=True,
                )
                optimizer.step()
                batch_count = stop - start
                total_sum += float(loss.detach().float().cpu()) * batch_count
                dynamic_sum += float(dynamic.detach().float().cpu()) * batch_count
                contrastive_sum += float(contrastive.detach().float().cpu()) * batch_count
                observations += batch_count
            history.append(
                {
                    "epoch": epoch,
                    "loss": total_sum / observations,
                    "dynamic_loss": dynamic_sum / observations,
                    "contrastive_loss": contrastive_sum / observations,
                    "ordered_batches": len(self._ranges(count, self.ssl_batch_size)),
                }
            )
        return tuple(history)

    def _supervised_history(
        self,
        model: Any,
        request: V8SeedTrainingRequest,
        tensors: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """Fitit frozen encoder na contiguous chronology s explicit prior carry."""
        torch = self.torch
        self.configure_supervised(model)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        optimizer = torch.optim.AdamW(
            trainable,
            lr=request.supervised_learning_rate,
            weight_decay=request.weight_decay,
        )
        view = request.training_view
        count = len(view.global_sample_indices)
        histories: list[dict[str, Any]] = []
        component_names = (
            "factor",
            "residual_nll",
            "direction",
            "crash_router",
            "regime_balance",
            "cost_aware",
        )
        cost = self.torch.from_numpy(
            np.ascontiguousarray(request.cost_scale.values_in_target_iqr, dtype=np.float32)
        ).to(self.device)
        for epoch in range(1, request.supervised_epochs + 1):
            model.train()
            totals = {name: 0.0 for name in ("loss", *component_names)}
            observations = 0
            previous_position = None
            for start, stop in self._ranges(count, self.supervised_batch_size):
                optimizer.zero_grad(set_to_none=True)
                with self._autocast():
                    output = model(
                        tensors["intraday"][start:stop],
                        tensors["intraday_valid"][start:stop],
                        tensors["daily"][start:stop],
                        tensors["daily_valid"][start:stop],
                        tensors["asset_valid"][start:stop],
                    )
                float_output = type(output)(
                    **{
                        name: getattr(output, name).float()
                        for name in output.__dataclass_fields__
                    }
                )
                target_batch = self.target_batch_class(
                    values=tensors["targets"][start:stop],
                    target_mask=tensors["target_valid"][start:stop]
                    & tensors["asset_valid"][start:stop],
                    label_end_times=np.asarray(view.target_availability_times)[start:stop],
                    purged_train_cutoff=view.effective_cutoff,
                )
                ordered = self.ordered_batch_class(
                    decision_times=np.asarray(view.decision_times)[start:stop],
                    sequence_numbers=np.asarray(view.global_sample_indices)[start:stop],
                    initial_position=previous_position,
                    starts_flat=previous_position is None,
                )
                breakdown = self.supervised_loss(
                    float_output,
                    target_batch,
                    request.statistics.train_target_iqr,
                    cost[start:stop],
                    ordered,
                    direction_weight=self.config.training.direction_loss_weight,
                    crash_weight=self.config.training.crash_loss_weight,
                    regime_balance_weight=self.config.training.regime_balance_weight,
                    cost_aware_weight=self.config.training.cost_aware_loss_weight,
                )
                if not torch.isfinite(breakdown.total):
                    raise FloatingPointError("V8 supervised loss ne finite")
                breakdown.total.backward()
                torch.nn.utils.clip_grad_norm_(
                    trainable,
                    request.gradient_clip_norm,
                    error_if_nonfinite=True,
                )
                optimizer.step()
                previous_position = output.decision_score[-1].detach()
                batch_count = stop - start
                totals["loss"] += float(breakdown.total.detach().float().cpu()) * batch_count
                for name in component_names:
                    value = getattr(breakdown, name)
                    totals[name] += float(value.detach().float().cpu()) * batch_count
                observations += batch_count
            histories.append(
                {
                    "epoch": epoch,
                    **{name: value / observations for name, value in totals.items()},
                    "ordered_batches": len(
                        self._ranges(count, self.supervised_batch_size)
                    ),
                    "starts_flat_once": True,
                }
            )
        return tuple(histories)

    def _checkpoint_bytes(
        self,
        model: Any,
        request: V8SeedTrainingRequest,
    ) -> bytes:
        """Serializuet completed CPU state tol'ko posle oboih exact stages."""
        state_dict = {
            name: tensor.detach().cpu().contiguous()
            for name, tensor in model.state_dict().items()
        }
        payload = {
            "format": V8_TORCH_CHECKPOINT_FORMAT,
            "fold_name": request.fold_name,
            "seed": request.seed,
            "ssl_epochs": request.ssl_epochs,
            "supervised_epochs": request.supervised_epochs,
            "model_config_sha256": _canonical_json_sha256(
                self.config.model.model_dump(mode="json")
            ),
            "model_state_dict": state_dict,
        }
        buffer = io.BytesIO()
        self.torch.save(payload, buffer)
        return buffer.getvalue()

    def train_completed_seed(
        self,
        request: V8SeedTrainingRequest,
    ) -> V8SeedTrainingOutcome:
        """Vypolniaet fresh init, SSL, freeze, supervised i completed checkpoint."""
        self._check_request(request)
        model = self._new_model(request.seed)
        tensors = self._training_tensors(request.training_view, request.statistics)
        ssl_history = self._ssl_history(model, request, tensors)
        supervised_history = self._supervised_history(model, request, tensors)
        model.eval()
        checkpoint = self._checkpoint_bytes(model, request)
        return V8SeedTrainingOutcome(
            seed=request.seed,
            state=_V8TorchSeedState(model=model, fold_name=request.fold_name, seed=request.seed),
            checkpoint_bytes=checkpoint,
            ssl_history=ssl_history,
            supervised_history=supervised_history,
            fresh_ssl_initialization=True,
            encoder_frozen_before_supervised=True,
        )

    def restore_completed_seed(
        self,
        checkpoint_bytes: bytes,
        request: V8SeedTrainingRequest,
    ) -> _V8TorchSeedState:
        """Vosstanavlivaet tol'ko backend payload posle runner sidecar SHA proverki."""
        self._check_request(request)
        try:
            payload = self.torch.load(
                io.BytesIO(checkpoint_bytes),
                map_location="cpu",
                weights_only=True,
            )
        except Exception as error:
            raise ValueError("V8 torch checkpoint deserialize fail") from error
        if not isinstance(payload, dict):
            raise ValueError("V8 torch checkpoint payload ne object")
        expected = {
            "format": V8_TORCH_CHECKPOINT_FORMAT,
            "fold_name": request.fold_name,
            "seed": request.seed,
            "ssl_epochs": request.ssl_epochs,
            "supervised_epochs": request.supervised_epochs,
            "model_config_sha256": _canonical_json_sha256(
                self.config.model.model_dump(mode="json")
            ),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ValueError("V8 torch checkpoint semantic identity mismatch")
        state_dict = payload.get("model_state_dict")
        if not isinstance(state_dict, dict):
            raise ValueError("V8 torch checkpoint state_dict otsutstvuet")
        model = self._new_model(request.seed)
        model.load_state_dict(state_dict, strict=True)
        self.configure_supervised(model)
        model.eval()
        return _V8TorchSeedState(model=model, fold_name=request.fold_name, seed=request.seed)

    def _scaled_inference(
        self,
        inference: V8InferenceView,
        statistics: V8FoldStatistics,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Masshtabiruet target-free OOS inputs lish' fold-train statistics."""
        intraday = _scaled_feature_array(
            inference.intraday,
            inference.intraday_valid,
            statistics.intraday_median,
            statistics.intraday_iqr,
            "inference intraday",
        )
        daily = _scaled_feature_array(
            inference.daily_context,
            inference.daily_valid,
            statistics.daily_median,
            statistics.daily_iqr,
            "inference daily",
        )
        return intraday, daily

    def predict_seed(
        self,
        state: _V8TorchSeedState,
        inference: V8InferenceView,
        statistics: V8FoldStatistics,
    ) -> V8SeedPrediction:
        """Predskazyvaet tol'ko iz causal OOS inputs; target container nedostupen."""
        if not isinstance(state, _V8TorchSeedState):
            raise TypeError("V8 torch predict trebuet completed seed state")
        torch = self.torch
        model = state.model
        model.eval()
        intraday, daily = self._scaled_inference(inference, statistics)
        samples = len(inference.global_sample_indices)
        assets = len(V8_ASSETS)
        factor_location = np.empty(samples, dtype=np.float32)
        factor_scale = np.empty(samples, dtype=np.float32)
        factor_score = np.empty(samples, dtype=np.float32)
        residual_location = np.zeros((samples, assets), dtype=np.float32)
        residual_scale = np.zeros((samples, assets), dtype=np.float32)
        residual_score = np.zeros((samples, assets), dtype=np.float32)
        direction_logit = np.zeros((samples, assets), dtype=np.float32)
        for start, stop in self._ranges(samples, self.inference_batch_size):
            factual_asset = np.asarray(inference.asset_valid[start:stop], dtype=bool) & np.asarray(
                inference.intraday_valid[start:stop],
                dtype=bool,
            ).any(axis=-1)

            def device_tensor(values: np.ndarray) -> Any:
                """Kopiruet odin target-free inference batch na device."""
                return torch.from_numpy(np.ascontiguousarray(values)).to(self.device)

            with torch.inference_mode(), self._autocast():
                output = model(
                    device_tensor(intraday[start:stop]),
                    device_tensor(np.asarray(inference.intraday_valid[start:stop], dtype=bool)),
                    device_tensor(daily[start:stop]),
                    device_tensor(np.asarray(inference.daily_valid[start:stop], dtype=bool)),
                    device_tensor(factual_asset),
                )
            factor_location[start:stop] = output.factor_location.float().cpu().numpy()
            factor_scale[start:stop] = output.factor_scale.float().cpu().numpy()
            factor_score[start:stop] = output.factor_decision_score.float().cpu().numpy()
            residual_location[start:stop] = output.residual_location.float().cpu().numpy()
            residual_scale[start:stop] = output.total_scale.float().cpu().numpy()
            residual_score[start:stop] = output.decision_score.float().cpu().numpy()
            direction_logit[start:stop] = output.direction_logit.float().cpu().numpy()
        return V8SeedPrediction(
            factor_location=factor_location,
            factor_scale=factor_scale,
            factor_score=factor_score,
            residual_location=residual_location,
            residual_scale=residual_scale,
            residual_decision_score=residual_score,
            direction_logit=direction_logit,
        )

    def reset_peak_vram(self) -> None:
        """Sbasyvaet CUDA peak counters neposredstvenno pered first fold."""
        if self.device.type == "cuda":
            self.torch.cuda.reset_peak_memory_stats(self.device)

    def peak_vram(self) -> dict[str, int]:
        """Vozvrashchaet peak allocated/reserved bytes bez ocenki PnL."""
        if self.device.type != "cuda":
            return {"peak_allocated_bytes": 0, "peak_reserved_bytes": 0}
        return {
            "peak_allocated_bytes": int(
                self.torch.cuda.max_memory_allocated(self.device)
            ),
            "peak_reserved_bytes": int(self.torch.cuda.max_memory_reserved(self.device)),
        }

    def release_fold(self) -> None:
        """Osvobozhdaet cached CUDA blocks posle three-seed ensemble folda."""
        import gc

        gc.collect()
        if self.device.type == "cuda":
            self.torch.cuda.empty_cache()


def build_v8_torch_training_api(
    config: V8ResearchConfig,
    *,
    device: str = "cuda:0",
    ssl_batch_size: int = V8_TORCH_SSL_BATCH_SIZE,
    supervised_batch_size: int = V8_TORCH_SUPERVISED_BATCH_SIZE,
    inference_batch_size: int = V8_TORCH_INFERENCE_BATCH_SIZE,
    test_only_allow_epoch_override: bool = False,
    test_only_allow_non_5090: bool = False,
) -> V8TrainingApi:
    """Stroit real PyTorch API; caller obyazan zavershit' pre-CUDA seals ran'she."""
    return _V8TorchBackend(
        config,
        device=device,
        ssl_batch_size=ssl_batch_size,
        supervised_batch_size=supervised_batch_size,
        inference_batch_size=inference_batch_size,
        test_only_allow_epoch_override=test_only_allow_epoch_override,
        test_only_allow_non_5090=test_only_allow_non_5090,
    ).api()


def _default_training_api(config: V8ResearchConfig) -> V8TrainingApi:
    """Inicializiruet sealed RTX5090 BF16 backend tol'ko posle runner pre-CUDA checks."""
    return build_v8_torch_training_api(config)


def run_v8_training(
    project_root: Path,
    config_path: Path,
    assembly_manifest_path: Path,
    output_directory: Path,
    *,
    expected_config_sha256: str = DEFAULT_V8_CONFIG_SHA256,
    expected_assembly_manifest_sha256: str,
    expected_code_identity_sha256: str | None = None,
    cost_spec_manifest_path: Path | None = None,
    expected_cost_spec_manifest_sha256: str | None = None,
    resume: bool = True,
    training_api: V8TrainingApi | None = None,
    array_loader: Callable[[Path, VerifiedV8AssemblyManifest], V8AssemblyResult] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> V8TrainingRunArtifacts:
    """Orkestriruet exact 5x3 fresh-SSL train i target-free OOS prediction."""
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    inputs = load_verified_v8_training_inputs(
        project_root,
        config_path,
        assembly_manifest_path,
        expected_config_sha256=expected_config_sha256,
        expected_assembly_manifest_sha256=expected_assembly_manifest_sha256,
        array_loader=array_loader,
    )
    root = inputs.project_root
    output = _bounded_path(root, output_directory, "V8 training output")
    if (cost_spec_manifest_path is None) != (expected_cost_spec_manifest_sha256 is None):
        raise ValueError("V8 cost spec manifest path i SHA dolzhny byt' zadany vmeste")
    authoritative_spec: VerifiedV8SpecProxy | None = None
    if cost_spec_manifest_path is not None:
        assert expected_cost_spec_manifest_sha256 is not None
        authoritative_spec = verify_authoritative_v8_spec_proxy(
            root,
            cost_spec_manifest_path,
            expected_cost_spec_manifest_sha256,
        )
    elif training_api is None:
        authoritative_spec = verify_authoritative_v8_spec_proxy(
            root,
            Path(inputs.config.training.one_way_cost_spec_manifest_path),
            inputs.config.training.one_way_cost_spec_manifest_sha256,
        )
    cost_source_identity = (
        authoritative_spec.identity
        if authoritative_spec is not None
        else {"provider": "injected_test_backend_pre_cuda_identity_unavailable"}
    )
    code_identity = build_v8_code_identity(root)
    if expected_code_identity_sha256 is not None and (
        not _is_sha256(expected_code_identity_sha256)
        or code_identity[
            "code_identity_sha256"
        ]
        != expected_code_identity_sha256.lower()
    ):
        raise ValueError("V8 runtime code identity pre-CUDA mismatch")
    identity = _identity_payload(inputs, code_identity, cost_source_identity)
    run_identity_path = output / "run_identity.json"
    progress_path = output / "training_progress.json"
    summary_path = output / "training_summary.json"
    checkpoints_path = output / "checkpoint_identities.json"
    checkpoint_directory = output / "checkpoints"
    if not run_identity_path.exists():
        orphaned = checkpoint_directory.exists() and any(
            path.is_file() for path in checkpoint_directory.rglob("*")
        )
        if orphaned:
            raise ValueError("V8 checkpoint sushchestvuet bez pre-CUDA run identity")
        output.mkdir(parents=True, exist_ok=True)
        write_json(
            run_identity_path,
            {
                "format": V8_RUN_FORMAT,
                "research_status": "pre_cuda_identity_committed_no_pnl",
                "identity": identity,
            },
        )
    _validate_existing_identity(run_identity_path, identity)
    _validate_existing_identity(progress_path, identity)
    _validate_existing_identity(summary_path, identity)
    _assert_code_unchanged(root, code_identity)
    api = training_api if training_api is not None else _default_training_api(inputs.config)
    checkpoint_directory.mkdir(parents=True, exist_ok=True)
    config = inputs.config
    if len(config.development.folds) != 5 or tuple(config.training.seeds) != V8_SEEDS:
        raise ValueError("V8 runner trebuet rovno 5 folds x 3 fixed seeds")
    if (
        config.training.ssl_epochs != V8_SSL_EPOCHS
        or config.training.supervised_epochs != V8_SUPERVISED_EPOCHS
        or config.training.precision != V8_PRECISION
        or not config.training.deterministic_algorithms
        or not config.training.fresh_ssl_per_fold
    ):
        raise ValueError("V8 fixed training stage seal mismatch")
    model_id = f"{V8_MODEL_ID_PREFIX}_{identity['architecture_sha256'][:12]}"
    all_frames: list[pd.DataFrame] = []
    checkpoint_identities: list[dict[str, Any]] = []
    used_oos: set[int] = set()
    api.reset_peak_vram()

    for fold in config.development.folds:
        oos_indices = build_v8_oos_sample_indices(
            inputs.result.inputs.sample_trade_dates,
            inputs.result.inputs.decision_times,
            fold,
            config.development.decision_timezone,
        )
        overlap = used_oos.intersection(int(value) for value in oos_indices)
        if overlap:
            raise ValueError(f"V8 outer-fold OOS overlap: {sorted(overlap)}")
        used_oos.update(int(value) for value in oos_indices)
        scope = build_v8_fold_scope(
            inputs.result.inputs,
            inputs.result.targets,
            train_start=fold.train_start,
            train_end=fold.train_end,
            purge_sessions=config.development.purge_sessions,
        )
        validate_v8_fold_scope(inputs.result.inputs, inputs.result.targets, scope)
        statistics = fit_v8_fold_statistics(inputs.result, scope, config)
        statistics_sha = _canonical_json_sha256(statistics.as_dict())
        training_view = build_v8_fold_training_view(inputs.result, scope)
        cost_scale = (
            build_authoritative_v8_cost_scale(training_view, statistics, authoritative_spec)
            if authoritative_spec is not None
            else api.fit_cost_scale(training_view, statistics)
        )
        cost_identity = _validate_cost_scale(cost_scale, training_view)
        inference = build_v8_inference_view(inputs.result, oos_indices)
        seed_predictions: list[V8SeedPrediction] = []
        for seed in config.training.seeds:
            _assert_code_unchanged(root, code_identity)
            request = V8SeedTrainingRequest(
                fold_name=fold.name,
                seed=seed,
                training_view=training_view,
                statistics=statistics,
                cost_scale=cost_scale,
                ssl_epochs=V8_SSL_EPOCHS,
                supervised_epochs=V8_SUPERVISED_EPOCHS,
                ssl_learning_rate=config.training.ssl_learning_rate,
                supervised_learning_rate=config.training.supervised_learning_rate,
                weight_decay=config.training.weight_decay,
                gradient_clip_norm=config.training.gradient_clip_norm,
                precision=V8_PRECISION,
                deterministic_algorithms=True,
                fresh_ssl_initialization_required=True,
                freeze_encoder_before_supervised_required=True,
            )
            checkpoint_path, sidecar_path = _checkpoint_paths(
                checkpoint_directory,
                fold.name,
                seed,
            )
            resumed = False
            if resume and (checkpoint_path.exists() or sidecar_path.exists()):
                checkpoint_bytes, outer = _load_completed_checkpoint_bundle(
                    checkpoint_path,
                    sidecar_path,
                    identity,
                    api.runtime_identity,
                    request,
                    statistics_sha,
                    cost_identity,
                )
                state = api.restore_completed_seed(checkpoint_bytes, request)
                resumed = True
            else:
                outcome = api.train_completed_seed(request)
                if int(outcome.seed) != seed:
                    raise ValueError("V8 backend seed outcome mismatch")
                ssl_history = _validate_history(outcome.ssl_history, V8_SSL_EPOCHS, "SSL")
                supervised_history = _validate_history(
                    outcome.supervised_history,
                    V8_SUPERVISED_EPOCHS,
                    "supervised",
                )
                if not outcome.fresh_ssl_initialization:
                    raise ValueError("V8 backend ne dokazal fresh SSL initialization")
                if not outcome.encoder_frozen_before_supervised:
                    raise ValueError("V8 backend ne zamorozil encoder pered supervised")
                normalized_outcome = V8SeedTrainingOutcome(
                    seed=outcome.seed,
                    state=outcome.state,
                    checkpoint_bytes=outcome.checkpoint_bytes,
                    ssl_history=ssl_history,
                    supervised_history=supervised_history,
                    fresh_ssl_initialization=True,
                    encoder_frozen_before_supervised=True,
                )
                _assert_code_unchanged(root, code_identity)
                core = _checkpoint_core(
                    identity,
                    api.runtime_identity,
                    request,
                    statistics_sha,
                    cost_identity,
                    normalized_outcome,
                )
                outer = _write_completed_checkpoint_bundle(
                    checkpoint_path,
                    sidecar_path,
                    normalized_outcome.checkpoint_bytes,
                    core,
                )
                state = normalized_outcome.state
            checkpoint_identities.append(
                _checkpoint_identity(
                    root,
                    checkpoint_path,
                    sidecar_path,
                    outer,
                    resumed,
                )
            )
            _write_progress(progress_path, identity, checkpoint_identities)
            prediction = api.predict_seed(state, inference, statistics)
            _validate_seed_prediction(prediction, inference)
            seed_predictions.append(prediction)
            if progress_callback is not None:
                progress_callback(
                    {
                        "event": "seed_complete",
                        "fold_name": fold.name,
                        "seed": seed,
                        "completed_seed_checkpoints": len(checkpoint_identities),
                        "total_seed_checkpoints": 15,
                    }
                )
        ensemble = ensemble_v8_seed_predictions(seed_predictions, inference)
        all_frames.append(build_v8_oos_prediction_frame(inference, ensemble, model_id))
        api.release_fold()

    if len(checkpoint_identities) != 15:
        raise ValueError("V8 runner ne zavershil exact 15 completed seed checkpoints")
    keys = [(item["fold_name"], item["seed"]) for item in checkpoint_identities]
    if len(set(keys)) != 15:
        raise ValueError("V8 completed seed checkpoint keys duplicate")
    _assert_code_unchanged(root, code_identity)
    predictions = pd.concat(all_frames, ignore_index=True).sort_values(
        ["decision_at", "asset", "model_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if list(predictions.columns) != list(V8_PREDICTION_COLUMNS):
        raise ValueError("V8 prediction column schema drift")
    if predictions.duplicated(["decision_at", "asset", "model_id"]).any():
        raise ValueError("V8 OOS prediction key duplicate")
    if pd.to_datetime(predictions["decision_at"], utc=True).ge(
        pd.Timestamp("2026-01-01T00:00:00Z")
    ).any():
        raise ValueError("V8 predictions pronikli v protected 2026")
    predictions_path = output / "oos_predictions.parquet"
    _atomic_write_parquet(predictions_path, predictions)
    write_json(
        checkpoints_path,
        {
            "format": V8_RUN_FORMAT,
            "research_status": "training_complete_no_pnl",
            "identity": identity,
            "checkpoints": checkpoint_identities,
        },
    )
    finished_at = datetime.now(UTC)
    summary = {
        "format": V8_RUN_FORMAT,
        "research_status": "training_complete_no_pnl_no_holdout_access",
        "identity": identity,
        "protocol_name": config.protocol_name,
        "protocol_version": config.protocol_version,
        "model_id": model_id,
        "fold_names": [fold.name for fold in config.development.folds],
        "seeds": list(config.training.seeds),
        "completed_seed_checkpoint_count": 15,
        "new_seed_checkpoint_count": sum(not item["resumed"] for item in checkpoint_identities),
        "resumed_seed_checkpoint_count": sum(
            item["resumed"] for item in checkpoint_identities
        ),
        "prediction_artifact": {
            "path": predictions_path.relative_to(root).as_posix(),
            "bytes": predictions_path.stat().st_size,
            "sha256": _file_sha256(predictions_path),
            "rows": len(predictions),
            "columns": list(V8_PREDICTION_COLUMNS),
            "mask_semantics": "causal_effective_asset_only_never_target_valid",
            "timing_semantics": "D18:50_decision_D19:00_capacity_D19:20_execution_Moscow",
        },
        "checkpoint_identity_artifact": {
            "path": checkpoints_path.relative_to(root).as_posix(),
            "bytes": checkpoints_path.stat().st_size,
            "sha256": _file_sha256(checkpoints_path),
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
        "training_contract": {
            "fold_count": 5,
            "seeds_per_fold": 3,
            "fresh_ssl_epochs_per_seed": V8_SSL_EPOCHS,
            "frozen_supervised_epochs_per_seed": V8_SUPERVISED_EPOCHS,
            "precision": V8_PRECISION,
            "deterministic_algorithms": True,
            "cost_provider_required_and_nonzero": True,
        },
        "resume_semantics": V8_RESUME_SEMANTICS,
        "oos_admission": "calendar_only_target_free",
        "protected_holdout_start": V8_PROTECTED_HOLDOUT_START.isoformat(),
        "pnl_or_trading_metrics_computed": False,
    }
    write_json(summary_path, summary)
    return V8TrainingRunArtifacts(
        output_directory=output,
        run_identity_path=run_identity_path,
        predictions_path=predictions_path,
        progress_path=progress_path,
        checkpoint_identities_path=checkpoints_path,
        training_summary_path=summary_path,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Stroit server CLI dlia pre-sealed RTX5090 train bez PnL."""
    parser = argparse.ArgumentParser(description="Run sealed futures-v8 training without PnL.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/futures_v8_development_protocol.yaml"),
    )
    parser.add_argument("--config-sha256", default=DEFAULT_V8_CONFIG_SHA256)
    parser.add_argument("--assembly-manifest", type=Path, required=True)
    parser.add_argument("--assembly-manifest-sha256", required=True)
    parser.add_argument("--code-identity-sha256")
    parser.add_argument("--cost-spec-manifest", type=Path)
    parser.add_argument("--cost-spec-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Zapuskaet CLI i pechataet artefact paths tol'ko posle complete run."""
    arguments = build_argument_parser().parse_args(argv)
    artifacts = run_v8_training(
        arguments.project_root,
        arguments.config,
        arguments.assembly_manifest,
        arguments.output,
        expected_config_sha256=arguments.config_sha256,
        expected_assembly_manifest_sha256=arguments.assembly_manifest_sha256,
        expected_code_identity_sha256=arguments.code_identity_sha256,
        cost_spec_manifest_path=arguments.cost_spec_manifest,
        expected_cost_spec_manifest_sha256=arguments.cost_spec_manifest_sha256,
        resume=not arguments.no_resume,
    )
    print(
        json.dumps(
            {
                "output": str(artifacts.output_directory),
                "predictions": str(artifacts.predictions_path),
                "summary": str(artifacts.training_summary_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LoadedV8TrainingInputs",
    "V8CostScale",
    "V8FoldStatistics",
    "V8FoldTrainingView",
    "V8InferenceView",
    "V8SeedPrediction",
    "V8SeedTrainingOutcome",
    "V8SeedTrainingRequest",
    "V8TrainingApi",
    "V8TrainingRunArtifacts",
    "VerifiedV8AssemblyManifest",
    "VerifiedV8SpecProxy",
    "build_authoritative_v8_cost_scale",
    "build_v8_torch_training_api",
    "build_v8_code_identity",
    "build_v8_fold_training_view",
    "build_v8_inference_view",
    "build_v8_oos_prediction_frame",
    "build_v8_oos_sample_indices",
    "ensemble_v8_seed_predictions",
    "fit_v8_fold_statistics",
    "load_v8_assembly_arrays",
    "load_verified_v8_training_inputs",
    "run_v8_training",
    "verify_authoritative_v8_spec_proxy",
    "verify_v8_assembly_manifest",
]
