"""Fixed training, OOS evaluation, and reporting for market-graph-v1."""

from __future__ import annotations

import argparse
import io
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as F

from .data import (
    PROJECT_ROOT,
    PROTOCOL_PATH,
    FoldDefinition,
    InferenceArrays,
    MarketGraphArrays,
    build_folds,
    causal_correlations,
    inference_arrays,
    load_market_graph_arrays,
    load_protocol,
    relative_momentum_scores,
    sha256_file,
)
from .model import MarketGraphModel, ModelOutput, parameter_count
from .portfolio import construct_prediction_weights, run_five_sleeve_backtest

VARIANTS = ("market_graph_full", "identical_temporal_encoder_without_cross_asset_attention")
MODEL_VARIANT = {
    "market_graph_full": "graph",
    "identical_temporal_encoder_without_cross_asset_attention": "no_attention",
}


@dataclass(frozen=True, slots=True)
class TorchInferenceArrays:
    """Target-free inference tensors resident on one compute device."""

    normalized_features: torch.Tensor
    asset_mask: torch.Tensor
    correlations: torch.Tensor


def _to_device_inference(
    inference: InferenceArrays,
    device: torch.device,
) -> TorchInferenceArrays:
    return TorchInferenceArrays(
        normalized_features=torch.as_tensor(inference.normalized_features, device=device),
        asset_mask=torch.as_tensor(inference.asset_mask, device=device, dtype=torch.bool),
        correlations=torch.as_tensor(inference.correlations, device=device),
    )


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
    torch.use_deterministic_algorithms(True)


def _batch_windows(
    inference: TorchInferenceArrays,
    indices: torch.Tensor,
    *,
    history: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Materialize only histories ending at the requested decision indices."""
    offsets = torch.arange(history - 1, -1, -1, device=device)
    lookup = indices[:, None] - offsets[None, :]
    windows = inference.normalized_features[lookup].permute(0, 2, 1, 3).contiguous()
    history_mask = inference.asset_mask[lookup].permute(0, 2, 1).contiguous()
    return windows, history_mask, inference.asset_mask[indices], inference.correlations[indices]


def _target_components(
    target: torch.Tensor,
    mask: torch.Tensor,
    factor_iqr: float,
    residual_iqr: float,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    count = mask.sum(dim=1).clamp_min(1)
    factor_raw = (target * mask).sum(dim=1) / count
    residual_raw = (target - factor_raw[:, None]) * mask
    return factor_raw / factor_iqr, residual_raw / residual_iqr, factor_raw


def _pairwise_rank_loss(
    predicted: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    assets = predicted.shape[1]
    predicted_difference = predicted[:, :, None] - predicted[:, None, :]
    target_difference = target[:, :, None] - target[:, None, :]
    pair_mask = mask[:, :, None] & mask[:, None, :]
    upper = torch.triu(
        torch.ones(assets, assets, device=predicted.device, dtype=torch.bool), diagonal=1
    )
    pair_mask = pair_mask & upper[None, :, :] & (target_difference.abs() > 1e-8)
    if not bool(pair_mask.any()):
        return predicted.sum() * 0.0
    signs = target_difference.sign()
    return F.softplus(-signs[pair_mask] * predicted_difference[pair_mask]).mean()


def _transaction_utility_loss(
    output: ModelOutput,
    target: torch.Tensor,
    target_mask: torch.Tensor,
    residual_iqr: float,
    one_way_cost: float,
) -> torch.Tensor:
    current = target_mask
    count = current.sum(dim=1, keepdim=True).clamp_min(1)
    residual_signal = torch.tanh(output.residual_location) * current
    residual_signal = residual_signal - (residual_signal.sum(dim=1, keepdim=True) / count) * current
    residual_signal = (
        0.75 * residual_signal / residual_signal.abs().sum(dim=1, keepdim=True).clamp_min(1e-6)
    )
    factor_signal = 0.25 * torch.tanh(output.factor_location)[:, None] * current / count
    weights = residual_signal + factor_signal
    utility = (weights * target).sum(dim=1) / residual_iqr
    if len(weights) > 1:
        turnover = (weights[1:] - weights[:-1]).abs().sum(dim=1)
        cost = one_way_cost * turnover / residual_iqr
        utility = utility.clone()
        utility[1:] = utility[1:] - cost
    return -utility.mean()


def training_loss(
    output: ModelOutput,
    target: torch.Tensor,
    target_mask: torch.Tensor,
    fold: FoldDefinition,
    loss_config: dict[str, float],
    one_way_cost: float,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Apply the frozen multi-head objective without using direction as return."""
    factor_target, residual_target, _ = _target_components(
        target, target_mask, fold.factor_iqr, fold.residual_iqr
    )
    date_valid = target_mask.any(dim=1)
    factor_huber = F.smooth_l1_loss(
        output.factor_location[date_valid], factor_target[date_valid], beta=1.0
    )
    residual_huber = F.smooth_l1_loss(
        output.residual_location[target_mask], residual_target[target_mask], beta=1.0
    )
    rank = _pairwise_rank_loss(output.residual_location, residual_target, target_mask)
    direction = F.binary_cross_entropy_with_logits(
        output.direction_logit[target_mask], (target[target_mask] > 0.0).float()
    )
    factor_sigma = output.factor_scale.clamp(0.03, 10.0)
    residual_sigma = output.residual_scale.clamp(0.03, 10.0)
    factor_error = output.factor_location - factor_target
    residual_error = output.residual_location - residual_target
    factor_nll = (
        0.5
        * (
            torch.square(factor_error[date_valid] / factor_sigma[date_valid])
            + 2.0 * torch.log(factor_sigma[date_valid])
        ).mean()
    )
    residual_nll = (
        0.5
        * (
            torch.square(residual_error[target_mask] / residual_sigma[target_mask])
            + 2.0 * torch.log(residual_sigma[target_mask])
        ).mean()
    )
    nll = 0.5 * (factor_nll + residual_nll)
    utility = _transaction_utility_loss(
        output, target, target_mask, fold.residual_iqr, one_way_cost
    )
    total = (
        float(loss_config["factor_huber_weight"]) * factor_huber
        + float(loss_config["residual_huber_weight"]) * residual_huber
        + float(loss_config["residual_pairwise_rank_weight"]) * rank
        + float(loss_config["auxiliary_direction_weight"]) * direction
        + float(loss_config["aleatoric_nll_weight"]) * nll
        + float(loss_config["transaction_cost_utility_weight"]) * utility
    )
    pieces = {
        "total": float(total.detach()),
        "factor_huber": float(factor_huber.detach()),
        "residual_huber": float(residual_huber.detach()),
        "rank": float(rank.detach()),
        "direction": float(direction.detach()),
        "nll": float(nll.detach()),
        "utility": float(utility.detach()),
    }
    return total, pieces


@torch.no_grad()
def predict_target_free(
    model: MarketGraphModel,
    inference: TorchInferenceArrays,
    indices: np.ndarray,
    *,
    history: int,
    batch_size: int,
    device: torch.device,
) -> dict[str, np.ndarray]:
    """Predict from a target-free container; labels cannot enter this call."""
    model.eval()
    result: dict[str, list[np.ndarray]] = {
        "factor_location": [],
        "factor_scale": [],
        "residual_location": [],
        "residual_scale": [],
        "direction_logit": [],
    }
    for start in range(0, len(indices), batch_size):
        batch = torch.as_tensor(
            indices[start : start + batch_size], device=device, dtype=torch.long
        )
        windows, history_mask, current_mask, correlations = _batch_windows(
            inference, batch, history=history, device=device
        )
        with torch.autocast(
            device_type=device.type,
            dtype=torch.bfloat16,
            enabled=device.type == "cuda",
        ):
            output = model(windows, history_mask, current_mask, correlations)
        for name in result:
            result[name].append(getattr(output, name).float().cpu().numpy())
    return {name: np.concatenate(parts, axis=0) for name, parts in result.items()}


def _state_sha256(model: MarketGraphModel) -> str:
    buffer = io.BytesIO()
    torch.save({name: value.detach().cpu() for name, value in model.state_dict().items()}, buffer)
    import hashlib

    return hashlib.sha256(buffer.getvalue()).hexdigest()


def train_one_model(
    arrays: MarketGraphArrays,
    inference: InferenceArrays,
    fold: FoldDefinition,
    config: dict[str, Any],
    *,
    variant: Literal["graph", "no_attention"],
    seed: int,
    device: torch.device,
    smoke: bool = False,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Train exactly one fixed seed/fold/ablation model."""
    _seed_everything(seed)
    model_config = config["model"]
    model = MarketGraphModel(
        input_features=len(arrays.feature_names),
        assets=len(arrays.tickers),
        hidden=int(model_config["temporal_encoder"]["hidden_dimension"]),
        temporal_blocks=int(model_config["temporal_encoder"]["blocks"]),
        graph_layers=int(model_config["cross_asset_encoder"]["layers"]),
        heads=int(model_config["cross_asset_encoder"]["heads"]),
        kernel_size=int(model_config["temporal_encoder"]["kernel_size"]),
        dropout=float(model_config["temporal_encoder"]["dropout"]),
        variant=variant,
    ).to(device)
    device_inference = _to_device_inference(inference, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(model_config["learning_rate"]),
        weight_decay=float(model_config["weight_decay"]),
    )
    target = torch.as_tensor(arrays.targets, device=device)
    target_mask = torch.as_tensor(arrays.target_mask, device=device, dtype=torch.bool)
    history = int(config["features"]["history_sessions"])
    batch_size = int(model_config["batch_decision_dates"])
    epochs = 1 if smoke else int(model_config["epochs"])
    train_indices = fold.train_indices[-64:] if smoke else fold.train_indices
    test_indices = fold.test_indices[:16] if smoke else fold.test_indices
    history_rows: list[dict[str, float | int]] = []
    started = perf_counter()
    one_way_cost = (
        float(config["portfolio"]["one_way_commission_bps"])
        + float(config["portfolio"]["one_way_slippage_bps"])
    ) / 10_000.0
    for epoch in range(epochs):
        model.train()
        sums: dict[str, float] = {}
        batches = 0
        for start in range(0, len(train_indices), batch_size):
            indices = torch.as_tensor(
                train_indices[start : start + batch_size], device=device, dtype=torch.long
            )
            windows, history_mask, current_mask, correlations = _batch_windows(
                device_inference, indices, history=history, device=device
            )
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.bfloat16,
                enabled=device.type == "cuda",
            ):
                output = model(windows, history_mask, current_mask, correlations)
                loss, pieces = training_loss(
                    output,
                    target[indices],
                    target_mask[indices],
                    fold,
                    config["loss"],
                    one_way_cost,
                )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            for name, value in pieces.items():
                sums[name] = sums.get(name, 0.0) + value
            batches += 1
        history_rows.append(
            {"epoch": epoch + 1, **{name: value / batches for name, value in sums.items()}}
        )
    predictions = predict_target_free(
        model,
        device_inference,
        test_indices,
        history=history,
        batch_size=batch_size,
        device=device,
    )
    audit = {
        "seed": seed,
        "fold_year": fold.year,
        "variant": variant,
        "epochs": epochs,
        "train_dates": int(len(train_indices)),
        "test_dates": int(len(test_indices)),
        "parameter_count": parameter_count(model),
        "state_sha256": _state_sha256(model),
        "elapsed_seconds": perf_counter() - started,
        "final_training_loss": history_rows[-1],
        "history": history_rows,
    }
    del model, optimizer, target, target_mask, device_inference
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return predictions, audit


def _empty_prediction_store(arrays: MarketGraphArrays) -> dict[str, np.ndarray]:
    days, assets = arrays.asset_mask.shape
    return {
        "factor_location": np.full(days, np.nan, dtype=np.float64),
        "factor_scale": np.full(days, np.nan, dtype=np.float64),
        "residual_location": np.full((days, assets), np.nan, dtype=np.float64),
        "residual_scale": np.full((days, assets), np.nan, dtype=np.float64),
        "direction_logit": np.full((days, assets), np.nan, dtype=np.float64),
    }


def arithmetic_seed_ensemble(seed_predictions: dict[int, np.ndarray]) -> np.ndarray:
    """Average every fixed seed in numeric order without seed selection."""
    if not seed_predictions:
        raise ValueError("seed ensemble cannot be empty")
    ordered = [seed_predictions[seed] for seed in sorted(seed_predictions)]
    reference = ordered[0].shape
    if any(values.shape != reference for values in ordered):
        raise ValueError("seed predictions have inconsistent shapes")
    return np.stack(ordered, axis=0).mean(axis=0)


def _cross_sectional_ic(
    dates: np.ndarray,
    scores: np.ndarray,
    targets: np.ndarray,
    mask: np.ndarray,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, date in enumerate(dates):
        valid = mask[index] & np.isfinite(scores[index]) & np.isfinite(targets[index])
        if valid.sum() < 3:
            continue
        score_rank = pd.Series(scores[index, valid]).rank(method="average").to_numpy()
        target_rank = pd.Series(targets[index, valid]).rank(method="average").to_numpy()
        correlation = float(np.corrcoef(score_rank, target_rank)[0, 1])
        rows.append(
            {"session_date": pd.Timestamp(date), "ic": correlation, "assets": int(valid.sum())}
        )
    return pd.DataFrame(rows)


def _ic_summary(frame: pd.DataFrame) -> dict[str, Any]:
    yearly = {
        str(int(year)): float(part["ic"].mean())
        for year, part in frame.groupby(frame["session_date"].dt.year)
    }
    return {
        "mean_daily_cross_sectional_spearman_ic": float(frame["ic"].mean()),
        "median_daily_cross_sectional_spearman_ic": float(frame["ic"].median()),
        "daily_ic_observations": int(len(frame)),
        "yearly_cross_sectional_spearman_ic": yearly,
    }


def _paired_graph_increment(graph: pd.DataFrame, independent: pd.DataFrame) -> dict[str, Any]:
    paired = graph.merge(independent, on="session_date", suffixes=("_graph", "_no_attention"))
    difference = paired["ic_graph"] - paired["ic_no_attention"]
    standard_error = float(difference.std(ddof=1) / math.sqrt(len(difference)))
    mean = float(difference.mean())
    return {
        "paired_dates": int(len(difference)),
        "mean_daily_ic_difference": mean,
        "median_daily_ic_difference": float(difference.median()),
        "paired_win_rate": float((difference > 0.0).mean()),
        "standard_error": standard_error,
        "t_statistic": mean / standard_error if standard_error > 0.0 else 0.0,
        "normal_95pct_interval": [mean - 1.96 * standard_error, mean + 1.96 * standard_error],
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _manifest(run_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files[path.relative_to(run_dir).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return {"files": files}


def _preflight(
    config: dict[str, Any], arrays: MarketGraphArrays, device: torch.device
) -> dict[str, Any]:
    return {
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "panel_sha256": config["source"]["panel_sha256"],
        "manifest_sha256": config["source"]["manifest_sha256"],
        "rows": int(len(arrays.dates) * len(arrays.tickers)),
        "dates": int(len(arrays.dates)),
        "tickers": int(len(arrays.tickers)),
        "minimum_date": str(pd.Timestamp(arrays.dates[0]).date()),
        "maximum_date": str(pd.Timestamp(arrays.dates[-1]).date()),
        "input_layout": ["batch_decision_dates", 30, 128, len(arrays.feature_names)],
        "target_free_inference_container": list(InferenceArrays.__dataclass_fields__),
        "device": str(device),
        "accelerator": torch.cuda.get_device_name(device)
        if device.type == "cuda"
        else "CPU smoke only",
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "protected_2026_read": False,
        "semantic_audit": {
            "signal_after_factual_daily_close": True,
            "entry_next_factual_asset_open": True,
            "exit_after_five_complete_common_sessions_with_factual_open_extension": True,
            "target_formula_exact": True,
            "reseal_required": False,
        },
    }


def run_experiment(*, output: Path | None = None, smoke: bool = False) -> Path:
    """Execute the tiny no-metric smoke or the full frozen experiment."""
    config = load_protocol()
    arrays = load_market_graph_arrays(config)
    correlations = causal_correlations(
        arrays.correlation_returns,
        arrays.asset_mask,
        lookback=int(config["features"]["correlation_bias"]["lookback_sessions"]),
        minimum_observations=int(
            config["features"]["correlation_bias"]["minimum_pair_observations"]
        ),
        clipping=tuple(config["features"]["correlation_bias"]["clipping"]),
    )
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if not smoke and (
        device.type != "cuda" or "RTX 5090" not in torch.cuda.get_device_name(device)
    ):
        raise RuntimeError("full market_graph_v1 requires the isolated RTX 5090")
    run_id = datetime.now(UTC).strftime("market_graph_v1_%Y%m%dT%H%M%SZ")
    run_dir = (output or PROJECT_ROOT / "runs" / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "preflight.json", _preflight(config, arrays, device))
    folds = build_folds(arrays, config)

    if smoke:
        fold = folds[0]
        inference = inference_arrays(arrays, fold, correlations)
        _, audit = train_one_model(
            arrays,
            inference,
            fold,
            config,
            variant="graph",
            seed=int(config["model"]["seeds"][0]),
            device=device,
            smoke=True,
        )
        audit["smoke_only_no_outcome_metrics"] = True
        _write_json(run_dir / "smoke.json", audit)
        _write_json(run_dir / "manifest.json", _manifest(run_dir))
        print(
            json.dumps(
                {"run_dir": str(run_dir), "smoke": True, "elapsed": audit["elapsed_seconds"]}
            ),
            flush=True,
        )
        return run_dir

    stores = {variant: _empty_prediction_store(arrays) for variant in VARIANTS}
    seed_stores: dict[str, dict[int, dict[str, np.ndarray]]] = {
        variant: {int(seed): _empty_prediction_store(arrays) for seed in config["model"]["seeds"]}
        for variant in VARIANTS
    }
    training_audit: list[dict[str, Any]] = []
    full_started = perf_counter()
    for fold in folds:
        inference = inference_arrays(arrays, fold, correlations)
        for declared_variant in VARIANTS:
            model_variant = MODEL_VARIANT[declared_variant]
            per_seed: list[dict[str, np.ndarray]] = []
            for seed in config["model"]["seeds"]:
                predictions, audit = train_one_model(
                    arrays,
                    inference,
                    fold,
                    config,
                    variant=model_variant,
                    seed=int(seed),
                    device=device,
                )
                for name, values in predictions.items():
                    if name.startswith("factor"):
                        converted = values * fold.factor_iqr
                    elif name.startswith("residual"):
                        converted = values * fold.residual_iqr
                    else:
                        converted = values
                    seed_stores[declared_variant][int(seed)][name][fold.test_indices] = converted
                per_seed.append(predictions)
                audit["declared_variant"] = declared_variant
                training_audit.append(audit)
                print(
                    json.dumps(
                        {
                            "complete": len(training_audit),
                            "total": len(folds) * len(VARIANTS) * len(config["model"]["seeds"]),
                            "fold": fold.year,
                            "variant": declared_variant,
                            "seed": seed,
                            "seconds": audit["elapsed_seconds"],
                        }
                    ),
                    flush=True,
                )
            for name in stores[declared_variant]:
                ensemble = arithmetic_seed_ensemble(
                    {
                        int(seed): seed_stores[declared_variant][int(seed)][name][fold.test_indices]
                        for seed in config["model"]["seeds"]
                    }
                )
                stores[declared_variant][name][fold.test_indices] = ensemble

    oos = np.zeros(len(arrays.dates), dtype=bool)
    for fold in folds:
        oos[fold.test_indices] = True
    target_mask = arrays.target_mask & oos[:, None]
    momentum = relative_momentum_scores(arrays).astype(np.float64)
    scores: dict[str, np.ndarray] = {
        variant: stores[variant]["factor_location"][:, None] + stores[variant]["residual_location"]
        for variant in VARIANTS
    }
    scores["relative_momentum_20_60_120"] = momentum
    ic_frames = {
        name: _cross_sectional_ic(arrays.dates, values, arrays.targets, target_mask)
        for name, values in scores.items()
    }
    ic_summaries = {name: _ic_summary(frame) for name, frame in ic_frames.items()}
    graph_increment = _paired_graph_increment(ic_frames[VARIANTS[0]], ic_frames[VARIANTS[1]])

    portfolio_config = config["portfolio"]
    portfolio_metrics: dict[str, Any] = {}
    first_oos = int(np.flatnonzero(oos)[0])
    portfolio_dir = run_dir / "portfolio"
    portfolio_dir.mkdir()
    for name in (*VARIANTS, "relative_momentum_20_60_120"):
        if name in stores:
            factor_location = stores[name]["factor_location"]
            factor_scale = stores[name]["factor_scale"]
            residual_location = stores[name]["residual_location"]
        else:
            factor_location = np.zeros(len(arrays.dates), dtype=np.float64)
            factor_scale = np.full(len(arrays.dates), np.inf, dtype=np.float64)
            residual_location = momentum
        weights = construct_prediction_weights(
            factor_location,
            factor_scale,
            residual_location,
            arrays.asset_mask & oos[:, None],
            target_mask,
            factor_budget=float(portfolio_config["factor_gross_budget"]),
            factor_minimum_snr=float(portfolio_config["factor_minimum_snr"]),
            residual_budget=float(portfolio_config["residual_gross_budget"]),
            top_bottom=5,
            maximum_stock_weight=float(portfolio_config["maximum_single_stock_absolute_weight"]),
        )
        portfolio_metrics[name] = {}
        for multiplier in (1.0, float(portfolio_config["stress_cost_multiplier"])):
            result = run_five_sleeve_backtest(
                arrays.dates,
                arrays.tickers,
                arrays.raw_open,
                weights,
                start_index=first_oos,
                initial_capital=float(portfolio_config["initial_capital_rub"]),
                one_way_cost_bps=float(portfolio_config["one_way_commission_bps"])
                + float(portfolio_config["one_way_slippage_bps"]),
                short_borrow_rate_annual=float(portfolio_config["short_borrow_rate_annual"]),
                cost_multiplier=multiplier,
                maximum_stock_weight=float(
                    portfolio_config["maximum_single_stock_absolute_weight"]
                ),
            )
            label = "base_cost" if multiplier == 1.0 else "double_cost"
            portfolio_metrics[name][label] = {
                **result.metrics,
                "yearly_returns": result.yearly_returns,
            }
            result.ledger.to_csv(portfolio_dir / f"{name}_{label}_ledger.csv", index=False)
            result.orders.to_csv(portfolio_dir / f"{name}_{label}_orders.csv", index=False)
        np.save(portfolio_dir / f"{name}_signal_weights.npy", weights.astype(np.float32))

    prediction_rows: list[pd.DataFrame] = []
    for date_index in np.flatnonzero(oos):
        part: dict[str, Any] = {
            "session_date": np.repeat(arrays.dates[date_index], len(arrays.tickers)),
            "ticker": arrays.tickers,
            "target_valid": arrays.target_mask[date_index],
            "raw_target_return": arrays.targets[date_index],
        }
        for variant in VARIANTS:
            part[f"{variant}_factor_location"] = np.repeat(
                stores[variant]["factor_location"][date_index], len(arrays.tickers)
            )
            part[f"{variant}_factor_scale"] = np.repeat(
                stores[variant]["factor_scale"][date_index], len(arrays.tickers)
            )
            part[f"{variant}_residual_location"] = stores[variant]["residual_location"][date_index]
            part[f"{variant}_residual_scale"] = stores[variant]["residual_scale"][date_index]
            part[f"{variant}_aux_direction_logit"] = stores[variant]["direction_logit"][date_index]
            for seed in config["model"]["seeds"]:
                seed_store = seed_stores[variant][int(seed)]
                part[f"{variant}_seed_{seed}_score"] = (
                    seed_store["factor_location"][date_index]
                    + seed_store["residual_location"][date_index]
                )
        part["relative_momentum_score"] = momentum[date_index]
        prediction_rows.append(pd.DataFrame(part))
    predictions_frame = pd.concat(prediction_rows, ignore_index=True)
    predictions_frame.to_parquet(run_dir / "oos_predictions.parquet", index=False)
    for name, frame in ic_frames.items():
        frame.to_csv(run_dir / f"daily_ic_{name}.csv", index=False)
    _write_json(run_dir / "training_audit.json", training_audit)

    graph_sharpe = float(portfolio_metrics[VARIANTS[0]]["base_cost"]["net_sharpe"])
    promoted = graph_increment["mean_daily_ic_difference"] > 0.0 and graph_sharpe >= float(
        config["reporting"]["promote_only_if_graph_beats_no_attention_and_net_sharpe_ge"]
    )
    metrics = {
        "research_status": "DEVELOPMENT_ONLY_NO_LIVE_TRADING",
        "oos_date_count": int(oos.sum()),
        "oos_valid_asset_rows": int(target_mask.sum()),
        "ic": ic_summaries,
        "paired_graph_increment": graph_increment,
        "portfolio": portfolio_metrics,
        "promotion": {
            "promoted": bool(promoted),
            "required_graph_ic_improvement_positive": True,
            "required_net_sharpe": float(
                config["reporting"]["promote_only_if_graph_beats_no_attention_and_net_sharpe_ge"]
            ),
        },
        "known_failures": [
            "Fixed 30-name development universe is not a historical index-membership "
            "universe and can retain survivorship bias.",
            "Historical point-in-time short-borrow availability is absent; the backtest "
            "applies the sealed 20% annual borrow charge but cannot prove borrowability.",
            "Daily open data cannot model intraday path, auction queue, bid/ask, or market impact.",
            "MOEX data rights must be confirmed separately before commercial or live use.",
        ],
        "elapsed_seconds": perf_counter() - full_started,
    }
    _write_json(run_dir / "metrics.json", metrics)
    code_files = [
        Path(__file__),
        Path(__file__).with_name("data.py"),
        Path(__file__).with_name("model.py"),
        Path(__file__).with_name("portfolio.py"),
    ]
    _write_json(
        run_dir / "code_identity.json",
        {path.name: sha256_file(path) for path in code_files},
    )
    _write_json(run_dir / "manifest.json", _manifest(run_dir))
    print(json.dumps({"run_dir": str(run_dir), "metrics": metrics}, default=str), flush=True)
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sealed market_graph_v1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--smoke", action="store_true")
    arguments = parser.parse_args()
    run_experiment(output=arguments.output, smoke=arguments.smoke)


if __name__ == "__main__":
    main()
