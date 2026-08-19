"""Deterministichnoe mixed-precision obuchenie causal-TCN na CUDA."""

from __future__ import annotations

import copy
import logging
import random
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from scipy.stats import spearmanr
from torch import nn
from torch.nn import functional as functional
from torch.utils.data import DataLoader

from market_lab.sequence.config import SequenceModelConfig
from market_lab.sequence.dataset import (
    DynamicSequenceDataset,
    EntryTimeBatchSampler,
    SequenceSamples,
    SequenceStore,
)
from market_lab.sequence.model import CausalTCN, build_causal_tcn

LOGGER = logging.getLogger(__name__)  # Logger processa obucheniya TCN.


@dataclass(frozen=True)
class TrainingOutcome:
    """Hranit luchshuyu model', epohu, istoriyu i train-time."""

    model: CausalTCN
    best_epoch: int
    best_validation_ic: float
    history: pd.DataFrame
    elapsed_seconds: float


def seed_everything(seed: int) -> None:
    """Fiksiruet vse dostupnye generatory sluchainyh chisel."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True, warn_only=True)


def _seed_worker(worker_id: int) -> None:
    """Delaet DataLoader worker vosproizvodimym."""
    worker_seed = torch.initial_seed() % (2**32)
    np.random.seed(worker_seed)
    random.seed(worker_seed)


def _device() -> torch.device:
    """Trebuet CUDA dlya servernogo sequence-eksperimenta."""
    if not torch.cuda.is_available():
        raise RuntimeError("Sequence-eksperiment trebuet dostupnuyu CUDA")
    return torch.device("cuda")


def _autocast_dtype(precision: str) -> torch.dtype | None:
    """Sopostavlyaet YAML-precision s CUDA dtype."""
    if precision == "bf16":
        return torch.bfloat16
    if precision == "fp16":
        return torch.float16
    return None


def _loader(
    dataset: DynamicSequenceDataset,
    model_config: SequenceModelConfig,
    shuffle: bool,
    seed: int,
) -> DataLoader:
    """Sozdaet DataLoader s fiksirovannym generatorom i pinned memory."""
    generator = torch.Generator()
    generator.manual_seed(seed)
    common = {
        "num_workers": model_config.workers,
        "pin_memory": True,
        "persistent_workers": model_config.workers > 0,
        "worker_init_fn": _seed_worker,
        "generator": generator,
    }
    if model_config.ranking_weight > 0.0 and dataset.include_target:
        if not dataset.include_group_id:
            raise ValueError("Ranking loader trebuet dataset s group_id")
        batch_sampler = EntryTimeBatchSampler(
            dataset.samples,
            batch_size=model_config.batch_size,
            shuffle=shuffle,
            seed=seed,
        )
        return DataLoader(dataset, batch_sampler=batch_sampler, **common)
    return DataLoader(
        dataset,
        batch_size=model_config.batch_size,
        shuffle=shuffle,
        drop_last=shuffle,
        **common,
    )


def pairwise_ranking_loss(
    predictions: torch.Tensor,
    targets: torch.Tensor,
    group_ids: torch.Tensor,
    temperature: float,
) -> torch.Tensor:
    """Schitaet logistic-loss tol'ko po uporyadochennym param vnutri timestamp."""
    if temperature <= 0:
        raise ValueError("ranking_temperature dolzhna byt polozhitel'noi")
    if predictions.ndim != 1 or targets.ndim != 1 or group_ids.ndim != 1:
        raise ValueError("Ranking tensors dolzhny byt odnomernymi")
    if not (len(predictions) == len(targets) == len(group_ids)):
        raise ValueError("Ranking tensors dolzhny imet odinakovuyu dlinu")
    group_losses: list[torch.Tensor] = []
    for group_id in torch.unique(group_ids, sorted=True):
        group_mask = group_ids.eq(group_id)
        group_predictions = predictions[group_mask]
        group_targets = targets[group_mask]
        ordered_target = group_targets[:, None] > group_targets[None, :]
        score_difference = (
            group_predictions[:, None] - group_predictions[None, :]
        )
        group_losses.append(
            functional.softplus(
                -score_difference[ordered_target] / temperature
            )
        )
    pair_losses = torch.cat(group_losses) if group_losses else predictions.new_empty(0)
    if pair_losses.numel() == 0:
        return predictions.sum() * 0.0
    return pair_losses.mean()


def _batch_loss(
    model: CausalTCN,
    batch: tuple[torch.Tensor, ...],
    device: torch.device,
    classification_weight: float,
    autocast_dtype: torch.dtype | None,
    ranking_weight: float = 0.0,
    ranking_temperature: float = 1.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Schitaet Huber, BCE i optional cross-sectional ranking loss."""
    if len(batch) not in {3, 4}:
        raise ValueError("Training batch dolzhen soderzhat' 3 ili 4 tenzora")
    features, targets, directions = (
        item.to(device, non_blocking=True) for item in batch[:3]
    )
    group_ids = batch[3].to(device, non_blocking=True) if len(batch) == 4 else None
    if ranking_weight > 0.0 and group_ids is None:
        raise ValueError("Ranking loss trebuet group_id v training batch")
    with torch.autocast(
        device_type="cuda",
        dtype=autocast_dtype or torch.float32,
        enabled=autocast_dtype is not None,
    ):
        predictions, logits = model(features)
        regression_loss = functional.smooth_l1_loss(predictions, targets, beta=0.5)
        classification_loss = functional.binary_cross_entropy_with_logits(logits, directions)
        loss = regression_loss + classification_weight * classification_loss
        if ranking_weight > 0.0 and group_ids is not None:
            ranking_loss = pairwise_ranking_loss(
                predictions.float(),
                targets.float(),
                group_ids,
                ranking_temperature,
            )
            loss = loss + ranking_weight * ranking_loss
    return loss, predictions


def mean_cross_section_ic(
    metadata: pd.DataFrame,
    predictions: np.ndarray,
    target_column: str = "target_return",
) -> float:
    """Schitaet srednyuyu Spearman-korrelyaciyu s ukazannym target po entry-time."""
    if len(metadata) != len(predictions):
        raise ValueError("Dlina prognozov ne sovpadaet s metadata")
    if target_column not in metadata:
        raise ValueError(f"Net target-kolonki dlya IC: {target_column}")
    evaluated = metadata.loc[:, ["entry_time", target_column]].copy()
    evaluated["prediction"] = predictions
    correlations: list[float] = []
    for _, group in evaluated.groupby("entry_time", sort=False):
        group = group.dropna(subset=["prediction", target_column])
        if len(group) < 3 or group["prediction"].nunique() < 2:
            continue
        correlation = spearmanr(group["prediction"], group[target_column]).statistic
        if np.isfinite(correlation):
            correlations.append(float(correlation))
    return float(np.mean(correlations)) if correlations else float("nan")


def predict_sequence_scores(
    model: CausalTCN,
    store: SequenceStore,
    samples: SequenceSamples,
    target_scale: float,
    model_config: SequenceModelConfig,
) -> np.ndarray:
    """Vychislyaet score v edinicah fakticheskoi dohodnosti bez shuffle."""
    device = _device()
    dataset = DynamicSequenceDataset(store, samples, target_scale, include_target=False)
    loader = _loader(dataset, model_config, shuffle=False, seed=0)
    model.eval()
    predictions: list[np.ndarray] = []
    autocast_dtype = _autocast_dtype(model_config.precision)
    with torch.inference_mode():
        for batch in loader:
            features = batch[0].to(device, non_blocking=True)
            with torch.autocast(
                device_type="cuda",
                dtype=autocast_dtype or torch.float32,
                enabled=autocast_dtype is not None,
            ):
                regression, _ = model(features)
            predictions.append(regression.float().cpu().numpy())
    return np.concatenate(predictions).astype(np.float64) * target_scale


def fit_with_early_stopping(
    store: SequenceStore,
    train_samples: SequenceSamples,
    validation_samples: SequenceSamples,
    target_scale: float,
    model_config: SequenceModelConfig,
    seed: int,
) -> TrainingOutcome:
    """Obuchaet model' i vybiraet epohu tol'ko po validation IC."""
    seed_everything(seed)
    device = _device()
    model = build_causal_tcn(store.assets[0].features.shape[1], model_config).to(device)
    train_dataset = DynamicSequenceDataset(
        store,
        train_samples,
        target_scale,
        include_group_id=model_config.ranking_weight > 0.0,
    )
    train_loader = _loader(train_dataset, model_config, shuffle=True, seed=seed)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=model_config.learning_rate,
        weight_decay=model_config.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=model_config.precision == "fp16")
    best_state: dict[str, torch.Tensor] | None = None
    best_ic = -np.inf
    best_epoch = 0
    stale_epochs = 0
    rows: list[dict[str, float | int]] = []
    started = time.perf_counter()
    autocast_dtype = _autocast_dtype(model_config.precision)
    for epoch in range(1, model_config.epochs + 1):
        model.train()
        losses: list[float] = []
        for batch in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss, _ = _batch_loss(
                model,
                batch,
                device,
                model_config.classification_weight,
                autocast_dtype,
                model_config.ranking_weight,
                model_config.ranking_temperature,
            )
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), model_config.gradient_clip)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
        predictions = predict_sequence_scores(
            model,
            store,
            validation_samples,
            target_scale,
            model_config,
        )
        validation_ic = mean_cross_section_ic(
            validation_samples.metadata,
            predictions,
            target_column="model_target",
        )
        comparable_ic = validation_ic if np.isfinite(validation_ic) else -np.inf
        rows.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)),
                "validation_ic": validation_ic,
            }
        )
        LOGGER.info(
            "TCN epoch=%s train_loss=%.6f validation_ic=%.6f",
            epoch,
            float(np.mean(losses)),
            validation_ic,
        )
        if comparable_ic > best_ic + 1e-5:
            best_ic = comparable_ic
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= model_config.patience:
            break
    if best_state is None:
        raise RuntimeError("Ne udalos vybrat' ni odnu TCN-epohu")
    model.load_state_dict(best_state)
    elapsed = time.perf_counter() - started
    return TrainingOutcome(
        model=model,
        best_epoch=best_epoch,
        best_validation_ic=float(best_ic),
        history=pd.DataFrame(rows),
        elapsed_seconds=elapsed,
    )


def fit_fixed_epochs(
    store: SequenceStore,
    samples: SequenceSamples,
    target_scale: float,
    model_config: SequenceModelConfig,
    epochs: int,
    seed: int,
) -> tuple[CausalTCN, pd.DataFrame]:
    """Pereobuchaet frozen-arhitekturu na vsem pre-test periode."""
    if epochs < 1:
        raise ValueError("epochs dolzhen byt polozhitel'nym")
    seed_everything(seed)
    device = _device()
    model = build_causal_tcn(store.assets[0].features.shape[1], model_config).to(device)
    dataset = DynamicSequenceDataset(
        store,
        samples,
        target_scale,
        include_group_id=model_config.ranking_weight > 0.0,
    )
    loader = _loader(dataset, model_config, shuffle=True, seed=seed)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=model_config.learning_rate,
        weight_decay=model_config.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=model_config.precision == "fp16")
    autocast_dtype = _autocast_dtype(model_config.precision)
    rows: list[dict[str, float | int]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        losses: list[float] = []
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            loss, _ = _batch_loss(
                model,
                batch,
                device,
                model_config.classification_weight,
                autocast_dtype,
                model_config.ranking_weight,
                model_config.ranking_temperature,
            )
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), model_config.gradient_clip)
            scaler.step(optimizer)
            scaler.update()
            losses.append(float(loss.detach().cpu()))
        rows.append({"epoch": epoch, "train_loss": float(np.mean(losses))})
        LOGGER.info("Final TCN epoch=%s train_loss=%.6f", epoch, float(np.mean(losses)))
    return model, pd.DataFrame(rows)
