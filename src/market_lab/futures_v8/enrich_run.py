"""Target-free regime/abstain enrichment dlia zapechatannogo futures-v8 run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures_v8.assembly import (
    V8_CAUSAL_V7_KEYS,
    V8_PROTECTED_HOLDOUT_START,
    V8CausalInputs,
    load_v7_causal_inputs,
)
from market_lab.futures_v8.config import (
    DEFAULT_V8_CONFIG_SHA256,
    V8_ASSETS,
    V8_SEEDS,
    V8FoldConfig,
    V8ResearchConfig,
    load_v8_research_config,
)
from market_lab.futures_v8.train_run import (
    V8InferenceView,
    V8SeedPrediction,
    build_v8_code_identity,
    build_v8_oos_prediction_frame,
    build_v8_oos_sample_indices,
    ensemble_v8_seed_predictions,
    verify_v8_assembly_manifest,
)
from market_lab.io_utils import write_json

V8_ENRICHMENT_FORMAT: Final[str] = "market-lab-futures-v8-regime-enrichment-v2"
V8_SCALER_FORMAT: Final[str] = "market-lab-futures-v8-fold-scalers-v2"
V8_TORCH_CHECKPOINT_FORMAT: Final[str] = "market-lab-futures-v8-torch-state-v1"
V8_BASE_RUN_FORMAT: Final[str] = "market-lab-futures-v8-training-run-v1"
V8_ENRICHMENT_CODE_PATH: Final[str] = "src/market_lab/futures_v8/enrich_run.py"
V8_INFERENCE_BATCH_SIZE: Final[int] = 256
V8_REGIME_NAMES: Final[tuple[str, ...]] = ("normal", "trend", "crash")
V8_BASE_REPLAY_NUMERIC_COLUMNS: Final[tuple[str, ...]] = (
    "factor_location",
    "factor_scale",
    "factor_score",
    "residual_location",
    "residual_scale",
    "residual_decision_score",
    "direction_logit",
)
V8_BASE_REPLAY_IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "model_id",
)
V8_PER_SEED_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "model_id",
    "fold_name",
    "seed",
    "checkpoint_sha256",
    "regime_probability_normal",
    "regime_probability_trend",
    "regime_probability_crash",
    "factor_abstain_probability",
    "residual_abstain_probability",
)
V8_ENSEMBLE_COLUMNS: Final[tuple[str, ...]] = (
    "decision_date",
    "decision_at",
    "capacity_window_open_at",
    "capacity_window_close_at",
    "execution_window_open_at",
    "execution_window_close_at",
    "asset",
    "asset_valid",
    "model_id",
    "fold_name",
    "seed_count",
    "seed_set_sha256",
    "regime_probability_normal",
    "regime_probability_trend",
    "regime_probability_crash",
    "factor_abstain_probability",
    "residual_abstain_probability",
)
_SHA256_SYMBOLS: Final[frozenset[str]] = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class V8CheckpointBundle:
    """Hranit byte-proverennyi completed checkpoint bez zagruzki targetov."""

    fold_name: str
    seed: int
    checkpoint_path: Path
    checkpoint_sha256: str
    sidecar_path: Path
    sidecar_sha256: str
    original_statistics_sha256: str


@dataclass(frozen=True, slots=True)
class V8VerifiedBaseRun:
    """Hranit proverennyi immutable base run i ego target-free prediction frame."""

    directory: Path
    run_identity_path: Path
    run_identity_sha256: str
    identity: dict[str, Any]
    predictions_path: Path
    predictions_sha256: str
    predictions: pd.DataFrame
    model_id: str
    checkpoints: tuple[V8CheckpointBundle, ...]
    checkpoint_inventory_sha256: str


@dataclass(frozen=True, slots=True)
class V8FoldScaler:
    """Hranit tol'ko train-mask-fit median/IQR i hashes bez samih metok/maskov."""

    fold_name: str
    effective_cutoff: str
    purge_sessions: int
    horizon_common_sessions: int
    train_sample_count: int
    intraday_median: tuple[float, ...]
    intraday_iqr: tuple[float, ...]
    daily_median: tuple[float, ...]
    daily_iqr: tuple[float, ...]
    train_indices_sha256: str
    train_target_valid_sha256: str
    scaler_asset_mask_sha256: str
    original_statistics_sha256: str
    scaler_statistics_sha256: str

    def inference_payload(self) -> dict[str, Any]:
        """Vozvrashchaet target-free scaler payload dlia canonical seal."""
        return {
            "fold_name": self.fold_name,
            "effective_cutoff": self.effective_cutoff,
            "purge_sessions": self.purge_sessions,
            "horizon_common_sessions": self.horizon_common_sessions,
            "train_sample_count": self.train_sample_count,
            "intraday_median": list(self.intraday_median),
            "intraday_iqr": list(self.intraday_iqr),
            "daily_median": list(self.daily_median),
            "daily_iqr": list(self.daily_iqr),
            "train_indices_sha256": self.train_indices_sha256,
            "train_target_valid_sha256": self.train_target_valid_sha256,
            "scaler_asset_mask_sha256": self.scaler_asset_mask_sha256,
            "original_statistics_sha256": self.original_statistics_sha256,
        }

    def as_dict(self) -> dict[str, Any]:
        """Serializuet scaler vmeste s ego independent canonical SHA."""
        return {
            **self.inference_payload(),
            "scaler_statistics_sha256": self.scaler_statistics_sha256,
        }


@dataclass(frozen=True, slots=True)
class V8DiagnosticOutput:
    """Hranit model-native router i abstention vyhody odnogo seed."""

    regime_probabilities: np.ndarray
    factor_abstain_probability: np.ndarray
    residual_abstain_probability: np.ndarray


@dataclass(frozen=True, slots=True)
class V8CheckpointOutput:
    """Hranit diagnostic i exact base-prediction outputs odnogo checkpoint."""

    diagnostic: V8DiagnosticOutput
    base_prediction: V8SeedPrediction


@dataclass(frozen=True, slots=True)
class V8EnrichmentArtifacts:
    """Vozvrashchaet immutable published enrichment paths."""

    output_directory: Path
    manifest_path: Path
    scaler_path: Path
    ensemble_path: Path


def _is_sha256(value: Any) -> bool:
    """Proveryaet lowercase/uppercase SHA-256 bez implicit coercion."""
    return (
        isinstance(value, str) and len(value) == 64 and set(value.lower()).issubset(_SHA256_SYMBOLS)
    )


def _file_sha256(path: Path) -> str:
    """Hashiruet file potokovo bez text normalization."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _bytes_sha256(content: bytes) -> str:
    """Hashiruet immutable bytes."""
    return hashlib.sha256(content).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    """Serializuet JSON odnoznachno dlia content seal."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _canonical_json_sha256(payload: Any) -> str:
    """Hashiruet canonical JSON payload."""
    return _bytes_sha256(_canonical_json_bytes(payload))


def _array_sha256(values: np.ndarray) -> str:
    """Hashiruet dtype, shape i contiguous bytes massiva."""
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    """Chitaet JSON object s BOM support i fail-closed tipom."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"V8 enrichment ne mozhet prochitat' JSON: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"V8 enrichment JSON ne object: {path}")
    return payload


def _bounded_path(root: Path, value: Path, label: str) -> Path:
    """Razreshaet put' tol'ko vnutri project root."""
    candidate = value if value.is_absolute() else root / value
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} vyshel iz project root") from error
    return resolved


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno pishet deterministic Parquet i fsync-it ego do replace."""
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


def build_v8_enrichment_code_identity(project_root: Path) -> dict[str, Any]:
    """Dobavliaet enrichment module k proverennoy base runtime closure."""
    root = project_root.resolve()
    base = build_v8_code_identity(root)
    module = _bounded_path(root, Path(V8_ENRICHMENT_CODE_PATH), "V8 enrichment code")
    records = [dict(item) for item in base["files"]]
    records.append(
        {
            "path": module.relative_to(root).as_posix(),
            "bytes": module.stat().st_size,
            "sha256": _file_sha256(module),
        }
    )
    records = sorted(records, key=lambda item: item["path"])
    if len({item["path"] for item in records}) != len(records):
        raise ValueError("V8 enrichment code closure imeet duplicate path")
    return {"files": records, "code_identity_sha256": _canonical_json_sha256(records)}


def _verify_base_code_identity(project_root: Path, identity: dict[str, Any]) -> None:
    """Dokazyvaet, chto original training closure ne izmenilas'."""
    expected = identity.get("code_identity")
    current = build_v8_code_identity(project_root)
    if not isinstance(expected, dict) or current != expected:
        raise ValueError("V8 original training code identity drift")


def _verify_checkpoint_sidecar(
    project_root: Path,
    record: dict[str, Any],
    identity: dict[str, Any],
) -> V8CheckpointBundle:
    """Proveryaet completed checkpoint/sidecar SHA i semantic identity."""
    checkpoint = _bounded_path(
        project_root,
        Path(str(record.get("checkpoint_path", ""))),
        "V8 checkpoint",
    )
    sidecar = _bounded_path(
        project_root,
        Path(str(record.get("sidecar_path", ""))),
        "V8 checkpoint sidecar",
    )
    if not checkpoint.is_file() or not sidecar.is_file():
        raise FileNotFoundError("V8 checkpoint bundle nepolon")
    checkpoint_sha = _file_sha256(checkpoint)
    sidecar_sha = _file_sha256(sidecar)
    if (
        checkpoint_sha != record.get("checkpoint_sha256")
        or sidecar_sha != record.get("sidecar_sha256")
        or checkpoint.stat().st_size != int(record.get("checkpoint_bytes", -1))
        or sidecar.stat().st_size != int(record.get("sidecar_bytes", -1))
    ):
        raise ValueError("V8 checkpoint index byte seal mismatch")
    outer = _read_json(sidecar)
    core = outer.get("manifest")
    if (
        outer.get("checkpoint_file") != checkpoint.name
        or outer.get("checkpoint_sha256") != checkpoint_sha
        or not isinstance(core, dict)
        or outer.get("manifest_sha256") != _canonical_json_sha256(core)
    ):
        raise ValueError("V8 checkpoint sidecar internal seal mismatch")
    fold_name = str(record.get("fold_name", ""))
    seed = int(record.get("seed", -1))
    statistics_sha = core.get("statistics_sha256")
    if (
        core.get("identity") != identity
        or core.get("completed") is not True
        or core.get("fold_name") != fold_name
        or int(core.get("seed", -1)) != seed
        or not _is_sha256(statistics_sha)
    ):
        raise ValueError("V8 checkpoint semantic identity mismatch")
    return V8CheckpointBundle(
        fold_name=fold_name,
        seed=seed,
        checkpoint_path=checkpoint,
        checkpoint_sha256=checkpoint_sha,
        sidecar_path=sidecar,
        sidecar_sha256=sidecar_sha,
        original_statistics_sha256=str(statistics_sha).lower(),
    )


def verify_v8_base_run(
    project_root: Path,
    base_run_directory: Path,
    *,
    expected_run_identity_sha256: str,
    expected_predictions_sha256: str,
    config_sha256: str,
    assembly_manifest_sha256: str,
) -> V8VerifiedBaseRun:
    """Proveryaet final base run i predictions bez target/PnL dostupa."""
    root = project_root.resolve()
    base = _bounded_path(root, base_run_directory, "V8 base run")
    if not base.is_dir() or not all(
        _is_sha256(value)
        for value in (
            expected_run_identity_sha256,
            expected_predictions_sha256,
            config_sha256,
            assembly_manifest_sha256,
        )
    ):
        raise ValueError("V8 base run path ili expected SHA invalid")
    run_path = base / "run_identity.json"
    progress_path = base / "training_progress.json"
    index_path = base / "checkpoint_identities.json"
    summary_path = base / "training_summary.json"
    predictions_path = base / "oos_predictions.parquet"
    required = (run_path, progress_path, index_path, summary_path, predictions_path)
    if any(not path.is_file() for path in required):
        raise FileNotFoundError("V8 base run final artifacts nepolny")
    if _file_sha256(run_path) != expected_run_identity_sha256.lower():
        raise ValueError("V8 base run identity byte seal mismatch")
    run = _read_json(run_path)
    progress = _read_json(progress_path)
    index = _read_json(index_path)
    summary = _read_json(summary_path)
    identity = run.get("identity")
    if (
        run.get("format") != V8_BASE_RUN_FORMAT
        or not isinstance(identity, dict)
        or progress.get("identity") != identity
        or index.get("identity") != identity
        or summary.get("identity") != identity
        or int(progress.get("completed_seed_checkpoint_count", -1)) != 15
        or int(summary.get("completed_seed_checkpoint_count", -1)) != 15
        or summary.get("pnl_or_trading_metrics_computed") is not False
    ):
        raise ValueError("V8 base run completion identity mismatch")
    if (
        identity.get("config_sha256") != config_sha256.lower()
        or identity.get("assembly_manifest_sha256") != assembly_manifest_sha256.lower()
    ):
        raise ValueError("V8 base run config/assembly identity mismatch")
    _verify_base_code_identity(root, identity)
    if _file_sha256(predictions_path) != expected_predictions_sha256.lower():
        raise ValueError("V8 base predictions byte seal mismatch")
    prediction_artifact = summary.get("prediction_artifact")
    if (
        not isinstance(prediction_artifact, dict)
        or prediction_artifact.get("sha256") != expected_predictions_sha256.lower()
        or int(prediction_artifact.get("bytes", -1)) != predictions_path.stat().st_size
    ):
        raise ValueError("V8 base prediction summary seal mismatch")
    records = index.get("checkpoints")
    if not isinstance(records, list) or len(records) != 15:
        raise ValueError("V8 base run trebuet exact 15 checkpoints")
    checkpoints = tuple(_verify_checkpoint_sidecar(root, item, identity) for item in records)
    expected_keys = {
        (fold_name, seed)
        for fold_name in (f"outer_{year}" for year in range(2021, 2026))
        for seed in V8_SEEDS
    }
    keys = {(item.fold_name, item.seed) for item in checkpoints}
    if keys != expected_keys:
        raise ValueError("V8 base checkpoint fold/seed matrix mismatch")
    per_fold_statistics: dict[str, set[str]] = {}
    for item in checkpoints:
        per_fold_statistics.setdefault(item.fold_name, set()).add(item.original_statistics_sha256)
    if any(len(values) != 1 for values in per_fold_statistics.values()):
        raise ValueError("V8 original fold statistics SHA zavisit ot seed")
    predictions = pd.read_parquet(predictions_path)
    required_columns = {
        "decision_date",
        "decision_at",
        "capacity_window_open_at",
        "capacity_window_close_at",
        "execution_window_open_at",
        "execution_window_close_at",
        "asset",
        "asset_valid",
        "model_id",
    }
    if not required_columns.issubset(predictions.columns) or len(predictions) != int(
        prediction_artifact.get("rows", -1)
    ):
        raise ValueError("V8 base prediction schema/rows mismatch")
    if predictions.duplicated(["decision_at", "asset", "model_id"]).any():
        raise ValueError("V8 base prediction key duplicate")
    decisions = pd.to_datetime(predictions["decision_at"], utc=True)
    protected = pd.Timestamp(V8_PROTECTED_HOLDOUT_START, tz="UTC")
    if decisions.isna().any() or (decisions >= protected).any():
        raise ValueError("V8 base predictions dostigli protected holdout")
    model_ids = predictions["model_id"].drop_duplicates().tolist()
    if len(model_ids) != 1 or set(predictions["asset"]) != set(V8_ASSETS):
        raise ValueError("V8 base prediction model/assets mismatch")
    inventory = [
        {
            "fold_name": item.fold_name,
            "seed": item.seed,
            "checkpoint_sha256": item.checkpoint_sha256,
            "sidecar_sha256": item.sidecar_sha256,
        }
        for item in sorted(checkpoints, key=lambda value: (value.fold_name, value.seed))
    ]
    return V8VerifiedBaseRun(
        directory=base,
        run_identity_path=run_path,
        run_identity_sha256=_file_sha256(run_path),
        identity=identity,
        predictions_path=predictions_path,
        predictions_sha256=_file_sha256(predictions_path),
        predictions=predictions,
        model_id=str(model_ids[0]),
        checkpoints=checkpoints,
        checkpoint_inventory_sha256=_canonical_json_sha256(inventory),
    )


def build_causal_purged_train_indices(
    inputs: V8CausalInputs,
    fold: V8FoldConfig,
    *,
    purge_sessions: int,
    horizon_common_sessions: int,
    timezone_name: str,
) -> tuple[np.ndarray, np.datetime64]:
    """Vosstanavlivaet original train prefix bez target timing/value dostupa."""
    if (
        isinstance(purge_sessions, bool)
        or isinstance(horizon_common_sessions, bool)
        or purge_sessions <= 0
        or horizon_common_sessions <= 0
    ):
        raise ValueError("V8 enrichment purge/horizon sessions invalid")
    decisions = np.asarray(inputs.decision_times).astype("datetime64[ns]")
    dates = np.asarray(inputs.sample_trade_dates).astype("datetime64[ns]")
    if decisions.ndim != 1 or dates.shape != decisions.shape or np.isnat(decisions).any():
        raise ValueError("V8 enrichment causal calendar invalid")

    def local_midnight(value: date) -> np.datetime64:
        """Prevrashchaet local calendar date v UTC-naive ns."""
        timestamp = (
            pd.Timestamp(value).tz_localize(timezone_name).tz_convert("UTC").tz_localize(None)
        )
        return np.datetime64(timestamp, "ns")

    calendar_start = local_midnight(fold.train_start)
    calendar_end = local_midnight(fold.train_end + pd.Timedelta(days=1))
    candidates = np.flatnonzero((decisions >= calendar_start) & (decisions < calendar_end))
    excluded_tail = purge_sessions + horizon_common_sessions
    if len(candidates) <= excluded_tail:
        raise ValueError("V8 enrichment fold slishkom korotok dlia purge+horizon")
    first_purged_date = pd.Timestamp(dates[candidates[-purge_sessions]]).date()
    cutoff = local_midnight(first_purged_date)
    # Original build_v8_fold_scope first removes purge10, then availability of the
    # five-session supervised horizon removes another five tail decisions.  The
    # same prefix is fully determined by the factual common-session calendar.
    # Reading target availability here would make the enrichment depend on OOS
    # target timing and is therefore deliberately forbidden.
    indices = candidates[:-excluded_tail].astype(np.int64, copy=True)
    if not len(indices) or (len(indices) > 1 and (np.diff(indices) != 1).any()):
        raise ValueError("V8 enrichment train indices ne contiguous")
    horizon_buffer = candidates[-excluded_tail:-purge_sessions]
    if len(horizon_buffer) != horizon_common_sessions:
        raise ValueError("V8 enrichment causal horizon buffer mismatch")
    if (decisions[indices] >= cutoff).any() or (decisions[horizon_buffer] >= cutoff).any():
        raise ValueError("V8 enrichment causal train prefix dostig cutoff")
    selected_bars = np.asarray(inputs.bar_times)[indices].astype("datetime64[ns]")
    if np.isnat(selected_bars).any() or (selected_bars >= cutoff).any():
        raise ValueError("V8 enrichment causal train bars dostigli cutoff")
    indices.flags.writeable = False
    return indices, cutoff


def read_selected_train_target_valid(
    arrays_path: Path,
    train_indices: np.ndarray,
    *,
    expected_shape: tuple[int, int],
) -> np.ndarray:
    """Chitaet edinstvennyi razreshennyi target_valid i vozvrashchaet tol'ko train slice."""
    indices = np.asarray(train_indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices) or (indices < 0).any():
        raise ValueError("V8 target_valid train indices invalid")
    with np.load(arrays_path.resolve(), allow_pickle=False) as payload:
        if "target_valid" not in payload.files:
            raise ValueError("V8 assembly ne soderzhit target_valid")
        target_valid = np.asarray(payload["target_valid"], dtype=bool)
        if target_valid.shape != expected_shape:
            raise ValueError("V8 assembly target_valid shape mismatch")
        selected = target_valid[indices].copy()
        del target_valid
    if selected.shape != (len(indices), expected_shape[1]):
        raise ValueError("V8 selected train target_valid shape mismatch")
    selected.flags.writeable = False
    return selected


def _robust_location_scale(values: np.ndarray) -> tuple[float, float]:
    """Povtoriaet sealed median/IQR s fail-safe scale 1 dlia constanty."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.0, 1.0
    lower, median, upper = np.quantile(finite, (0.25, 0.5, 0.75))
    scale = float(upper - lower)
    if not np.isfinite(scale) or scale <= np.finfo(np.float32).eps:
        scale = 1.0
    return float(median), scale


def fit_target_masked_feature_scaler(
    inputs: V8CausalInputs,
    train_indices: np.ndarray,
    effective_cutoff: np.datetime64,
    selected_train_target_valid: np.ndarray,
    *,
    fold_name: str,
    purge_sessions: int,
    horizon_common_sessions: int,
    original_statistics_sha256: str,
) -> V8FoldScaler:
    """Fitit tol'ko feature scaler; supervised target values API ne prinimaet."""
    indices = np.asarray(train_indices, dtype=np.int64)
    target_valid = np.asarray(selected_train_target_valid, dtype=bool)
    expected = (len(indices), inputs.asset_count)
    if (
        target_valid.shape != expected
        or isinstance(purge_sessions, bool)
        or isinstance(horizon_common_sessions, bool)
        or purge_sessions <= 0
        or horizon_common_sessions <= 0
        or not _is_sha256(original_statistics_sha256)
    ):
        raise ValueError("V8 train-only scaler mask/original SHA invalid")
    intraday = np.asarray(inputs.intraday, dtype=np.float32)[indices]
    asset_valid = np.asarray(inputs.asset_valid, dtype=bool)[indices]
    scaler_asset_valid = asset_valid & target_valid
    bars = np.asarray(inputs.bar_times)[indices].astype("datetime64[ns]")
    temporal = bars < np.datetime64(effective_cutoff, "ns")
    bar_valid = np.asarray(inputs.intraday_valid, dtype=bool)[indices]
    bar_valid &= scaler_asset_valid[..., None]
    bar_valid &= temporal[:, None, :]
    intraday_stats = tuple(
        _robust_location_scale(intraday[..., feature][bar_valid])
        for feature in range(intraday.shape[-1])
    )
    daily = np.asarray(inputs.daily_context, dtype=np.float32)[indices]
    daily_valid = np.asarray(inputs.daily_valid, dtype=bool)[indices]
    daily_valid &= scaler_asset_valid[..., None]
    daily_stats = tuple(
        _robust_location_scale(daily[..., feature][daily_valid[..., feature]])
        for feature in range(daily.shape[-1])
    )
    payload = {
        "fold_name": fold_name,
        "effective_cutoff": str(np.datetime64(effective_cutoff, "ns")),
        "purge_sessions": purge_sessions,
        "horizon_common_sessions": horizon_common_sessions,
        "train_sample_count": len(indices),
        "intraday_median": [item[0] for item in intraday_stats],
        "intraday_iqr": [item[1] for item in intraday_stats],
        "daily_median": [item[0] for item in daily_stats],
        "daily_iqr": [item[1] for item in daily_stats],
        "train_indices_sha256": _array_sha256(indices),
        "train_target_valid_sha256": _array_sha256(target_valid),
        "scaler_asset_mask_sha256": _array_sha256(scaler_asset_valid),
        "original_statistics_sha256": original_statistics_sha256.lower(),
    }
    return V8FoldScaler(
        fold_name=fold_name,
        effective_cutoff=payload["effective_cutoff"],
        purge_sessions=payload["purge_sessions"],
        horizon_common_sessions=payload["horizon_common_sessions"],
        train_sample_count=payload["train_sample_count"],
        intraday_median=tuple(payload["intraday_median"]),
        intraday_iqr=tuple(payload["intraday_iqr"]),
        daily_median=tuple(payload["daily_median"]),
        daily_iqr=tuple(payload["daily_iqr"]),
        train_indices_sha256=payload["train_indices_sha256"],
        train_target_valid_sha256=payload["train_target_valid_sha256"],
        scaler_asset_mask_sha256=payload["scaler_asset_mask_sha256"],
        original_statistics_sha256=payload["original_statistics_sha256"],
        scaler_statistics_sha256=_canonical_json_sha256(payload),
    )


def extract_sealed_fold_scalers(
    inputs: V8CausalInputs,
    arrays_path: Path,
    config: V8ResearchConfig,
    base_run: V8VerifiedBaseRun,
    *,
    target_valid_reader: Callable[..., np.ndarray] = read_selected_train_target_valid,
) -> tuple[V8FoldScaler, ...]:
    """Izvlekaet train-only mask odin raz i vozvrashchaet tol'ko sealed scalers."""
    original_by_fold: dict[str, set[str]] = {}
    for checkpoint in base_run.checkpoints:
        original_by_fold.setdefault(checkpoint.fold_name, set()).add(
            checkpoint.original_statistics_sha256
        )
    scalers: list[V8FoldScaler] = []
    for fold in config.development.folds:
        original = original_by_fold.get(fold.name, set())
        if len(original) != 1:
            raise ValueError("V8 fold ne imeet odin original statistics SHA")
        indices, cutoff = build_causal_purged_train_indices(
            inputs,
            fold,
            purge_sessions=config.development.purge_sessions,
            horizon_common_sessions=config.supervised_target.horizon_common_sessions,
            timezone_name=config.development.decision_timezone,
        )
        selected = target_valid_reader(
            arrays_path,
            indices,
            expected_shape=(inputs.sample_count, inputs.asset_count),
        )
        scalers.append(
            fit_target_masked_feature_scaler(
                inputs,
                indices,
                cutoff,
                selected,
                fold_name=fold.name,
                purge_sessions=config.development.purge_sessions,
                horizon_common_sessions=config.supervised_target.horizon_common_sessions,
                original_statistics_sha256=next(iter(original)),
            )
        )
        del selected
    if len(scalers) != 5:
        raise ValueError("V8 enrichment trebuet exact five fold scalers")
    return tuple(scalers)


def build_target_free_inference_view(
    inputs: V8CausalInputs,
    sample_indices: np.ndarray,
) -> V8InferenceView:
    """Materializuet OOS tol'ko iz causal whitelist bez target container."""
    indices = np.asarray(sample_indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices) or len(np.unique(indices)) != len(indices):
        raise ValueError("V8 enrichment OOS indices invalid")
    factual_asset = np.asarray(inputs.intraday_valid, dtype=bool)[indices].any(axis=-1)
    effective_asset = np.asarray(inputs.asset_valid, dtype=bool)[indices] & factual_asset
    return V8InferenceView(
        intraday=np.asarray(inputs.intraday)[indices].copy(),
        intraday_valid=np.asarray(inputs.intraday_valid)[indices].copy(),
        daily_context=np.asarray(inputs.daily_context)[indices].copy(),
        daily_valid=np.asarray(inputs.daily_valid)[indices].copy(),
        asset_valid=effective_asset.copy(),
        bar_times=np.asarray(inputs.bar_times)[indices].copy(),
        decision_times=np.asarray(inputs.decision_times)[indices].copy(),
        sample_trade_dates=np.asarray(inputs.sample_trade_dates)[indices].copy(),
        global_sample_indices=indices.copy(),
    )


def _scaled_feature_array(
    values: np.ndarray,
    valid: np.ndarray,
    median: Sequence[float],
    iqr: Sequence[float],
    label: str,
) -> np.ndarray:
    """Primeniaet train-only scaler i zanuliaet masked causal observations."""
    source = np.asarray(values, dtype=np.float32)
    mask = np.asarray(valid, dtype=bool)
    if source.ndim == mask.ndim + 1:
        mask = np.broadcast_to(mask[..., None], source.shape)
    if mask.shape != source.shape:
        raise ValueError(f"V8 enrichment {label} mask shape mismatch")
    center = np.asarray(median, dtype=np.float32)
    scale = np.asarray(iqr, dtype=np.float32)
    if center.shape != source.shape[-1:] or scale.shape != center.shape:
        raise ValueError(f"V8 enrichment {label} statistics shape mismatch")
    if not np.isfinite(center).all() or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError(f"V8 enrichment {label} statistics invalid")
    if not np.isfinite(source[mask]).all():
        raise ValueError(f"V8 enrichment {label} factual input ne finite")
    return np.where(mask, (source - center) / scale, np.float32(0.0)).astype(
        np.float32,
        copy=False,
    )


def _preverify_torch_checkpoints(
    checkpoints: Sequence[V8CheckpointBundle],
    config: V8ResearchConfig,
) -> dict[str, Any]:
    """Deserializuet vse weights na CPU i proveryaet ih do CUDA initialization."""
    import torch

    model_config_sha = _canonical_json_sha256(config.model.model_dump(mode="json"))
    state_signature: tuple[tuple[str, tuple[int, ...], str], ...] | None = None
    total_numel: int | None = None
    for bundle in checkpoints:
        payload = torch.load(bundle.checkpoint_path, map_location="cpu", weights_only=True)
        expected = {
            "format": V8_TORCH_CHECKPOINT_FORMAT,
            "fold_name": bundle.fold_name,
            "seed": bundle.seed,
            "ssl_epochs": 48,
            "supervised_epochs": 32,
            "model_config_sha256": model_config_sha,
        }
        if not isinstance(payload, dict) or any(
            payload.get(key) != value for key, value in expected.items()
        ):
            raise ValueError("V8 enrichment checkpoint torch semantic mismatch")
        state = payload.get("model_state_dict")
        if not isinstance(state, dict) or not state:
            raise ValueError("V8 enrichment checkpoint state_dict otsutstvuet")
        signature = tuple(
            (name, tuple(tensor.shape), str(tensor.dtype)) for name, tensor in state.items()
        )
        numel = sum(int(tensor.numel()) for tensor in state.values())
        if numel != config.model.expected_parameter_count or any(
            not bool(torch.isfinite(tensor).all()) for tensor in state.values()
        ):
            raise ValueError("V8 enrichment checkpoint weights invalid")
        if state_signature is None:
            state_signature = signature
            total_numel = numel
        elif signature != state_signature or numel != total_numel:
            raise ValueError("V8 enrichment checkpoint architecture drift")
        del payload, state
    return {
        "checkpoint_count": len(checkpoints),
        "state_tensor_count": len(state_signature or ()),
        "parameter_count": total_numel,
        "state_signature_sha256": _canonical_json_sha256(state_signature),
        "torch_version": str(torch.__version__),
    }


def _configure_inference_runtime(device_name: str) -> tuple[Any, Any, dict[str, Any]]:
    """Inicializiruet deterministic BF16 CUDA tol'ko posle vseh preflight seals."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch

    device = torch.device(device_name)
    if device.type != "cuda" or not torch.cuda.is_available():
        raise RuntimeError("V8 enrichment real inference trebuet CUDA")
    torch.cuda.set_device(device)
    accelerator = torch.cuda.get_device_name(device)
    if "RTX 5090" not in accelerator:
        raise RuntimeError(f"V8 enrichment accelerator ne RTX 5090: {accelerator}")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("V8 enrichment CUDA ne podderzhivaet BF16")
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    if torch.backends.cudnn.is_available():
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
    runtime = {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "torch_cuda": str(torch.version.cuda),
        "cudnn": int(torch.backends.cudnn.version() or 0),
        "device": str(device),
        "device_name": accelerator,
        "precision": "bfloat16",
        "deterministic_algorithms": True,
        "tf32": False,
        "inference_batch_size": V8_INFERENCE_BATCH_SIZE,
    }
    return torch, device, runtime


def predict_checkpoint_outputs(
    checkpoint: V8CheckpointBundle,
    inference: V8InferenceView,
    scaler: V8FoldScaler,
    config: V8ResearchConfig,
    *,
    torch_module: Any,
    device: Any,
    batch_size: int = V8_INFERENCE_BATCH_SIZE,
) -> V8CheckpointOutput:
    """Schitaet diagnostic i replay fields iz odnogo causal forward pass."""
    from market_lab.futures_v8.model import (
        CausalPatchStateSpaceRegimeAlphaModel,
        model_architecture_manifest,
        set_v8_determinism,
    )

    if checkpoint.fold_name != scaler.fold_name:
        raise ValueError("V8 enrichment checkpoint/scaler fold mismatch")
    if _file_sha256(checkpoint.checkpoint_path) != checkpoint.checkpoint_sha256:
        raise ValueError("V8 enrichment checkpoint drift pered inference")
    set_v8_determinism(checkpoint.seed)
    payload = torch_module.load(checkpoint.checkpoint_path, map_location="cpu", weights_only=True)
    model = CausalPatchStateSpaceRegimeAlphaModel(config.model)
    manifest = model_architecture_manifest(model)
    if manifest["parameter_count"] != config.model.expected_parameter_count:
        raise ValueError("V8 enrichment model parameter seal mismatch")
    model.load_state_dict(payload["model_state_dict"], strict=True)
    model.to(device)
    model.eval()
    intraday = _scaled_feature_array(
        inference.intraday,
        inference.intraday_valid,
        scaler.intraday_median,
        scaler.intraday_iqr,
        "intraday",
    )
    daily = _scaled_feature_array(
        inference.daily_context,
        inference.daily_valid,
        scaler.daily_median,
        scaler.daily_iqr,
        "daily",
    )
    samples = len(inference.global_sample_indices)
    assets = len(V8_ASSETS)
    regimes = np.empty((samples, len(V8_REGIME_NAMES)), dtype=np.float32)
    factor_abstain = np.empty(samples, dtype=np.float32)
    residual_abstain = np.zeros((samples, assets), dtype=np.float32)
    factor_location = np.empty(samples, dtype=np.float32)
    factor_scale = np.empty(samples, dtype=np.float32)
    factor_score = np.empty(samples, dtype=np.float32)
    residual_location = np.zeros((samples, assets), dtype=np.float32)
    residual_scale = np.zeros((samples, assets), dtype=np.float32)
    residual_score = np.zeros((samples, assets), dtype=np.float32)
    direction_logit = np.zeros((samples, assets), dtype=np.float32)
    for start in range(0, samples, batch_size):
        stop = min(start + batch_size, samples)
        factual_asset = np.asarray(inference.asset_valid[start:stop], dtype=bool) & np.asarray(
            inference.intraday_valid[start:stop],
            dtype=bool,
        ).any(axis=-1)

        def tensor(values: np.ndarray) -> Any:
            """Perenosit contiguous causal batch na fixed device."""
            return torch_module.from_numpy(np.ascontiguousarray(values)).to(device)

        with (
            torch_module.inference_mode(),
            torch_module.autocast(
                device_type="cuda",
                dtype=torch_module.bfloat16,
                enabled=True,
            ),
        ):
            output = model(
                tensor(intraday[start:stop]),
                tensor(np.asarray(inference.intraday_valid[start:stop], dtype=bool)),
                tensor(daily[start:stop]),
                tensor(np.asarray(inference.daily_valid[start:stop], dtype=bool)),
                tensor(factual_asset),
            )
        regimes[start:stop] = output.regime_probabilities.float().cpu().numpy()
        factor_abstain[start:stop] = output.factor_abstain_probability.float().cpu().numpy()
        residual_abstain[start:stop] = output.abstain_probability.float().cpu().numpy()
        factor_location[start:stop] = output.factor_location.float().cpu().numpy()
        factor_scale[start:stop] = output.factor_scale.float().cpu().numpy()
        factor_score[start:stop] = output.factor_decision_score.float().cpu().numpy()
        residual_location[start:stop] = output.residual_location.float().cpu().numpy()
        residual_scale[start:stop] = output.total_scale.float().cpu().numpy()
        residual_score[start:stop] = output.decision_score.float().cpu().numpy()
        direction_logit[start:stop] = output.direction_logit.float().cpu().numpy()
    diagnostic = V8DiagnosticOutput(regimes, factor_abstain, residual_abstain)
    validate_diagnostic_output(diagnostic, inference)
    prediction = V8SeedPrediction(
        factor_location=factor_location,
        factor_scale=factor_scale,
        factor_score=factor_score,
        residual_location=residual_location,
        residual_scale=residual_scale,
        residual_decision_score=residual_score,
        direction_logit=direction_logit,
    )
    del model, payload
    torch_module.cuda.empty_cache()
    return V8CheckpointOutput(diagnostic=diagnostic, base_prediction=prediction)


def validate_diagnostic_output(output: V8DiagnosticOutput, inference: V8InferenceView) -> None:
    """Trebuet calibrated simplex i finite abstention tol'ko na causal valid cells."""
    samples = len(inference.global_sample_indices)
    regimes = np.asarray(output.regime_probabilities, dtype=np.float64)
    factor = np.asarray(output.factor_abstain_probability, dtype=np.float64)
    residual = np.asarray(output.residual_abstain_probability, dtype=np.float64)
    if (
        regimes.shape != (samples, 3)
        or factor.shape != (samples,)
        or residual.shape
        != (
            samples,
            len(V8_ASSETS),
        )
    ):
        raise ValueError("V8 enrichment diagnostic shape mismatch")
    sample_valid = np.asarray(inference.asset_valid, dtype=bool).any(axis=1)
    valid = np.asarray(inference.asset_valid, dtype=bool)
    if (
        not np.isfinite(regimes[sample_valid]).all()
        or not np.isfinite(factor[sample_valid]).all()
        or not np.isfinite(residual[valid]).all()
    ):
        raise ValueError("V8 enrichment diagnostic ne finite")
    if (
        (regimes[sample_valid] < 0).any()
        or (regimes[sample_valid] > 1).any()
        or not np.allclose(regimes[sample_valid].sum(axis=1), 1.0, atol=5e-4, rtol=0.0)
        or (factor[sample_valid] < 0).any()
        or (factor[sample_valid] > 1).any()
        or (residual[valid] < 0).any()
        or (residual[valid] > 1).any()
    ):
        raise ValueError("V8 enrichment probability calibration invalid")


def _base_fold_template(
    base: V8VerifiedBaseRun,
    inference: V8InferenceView,
) -> pd.DataFrame:
    """Sveriaet exact OOS calendar/model/mask s immutable base predictions."""
    decisions = pd.DatetimeIndex(
        np.asarray(inference.decision_times).astype("datetime64[ns]")
    ).tz_localize("UTC")
    selected = base.predictions[
        pd.to_datetime(base.predictions["decision_at"], utc=True).isin(decisions)
    ].copy()
    selected = selected.sort_values(
        ["decision_at", "asset", "model_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    expected_decisions = np.repeat(decisions.to_numpy(), len(V8_ASSETS))
    expected_assets = np.tile(np.asarray(V8_ASSETS, dtype=object), len(decisions))
    expected_valid = np.asarray(inference.asset_valid, dtype=bool).reshape(-1)
    if (
        len(selected) != len(expected_decisions)
        or not np.array_equal(
            pd.to_datetime(selected["decision_at"], utc=True).to_numpy(),
            expected_decisions,
        )
        or not np.array_equal(selected["asset"].to_numpy(object), expected_assets)
        or not np.array_equal(selected["asset_valid"].to_numpy(bool), expected_valid)
        or selected["model_id"].nunique() != 1
        or str(selected["model_id"].iloc[0]) != base.model_id
    ):
        raise ValueError("V8 enrichment OOS calendar/model/mask ne sovpal s base")
    return selected


def build_per_seed_enrichment_frame(
    base_template: pd.DataFrame,
    inference: V8InferenceView,
    output: V8DiagnosticOutput,
    checkpoint: V8CheckpointBundle,
) -> pd.DataFrame:
    """Stroit per-seed long frame bez dobavleniya target ili trading kolonok."""
    validate_diagnostic_output(output, inference)
    assets = len(V8_ASSETS)
    valid = np.asarray(inference.asset_valid, dtype=bool)
    sample_valid = valid.any(axis=1)
    regimes = np.asarray(output.regime_probabilities, dtype=np.float32)
    frame = base_template[
        [
            "decision_date",
            "decision_at",
            "capacity_window_open_at",
            "capacity_window_close_at",
            "execution_window_open_at",
            "execution_window_close_at",
            "asset",
            "asset_valid",
            "model_id",
        ]
    ].copy()
    frame["fold_name"] = checkpoint.fold_name
    frame["seed"] = checkpoint.seed
    frame["checkpoint_sha256"] = checkpoint.checkpoint_sha256
    repeated_sample_valid = np.repeat(sample_valid, assets)
    for index, name in enumerate(V8_REGIME_NAMES):
        frame[f"regime_probability_{name}"] = np.where(
            repeated_sample_valid,
            np.repeat(regimes[:, index], assets),
            np.nan,
        )
    frame["factor_abstain_probability"] = np.where(
        repeated_sample_valid,
        np.repeat(np.asarray(output.factor_abstain_probability, dtype=np.float32), assets),
        np.nan,
    )
    frame["residual_abstain_probability"] = np.where(
        valid,
        np.asarray(output.residual_abstain_probability, dtype=np.float32),
        np.nan,
    ).reshape(-1)
    return frame.loc[:, list(V8_PER_SEED_COLUMNS)]


def ensemble_diagnostic_outputs(
    outputs: Sequence[V8DiagnosticOutput],
    inference: V8InferenceView,
) -> V8DiagnosticOutput:
    """Usredniaet fixed three seeds bez selection i normalizuet probability simplex."""
    if len(outputs) != len(V8_SEEDS):
        raise ValueError("V8 enrichment ensemble trebuet exact three seeds")
    for output in outputs:
        validate_diagnostic_output(output, inference)
    regimes = np.mean(
        np.stack([item.regime_probabilities for item in outputs]).astype(np.float64),
        axis=0,
    )
    denominator = regimes.sum(axis=1, keepdims=True)
    if not np.isfinite(denominator).all() or (denominator <= 0).any():
        raise ValueError("V8 enrichment ensemble regime denominator invalid")
    result = V8DiagnosticOutput(
        regime_probabilities=(regimes / denominator).astype(np.float32),
        factor_abstain_probability=np.mean(
            np.stack([item.factor_abstain_probability for item in outputs]).astype(np.float64),
            axis=0,
        ).astype(np.float32),
        residual_abstain_probability=np.mean(
            np.stack([item.residual_abstain_probability for item in outputs]).astype(np.float64),
            axis=0,
        ).astype(np.float32),
    )
    validate_diagnostic_output(result, inference)
    return result


def build_ensemble_enrichment_frame(
    base_template: pd.DataFrame,
    inference: V8InferenceView,
    output: V8DiagnosticOutput,
    fold_name: str,
    checkpoint_shas: Sequence[str],
) -> pd.DataFrame:
    """Stroit fixed three-seed mean frame s exact base calendar/model identity."""
    synthetic_checkpoint = V8CheckpointBundle(
        fold_name=fold_name,
        seed=V8_SEEDS[0],
        checkpoint_path=Path("unused"),
        checkpoint_sha256="0" * 64,
        sidecar_path=Path("unused"),
        sidecar_sha256="0" * 64,
        original_statistics_sha256="0" * 64,
    )
    per_seed_shape = build_per_seed_enrichment_frame(
        base_template,
        inference,
        output,
        synthetic_checkpoint,
    )
    frame = per_seed_shape.drop(columns=["seed", "checkpoint_sha256"])
    frame["seed_count"] = len(V8_SEEDS)
    frame["seed_set_sha256"] = _canonical_json_sha256(
        {"seeds": list(V8_SEEDS), "checkpoint_sha256": list(checkpoint_shas)}
    )
    return frame.loc[:, list(V8_ENSEMBLE_COLUMNS)]


def verify_exact_base_prediction_replay(
    base_template: pd.DataFrame,
    inference: V8InferenceView,
    seed_predictions: Sequence[V8SeedPrediction],
    *,
    fold_name: str,
    model_id: str,
) -> dict[str, Any]:
    """Trebuet exact replay vseh semi base fields i mask do publication."""
    if len(seed_predictions) != len(V8_SEEDS):
        raise ValueError("V8 base replay trebuet exact three seeds")
    replay_prediction = ensemble_v8_seed_predictions(seed_predictions, inference)
    replayed = build_v8_oos_prediction_frame(inference, replay_prediction, model_id)
    order = ["decision_at", "asset", "model_id"]
    expected = base_template.sort_values(order, kind="mergesort").reset_index(drop=True)
    replayed = replayed.sort_values(order, kind="mergesort").reset_index(drop=True)
    if len(expected) != len(replayed):
        raise ValueError("V8 base replay row count mismatch")

    timestamp_columns = {
        "decision_date",
        "decision_at",
        "capacity_window_open_at",
        "capacity_window_close_at",
        "execution_window_open_at",
        "execution_window_close_at",
    }
    for column in V8_BASE_REPLAY_IDENTITY_COLUMNS:
        if column in timestamp_columns:
            left = pd.to_datetime(expected[column], utc=True).to_numpy()
            right = pd.to_datetime(replayed[column], utc=True).to_numpy()
        else:
            left = expected[column].to_numpy()
            right = replayed[column].to_numpy()
        if not np.array_equal(left, right):
            raise ValueError(f"V8 base replay identity/mask mismatch: {column}")

    base_column_sha256: dict[str, str] = {}
    replay_column_sha256: dict[str, str] = {}
    max_abs_diff: dict[str, float] = {}
    for column in V8_BASE_REPLAY_NUMERIC_COLUMNS:
        left = expected[column].to_numpy(np.float64)
        right = replayed[column].to_numpy(np.float64)
        finite_pair = np.isfinite(left) & np.isfinite(right)
        difference = np.abs(left[finite_pair] - right[finite_pair])
        maximum = float(difference.max()) if len(difference) else 0.0
        max_abs_diff[column] = maximum
        base_column_sha256[column] = _array_sha256(left)
        replay_column_sha256[column] = _array_sha256(right)
        if not np.array_equal(left, right, equal_nan=True):
            equal = (left == right) | (np.isnan(left) & np.isnan(right))
            mismatch_count = int((~equal).sum())
            raise ValueError(
                "V8 base replay numeric mismatch: "
                f"{fold_name}/{column}, cells={mismatch_count}, max_abs={maximum}"
            )
    if base_column_sha256 != replay_column_sha256 or any(max_abs_diff.values()):
        raise ValueError("V8 base replay cryptographic equality mismatch")

    asset_valid = expected["asset_valid"].to_numpy(bool)
    return {
        "fold_name": fold_name,
        "rows": len(expected),
        "valid_rows": int(asset_valid.sum()),
        "invalid_rows": int((~asset_valid).sum()),
        "seed_count": len(V8_SEEDS),
        "comparison": "numpy_exact_equal_nan_after_exact_identity_and_mask",
        "numeric_columns": list(V8_BASE_REPLAY_NUMERIC_COLUMNS),
        "column_sha256": base_column_sha256,
        "asset_valid_sha256": _array_sha256(asset_valid),
        "max_abs_diff": max_abs_diff,
        "exact": True,
    }


def _artifact_record(path: Path, root: Path, *, rows: int | None = None) -> dict[str, Any]:
    """Stroit path/bytes/SHA record immutable artefakta."""
    record: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
    }
    if rows is not None:
        record["rows"] = int(rows)
    return record


def _assert_source_unchanged(
    project_root: Path,
    base: V8VerifiedBaseRun,
    enrichment_code_identity: dict[str, Any],
) -> None:
    """Otkazyvaet publication pri drift original ili enrichment code/base prediction."""
    _verify_base_code_identity(project_root, base.identity)
    if build_v8_enrichment_code_identity(project_root) != enrichment_code_identity:
        raise ValueError("V8 enrichment runtime code drift")
    if _file_sha256(base.predictions_path) != base.predictions_sha256:
        raise ValueError("V8 immutable base predictions izmenilis'")


def run_v8_regime_enrichment(
    project_root: Path,
    config_path: Path,
    assembly_manifest_path: Path,
    base_run_directory: Path,
    output_directory: Path,
    *,
    expected_config_sha256: str = DEFAULT_V8_CONFIG_SHA256,
    expected_assembly_manifest_sha256: str,
    expected_base_run_identity_sha256: str,
    expected_base_predictions_sha256: str,
    expected_enrichment_code_identity_sha256: str,
    device: str = "cuda:0",
) -> V8EnrichmentArtifacts:
    """Vypolniaet sealed scaler extraction i target-free checkpoint enrichment."""
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    root = project_root.resolve()
    output = _bounded_path(root, output_directory, "V8 enrichment output")
    runs_root = (root / "runs").resolve()
    try:
        output.relative_to(runs_root)
    except ValueError as error:
        raise ValueError("V8 enrichment output dolzhen byt' v runs root") from error
    if output.exists():
        raise FileExistsError(f"Immutable V8 enrichment output uzhe sushchestvuet: {output}")
    config_resolved = _bounded_path(root, config_path, "V8 config")
    config = load_v8_research_config(config_resolved, expected_config_sha256)
    assembly = verify_v8_assembly_manifest(
        root,
        assembly_manifest_path,
        expected_assembly_manifest_sha256,
    )
    base = verify_v8_base_run(
        root,
        base_run_directory,
        expected_run_identity_sha256=expected_base_run_identity_sha256,
        expected_predictions_sha256=expected_base_predictions_sha256,
        config_sha256=expected_config_sha256,
        assembly_manifest_sha256=expected_assembly_manifest_sha256,
    )
    code_identity = build_v8_enrichment_code_identity(root)
    if (
        not _is_sha256(expected_enrichment_code_identity_sha256)
        or code_identity["code_identity_sha256"] != expected_enrichment_code_identity_sha256.lower()
    ):
        raise ValueError("V8 enrichment code identity pre-CUDA mismatch")
    causal_inputs = load_v7_causal_inputs(assembly.arrays_path)
    if (
        causal_inputs.source_sha256 != assembly.arrays_sha256
        or causal_inputs.keys_read != V8_CAUSAL_V7_KEYS
    ):
        raise ValueError("V8 enrichment causal whitelist/array SHA mismatch")
    scalers = extract_sealed_fold_scalers(causal_inputs, assembly.arrays_path, config, base)
    cpu_checkpoint_audit = _preverify_torch_checkpoints(base.checkpoints, config)
    _assert_source_unchanged(root, base, code_identity)
    staging = output.parent / f".{output.name}.staging-{uuid.uuid4().hex[:12]}"
    staging.mkdir(parents=True, exist_ok=False)
    identity = {
        "format": V8_ENRICHMENT_FORMAT,
        "base_run_id": base.directory.name,
        "base_run_identity_sha256": base.run_identity_sha256,
        "base_predictions_sha256": base.predictions_sha256,
        "base_checkpoint_inventory_sha256": base.checkpoint_inventory_sha256,
        "config_sha256": expected_config_sha256.lower(),
        "assembly_manifest_sha256": expected_assembly_manifest_sha256.lower(),
        "assembly_arrays_sha256": assembly.arrays_sha256,
        "original_training_code_identity_sha256": base.identity["code_identity_sha256"],
        "enrichment_code_identity": code_identity,
        "enrichment_code_identity_sha256": code_identity["code_identity_sha256"],
        "model_id": base.model_id,
        "seeds": list(V8_SEEDS),
        "causal_train_scope": {
            "selection": "common_session_prefix_excluding_purge_plus_supervised_horizon",
            "purge_sessions": config.development.purge_sessions,
            "horizon_common_sessions": config.supervised_target.horizon_common_sessions,
            "target_timing_read": False,
        },
        "base_prediction_replay_contract": {
            "required_rows": len(base.predictions),
            "numeric_columns": list(V8_BASE_REPLAY_NUMERIC_COLUMNS),
            "comparison": "exact_equal_nan_after_exact_identity_and_asset_valid_mask",
            "publication_on_mismatch": "forbidden",
        },
        "target_access_contract": {
            "train_target_valid_mask_read": True,
            "train_target_values_read": False,
            "oos_target_values_read": False,
            "oos_target_timing_read": False,
            "oos_target_valid_influence": False,
            "inference_reads": "causal_inputs_plus_sealed_fold_scalers_plus_checkpoints_only",
        },
        "cpu_checkpoint_audit": cpu_checkpoint_audit,
    }
    run_identity_path = staging / "run_identity.json"
    write_json(
        run_identity_path,
        {
            "format": V8_ENRICHMENT_FORMAT,
            "research_status": "pre_cuda_identity_and_train_scalers_committed_no_pnl",
            "identity": identity,
        },
    )
    scaler_path = staging / "sealed_fold_scalers.json"
    scaler_payload = {
        "format": V8_SCALER_FORMAT,
        "research_status": "train_mask_only_scalers_no_target_values_no_pnl",
        "target_access_contract": identity["target_access_contract"],
        "causal_train_scope": identity["causal_train_scope"],
        "folds": [item.as_dict() for item in scalers],
    }
    write_json(scaler_path, scaler_payload)
    _assert_source_unchanged(root, base, code_identity)
    torch_module, torch_device, runtime = _configure_inference_runtime(device)
    checkpoint_lookup = {(item.fold_name, item.seed): item for item in base.checkpoints}
    scaler_lookup = {item.fold_name: item for item in scalers}
    per_seed_records: list[dict[str, Any]] = []
    ensemble_frames: list[pd.DataFrame] = []
    base_replay_records: list[dict[str, Any]] = []
    for fold in config.development.folds:
        oos_indices = build_v8_oos_sample_indices(
            causal_inputs.sample_trade_dates,
            causal_inputs.decision_times,
            fold,
            config.development.decision_timezone,
        )
        inference = build_target_free_inference_view(causal_inputs, oos_indices)
        template = _base_fold_template(base, inference)
        outputs: list[V8DiagnosticOutput] = []
        seed_predictions: list[V8SeedPrediction] = []
        checkpoint_shas: list[str] = []
        for seed in V8_SEEDS:
            _assert_source_unchanged(root, base, code_identity)
            checkpoint = checkpoint_lookup[(fold.name, seed)]
            checkpoint_output = predict_checkpoint_outputs(
                checkpoint,
                inference,
                scaler_lookup[fold.name],
                config,
                torch_module=torch_module,
                device=torch_device,
            )
            diagnostic = checkpoint_output.diagnostic
            outputs.append(diagnostic)
            seed_predictions.append(checkpoint_output.base_prediction)
            checkpoint_shas.append(checkpoint.checkpoint_sha256)
            frame = build_per_seed_enrichment_frame(template, inference, diagnostic, checkpoint)
            path = staging / "per_seed" / fold.name / f"seed-{seed}.parquet"
            _atomic_write_parquet(path, frame)
            per_seed_records.append(
                {
                    "fold_name": fold.name,
                    "seed": seed,
                    "checkpoint_sha256": checkpoint.checkpoint_sha256,
                    **_artifact_record(path, staging, rows=len(frame)),
                }
            )
        base_replay_records.append(
            verify_exact_base_prediction_replay(
                template,
                inference,
                seed_predictions,
                fold_name=fold.name,
                model_id=base.model_id,
            )
        )
        ensemble = ensemble_diagnostic_outputs(outputs, inference)
        ensemble_frames.append(
            build_ensemble_enrichment_frame(
                template,
                inference,
                ensemble,
                fold.name,
                checkpoint_shas,
            )
        )
        del outputs, seed_predictions, inference, template
        torch_module.cuda.empty_cache()
    ensemble_frame = (
        pd.concat(ensemble_frames, ignore_index=True)
        .sort_values(
            ["decision_at", "asset", "model_id"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    if ensemble_frame.duplicated(["decision_at", "asset", "model_id"]).any():
        raise ValueError("V8 enrichment ensemble key duplicate")
    regime_columns = [f"regime_probability_{name}" for name in V8_REGIME_NAMES]
    sample_rows = ensemble_frame.drop_duplicates(["decision_at", "model_id"])
    if not np.allclose(
        sample_rows[regime_columns].to_numpy(np.float64).sum(axis=1),
        1.0,
        atol=5e-6,
        rtol=0.0,
    ):
        raise ValueError("V8 enrichment ensemble regime simplex drift")
    ensemble_path = staging / "regime_abstain_ensemble.parquet"
    _atomic_write_parquet(ensemble_path, ensemble_frame)
    _assert_source_unchanged(root, base, code_identity)
    if (
        len(per_seed_records) != 15
        or len(base_replay_records) != 5
        or sum(item["rows"] for item in base_replay_records) != len(base.predictions)
        or _file_sha256(base.predictions_path) != expected_base_predictions_sha256
    ):
        raise ValueError("V8 enrichment artifact/replay count/base immutability mismatch")
    finished_at = datetime.now(UTC)
    artifact_inventory = sorted(
        [
            _artifact_record(run_identity_path, staging),
            _artifact_record(scaler_path, staging),
            _artifact_record(ensemble_path, staging, rows=len(ensemble_frame)),
            *per_seed_records,
        ],
        key=lambda item: item["path"],
    )
    manifest = {
        "format": V8_ENRICHMENT_FORMAT,
        "research_status": "target_free_oos_enrichment_base_replay_exact_no_pnl_no_2026",
        "identity": identity,
        "runtime": {
            **runtime,
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "elapsed_seconds": time.perf_counter() - started_clock,
            "peak_allocated_bytes": int(torch_module.cuda.max_memory_allocated(torch_device)),
            "peak_reserved_bytes": int(torch_module.cuda.max_memory_reserved(torch_device)),
        },
        "base_predictions_unchanged": True,
        "base_predictions_sha256_before_after": [
            expected_base_predictions_sha256.lower(),
            _file_sha256(base.predictions_path),
        ],
        "base_prediction_replay_audit": {
            "status": "exact_match",
            "rows": sum(item["rows"] for item in base_replay_records),
            "valid_rows": sum(item["valid_rows"] for item in base_replay_records),
            "invalid_rows": sum(item["invalid_rows"] for item in base_replay_records),
            "folds": base_replay_records,
        },
        "scaler_artifact": _artifact_record(scaler_path, staging),
        "per_seed_artifacts": per_seed_records,
        "ensemble_artifact": _artifact_record(
            ensemble_path,
            staging,
            rows=len(ensemble_frame),
        ),
        "probability_semantics": {
            "regime_order": list(V8_REGIME_NAMES),
            "regime_sum": 1.0,
            "ensemble": "fixed_arithmetic_mean_over_exact_three_seeds",
            "residual_abstain": "per_asset_model_native_probability",
            "factor_abstain": "global_factor_model_native_probability",
        },
        "artifact_inventory": artifact_inventory,
        "artifact_inventory_sha256": _canonical_json_sha256(artifact_inventory),
        "pnl_or_trading_metrics_computed": False,
        "protected_holdout_accessed": False,
    }
    manifest_path = staging / "enrichment_manifest.json"
    write_json(manifest_path, manifest)
    _assert_source_unchanged(root, base, code_identity)
    os.replace(staging, output)
    return V8EnrichmentArtifacts(
        output_directory=output,
        manifest_path=output / manifest_path.name,
        scaler_path=output / scaler_path.name,
        ensemble_path=output / ensemble_path.name,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Stroit CLI dlia separate immutable enrichment run."""
    parser = argparse.ArgumentParser(
        description="Enrich sealed futures-v8 predictions without OOS targets."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/futures_v8_development_protocol.yaml"),
    )
    parser.add_argument("--config-sha256", default=DEFAULT_V8_CONFIG_SHA256)
    parser.add_argument("--assembly-manifest", type=Path, required=True)
    parser.add_argument("--assembly-manifest-sha256", required=True)
    parser.add_argument("--base-run", type=Path, required=True)
    parser.add_argument("--base-run-identity-sha256", required=True)
    parser.add_argument("--base-predictions-sha256", required=True)
    parser.add_argument("--code-identity-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Zapuskaet enrichment i pechataet paths tol'ko posle atomic publication."""
    arguments = build_argument_parser().parse_args(argv)
    artifacts = run_v8_regime_enrichment(
        arguments.project_root,
        arguments.config,
        arguments.assembly_manifest,
        arguments.base_run,
        arguments.output,
        expected_config_sha256=arguments.config_sha256,
        expected_assembly_manifest_sha256=arguments.assembly_manifest_sha256,
        expected_base_run_identity_sha256=arguments.base_run_identity_sha256,
        expected_base_predictions_sha256=arguments.base_predictions_sha256,
        expected_enrichment_code_identity_sha256=arguments.code_identity_sha256,
        device=arguments.device,
    )
    print(
        json.dumps(
            {
                "output": str(artifacts.output_directory),
                "manifest": str(artifacts.manifest_path),
                "ensemble": str(artifacts.ensemble_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "V8CheckpointOutput",
    "V8DiagnosticOutput",
    "V8EnrichmentArtifacts",
    "V8FoldScaler",
    "build_causal_purged_train_indices",
    "build_ensemble_enrichment_frame",
    "build_per_seed_enrichment_frame",
    "build_target_free_inference_view",
    "build_v8_enrichment_code_identity",
    "ensemble_diagnostic_outputs",
    "extract_sealed_fold_scalers",
    "fit_target_masked_feature_scaler",
    "predict_checkpoint_outputs",
    "read_selected_train_target_valid",
    "run_v8_regime_enrichment",
    "validate_diagnostic_output",
    "verify_exact_base_prediction_replay",
    "verify_v8_base_run",
]
