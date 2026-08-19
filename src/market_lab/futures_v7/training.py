"""Deterministichnoe train-only obuchenie i checkpointing futures-v7."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import numpy as np
import torch
from torch import nn
from torch.nn import functional as functional
from torch.utils.data import DataLoader, Dataset, Sampler

from market_lab.futures_v7.config import (
    V7_SEEDS,
    V7FoldConfig,
    V7ModelConfig,
    V7ResearchConfig,
    V7TrainingConfig,
)
from market_lab.futures_v7.contracts import DecisionTimingBatch
from market_lab.futures_v7.dataset import MultiResolutionArrays, SelfSupervisedTargets
from market_lab.futures_v7.model import (
    CausalMultiResolutionFuturesModel,
    configure_supervised_finetuning,
    masked_ssl_loss,
    masked_supervised_loss,
    model_architecture_manifest,
    set_v7_determinism,
)
from market_lab.io_utils import atomic_write_bytes, write_json

V7_TRAIN_BATCH_SIZE = 8  # Fiksirovannyi razmer batch, ne podbiraemyi po OOS.
V7_INFERENCE_BATCH_SIZE = 32  # Fiksirovannyi batch tol'ko dlya inference.
V7_DATALOADER_WORKERS = 0  # Odin process isklyuchaet skrytyi worker-state.
V7_RANKING_WEIGHT = 0.25  # Fiksirovannyi ves within-timestamp pairwise loss.
V7_TARGET_SCALE_FLOOR = 1e-4  # Nizhnyaya granica train-IQR dlya ranking temperature.
V7_NORMALIZATION_VERSION = "train-fold-median-iqr-v1"  # Versiya robust normalizacii.
V7_CHECKPOINT_FORMAT = "market-lab-futures-v7-seed-checkpoint-v2"  # Format checkpoint.
V7_MANIFEST_FORMAT = "market-lab-futures-v7-seed-manifest-v1"  # Format sidecar manifest.
V7_RESUME_SEMANTICS = (  # Resume tol'ko polnost'yu zavershennogo seed-run.
    "completed_seed_checkpoint_only_no_mid_stage_resume"
)
V7_SSL_STAGE_SEED_OFFSET = 10_000  # Razdelitel' shuffle-potoka SSL.
V7_SUPERVISED_STAGE_SEED_OFFSET = 20_000  # Razdelitel' shuffle-potoka supervised.


def _canonical_json_bytes(payload: Any) -> bytes:
    """Serializuet prostoi payload stabil'no dlya kriptograficheskogo hash."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_sha256(payload: Any) -> str:
    """Vychislyaet SHA-256 kanonicheskogo JSON-payload."""
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo bez zagruzki v pamyat'."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _local_midnight_utc(day: date, timezone_name: str) -> np.datetime64:
    """Perevodit lokal'nuyu granicu trade-date v naive UTC nanoseconds."""
    local = datetime.combine(day, time.min, tzinfo=ZoneInfo(timezone_name))
    utc_naive = local.astimezone(UTC).replace(tzinfo=None)
    return np.datetime64(utc_naive, "ns")


def _timestamp_local_date(value: np.datetime64, timezone_name: str) -> date:
    """Vozvrashchaet lokal'nuyu datu dlya numpy UTC timestamp bez float-rounding."""
    nanoseconds = int(np.datetime64(value, "ns").astype(np.int64))
    utc_value = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
        microseconds=nanoseconds // 1_000
    )
    return utc_value.astimezone(ZoneInfo(timezone_name)).date()


def _readonly_int64(values: np.ndarray) -> np.ndarray:
    """Kopiruet indeksy i zapreshchaet ih mutaciyu posle postroeniya scope."""
    result = np.asarray(values, dtype=np.int64).copy()
    result.flags.writeable = False
    return result


@dataclass(frozen=True)
class FoldTrainingScope:
    """Fiksiruet train samples i fakticheskuyu granicu posle session-purge."""

    fold_name: str
    sample_indices: np.ndarray
    calendar_start_utc: np.datetime64
    calendar_end_exclusive_utc: np.datetime64
    effective_end_exclusive_utc: np.datetime64
    purge_sessions: int
    timezone_name: str

    def as_dict(self) -> dict[str, Any]:
        """Serializuet granicy i hash indeksov bez ogromnogo spiska samples."""
        return {
            "fold_name": self.fold_name,
            "sample_count": int(len(self.sample_indices)),
            "sample_indices_sha256": hashlib.sha256(
                np.ascontiguousarray(self.sample_indices).tobytes()
            ).hexdigest(),
            "calendar_start_utc": str(self.calendar_start_utc),
            "calendar_end_exclusive_utc": str(self.calendar_end_exclusive_utc),
            "effective_end_exclusive_utc": str(self.effective_end_exclusive_utc),
            "purge_sessions": self.purge_sessions,
            "timezone_name": self.timezone_name,
        }


def build_fold_training_scope(
    timing: DecisionTimingBatch,
    fold: V7FoldConfig,
    timezone_name: str,
    purge_sessions: int,
) -> FoldTrainingScope:
    """Vyberaet train tol'ko po decision/exit i udalyaet poslednie session do OOS."""
    if purge_sessions < 0:
        raise ValueError("purge_sessions ne mozhet byt' otricatel'nym")
    timing.validate()
    decisions = np.asarray(timing.decision_times).astype("datetime64[ns]")
    exits = np.asarray(timing.exit_open_times).astype("datetime64[ns]")
    calendar_start = _local_midnight_utc(fold.train_start, timezone_name)
    calendar_end = _local_midnight_utc(fold.train_end + timedelta(days=1), timezone_name)
    calendar_candidate = (
        (decisions >= calendar_start)
        & (decisions < calendar_end)
        & (exits < calendar_end)
    )
    candidate_indices = np.flatnonzero(calendar_candidate)
    if not len(candidate_indices):
        raise ValueError(f"Fold {fold.name} ne soderzhit train samples")
    session_dates = sorted(
        {
            _timestamp_local_date(decisions[index], timezone_name)
            for index in candidate_indices
        }
    )
    if purge_sessions:
        if len(session_dates) <= purge_sessions:
            raise ValueError("Purge udalil by vse train sessions")
        first_purged_date = session_dates[-purge_sessions]
        effective_end = _local_midnight_utc(first_purged_date, timezone_name)
    else:
        effective_end = calendar_end
    selected = np.flatnonzero(
        (decisions >= calendar_start)
        & (decisions < effective_end)
        & (exits < effective_end)
    )
    if not len(selected):
        raise ValueError(f"Fold {fold.name} pust posle target-boundary i purge")
    return FoldTrainingScope(
        fold_name=fold.name,
        sample_indices=_readonly_int64(selected),
        calendar_start_utc=calendar_start,
        calendar_end_exclusive_utc=calendar_end,
        effective_end_exclusive_utc=effective_end,
        purge_sessions=purge_sessions,
        timezone_name=timezone_name,
    )


def _validate_scope(timing: DecisionTimingBatch, scope: FoldTrainingScope) -> None:
    """Fail-closed proveryaet scope protiv fakticheskih decision i exit timestamps."""
    indices = np.asarray(scope.sample_indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices):
        raise ValueError("Fold scope trebuet nepustoi odnomernyi indeks")
    if (indices < 0).any() or (indices >= len(timing.decision_times)).any():
        raise ValueError("Fold scope soderzhit indeks vne timing")
    if len(np.unique(indices)) != len(indices) or (np.diff(indices) <= 0).any():
        raise ValueError("Fold scope indices dolzhny byt' strogo vozrastayushchimi")
    decisions = np.asarray(timing.decision_times).astype("datetime64[ns]")[indices]
    exits = np.asarray(timing.exit_open_times).astype("datetime64[ns]")[indices]
    if (decisions < scope.calendar_start_utc).any():
        raise ValueError("Fold scope prochel decision do train start")
    if (decisions >= scope.effective_end_exclusive_utc).any():
        raise ValueError("Fold scope prochel decision iz purge/OOS")
    if (exits >= scope.effective_end_exclusive_utc).any():
        raise ValueError("Fold scope prochel target, zavershivshiisya v purge/OOS")


def _robust_location_scale(values: np.ndarray) -> tuple[float, float, int]:
    """Schitaet median i IQR; pustoi ili konstantnyi kanal poluchaet scale odin."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return 0.0, 1.0, 0
    lower, median, upper = np.quantile(finite, (0.25, 0.50, 0.75))
    scale = float(upper - lower)
    if not np.isfinite(scale) or scale <= np.finfo(np.float32).eps:
        scale = 1.0
    return float(median), scale, int(len(finite))


@dataclass(frozen=True)
class FoldRobustScaler:
    """Hranit train-fold median/IQR otdel'no dlya 10m i daily kanalov."""

    intraday_feature_names: tuple[str, ...]
    daily_feature_names: tuple[str, ...]
    intraday_median: tuple[float, ...]
    intraday_iqr: tuple[float, ...]
    intraday_observations: tuple[int, ...]
    daily_median: tuple[float, ...]
    daily_iqr: tuple[float, ...]
    daily_observations: tuple[int, ...]
    scope: dict[str, Any]
    version: str = V7_NORMALIZATION_VERSION

    def __post_init__(self) -> None:
        """Proveryaet razmery i polozhitel'nost' vseh zapechatannyh scale."""
        intraday_size = len(self.intraday_feature_names)
        daily_size = len(self.daily_feature_names)
        if not all(
            len(values) == intraday_size
            for values in (
                self.intraday_median,
                self.intraday_iqr,
                self.intraday_observations,
            )
        ):
            raise ValueError("Intraday scaler imeet nevernuyu dlinu")
        if not all(
            len(values) == daily_size
            for values in (self.daily_median, self.daily_iqr, self.daily_observations)
        ):
            raise ValueError("Daily scaler imeet nevernuyu dlinu")
        if any(scale <= 0.0 or not np.isfinite(scale) for scale in self.intraday_iqr):
            raise ValueError("Intraday IQR dolzhen byt' polozhitel'nym")
        if any(scale <= 0.0 or not np.isfinite(scale) for scale in self.daily_iqr):
            raise ValueError("Daily IQR dolzhen byt' polozhitel'nym")

    def as_dict(self) -> dict[str, Any]:
        """Serializuet scaler v samodostatochnyi JSON-compatible payload."""
        return {
            "version": self.version,
            "intraday_feature_names": list(self.intraday_feature_names),
            "daily_feature_names": list(self.daily_feature_names),
            "intraday_median": list(self.intraday_median),
            "intraday_iqr": list(self.intraday_iqr),
            "intraday_observations": list(self.intraday_observations),
            "daily_median": list(self.daily_median),
            "daily_iqr": list(self.daily_iqr),
            "daily_observations": list(self.daily_observations),
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FoldRobustScaler:
        """Vosstanavlivaet scaler iz proverennogo checkpoint payload."""
        return cls(
            version=str(payload["version"]),
            intraday_feature_names=tuple(payload["intraday_feature_names"]),
            daily_feature_names=tuple(payload["daily_feature_names"]),
            intraday_median=tuple(float(value) for value in payload["intraday_median"]),
            intraday_iqr=tuple(float(value) for value in payload["intraday_iqr"]),
            intraday_observations=tuple(
                int(value) for value in payload["intraday_observations"]
            ),
            daily_median=tuple(float(value) for value in payload["daily_median"]),
            daily_iqr=tuple(float(value) for value in payload["daily_iqr"]),
            daily_observations=tuple(int(value) for value in payload["daily_observations"]),
            scope=dict(payload["scope"]),
        )

    def transform_intraday(
        self,
        values: np.ndarray,
        bar_valid: np.ndarray,
        asset_valid: np.ndarray,
    ) -> np.ndarray:
        """Primenaet train median/IQR i nulit tol'ko masked yacheiki."""
        raw = np.asarray(values, dtype=np.float32)
        bar_mask = np.asarray(bar_valid, dtype=bool)
        assets = np.asarray(asset_valid, dtype=bool)
        if raw.shape[:-1] != bar_mask.shape or raw.shape[-1] != len(
            self.intraday_feature_names
        ):
            raise ValueError("Intraday values/mask ne sovpadayut so scaler")
        if assets.shape != raw.shape[:-2]:
            raise ValueError("Intraday asset mask imeet nevernuyu formu")
        median = np.asarray(self.intraday_median, dtype=np.float32)
        scale = np.asarray(self.intraday_iqr, dtype=np.float32)
        valid = bar_mask & assets[..., None]
        normalized = (raw - median) / scale
        return np.where(valid[..., None] & np.isfinite(raw), normalized, 0.0).astype(
            np.float32,
            copy=False,
        )

    def transform_daily(
        self,
        values: np.ndarray,
        feature_valid: np.ndarray,
        asset_valid: np.ndarray,
    ) -> np.ndarray:
        """Primenaet train daily median/IQR s otdel'noi feature-mask."""
        raw = np.asarray(values, dtype=np.float32)
        valid_features = np.asarray(feature_valid, dtype=bool)
        assets = np.asarray(asset_valid, dtype=bool)
        if raw.shape != valid_features.shape or raw.shape[-1] != len(
            self.daily_feature_names
        ):
            raise ValueError("Daily values/mask ne sovpadayut so scaler")
        if assets.shape != raw.shape[:-1]:
            raise ValueError("Daily asset mask imeet nevernuyu formu")
        median = np.asarray(self.daily_median, dtype=np.float32)
        scale = np.asarray(self.daily_iqr, dtype=np.float32)
        valid = valid_features & assets[..., None]
        normalized = (raw - median) / scale
        return np.where(valid & np.isfinite(raw), normalized, 0.0).astype(
            np.float32,
            copy=False,
        )


def _validate_training_shapes(arrays: MultiResolutionArrays, config: V7ModelConfig) -> None:
    """Proveryaet tol'ko formy, ne skaniruya znacheniya OOS samples."""
    intraday = np.asarray(arrays.intraday)
    if intraday.ndim != 4:
        raise ValueError("Intraday dolzhen imet' chetyrehmernuyu formu")
    expected = (
        intraday.shape[0],
        np.asarray(arrays.asset_valid).shape[1],
        config.sequence_bars,
        len(config.bar_feature_names),
    )
    if intraday.shape != expected:
        raise ValueError(f"Intraday shape {intraday.shape} != {expected}")
    if np.asarray(arrays.intraday_valid).shape != intraday.shape[:3]:
        raise ValueError("Intraday mask imeet nevernuyu formu")
    daily_shape = (
        intraday.shape[0],
        intraday.shape[1],
        len(config.daily_feature_names),
    )
    if np.asarray(arrays.daily_context).shape != daily_shape:
        raise ValueError("Daily context imeet nevernuyu formu")
    if np.asarray(arrays.daily_valid).shape != daily_shape:
        raise ValueError("Daily mask imeet nevernuyu formu")
    if np.asarray(arrays.asset_valid).shape != intraday.shape[:2]:
        raise ValueError("Asset mask imeet nevernuyu formu")
    if np.asarray(arrays.supervised_target).shape != intraday.shape[:2]:
        raise ValueError("Supervised target imeet nevernuyu formu")
    if np.asarray(arrays.supervised_valid).shape != intraday.shape[:2]:
        raise ValueError("Supervised mask imeet nevernuyu formu")
    if arrays.timing.bar_times.shape != (intraday.shape[0], intraday.shape[2]):
        raise ValueError("Timing bar-grid ne sovpadaet s intraday")


def fit_fold_robust_scaler(
    arrays: MultiResolutionArrays,
    config: V7ModelConfig,
    scope: FoldTrainingScope,
) -> FoldRobustScaler:
    """Fitit median/IQR tol'ko na tekushchem train-fold do target/purge cutoff."""
    _validate_training_shapes(arrays, config)
    _validate_scope(arrays.timing, scope)
    indices = scope.sample_indices
    intraday = np.asarray(arrays.intraday)[indices]
    bar_valid = np.asarray(arrays.intraday_valid, dtype=bool)[indices]
    asset_valid = np.asarray(arrays.asset_valid, dtype=bool)[indices]
    bar_times = np.asarray(arrays.timing.bar_times).astype("datetime64[ns]")[indices]
    temporal_valid = (
        (bar_times >= scope.calendar_start_utc)
        & (bar_times < scope.effective_end_exclusive_utc)
    )
    intraday_valid = bar_valid & asset_valid[:, :, None] & temporal_valid[:, None, :]
    intraday_stats = [
        _robust_location_scale(intraday[..., feature_index][intraday_valid])
        for feature_index in range(intraday.shape[-1])
    ]
    daily = np.asarray(arrays.daily_context)[indices]
    daily_valid = (
        np.asarray(arrays.daily_valid, dtype=bool)[indices]
        & asset_valid[:, :, None]
    )
    daily_stats = [
        _robust_location_scale(daily[..., feature_index][daily_valid[..., feature_index]])
        for feature_index in range(daily.shape[-1])
    ]
    return FoldRobustScaler(
        intraday_feature_names=tuple(config.bar_feature_names),
        daily_feature_names=tuple(config.daily_feature_names),
        intraday_median=tuple(statistic[0] for statistic in intraday_stats),
        intraday_iqr=tuple(statistic[1] for statistic in intraday_stats),
        intraday_observations=tuple(statistic[2] for statistic in intraday_stats),
        daily_median=tuple(statistic[0] for statistic in daily_stats),
        daily_iqr=tuple(statistic[1] for statistic in daily_stats),
        daily_observations=tuple(statistic[2] for statistic in daily_stats),
        scope=scope.as_dict(),
    )


def fit_fold_target_iqr(
    arrays: MultiResolutionArrays,
    scope: FoldTrainingScope,
) -> float:
    """Fitit ranking-temperature tol'ko po finite target s exit do train cutoff."""
    _validate_scope(arrays.timing, scope)
    indices = scope.sample_indices
    target = np.asarray(arrays.supervised_target, dtype=np.float64)[indices]
    valid = (
        np.asarray(arrays.supervised_valid, dtype=bool)[indices]
        & np.asarray(arrays.asset_valid, dtype=bool)[indices]
        & np.isfinite(target)
    )
    values = target[valid]
    if not len(values):
        raise ValueError("Train fold ne soderzhit ni odnogo supervised target")
    lower, upper = np.quantile(values, (0.25, 0.75))
    return float(max(float(upper - lower), V7_TARGET_SCALE_FLOOR))


def build_strict_fold_ssl_sample(
    log_price: np.ndarray,
    bar_valid: np.ndarray,
    bar_times: np.ndarray,
    asset_valid: np.ndarray,
    horizons: tuple[int, ...],
    scope: FoldTrainingScope,
) -> SelfSupervisedTargets:
    """Stroit SSL labels, u kotoryh origin i horizon-end lezhat v train-scope."""
    prices = np.asarray(log_price, dtype=np.float64)
    valid_bars = np.asarray(bar_valid, dtype=bool)
    timestamps = np.asarray(bar_times).astype("datetime64[ns]")
    assets = np.asarray(asset_valid, dtype=bool)
    if prices.ndim != 2 or valid_bars.shape != prices.shape:
        raise ValueError("SSL sample trebuet [assets, bars] price i mask")
    if timestamps.shape != (prices.shape[1],) or assets.shape != (prices.shape[0],):
        raise ValueError("SSL timing/asset mask imeet nevernuyu formu")
    if not horizons or any(horizon < 1 for horizon in horizons):
        raise ValueError("SSL horizons dolzhny byt' polozhitel'nymi")
    if (np.diff(timestamps) <= np.timedelta64(0, "ns")).any():
        raise ValueError("SSL bar timestamps dolzhny strogo vozrastat'")
    asset_count, bar_count = prices.shape
    values = np.zeros((asset_count, bar_count, len(horizons), 2), dtype=np.float32)
    target_valid = np.zeros((asset_count, bar_count, len(horizons)), dtype=bool)
    finite = np.isfinite(prices) & valid_bars & assets[:, None]
    clean = np.where(finite, prices, 0.0)
    squared_increment = np.square(np.diff(clean, axis=-1))
    invalid_prefix = np.concatenate(
        (
            np.zeros((asset_count, 1), dtype=np.int32),
            np.cumsum(~finite, axis=-1, dtype=np.int32),
        ),
        axis=-1,
    )
    for horizon_index, horizon in enumerate(horizons):
        if horizon >= bar_count:
            continue
        usable_count = bar_count - horizon
        invalid_count = (
            invalid_prefix[:, horizon + 1 :] - invalid_prefix[:, :usable_count]
        )
        time_valid = (
            (timestamps[:usable_count] >= scope.calendar_start_utc)
            & (timestamps[horizon:] < scope.effective_end_exclusive_utc)
        )
        valid = (invalid_count == 0) & time_valid[None, :]
        future_return = clean[:, horizon:] - clean[:, :usable_count]
        future_square_sum = np.lib.stride_tricks.sliding_window_view(
            squared_increment,
            window_shape=horizon,
            axis=-1,
        ).sum(axis=-1, dtype=np.float64)
        future_volatility = np.sqrt(future_square_sum / float(horizon))
        values[:, :usable_count, horizon_index, 0] = np.where(
            valid, future_return, 0.0
        )
        values[:, :usable_count, horizon_index, 1] = np.where(
            valid, future_volatility, 0.0
        )
        target_valid[:, :usable_count, horizon_index] = valid
    return SelfSupervisedTargets(values=values, valid=target_valid)


def fold_pairwise_ranking_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
    train_target_iqr: float,
) -> torch.Tensor:
    """Schitaet logistic ordering loss po param aktivov odnogo timestamp."""
    if predictions.ndim != 2 or predictions.shape != targets.shape:
        raise ValueError("Ranking trebuet predictions/targets [batch, assets]")
    if target_mask.shape != targets.shape:
        raise ValueError("Ranking target mask imeet nevernuyu formu")
    if not np.isfinite(train_target_iqr) or train_target_iqr < V7_TARGET_SCALE_FLOOR:
        raise ValueError("Ranking temperature dolzhna byt' train-fold IQR")
    asset_count = predictions.shape[1]
    if asset_count < 2:
        return predictions.sum() * 0.0
    left, right = torch.triu_indices(
        asset_count,
        asset_count,
        offset=1,
        device=predictions.device,
    )
    valid = target_mask[:, left] & target_mask[:, right]
    target_difference = targets[:, left] - targets[:, right]
    valid = valid & torch.isfinite(target_difference)
    if not valid.any():
        return predictions.sum() * 0.0
    prediction_difference = predictions[:, left] - predictions[:, right]
    signed_margin = (
        target_difference.sign() * prediction_difference / float(train_target_iqr)
    )
    return functional.softplus(-signed_margin[valid]).mean()


def masked_portfolio_supervised_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
    train_target_iqr: float,
) -> torch.Tensor:
    """Dobavlyaet fixed 0.25 pairwise ranking k Huber i direction BCE."""
    base = masked_supervised_loss(predictions, targets, target_mask)
    ranking = fold_pairwise_ranking_loss(
        predictions,
        targets,
        target_mask & torch.isfinite(targets),
        train_target_iqr,
    )
    return base + V7_RANKING_WEIGHT * ranking


class DeterministicEpochSampler(Sampler[int]):
    """Formiruet fiksirovannuyu per-epoch permutaciyu bez global RNG."""

    def __init__(self, sample_count: int, seed: int, stage_offset: int) -> None:
        """Zapominaet razmer, seed i nezavisimyi identifikator stage."""
        if sample_count < 1:
            raise ValueError("Sampler trebuet hotya by odin sample")
        self.sample_count = sample_count
        self.seed = seed
        self.stage_offset = stage_offset
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        """Perekluchaet determinirovannuyu permutaciyu na ukazannuyu epohu."""
        if epoch < 0:
            raise ValueError("Epoch ne mozhet byt' otricatel'nym")
        self.epoch = epoch

    def __iter__(self) -> Iterator[int]:
        """Vozvrashchaet iterator fiksirovannoi torch-permutacii."""
        generator = torch.Generator(device="cpu")
        generator.manual_seed(self.seed + self.stage_offset + self.epoch)
        return iter(torch.randperm(self.sample_count, generator=generator).tolist())

    def __len__(self) -> int:
        """Vozvrashchaet chislo samples v odnoi epohe."""
        return self.sample_count


class _FoldStageDataset(Dataset[dict[str, np.ndarray]]):
    """Lenivo normalizuet tol'ko train samples i stroit SSL po odnomu oknu."""

    def __init__(
        self,
        arrays: MultiResolutionArrays,
        log_price: np.ndarray,
        scaler: FoldRobustScaler,
        scope: FoldTrainingScope,
        horizons: tuple[int, ...],
        stage: Literal["ssl", "supervised"],
    ) -> None:
        """Svazyvaet immutable train scope s odnim tipom label."""
        prices = np.asarray(log_price)
        expected = np.asarray(arrays.intraday).shape[:3]
        if prices.shape != expected:
            raise ValueError(f"log_price shape {prices.shape} != {expected}")
        _validate_scope(arrays.timing, scope)
        self.arrays = arrays
        self.log_price = prices
        self.scaler = scaler
        self.scope = scope
        self.horizons = horizons
        self.stage = stage

    def __len__(self) -> int:
        """Vozvrashchaet chislo train samples posle purge."""
        return int(len(self.scope.sample_indices))

    def __getitem__(self, position: int) -> dict[str, np.ndarray]:
        """Vozvrashchaet odin normalized train sample i tol'ko nuzhnyi label."""
        index = int(self.scope.sample_indices[position])
        bar_mask = np.asarray(self.arrays.intraday_valid[index], dtype=bool)
        daily_mask = np.asarray(self.arrays.daily_valid[index], dtype=bool)
        asset_mask = np.asarray(self.arrays.asset_valid[index], dtype=bool)
        sample = {
            "intraday": self.scaler.transform_intraday(
                self.arrays.intraday[index], bar_mask, asset_mask
            ),
            "intraday_mask": bar_mask,
            "daily_context": self.scaler.transform_daily(
                self.arrays.daily_context[index], daily_mask, asset_mask
            ),
            "daily_mask": daily_mask,
            "asset_mask": asset_mask,
        }
        if self.stage == "ssl":
            ssl = build_strict_fold_ssl_sample(
                self.log_price[index],
                bar_mask,
                self.arrays.timing.bar_times[index],
                asset_mask,
                self.horizons,
                self.scope,
            )
            sample["target"] = ssl.values
            sample["target_mask"] = ssl.valid
        else:
            target_mask = (
                np.asarray(self.arrays.supervised_valid[index], dtype=bool)
                & asset_mask
                & np.isfinite(self.arrays.supervised_target[index])
            )
            sample["target"] = np.where(
                target_mask,
                np.asarray(self.arrays.supervised_target[index], dtype=np.float32),
                0.0,
            ).astype(np.float32, copy=False)
            sample["target_mask"] = target_mask
        return sample


def _configure_training_determinism(seed: int) -> None:
    """Fiksiruet RNG i otklyuchaet nedeterministichnye CUDA attention kernels."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    set_v7_determinism(seed)
    torch.set_float32_matmul_precision("highest")
    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)


def require_v7_training_device() -> torch.device:
    """Trebuet odnu fakticheski ispol'zuemuyu RTX 5090 s BF16."""
    if not torch.cuda.is_available():
        raise RuntimeError("Futures-v7 training trebuet CUDA RTX 5090")
    device = torch.device("cuda", 0)
    device_name = torch.cuda.get_device_name(device)
    if "5090" not in device_name:
        raise RuntimeError(f"Futures-v7 accelerator drift: {device_name}")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("Futures-v7 trebuet native CUDA BF16")
    return device


def _training_loader(
    dataset: _FoldStageDataset,
    sampler: DeterministicEpochSampler,
) -> DataLoader:
    """Stroit odno-processnyi loader s fiksirovannym batch size."""
    return DataLoader(
        dataset,
        batch_size=V7_TRAIN_BATCH_SIZE,
        sampler=sampler,
        num_workers=V7_DATALOADER_WORKERS,
        pin_memory=True,
        drop_last=False,
    )


def _move_batch(
    batch: dict[str, torch.Tensor],
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """Peremeshchaet tensor batch na odno ustroistvo bez izmeneniya dtype mask."""
    return {
        name: value.to(device, non_blocking=True)
        for name, value in batch.items()
    }


def _ssl_forward_only(
    model: CausalMultiResolutionFuturesModel,
    batch: dict[str, torch.Tensor],
) -> torch.Tensor:
    """Vychislyaet tol'ko SSL vetku bez bespoleznogo daily graph."""
    encoded = model.encode_intraday(
        batch["intraday"],
        batch["intraday_mask"],
        batch["asset_mask"],
    )
    raw = model.ssl_head(encoded).reshape(
        *encoded.shape[:-1],
        len(model.config.ssl_horizons),
        2,
    )
    prediction = torch.stack((raw[..., 0], functional.softplus(raw[..., 1])), dim=-1)
    return prediction * batch["asset_mask"][:, :, None, None, None].to(prediction.dtype)


def _supervised_forward_only(
    model: CausalMultiResolutionFuturesModel,
    batch: dict[str, torch.Tensor],
) -> torch.Tensor:
    """Vychislyaet daily vetku bez ogromnogo neispol'zuemogo SSL output."""
    encoded = model.encode_intraday(
        batch["intraday"],
        batch["intraday_mask"],
        batch["asset_mask"],
    )
    decision = model.asset_attention(encoded[:, :, -1], batch["asset_mask"])
    conditioned = model._condition_daily(  # noqa: SLF001
        decision,
        batch["daily_context"],
        batch["daily_mask"],
    )
    prediction = model.daily_head(conditioned).squeeze(-1)
    return prediction * batch["asset_mask"].to(prediction.dtype)


def _fixed_stage_training(
    model: CausalMultiResolutionFuturesModel,
    dataset: _FoldStageDataset,
    stage: Literal["ssl", "supervised"],
    epochs: int,
    learning_rate: float,
    weight_decay: float,
    gradient_clip_norm: float,
    seed: int,
    train_target_iqr: float,
    device: torch.device,
) -> tuple[dict[str, Any], ...]:
    """Vypolnyaet vse fixed epochs bez validation, early stop ili OOS tuning."""
    if epochs < 1:
        raise ValueError("Training stage trebuet hotya by odnu epohu")
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable:
        raise ValueError("Training stage ne imeet trainable parameters")
    optimizer = torch.optim.AdamW(
        trainable,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    stage_offset = (
        V7_SSL_STAGE_SEED_OFFSET if stage == "ssl" else V7_SUPERVISED_STAGE_SEED_OFFSET
    )
    sampler = DeterministicEpochSampler(len(dataset), seed, stage_offset)
    loader = _training_loader(dataset, sampler)
    history: list[dict[str, Any]] = []
    for epoch in range(epochs):
        sampler.set_epoch(epoch)
        model.train()
        loss_sum = 0.0
        batch_count = 0
        valid_label_count = 0
        for raw_batch in loader:
            batch = _move_batch(raw_batch, device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type="cuda",
                dtype=torch.bfloat16,
                enabled=device.type == "cuda",
            ):
                if stage == "ssl":
                    loss = masked_ssl_loss(
                        _ssl_forward_only(model, batch),
                        batch["target"],
                        batch["target_mask"],
                    )
                else:
                    loss = masked_portfolio_supervised_loss(
                        _supervised_forward_only(model, batch),
                        batch["target"],
                        batch["target_mask"],
                        train_target_iqr,
                    )
            label_count = int(batch["target_mask"].sum().detach().cpu())
            if not label_count:
                continue
            if not torch.isfinite(loss):
                raise RuntimeError(f"Non-finite {stage} loss")
            loss.backward()
            nn.utils.clip_grad_norm_(trainable, gradient_clip_norm)
            optimizer.step()
            loss_sum += float(loss.detach().float().cpu())
            batch_count += 1
            valid_label_count += label_count
        if not batch_count:
            raise RuntimeError(f"Stage {stage} ne poluchil valid labels")
        history.append(
            {
                "stage": stage,
                "epoch": epoch + 1,
                "train_loss": loss_sum / batch_count,
                "batches": batch_count,
                "valid_labels": valid_label_count,
            }
        )
    return tuple(history)


def architecture_sha256(config: V7ModelConfig) -> str:
    """Hashiruet polnuyu zapechatannuyu arhitekturu modeli."""
    return _payload_sha256(config.model_dump(mode="json"))


def feature_schema_sha256(config: V7ModelConfig) -> str:
    """Hashiruet poryadok 10m/daily features i tip normalizacii."""
    return _payload_sha256(
        {
            "normalization": V7_NORMALIZATION_VERSION,
            "intraday": list(config.bar_feature_names),
            "daily": list(config.daily_feature_names),
        }
    )


def timing_scope_sha256(timing: DecisionTimingBatch, scope: FoldTrainingScope) -> str:
    """Hashiruet tol'ko train timing rows vmeste s granicami fold."""
    _validate_scope(timing, scope)
    digest = hashlib.sha256(_canonical_json_bytes(scope.as_dict()))
    indices = scope.sample_indices
    for name, values in (
        ("bar_times", timing.bar_times[indices]),
        ("decision_times", timing.decision_times[indices]),
        ("entry_open_times", timing.entry_open_times[indices]),
        ("exit_open_times", timing.exit_open_times[indices]),
    ):
        array = np.ascontiguousarray(np.asarray(values).astype("datetime64[ns]").view(np.int64))
        digest.update(name.encode("ascii"))
        digest.update(_canonical_json_bytes(list(array.shape)))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _update_array_hash(digest: Any, name: str, values: np.ndarray) -> None:
    """Dobavlyaet imya, dtype, shape i tochnye bytes odnogo massiva v hash."""
    array = np.ascontiguousarray(values)
    digest.update(name.encode("utf-8"))
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(_canonical_json_bytes(list(array.shape)))
    digest.update(array.tobytes())


def fold_training_data_sha256(
    arrays: MultiResolutionArrays,
    log_price: np.ndarray,
    scope: FoldTrainingScope,
) -> str:
    """Hashiruet vse i tol'ko train inputs, masks, SSL source i target."""
    _validate_scope(arrays.timing, scope)
    prices = np.asarray(log_price)
    if prices.shape != np.asarray(arrays.intraday).shape[:3]:
        raise ValueError("log_price ne sovpadaet s intraday")
    indices = scope.sample_indices
    digest = hashlib.sha256(_canonical_json_bytes(scope.as_dict()))
    for name, values in (
        ("intraday", np.asarray(arrays.intraday)[indices]),
        ("intraday_valid", np.asarray(arrays.intraday_valid)[indices]),
        ("daily_context", np.asarray(arrays.daily_context)[indices]),
        ("daily_valid", np.asarray(arrays.daily_valid)[indices]),
        ("asset_valid", np.asarray(arrays.asset_valid)[indices]),
        ("supervised_target", np.asarray(arrays.supervised_target)[indices]),
        ("supervised_valid", np.asarray(arrays.supervised_valid)[indices]),
        ("log_price", prices[indices]),
    ):
        _update_array_hash(digest, name, values)
    return digest.hexdigest()


def _state_dict_sha256(state_dict: dict[str, torch.Tensor]) -> str:
    """Hashiruet imena, dtype, shape i tochnye bytes vseh tensor vesov."""
    digest = hashlib.sha256()
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(_canonical_json_bytes(list(tensor.shape)))
        digest.update(tensor.reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class V7TrainingHashes:
    """Obedinyaet chetyre proverki identity train-zapuska."""

    architecture_sha256: str
    feature_schema_sha256: str
    timing_sha256: str
    training_data_sha256: str

    def as_dict(self) -> dict[str, str]:
        """Serializuet hash-contract bez dobavleniya runtime state."""
        return {
            "architecture_sha256": self.architecture_sha256,
            "feature_schema_sha256": self.feature_schema_sha256,
            "timing_sha256": self.timing_sha256,
            "training_data_sha256": self.training_data_sha256,
        }


def build_v7_training_hashes(
    arrays: MultiResolutionArrays,
    log_price: np.ndarray,
    model_config: V7ModelConfig,
    scope: FoldTrainingScope,
) -> V7TrainingHashes:
    """Stroit identity train run bez chteniya OOS values."""
    return V7TrainingHashes(
        architecture_sha256=architecture_sha256(model_config),
        feature_schema_sha256=feature_schema_sha256(model_config),
        timing_sha256=timing_scope_sha256(arrays.timing, scope),
        training_data_sha256=fold_training_data_sha256(arrays, log_price, scope),
    )


def _atomic_torch_save(path: Path, payload: dict[str, Any]) -> None:
    """Atomarno pishet torch payload s fsync v tom zhe kataloge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        torch.save(payload, temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_fixed_history(
    history: Sequence[dict[str, Any]],
    stage: Literal["ssl", "supervised"],
    expected_epochs: int,
) -> None:
    """Zapreshchaet checkpoint s obrezannym ili early-stopped schedule."""
    if len(history) != expected_epochs:
        raise ValueError(f"Checkpoint {stage} history ne ravna fixed epochs")
    expected_numbers = list(range(1, expected_epochs + 1))
    actual_numbers = [int(row.get("epoch", -1)) for row in history]
    if actual_numbers != expected_numbers:
        raise ValueError(f"Checkpoint {stage} epoch sequence mismatch")
    if any(row.get("stage") != stage for row in history):
        raise ValueError(f"Checkpoint {stage} history imeet drugoi stage")


def _checkpoint_manifest_core(
    model: CausalMultiResolutionFuturesModel,
    config: V7ResearchConfig,
    fold: V7FoldConfig,
    seed: int,
    scope: FoldTrainingScope,
    scaler: FoldRobustScaler,
    train_target_iqr: float,
    hashes: V7TrainingHashes,
    ssl_history: Sequence[dict[str, Any]],
    supervised_history: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Sobiraet determinirovannyi manifest bez circular checkpoint hash."""
    if seed not in config.training.seeds:
        raise ValueError("Checkpoint seed ne prinadlezhit fixed v7 ensemble")
    if not np.isfinite(train_target_iqr) or train_target_iqr < V7_TARGET_SCALE_FLOOR:
        raise ValueError("Checkpoint train target IQR dolzhen byt' konechnym i validnym")
    _validate_fixed_history(ssl_history, "ssl", config.training.ssl_epochs)
    _validate_fixed_history(
        supervised_history,
        "supervised",
        config.training.supervised_epochs,
    )
    state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
    return {
        "format": V7_CHECKPOINT_FORMAT,
        "protocol_name": config.protocol_name,
        "protocol_version": config.protocol_version,
        "fold": fold.model_dump(mode="json"),
        "scope": scope.as_dict(),
        "seed": seed,
        "fixed_seeds": list(config.training.seeds),
        "architecture": model_architecture_manifest(model),
        "model_config": config.model.model_dump(mode="json"),
        "training_config": config.training.model_dump(mode="json"),
        "training_hashes": hashes.as_dict(),
        "scaler": scaler.as_dict(),
        "scaler_sha256": _payload_sha256(scaler.as_dict()),
        "train_target_iqr": train_target_iqr,
        "supervised_loss": {
            "base": "smooth_l1_plus_0.25_direction_bce",
            "ranking": "mean_softplus(-sign(y_i-y_j)*(p_i-p_j)/train_iqr)",
            "ranking_weight": V7_RANKING_WEIGHT,
            "temperature_floor": V7_TARGET_SCALE_FLOOR,
        },
        "state_dict_sha256": _state_dict_sha256(state),
        "ssl_history": list(ssl_history),
        "supervised_history": list(supervised_history),
        "precision_runtime": "cuda_bfloat16",
        "seed_aggregation": "arithmetic_mean_prediction",
        "resume_semantics": V7_RESUME_SEMANTICS,
        "mid_stage_resume_supported": False,
        "optimizer_state_included": False,
        "rng_state_included": False,
        "early_stopping": False,
        "oos_hyperparameter_tuning": False,
        "torch_version": str(torch.__version__),
    }


def save_v7_checkpoint_bundle(
    path: Path,
    model: CausalMultiResolutionFuturesModel,
    config: V7ResearchConfig,
    fold: V7FoldConfig,
    seed: int,
    scope: FoldTrainingScope,
    scaler: FoldRobustScaler,
    train_target_iqr: float,
    hashes: V7TrainingHashes,
    ssl_history: Sequence[dict[str, Any]],
    supervised_history: Sequence[dict[str, Any]],
) -> Path:
    """Atomarno sohranyaet self-contained checkpoint i ego JSON sidecar."""
    core = _checkpoint_manifest_core(
        model,
        config,
        fold,
        seed,
        scope,
        scaler,
        train_target_iqr,
        hashes,
        ssl_history,
        supervised_history,
    )
    manifest_sha256 = _payload_sha256(core)
    state = {name: tensor.detach().cpu() for name, tensor in model.state_dict().items()}
    checkpoint_payload = {
        "manifest": core,
        "manifest_sha256": manifest_sha256,
        "state_dict": state,
    }
    _atomic_torch_save(path, checkpoint_payload)
    sidecar_path = path.with_suffix(path.suffix + ".manifest.json")
    sidecar = {
        "format": V7_MANIFEST_FORMAT,
        "checkpoint_file": path.name,
        "checkpoint_sha256": _file_sha256(path),
        "manifest_sha256": manifest_sha256,
        "manifest": core,
    }
    write_json(sidecar_path, sidecar)
    return sidecar_path


@dataclass(frozen=True)
class LoadedV7Checkpoint:
    """Hranit proverennuyu model, scaler i manifest posle resume."""

    model: CausalMultiResolutionFuturesModel
    scaler: FoldRobustScaler
    manifest: dict[str, Any]
    sidecar_path: Path


def load_v7_checkpoint_bundle(
    path: Path,
    expected_hashes: V7TrainingHashes | None = None,
) -> LoadedV7Checkpoint:
    """Fail-closed zagruzhaet checkpoint tol'ko posle proverki sidecar i hash."""
    sidecar_path = path.with_suffix(path.suffix + ".manifest.json")
    if not path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError("Checkpoint bundle nepolon")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8-sig"))
    if sidecar.get("format") != V7_MANIFEST_FORMAT:
        raise ValueError("Neizvestnyi v7 manifest format")
    if sidecar.get("checkpoint_file") != path.name:
        raise ValueError("Manifest ssylayetsya ne na tot checkpoint")
    if sidecar.get("checkpoint_sha256") != _file_sha256(path):
        raise ValueError("Checkpoint SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    core = payload.get("manifest")
    if not isinstance(core, dict) or core.get("format") != V7_CHECKPOINT_FORMAT:
        raise ValueError("Neizvestnyi v7 checkpoint format")
    manifest_sha256 = _payload_sha256(core)
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Checkpoint internal manifest hash mismatch")
    if sidecar.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Checkpoint/sidecar manifest mismatch")
    if sidecar.get("manifest") != core:
        raise ValueError("Checkpoint/sidecar content mismatch")
    state = payload.get("state_dict")
    if not isinstance(state, dict) or core.get("state_dict_sha256") != _state_dict_sha256(state):
        raise ValueError("Checkpoint state_dict hash mismatch")
    model_config = V7ModelConfig.model_validate(core["model_config"])
    training_config = V7TrainingConfig.model_validate(core["training_config"])
    if int(core["seed"]) not in training_config.seeds:
        raise ValueError("Checkpoint seed ne prinadlezhit training config")
    _validate_fixed_history(core["ssl_history"], "ssl", training_config.ssl_epochs)
    _validate_fixed_history(
        core["supervised_history"],
        "supervised",
        training_config.supervised_epochs,
    )
    loaded_target_iqr = float(core["train_target_iqr"])
    if not np.isfinite(loaded_target_iqr) or loaded_target_iqr < V7_TARGET_SCALE_FLOOR:
        raise ValueError("Checkpoint train target IQR nizhe fixed floor")
    if core.get("resume_semantics") != V7_RESUME_SEMANTICS:
        raise ValueError("Checkpoint resume semantics mismatch")
    if any(
        core.get(field_name) is not False
        for field_name in (
            "mid_stage_resume_supported",
            "optimizer_state_included",
            "rng_state_included",
        )
    ):
        raise ValueError("Checkpoint lozhno obyavlyaet mid-stage resume state")
    if core["training_hashes"]["architecture_sha256"] != architecture_sha256(model_config):
        raise ValueError("Checkpoint architecture hash mismatch")
    if core["training_hashes"]["feature_schema_sha256"] != feature_schema_sha256(
        model_config
    ):
        raise ValueError("Checkpoint feature schema hash mismatch")
    if expected_hashes is not None and core["training_hashes"] != expected_hashes.as_dict():
        raise ValueError("Checkpoint ne sovpadaet s tekushchim train data/timing")
    scaler = FoldRobustScaler.from_dict(core["scaler"])
    if core.get("scaler_sha256") != _payload_sha256(scaler.as_dict()):
        raise ValueError("Checkpoint scaler hash mismatch")
    model = CausalMultiResolutionFuturesModel(model_config)
    model.load_state_dict(state, strict=True)
    model.eval()
    return LoadedV7Checkpoint(
        model=model,
        scaler=scaler,
        manifest=core,
        sidecar_path=sidecar_path,
    )


@dataclass(frozen=True)
class SeedTrainingOutcome:
    """Hranit odin fixed-seed result bez OOS metric ili model selection."""

    seed: int
    model: CausalMultiResolutionFuturesModel
    scaler: FoldRobustScaler
    train_target_iqr: float
    ssl_history: tuple[dict[str, Any], ...]
    supervised_history: tuple[dict[str, Any], ...]
    checkpoint_path: Path
    manifest_path: Path
    resumed: bool


def _find_fold(config: V7ResearchConfig, fold_name: str) -> V7FoldConfig:
    """Nahodit odin zapechatannyi fold po imeni bez indeksnogo ugadyvaniya."""
    matches = [fold for fold in config.development.folds if fold.name == fold_name]
    if len(matches) != 1:
        raise ValueError(f"Ne naiden edinstvennyi v7 fold: {fold_name}")
    return matches[0]


def run_v7_fold_seed_training(
    arrays: MultiResolutionArrays,
    log_price: np.ndarray,
    config: V7ResearchConfig,
    fold_name: str,
    seed: int,
    checkpoint_directory: Path,
    *,
    resume: bool = True,
) -> SeedTrainingOutcome:
    """Obuchaet ili zagruzhaet tol'ko zavershennyi fold/seed bez mid-stage resume."""
    if tuple(config.training.seeds) != V7_SEEDS or seed not in V7_SEEDS:
        raise ValueError("V7 razreshaet tol'ko seeds 1729/2718/3141")
    fold = _find_fold(config, fold_name)
    scope = build_fold_training_scope(
        arrays.timing,
        fold,
        config.development.decision_timezone,
        config.development.purge_sessions,
    )
    scaler = fit_fold_robust_scaler(arrays, config.model, scope)
    train_target_iqr = fit_fold_target_iqr(arrays, scope)
    hashes = build_v7_training_hashes(arrays, log_price, config.model, scope)
    checkpoint_path = checkpoint_directory / f"{fold.name}-seed-{seed}.pt"
    manifest_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".manifest.json")
    if resume and (checkpoint_path.exists() or manifest_path.exists()):
        loaded = load_v7_checkpoint_bundle(checkpoint_path, expected_hashes=hashes)
        if loaded.manifest["seed"] != seed or loaded.manifest["fold"]["name"] != fold.name:
            raise ValueError("Resume checkpoint seed/fold mismatch")
        if loaded.manifest["scaler_sha256"] != _payload_sha256(scaler.as_dict()):
            raise ValueError("Resume checkpoint normalizer mismatch")
        loaded_target_iqr = float(loaded.manifest["train_target_iqr"])
        if not np.isfinite(loaded_target_iqr) or loaded_target_iqr != train_target_iqr:
            raise ValueError("Resume checkpoint train target IQR mismatch")
        return SeedTrainingOutcome(
            seed=seed,
            model=loaded.model,
            scaler=scaler,
            train_target_iqr=float(loaded.manifest["train_target_iqr"]),
            ssl_history=tuple(loaded.manifest["ssl_history"]),
            supervised_history=tuple(loaded.manifest["supervised_history"]),
            checkpoint_path=checkpoint_path,
            manifest_path=manifest_path,
            resumed=True,
        )
    _configure_training_determinism(seed)
    device = require_v7_training_device()
    model = CausalMultiResolutionFuturesModel(config.model).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if parameter_count != config.model.expected_parameter_count:
        raise RuntimeError("Futures-v7 model parameter count drift")
    ssl_dataset = _FoldStageDataset(
        arrays,
        log_price,
        scaler,
        scope,
        config.model.ssl_horizons,
        "ssl",
    )
    ssl_history = _fixed_stage_training(
        model,
        ssl_dataset,
        "ssl",
        config.training.ssl_epochs,
        config.training.ssl_learning_rate,
        config.training.weight_decay,
        config.training.gradient_clip_norm,
        seed,
        train_target_iqr,
        device,
    )
    configure_supervised_finetuning(model, config.training.freeze_first_temporal_blocks)
    supervised_dataset = _FoldStageDataset(
        arrays,
        log_price,
        scaler,
        scope,
        config.model.ssl_horizons,
        "supervised",
    )
    supervised_history = _fixed_stage_training(
        model,
        supervised_dataset,
        "supervised",
        config.training.supervised_epochs,
        config.training.supervised_learning_rate,
        config.training.weight_decay,
        config.training.gradient_clip_norm,
        seed,
        train_target_iqr,
        device,
    )
    manifest_path = save_v7_checkpoint_bundle(
        checkpoint_path,
        model,
        config,
        fold,
        seed,
        scope,
        scaler,
        train_target_iqr,
        hashes,
        ssl_history,
        supervised_history,
    )
    return SeedTrainingOutcome(
        seed=seed,
        model=model,
        scaler=scaler,
        train_target_iqr=train_target_iqr,
        ssl_history=ssl_history,
        supervised_history=supervised_history,
        checkpoint_path=checkpoint_path,
        manifest_path=manifest_path,
        resumed=False,
    )


def arithmetic_ensemble_predictions(predictions: Sequence[np.ndarray]) -> np.ndarray:
    """Usrednyaet tri seed prediction arifmeticheski bez vybora luchshego seed."""
    if len(predictions) != len(V7_SEEDS):
        raise ValueError("V7 ensemble trebuet rovno tri fixed-seed prediction")
    arrays = [np.asarray(values, dtype=np.float64) for values in predictions]
    if any(values.shape != arrays[0].shape for values in arrays[1:]):
        raise ValueError("Seed predictions imeyut raznye formy")
    if not all(np.isfinite(values).all() for values in arrays):
        raise ValueError("Seed predictions dolzhny byt' konechnymi")
    return np.mean(np.stack(arrays, axis=0), axis=0, dtype=np.float64)


def predict_v7_model(
    model: CausalMultiResolutionFuturesModel,
    arrays: MultiResolutionArrays,
    scaler: FoldRobustScaler,
    sample_indices: np.ndarray,
    device: torch.device,
) -> np.ndarray:
    """Vychislyaet daily scores fiksirovannoi modeli bez target ili shuffle."""
    indices = np.asarray(sample_indices, dtype=np.int64)
    if indices.ndim != 1 or not len(indices):
        raise ValueError("Inference trebuet nepustoi sample index")
    rows: list[np.ndarray] = []
    model = model.to(device).eval()
    with torch.inference_mode():
        for start in range(0, len(indices), V7_INFERENCE_BATCH_SIZE):
            batch_indices = indices[start : start + V7_INFERENCE_BATCH_SIZE]
            bar_mask = np.asarray(arrays.intraday_valid, dtype=bool)[batch_indices]
            daily_mask = np.asarray(arrays.daily_valid, dtype=bool)[batch_indices]
            asset_mask = np.asarray(arrays.asset_valid, dtype=bool)[batch_indices]
            intraday = scaler.transform_intraday(
                arrays.intraday[batch_indices], bar_mask, asset_mask
            )
            daily = scaler.transform_daily(
                arrays.daily_context[batch_indices], daily_mask, asset_mask
            )
            with torch.autocast(
                device_type="cuda",
                dtype=torch.bfloat16,
                enabled=device.type == "cuda",
            ):
                output = model(
                    torch.from_numpy(intraday).to(device),
                    torch.from_numpy(bar_mask).to(device),
                    torch.from_numpy(daily).to(device),
                    torch.from_numpy(daily_mask).to(device),
                    torch.from_numpy(asset_mask).to(device),
                )
            rows.append(output.daily_return.float().cpu().numpy())
    return np.concatenate(rows, axis=0).astype(np.float64)


def train_v7_fold_ensemble(
    arrays: MultiResolutionArrays,
    log_price: np.ndarray,
    config: V7ResearchConfig,
    fold_name: str,
    checkpoint_directory: Path,
    *,
    resume: bool = True,
) -> tuple[SeedTrainingOutcome, ...]:
    """Zapuskaet tri seed i resume tol'ko uzhe polnost'yu zavershennye seed."""
    return tuple(
        run_v7_fold_seed_training(
            arrays,
            log_price,
            config,
            fold_name,
            seed,
            checkpoint_directory,
            resume=resume,
        )
        for seed in V7_SEEDS
    )


@dataclass(frozen=True)
class V7CheckpointTransportBundle:
    """Hranit nerazdelimyi transportnyi payload checkpoint i ego sidecar."""

    checkpoint_content: bytes
    sidecar_content: bytes


def checkpoint_bytes(path: Path) -> V7CheckpointTransportBundle:
    """Chitaet proverennye checkpoint i sidecar kak odin tipizirovannyi payload."""
    loaded = load_v7_checkpoint_bundle(path)
    return V7CheckpointTransportBundle(
        checkpoint_content=path.read_bytes(),
        sidecar_content=loaded.sidecar_path.read_bytes(),
    )


def write_checkpoint_copy_atomic(
    path: Path,
    bundle: V7CheckpointTransportBundle,
) -> Path:
    """Atomarno pishet oba faila; sidecar poslednim sluzhit fail-closed commit-marker."""
    if not isinstance(bundle, V7CheckpointTransportBundle):
        raise TypeError("Checkpoint transport trebuet V7CheckpointTransportBundle")
    sidecar = json.loads(bundle.sidecar_content.decode("utf-8-sig"))
    if sidecar.get("format") != V7_MANIFEST_FORMAT:
        raise ValueError("Neizvestnyi transportnyi manifest format")
    checkpoint_sha256 = hashlib.sha256(bundle.checkpoint_content).hexdigest()
    if sidecar.get("checkpoint_sha256") != checkpoint_sha256:
        raise ValueError("Transport checkpoint/sidecar SHA-256 mismatch")
    core = sidecar.get("manifest")
    if not isinstance(core, dict) or sidecar.get("manifest_sha256") != _payload_sha256(core):
        raise ValueError("Transport checkpoint manifest mismatch")
    destination_sidecar = dict(sidecar)
    destination_sidecar["checkpoint_file"] = path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{path.name}.verify.", dir=path.parent) as name:
        staged_path = Path(name) / path.name
        atomic_write_bytes(staged_path, bundle.checkpoint_content)
        write_json(
            staged_path.with_suffix(staged_path.suffix + ".manifest.json"),
            destination_sidecar,
        )
        load_v7_checkpoint_bundle(staged_path)
    atomic_write_bytes(path, bundle.checkpoint_content)
    sidecar_path = path.with_suffix(path.suffix + ".manifest.json")
    write_json(sidecar_path, destination_sidecar)
    load_v7_checkpoint_bundle(path)
    return sidecar_path
