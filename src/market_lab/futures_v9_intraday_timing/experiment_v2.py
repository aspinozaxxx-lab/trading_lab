"""Pre-sealed v2: chronological train-only calibration of the entry gate."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd
import torch
from sklearn.isotonic import IsotonicRegression

from .data import ASSETS, FEATURE_NAMES, TimingArrays, load_timing_arrays, sha256_file
from .experiment import (
    OUTPUT_NAMES,
    PROJECT_ROOT,
    TARGET_SCALE,
    FoldDefinition,
    _batch_windows,
    _masked_training_loss,
    _predict,
    _scaled_inputs,
    _seed_everything,
    build_folds,
    calculate_metrics,
    simulate_policy,
)
from .model import TimingGRU

V2_PROTOCOL_PATH = PROJECT_ROOT / "configs/futures_v9_intraday_timing_v2.yaml"
V2_PROTOCOL_SHA256 = "4268723dbeca5408592399b680af36216f8f70cd7ca6439811d706e7977d3dcc"
DEFAULT_TENSOR = (
    PROJECT_ROOT / "data/processed/futures_v9_intraday_timing/development_2018_2025.npz"
)
QUANTILES = (0.90, 0.95, 0.975, 0.99, 0.995)


def _inner_indices(
    arrays: TimingArrays,
    fold: FoldDefinition,
) -> tuple[np.ndarray, np.ndarray]:
    timestamps = pd.to_datetime(arrays.timestamps_ns, utc=True)
    test_start = pd.Timestamp(f"{fold.test_year}-01-01", tz="UTC")
    gate_start = test_start - pd.Timedelta(days=60)
    purge = pd.Timedelta(minutes=180)
    validation_times = timestamps[fold.validation_indices]
    isotonic = fold.validation_indices[validation_times < gate_start - purge]
    gate = fold.validation_indices[
        (validation_times >= gate_start) & (validation_times < test_start - purge)
    ]
    if min(len(isotonic), len(gate)) < 500:
        raise ValueError(f"inner chronological slices too small for {fold.test_year}")
    return isotonic, gate


def _validation_loss(
    predicted: np.ndarray,
    sigma: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
) -> float:
    scaled_error = np.abs((predicted - target) * TARGET_SCALE)
    huber = np.where(scaled_error < 1.0, 0.5 * scaled_error**2, scaled_error - 0.5)
    value_loss = float(np.nanmean(np.where(mask, huber, np.nan)))
    counts = mask.sum(axis=-1)
    realized = np.divide(
        np.where(mask, scaled_error, 0.0).sum(axis=-1),
        counts,
        out=np.zeros_like(counts, dtype=float),
        where=counts > 0,
    )
    valid = counts > 0
    sigma_error = np.abs(sigma.squeeze(-1)[valid] * TARGET_SCALE - realized[valid])
    sigma_huber = np.where(sigma_error < 1.0, 0.5 * sigma_error**2, sigma_error - 0.5)
    return value_loss + 0.1 * float(np.mean(sigma_huber))


def train_v2_seed(
    arrays: TimingArrays,
    fold: FoldDefinition,
    *,
    isotonic_indices: np.ndarray,
    gate_indices: np.ndarray,
    variant: Literal["attention", "independent"],
    seed: int,
    device: torch.device,
    maximum_epochs: int = 8,
    batch_size: int = 512,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    _seed_everything(seed)
    normalized = _scaled_inputs(arrays, fold)
    inputs = torch.as_tensor(normalized, device=device)
    del normalized
    target_values = arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6)
    target_masks = arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6)
    targets = torch.as_tensor(target_values, device=device)
    masks = torch.as_tensor(target_masks, device=device)
    current_mask = torch.as_tensor(arrays.asset_mask, device=device, dtype=torch.bool)
    model = TimingGRU(input_size=2 * len(FEATURE_NAMES), variant=variant).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
    best_loss = math.inf
    best_state: dict[str, torch.Tensor] | None = None
    patience = 0
    histories: list[dict[str, float]] = []
    started = perf_counter()
    train_indices = torch.as_tensor(fold.train_indices, device=device, dtype=torch.long)
    for epoch in range(maximum_epochs):
        model.train()
        generator = torch.Generator(device=device).manual_seed(seed * 100 + epoch)
        order = train_indices[torch.randperm(len(train_indices), generator=generator, device=device)]
        train_loss = 0.0
        batches = 0
        for start in range(0, len(order), batch_size):
            batch = order[start : start + batch_size]
            windows = _batch_windows(inputs, batch)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type=device.type,
                dtype=torch.bfloat16,
                enabled=device.type == "cuda",
            ):
                predicted, uncertainty = model(windows, current_mask[batch])
                loss = _masked_training_loss(
                    predicted,
                    uncertainty,
                    targets[batch] * TARGET_SCALE,
                    masks[batch],
                )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += float(loss.detach())
            batches += 1
        fit_values, fit_sigma = _predict(
            model,
            inputs,
            arrays,
            isotonic_indices,
            device,
            batch_size,
        )
        validation_loss = _validation_loss(
            fit_values,
            fit_sigma,
            target_values[isotonic_indices],
            target_masks[isotonic_indices],
        )
        histories.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": train_loss / max(batches, 1),
                "isotonic_slice_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-5:
            best_loss = validation_loss
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }
            patience = 0
        else:
            patience += 1
            if patience >= 2:
                break
    if best_state is None:
        raise RuntimeError("v2 training produced no finite checkpoint")
    model.load_state_dict(best_state)
    fit_values, fit_sigma = _predict(
        model, inputs, arrays, isotonic_indices, device, batch_size
    )
    gate_values, gate_sigma = _predict(
        model, inputs, arrays, gate_indices, device, batch_size
    )
    test_values, test_sigma = _predict(
        model, inputs, arrays, fold.test_indices, device, batch_size
    )
    fit_target = target_values[isotonic_indices]
    fit_mask = target_masks[isotonic_indices]
    calibrated_gate = np.full_like(gate_values, np.nan)
    calibrated_test = np.full_like(test_values, np.nan)
    gate_total_sigma = np.full_like(gate_values, np.nan)
    test_total_sigma = np.full_like(test_values, np.nan)
    calibration: list[dict[str, object]] = []
    for output_index, output in enumerate(OUTPUT_NAMES):
        valid = fit_mask[:, :, output_index] & np.isfinite(fit_values[:, :, output_index])
        x = fit_values[:, :, output_index][valid]
        y = fit_target[:, :, output_index][valid]
        calibrator = IsotonicRegression(increasing=True, out_of_bounds="clip")
        calibrator.fit(x, y)
        fit_calibrated = calibrator.predict(
            fit_values[:, :, output_index].ravel()
        ).reshape(fit_values.shape[:2])
        calibrated_gate[:, :, output_index] = calibrator.predict(
            gate_values[:, :, output_index].ravel()
        ).reshape(gate_values.shape[:2])
        calibrated_test[:, :, output_index] = calibrator.predict(
            test_values[:, :, output_index].ravel()
        ).reshape(test_values.shape[:2])
        residual = y - fit_calibrated[valid]
        center = float(np.median(residual))
        scale = max(float(1.4826 * np.median(np.abs(residual - center))), 1e-5)
        gate_total_sigma[:, :, output_index] = np.maximum(gate_sigma.squeeze(-1), scale)
        test_total_sigma[:, :, output_index] = np.maximum(test_sigma.squeeze(-1), scale)
        calibration.append({"output": output, "rows": int(len(x)), "residual_scale": scale})
    audit = {
        "variant": variant,
        "seed": seed,
        "test_year": fold.test_year,
        "train_rows": int(len(fold.train_indices)),
        "isotonic_rows": int(len(isotonic_indices)),
        "gate_rows": int(len(gate_indices)),
        "test_rows": int(len(fold.test_indices)),
        "epochs": len(histories),
        "best_isotonic_slice_loss": best_loss,
        "elapsed_seconds": perf_counter() - started,
        "history": histories,
        "calibration": calibration,
    }
    del model, optimizer, inputs, targets, masks, current_mask
    torch.cuda.empty_cache()
    return calibrated_gate, gate_total_sigma, calibrated_test, test_total_sigma, audit


def _select_gate_thresholds(
    arrays: TimingArrays,
    gate_indices: np.ndarray,
    values: np.ndarray,
    uncertainty: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    target = arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6)[gate_indices]
    target_mask = arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6)[gate_indices]
    thresholds = np.full(6, np.inf, dtype=np.float64)
    audit: list[dict[str, object]] = []
    for output_index, output in enumerate(OUTPUT_NAMES):
        valid = (
            target_mask[:, :, output_index]
            & np.isfinite(values[:, :, output_index])
            & np.isfinite(uncertainty[:, :, output_index])
            & (uncertainty[:, :, output_index] > 0.0)
        )
        score = values[:, :, output_index][valid] / uncertainty[:, :, output_index][valid]
        realized = target[:, :, output_index][valid]
        candidates: list[dict[str, object]] = []
        selected_quantile: float | None = None
        for quantile in QUANTILES:
            cutoff = float(np.quantile(score, quantile))
            chosen = (score >= cutoff) & (score > 0.0)
            rows = int(chosen.sum())
            mean = float(np.mean(realized[chosen])) if rows else math.nan
            standard_error = (
                float(np.std(realized[chosen], ddof=1) / math.sqrt(rows)) if rows >= 2 else math.inf
            )
            lower_bound = mean - 1.645 * standard_error
            passed = bool(
                cutoff > 0.0
                and rows >= 200
                and mean > 0.0
                and lower_bound > 0.0
            )
            candidates.append(
                {
                    "quantile": quantile,
                    "cutoff": cutoff,
                    "rows": rows,
                    "mean_realized_net_value": mean,
                    "standard_error": standard_error,
                    "one_sided_95pct_lower_bound": lower_bound,
                    "passed": passed,
                }
            )
            if passed and selected_quantile is None:
                thresholds[output_index] = cutoff
                selected_quantile = quantile
        audit.append(
            {
                "output": output,
                "valid_gate_rows": int(valid.sum()),
                "selected_quantile": selected_quantile,
                "selected_cutoff": (
                    float(thresholds[output_index])
                    if np.isfinite(thresholds[output_index])
                    else None
                ),
                "sleeping": selected_quantile is None,
                "candidates": candidates,
            }
        )
    return thresholds, audit


def run_experiment_v2(
    *,
    tensor_path: Path,
    output_dir: Path,
    years: Sequence[int] = (2021, 2022, 2023, 2024, 2025),
    seeds: Sequence[int] = (1729, 2718, 3141),
    variants: Sequence[Literal["attention", "independent"]] = ("attention", "independent"),
    maximum_epochs: int = 8,
) -> dict[str, object]:
    if sha256_file(V2_PROTOCOL_PATH) != V2_PROTOCOL_SHA256:
        raise ValueError("v2 protocol byte drift")
    arrays = load_timing_arrays(tensor_path)
    if arrays.timestamps_ns[-1] >= pd.Timestamp("2026-01-01", tz="UTC").value:
        raise ValueError("v2 tensor touches protected holdout")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda" or "5090" not in torch.cuda.get_device_name(0):
        raise RuntimeError("v2 requires isolated RTX 5090")
    output_dir.mkdir(parents=True, exist_ok=False)
    folds = build_folds(arrays, years)
    all_metrics: dict[str, object] = {}
    threshold_audit: list[dict[str, object]] = []
    training_audit: list[dict[str, object]] = []
    prediction_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    for variant in variants:
        dense_values = np.full((len(arrays.timestamps_ns), 4, 6), np.nan, dtype=np.float32)
        dense_sigma = np.full_like(dense_values, np.nan)
        dense_gate = np.zeros(dense_values.shape, dtype=bool)
        for fold in folds:
            isotonic_indices, gate_indices = _inner_indices(arrays, fold)
            seed_gate_values: list[np.ndarray] = []
            seed_gate_sigma: list[np.ndarray] = []
            seed_test_values: list[np.ndarray] = []
            seed_test_sigma: list[np.ndarray] = []
            for seed in seeds:
                gate_values, gate_sigma, test_values, test_sigma, audit = train_v2_seed(
                    arrays,
                    fold,
                    isotonic_indices=isotonic_indices,
                    gate_indices=gate_indices,
                    variant=variant,
                    seed=seed,
                    device=device,
                    maximum_epochs=maximum_epochs,
                )
                seed_gate_values.append(gate_values)
                seed_gate_sigma.append(gate_sigma)
                seed_test_values.append(test_values)
                seed_test_sigma.append(test_sigma)
                training_audit.append(audit)
                print(json.dumps({"milestone": "v2_model_complete", **audit}), flush=True)
            gate_stack = np.stack(seed_gate_values)
            gate_mean = gate_stack.mean(axis=0)
            gate_sigma_stack = np.stack(seed_gate_sigma)
            gate_total_sigma = np.sqrt(
                np.mean(gate_sigma_stack**2 + (gate_stack - gate_mean[None]) ** 2, axis=0)
            )
            test_stack = np.stack(seed_test_values)
            test_mean = test_stack.mean(axis=0)
            test_sigma_stack = np.stack(seed_test_sigma)
            test_total_sigma = np.sqrt(
                np.mean(test_sigma_stack**2 + (test_stack - test_mean[None]) ** 2, axis=0)
            )
            thresholds, fold_gate_audit = _select_gate_thresholds(
                arrays,
                gate_indices,
                gate_mean,
                gate_total_sigma,
            )
            score = test_mean / test_total_sigma
            entry_gate = (
                (test_mean > 0.0)
                & np.isfinite(thresholds)[None, None, :]
                & (score >= thresholds[None, None, :])
            )
            dense_values[fold.test_indices] = test_mean
            dense_sigma[fold.test_indices] = test_total_sigma
            dense_gate[fold.test_indices] = entry_gate
            threshold_audit.append(
                {
                    "variant": variant,
                    "test_year": fold.test_year,
                    "isotonic_rows": int(len(isotonic_indices)),
                    "gate_rows": int(len(gate_indices)),
                    "outputs": fold_gate_audit,
                    "outer_rows_passing_gate": int(entry_gate.sum()),
                }
            )
        trades = simulate_policy(
            arrays,
            years=years,
            values=dense_values,
            uncertainty=dense_sigma,
            baseline_scores=None,
            entry_gate=dense_gate,
            minimum_snr=None,
        )
        all_metrics[variant] = {
            "cost_1x": calculate_metrics(arrays, trades, years, cost_column="pnl_1x"),
            "cost_2x": calculate_metrics(arrays, trades, years, cost_column="pnl_2x"),
        }
        test_indices = np.concatenate([fold.test_indices for fold in folds])
        frame = pd.DataFrame(
            {
                "timestamp": np.repeat(
                    pd.to_datetime(arrays.timestamps_ns[test_indices], utc=True), 4
                ),
                "asset": np.tile(np.asarray(ASSETS), len(test_indices)),
                "variant": variant,
            }
        )
        values_flat = dense_values[test_indices].reshape(-1, 6)
        sigma_flat = dense_sigma[test_indices].reshape(-1, 6)
        gate_flat = dense_gate[test_indices].reshape(-1, 6)
        for output_index, output in enumerate(OUTPUT_NAMES):
            frame[output] = values_flat[:, output_index]
            frame[f"{output}_uncertainty"] = sigma_flat[:, output_index]
            frame[f"{output}_gate"] = gate_flat[:, output_index]
        prediction_frames.append(frame)
        if not trades.empty:
            trade_frames.append(trades.assign(strategy=variant))
    predictions = pd.concat(prediction_frames, ignore_index=True)
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    predictions.to_parquet(output_dir / "predictions.parquet", index=False)
    trades.to_parquet(output_dir / "trades.parquet", index=False)
    (output_dir / "threshold_audit.json").write_text(
        json.dumps(threshold_audit, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    (output_dir / "training_audit.json").write_text(
        json.dumps(training_audit, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    result: dict[str, object] = {
        "schema_version": 2,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": V2_PROTOCOL_SHA256,
        "tensor_sha256": sha256_file(tensor_path),
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "years": list(years),
        "seeds": list(seeds),
        "variants": list(variants),
        "metrics": all_metrics,
        "artifacts": {},
    }
    for name in (
        "predictions.parquet",
        "trades.parquet",
        "threshold_audit.json",
        "training_audit.json",
    ):
        path = output_dir / name
        result["artifacts"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=float) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tensor", type=Path, default=DEFAULT_TENSOR)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", default="2021,2022,2023,2024,2025")
    parser.add_argument("--seeds", default="1729,2718,3141")
    parser.add_argument("--variants", default="attention,independent")
    parser.add_argument("--maximum-epochs", type=int, default=8)
    args = parser.parse_args()
    result = run_experiment_v2(
        tensor_path=args.tensor,
        output_dir=args.output,
        years=tuple(int(item) for item in args.folds.split(",") if item),
        seeds=tuple(int(item) for item in args.seeds.split(",") if item),
        variants=tuple(item for item in args.variants.split(",") if item),
        maximum_epochs=args.maximum_epochs,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=float))


if __name__ == "__main__":
    main()
