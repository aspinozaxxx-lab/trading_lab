"""Walk-forward training, calibration, execution, and reporting for timing-v9."""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import torch
from sklearn.isotonic import IsotonicRegression
from torch.nn import functional as F

from .data import ASSETS, FEATURE_NAMES, HORIZONS, TimingArrays, load_timing_arrays, sha256_file
from .model import TimingGRU

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = PROJECT_ROOT / "configs/futures_v9_intraday_timing.yaml"
PROTOCOL_SHA256 = "fd6ee70086bc7056ca60c73a91490362aae37c4caf053091cc73e2e0924159cf"
DEFAULT_TENSOR = PROJECT_ROOT / "data/processed/futures_v9_intraday_timing/development_2018_2025.npz"
MOSCOW = ZoneInfo("Europe/Moscow")
HISTORY = 144
TARGET_SCALE = 1000.0
OUTPUT_NAMES = (
    "long_value_3",
    "short_value_3",
    "long_value_6",
    "short_value_6",
    "long_value_18",
    "short_value_18",
)


@dataclass(frozen=True, slots=True)
class FoldDefinition:
    test_year: int
    train_indices: np.ndarray
    validation_indices: np.ndarray
    test_indices: np.ndarray
    median: np.ndarray
    iqr: np.ndarray


@dataclass(slots=True)
class OpenPosition:
    asset_index: int
    side: int
    quantity: int
    entry_index: int
    entry_time_ns: int
    entry_price: float
    point_value: float
    notional_per_contract: float
    fee_per_side: float
    participation: float
    forecast_horizon: int
    forecast_edge: float
    forecast_snr: float


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _eligible_indices(arrays: TimingArrays) -> np.ndarray:
    label_present = arrays.target_mask.any(axis=(1, 2, 3))
    current_present = arrays.asset_mask.any(axis=1)
    eligible = np.flatnonzero(label_present & current_present)
    return eligible[eligible >= HISTORY - 1]


def _robust_scale(arrays: TimingArrays, cutoff_index: int) -> tuple[np.ndarray, np.ndarray]:
    values = arrays.features[: cutoff_index + 1]
    mask = arrays.feature_mask[: cutoff_index + 1]
    median = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
    iqr = np.ones(len(FEATURE_NAMES), dtype=np.float32)
    for feature_index in range(len(FEATURE_NAMES)):
        sample = values[:, :, feature_index][mask[:, :, feature_index]]
        if len(sample) < 100:
            # A sealed feature may legitimately sleep when exact-gap rules make
            # its full lookback unavailable.  Its mask remains zero and it is
            # never silently presented to the network as an observation.
            median[feature_index] = 0.0
            iqr[feature_index] = 1.0
            continue
        q25, q50, q75 = np.quantile(sample, [0.25, 0.5, 0.75])
        median[feature_index] = q50
        iqr[feature_index] = max(float(q75 - q25), 1e-6)
    return median, iqr


def build_folds(arrays: TimingArrays, years: Sequence[int]) -> tuple[FoldDefinition, ...]:
    timestamps = pd.to_datetime(arrays.timestamps_ns, utc=True)
    eligible = _eligible_indices(arrays)
    folds: list[FoldDefinition] = []
    for year in years:
        test_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        test_end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        validation_start = test_start - pd.Timedelta(days=120)
        purge = pd.Timedelta(minutes=180)
        train_end = validation_start - purge
        validation_end = test_start - purge
        times = timestamps[eligible]
        train = eligible[times < train_end]
        validation = eligible[(times >= validation_start) & (times < validation_end)]
        test = eligible[(times >= test_start) & (times < test_end)]
        if min(len(train), len(validation), len(test)) == 0:
            raise ValueError(f"empty fold component for {year}")
        median, iqr = _robust_scale(arrays, int(train[-1]))
        folds.append(
            FoldDefinition(
                test_year=year,
                train_indices=train,
                validation_indices=validation,
                test_indices=test,
                median=median,
                iqr=iqr,
            )
        )
    return tuple(folds)


def _scaled_inputs(arrays: TimingArrays, fold: FoldDefinition) -> np.ndarray:
    scaled = (arrays.features - fold.median[None, None, :]) / fold.iqr[None, None, :]
    scaled = np.clip(scaled, -10.0, 10.0)
    observed = np.where(arrays.feature_mask, scaled, 0.0).astype(np.float32)
    return np.concatenate([observed, arrays.feature_mask.astype(np.float32)], axis=-1)


def _batch_windows(inputs: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    offsets = torch.arange(HISTORY - 1, -1, -1, device=indices.device)
    return inputs[indices[:, None] - offsets[None, :]]


def _masked_training_loss(
    predicted: torch.Tensor,
    predicted_uncertainty: torch.Tensor,
    target: torch.Tensor,
    target_mask: torch.Tensor,
) -> torch.Tensor:
    valid = target_mask
    if not bool(valid.any()):
        return predicted.sum() * 0.0
    value_loss = F.smooth_l1_loss(predicted[valid], target[valid], beta=1.0)
    absolute_error = torch.where(valid, torch.abs(predicted - target), 0.0)
    count = valid.sum(dim=-1).clamp_min(1)
    realized_uncertainty = absolute_error.sum(dim=-1) / count
    asset_valid = valid.any(dim=-1)
    uncertainty_loss = F.smooth_l1_loss(
        predicted_uncertainty.squeeze(-1)[asset_valid],
        realized_uncertainty.detach()[asset_valid],
        beta=1.0,
    )
    return value_loss + 0.1 * uncertainty_loss


@torch.no_grad()
def _predict(
    model: TimingGRU,
    inputs: torch.Tensor,
    arrays: TimingArrays,
    indices: np.ndarray,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    values: list[np.ndarray] = []
    uncertainty: list[np.ndarray] = []
    current_mask = torch.as_tensor(arrays.asset_mask, device=device, dtype=torch.bool)
    for start in range(0, len(indices), batch_size):
        batch_np = indices[start : start + batch_size]
        batch = torch.as_tensor(batch_np, device=device, dtype=torch.long)
        windows = _batch_windows(inputs, batch)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            predicted, sigma = model(windows, current_mask[batch])
        values.append((predicted.float() / TARGET_SCALE).cpu().numpy())
        uncertainty.append((sigma.float() / TARGET_SCALE).cpu().numpy())
    return np.concatenate(values), np.concatenate(uncertainty)


def train_one_model(
    arrays: TimingArrays,
    fold: FoldDefinition,
    *,
    variant: Literal["attention", "independent"],
    seed: int,
    maximum_epochs: int,
    device: torch.device,
    batch_size: int = 512,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    _seed_everything(seed)
    normalized = _scaled_inputs(arrays, fold)
    inputs = torch.as_tensor(normalized, device=device)
    del normalized
    targets = torch.as_tensor(arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6), device=device)
    target_mask = torch.as_tensor(arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6), device=device)
    current_mask = torch.as_tensor(arrays.asset_mask, device=device, dtype=torch.bool)
    model = TimingGRU(input_size=2 * len(FEATURE_NAMES), variant=variant).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.0001)
    scaler = torch.amp.GradScaler("cuda", enabled=False)
    best_loss = math.inf
    best_state: dict[str, torch.Tensor] | None = None
    patience = 0
    history: list[dict[str, float]] = []
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
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                predicted, sigma = model(windows, current_mask[batch])
                loss = _masked_training_loss(
                    predicted,
                    sigma,
                    targets[batch] * TARGET_SCALE,
                    target_mask[batch],
                )
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            train_loss += float(loss.detach())
            batches += 1
        validation_values, validation_sigma = _predict(
            model,
            inputs,
            arrays,
            fold.validation_indices,
            device,
            batch_size,
        )
        val_target = arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6)[fold.validation_indices]
        val_mask = arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6)[fold.validation_indices]
        val_scaled = validation_values * TARGET_SCALE
        val_sigma_scaled = validation_sigma * TARGET_SCALE
        value_loss = np.nanmean(
            np.where(
                val_mask,
                np.where(
                    np.abs(val_scaled - val_target * TARGET_SCALE) < 1.0,
                    0.5 * (val_scaled - val_target * TARGET_SCALE) ** 2,
                    np.abs(val_scaled - val_target * TARGET_SCALE) - 0.5,
                ),
                np.nan,
            )
        )
        abs_error = np.abs(val_scaled - val_target * TARGET_SCALE)
        counts = val_mask.sum(axis=-1)
        realized_sigma = np.divide(
            np.where(val_mask, abs_error, 0.0).sum(axis=-1),
            counts,
            out=np.zeros_like(counts, dtype=float),
            where=counts > 0,
        )
        sigma_valid = counts > 0
        uncertainty_loss = np.mean(
            np.where(
                np.abs(val_sigma_scaled.squeeze(-1)[sigma_valid] - realized_sigma[sigma_valid]) < 1,
                0.5 * (val_sigma_scaled.squeeze(-1)[sigma_valid] - realized_sigma[sigma_valid]) ** 2,
                np.abs(val_sigma_scaled.squeeze(-1)[sigma_valid] - realized_sigma[sigma_valid]) - 0.5,
            )
        )
        validation_loss = float(value_loss + 0.1 * uncertainty_loss)
        history.append(
            {
                "epoch": float(epoch + 1),
                "train_loss": train_loss / max(batches, 1),
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_loss - 1e-5:
            best_loss = validation_loss
            best_state = {name: value.detach().cpu().clone() for name, value in model.state_dict().items()}
            patience = 0
        else:
            patience += 1
            if patience >= 2:
                break
    if best_state is None:
        raise RuntimeError("training did not produce a finite checkpoint")
    model.load_state_dict(best_state)
    validation_values, validation_sigma = _predict(
        model, inputs, arrays, fold.validation_indices, device, batch_size
    )
    test_values, test_sigma = _predict(model, inputs, arrays, fold.test_indices, device, batch_size)
    validation_target = arrays.target_values.reshape(len(arrays.timestamps_ns), 4, 6)[fold.validation_indices]
    validation_mask = arrays.target_mask.reshape(len(arrays.timestamps_ns), 4, 6)[fold.validation_indices]
    calibrated = np.full_like(test_values, np.nan)
    calibrated_sigma = np.full_like(test_values, np.nan)
    calibration_records: list[dict[str, float | int | str]] = []
    for output_index, output_name in enumerate(OUTPUT_NAMES):
        valid = validation_mask[:, :, output_index] & np.isfinite(validation_values[:, :, output_index])
        x = validation_values[:, :, output_index][valid]
        y = validation_target[:, :, output_index][valid]
        if len(x) < 100:
            raise ValueError(f"insufficient validation rows for {output_name}")
        calibrator = IsotonicRegression(increasing=True, out_of_bounds="clip")
        calibrator.fit(x, y)
        validation_calibrated = calibrator.predict(validation_values[:, :, output_index].ravel()).reshape(
            validation_values.shape[:2]
        )
        calibrated[:, :, output_index] = calibrator.predict(
            test_values[:, :, output_index].ravel()
        ).reshape(test_values.shape[:2])
        residual = y - validation_calibrated[valid]
        residual_center = float(np.median(residual))
        residual_scale = max(float(1.4826 * np.median(np.abs(residual - residual_center))), 1e-5)
        calibrated_sigma[:, :, output_index] = np.maximum(
            test_sigma.squeeze(-1), residual_scale
        )
        calibration_records.append(
            {
                "output": output_name,
                "rows": int(len(x)),
                "residual_scale": residual_scale,
                "validation_positive_fraction": float(np.mean(y > 0)),
            }
        )
    audit = {
        "variant": variant,
        "seed": seed,
        "test_year": fold.test_year,
        "train_rows": int(len(fold.train_indices)),
        "validation_rows": int(len(fold.validation_indices)),
        "test_rows": int(len(fold.test_indices)),
        "epochs": len(history),
        "best_validation_loss": best_loss,
        "elapsed_seconds": perf_counter() - started,
        "history": history,
        "calibration": calibration_records,
    }
    del model, optimizer, inputs, targets, target_mask, current_mask
    torch.cuda.empty_cache()
    return calibrated, calibrated_sigma, audit


def _baseline_scores(arrays: TimingArrays) -> np.ndarray:
    returns = arrays.features[:, :, 0].astype(np.float64)
    valid = arrays.feature_mask[:, :, 0]
    output = np.full(returns.shape, np.nan, dtype=np.float64)
    for asset_index in range(len(ASSETS)):
        observed_indices = np.flatnonzero(valid[:, asset_index])
        observed_returns = pd.Series(returns[observed_indices, asset_index])
        momentum = observed_returns.rolling(18, min_periods=18).sum()
        volatility = observed_returns.rolling(72, min_periods=72).std(ddof=0)
        score = momentum / (volatility * math.sqrt(18.0)).replace(0.0, np.nan)
        output[observed_indices, asset_index] = score.to_numpy()
    return output


def _year_vector(arrays: TimingArrays) -> np.ndarray:
    return pd.to_datetime(arrays.timestamps_ns, utc=True).year.to_numpy()


def simulate_policy(
    arrays: TimingArrays,
    *,
    years: Sequence[int],
    values: np.ndarray | None,
    uncertainty: np.ndarray | None,
    baseline_scores: np.ndarray | None,
    entry_gate: np.ndarray | None = None,
    minimum_snr: float | None = 0.75,
) -> pd.DataFrame:
    year_values = _year_vector(arrays)
    selected = np.isin(year_values, np.asarray(years))
    indices = np.flatnonzero(selected)
    positions: list[OpenPosition | None] = [None] * len(ASSETS)
    trades: list[dict[str, object]] = []
    equity = 10_000_000.0
    for index in indices:
        year = int(year_values[index])
        for asset_index, asset in enumerate(ASSETS):
            position = positions[asset_index]
            if position is not None:
                should_exit = index - position.entry_index >= 17
                exit_reason = "maximum_holding_bars" if should_exit else ""
                if baseline_scores is not None:
                    score = baseline_scores[index, asset_index]
                    if np.isfinite(score) and score * position.side <= 0.0:
                        should_exit = True
                        exit_reason = "baseline_zero_cross"
                elif values is not None:
                    row = values[index, asset_index]
                    if np.isfinite(row).all():
                        same = float(np.max(row[0::2] if position.side == 1 else row[1::2]))
                        opposite = float(np.max(row[1::2] if position.side == 1 else row[0::2]))
                        if same <= 0.0:
                            should_exit = True
                            exit_reason = "same_side_nonpositive"
                        elif opposite > same:
                            should_exit = True
                            exit_reason = "opposite_value_dominates"
                if should_exit and arrays.execution_mask[index, asset_index]:
                    exit_price = float(
                        arrays.execution_ohlcv[index, asset_index, 2 if position.side == 1 else 1]
                    )
                    exit_fee = float(arrays.fee_per_side[index, asset_index])
                    if not np.isfinite(exit_fee):
                        exit_fee = position.fee_per_side
                    gross_pnl = (
                        position.quantity
                        * position.point_value
                        * position.side
                        * (exit_price - position.entry_price)
                    )
                    fees = position.quantity * (position.fee_per_side + exit_fee)
                    pnl = gross_pnl - fees
                    equity += pnl
                    trades.append(
                        {
                            "asset": asset,
                            "side": "long" if position.side == 1 else "short",
                            "entry_index": position.entry_index,
                            "exit_index": index,
                            "entry_time": pd.Timestamp(position.entry_time_ns, tz="UTC"),
                            "exit_time": pd.Timestamp(int(arrays.timestamps_ns[index] + 600_000_000_000), tz="UTC"),
                            "quantity": position.quantity,
                            "entry_price": position.entry_price,
                            "exit_price": exit_price,
                            "point_value": position.point_value,
                            "entry_notional": position.quantity * position.notional_per_contract,
                            "gross_pnl": gross_pnl,
                            "fees_1x": fees,
                            "pnl_1x": pnl,
                            "pnl_2x": gross_pnl - 2.0 * fees,
                            "holding_bars": index - position.entry_index + 1,
                            "exit_reason": exit_reason,
                            "participation": position.participation,
                            "forecast_horizon": position.forecast_horizon,
                            "forecast_edge": position.forecast_edge,
                            "forecast_snr": position.forecast_snr,
                        }
                    )
                    positions[asset_index] = None
                    position = None
            if position is not None:
                continue
            if not (
                arrays.execution_mask[index, asset_index]
                and arrays.sizing_mask[index, asset_index]
                and index + 18 < len(arrays.timestamps_ns)
                and year_values[index + 18] == year
                and arrays.target_mask[index, asset_index, 2, 0]
            ):
                continue
            side = 0
            horizon = 0
            edge = 0.0
            snr = 0.0
            if baseline_scores is not None:
                score = baseline_scores[index, asset_index]
                if not np.isfinite(score) or abs(score) < 1.0:
                    continue
                side = 1 if score > 0 else -1
                horizon = 18
                edge = float(abs(score))
                snr = float(abs(score))
            elif values is not None and uncertainty is not None:
                row = values[index, asset_index]
                sigma = uncertainty[index, asset_index]
                if not np.isfinite(row).all() or not np.isfinite(sigma).all():
                    continue
                if entry_gate is None:
                    allowed = np.ones(len(row), dtype=bool)
                else:
                    allowed = entry_gate[index, asset_index]
                if not allowed.any():
                    continue
                best = int(np.argmax(np.where(allowed, row, -np.inf)))
                edge = float(row[best])
                snr = edge / max(float(sigma[best]), 1e-12)
                if edge <= 0.0 or (minimum_snr is not None and snr < minimum_snr):
                    continue
                horizon = HORIZONS[best // 2]
                side = 1 if best % 2 == 0 else -1
            else:
                raise ValueError("one policy input must be provided")
            notional = float(arrays.notional[index, asset_index])
            point_value = float(arrays.point_value[index, asset_index])
            fee = float(arrays.fee_per_side[index, asset_index])
            volume = float(arrays.execution_ohlcv[index, asset_index, 4])
            requested = int(math.floor(0.25 * max(equity, 0.0) / notional))
            capacity = int(math.floor(0.01 * max(volume, 0.0)))
            quantity = min(requested, capacity)
            if quantity < 1:
                continue
            entry_price = float(
                arrays.execution_ohlcv[index, asset_index, 1 if side == 1 else 2]
            )
            positions[asset_index] = OpenPosition(
                asset_index=asset_index,
                side=side,
                quantity=quantity,
                entry_index=index,
                entry_time_ns=int(arrays.timestamps_ns[index] + 600_000_000_000),
                entry_price=entry_price,
                point_value=point_value,
                notional_per_contract=notional,
                fee_per_side=fee,
                participation=quantity / max(volume, 1.0),
                forecast_horizon=horizon,
                forecast_edge=edge,
                forecast_snr=snr,
            )
    return pd.DataFrame(trades)


def _calendar_dates(arrays: TimingArrays, years: Sequence[int]) -> pd.DatetimeIndex:
    timestamps = pd.to_datetime(arrays.timestamps_ns[arrays.asset_mask.any(axis=1)], utc=True)
    local = timestamps.tz_convert(MOSCOW).tz_localize(None).normalize()
    selected = local[np.isin(local.year, np.asarray(years))]
    return pd.DatetimeIndex(sorted(selected.unique()))


def calculate_metrics(
    arrays: TimingArrays,
    trades: pd.DataFrame,
    years: Sequence[int],
    *,
    cost_column: Literal["pnl_1x", "pnl_2x"],
) -> dict[str, Any]:
    initial = 10_000_000.0
    calendar = _calendar_dates(arrays, years)
    pnl = pd.Series(0.0, index=calendar)
    if not trades.empty:
        exit_dates = pd.to_datetime(trades["exit_time"], utc=True).dt.tz_convert(MOSCOW).dt.tz_localize(None).dt.normalize()
        grouped = trades.assign(exit_date=exit_dates).groupby("exit_date")[cost_column].sum()
        pnl.loc[pnl.index.intersection(grouped.index)] = grouped.loc[pnl.index.intersection(grouped.index)]
    equity = initial + pnl.cumsum()
    previous = equity.shift(1).fillna(initial)
    returns = pnl / previous
    elapsed_days = max((calendar[-1] - calendar[0]).days + 1, 1) if len(calendar) else 1
    final = float(equity.iloc[-1]) if len(equity) else initial
    cagr = (max(final, 1e-12) / initial) ** (365.25 / elapsed_days) - 1.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * math.sqrt(252.0))
        if len(returns) > 1 and returns.std(ddof=0) > 0
        else 0.0
    )
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series([0.0])
    per_year: dict[str, dict[str, float | int]] = {}
    for year in years:
        yearly = pnl[pnl.index.year == year]
        start_equity = float(initial + pnl[pnl.index.year < year].sum())
        yearly_return = float(yearly.sum() / start_equity) if start_equity > 0 else -1.0
        yearly_trades = 0
        if not trades.empty:
            yearly_trades = int((pd.to_datetime(trades["exit_time"], utc=True).dt.year == year).sum())
        per_year[str(year)] = {
            "return": yearly_return,
            "pnl_rub": float(yearly.sum()),
            "trades": yearly_trades,
        }
    long_count = int((trades["side"] == "long").sum()) if not trades.empty else 0
    short_count = int((trades["side"] == "short").sum()) if not trades.empty else 0
    years_elapsed = max(elapsed_days / 365.25, 1e-9)
    turnover = (
        float(2.0 * trades["entry_notional"].sum() / initial / years_elapsed)
        if not trades.empty
        else 0.0
    )
    return {
        "decisions": int(
            arrays.asset_mask[np.isin(_year_vector(arrays), np.asarray(years))].sum()
        ),
        "trades": int(len(trades)),
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "worst_year": min((item["return"] for item in per_year.values()), default=0.0),
        "final_equity_rub": final,
        "turnover_annualized": turnover,
        "costs_rub": (
            float(trades["fees_1x"].sum() * (1.0 if cost_column == "pnl_1x" else 2.0))
            if not trades.empty
            else 0.0
        ),
        "long_trades": long_count,
        "short_trades": short_count,
        "long_fraction": long_count / max(long_count + short_count, 1),
        "maximum_participation": float(trades["participation"].max()) if not trades.empty else 0.0,
        "per_year": per_year,
    }


def _assemble_dense_predictions(
    length: int,
    folds: Sequence[FoldDefinition],
    fold_predictions: Sequence[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    values = np.full((length, 4, 6), np.nan, dtype=np.float32)
    uncertainty = np.full_like(values, np.nan)
    for fold, (fold_values, fold_uncertainty) in zip(folds, fold_predictions, strict=True):
        values[fold.test_indices] = fold_values
        uncertainty[fold.test_indices] = fold_uncertainty
    return values, uncertainty


def run_experiment(
    *,
    tensor_path: Path = DEFAULT_TENSOR,
    output_dir: Path,
    years: Sequence[int] = (2021, 2022, 2023, 2024, 2025),
    seeds: Sequence[int] = (1729, 2718, 3141),
    variants: Sequence[Literal["attention", "independent"]] = ("attention", "independent"),
    maximum_epochs: int = 8,
) -> dict[str, Any]:
    if sha256_file(PROTOCOL_PATH) != PROTOCOL_SHA256:
        raise ValueError("sealed timing protocol byte drift")
    if max(years) >= 2026:
        raise ValueError("protected holdout access requested")
    arrays = load_timing_arrays(tensor_path)
    if arrays.timestamps_ns[-1] >= pd.Timestamp("2026-01-01", tz="UTC").value:
        raise ValueError("tensor touches protected 2026 holdout")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda" or "5090" not in torch.cuda.get_device_name(0):
        raise RuntimeError("full timing experiment requires the isolated RTX 5090")
    output_dir.mkdir(parents=True, exist_ok=False)
    folds = build_folds(arrays, years)
    all_metrics: dict[str, Any] = {}
    training_audit: list[dict[str, Any]] = []
    prediction_rows: list[pd.DataFrame] = []
    trade_rows: list[pd.DataFrame] = []
    for variant in variants:
        fold_ensembles: list[tuple[np.ndarray, np.ndarray]] = []
        for fold in folds:
            seed_values: list[np.ndarray] = []
            seed_uncertainty: list[np.ndarray] = []
            for seed in seeds:
                calibrated, uncertainty, audit = train_one_model(
                    arrays,
                    fold,
                    variant=variant,
                    seed=seed,
                    maximum_epochs=maximum_epochs,
                    device=device,
                )
                seed_values.append(calibrated)
                seed_uncertainty.append(uncertainty)
                training_audit.append(audit)
                print(json.dumps({"milestone": "model_complete", **audit}, default=float), flush=True)
            seed_stack = np.stack(seed_values)
            mean = seed_stack.mean(axis=0)
            sigma_stack = np.stack(seed_uncertainty)
            total_sigma = np.sqrt(np.mean(sigma_stack**2 + (seed_stack - mean[None]) ** 2, axis=0))
            fold_ensembles.append((mean.astype(np.float32), total_sigma.astype(np.float32)))
        dense_values, dense_uncertainty = _assemble_dense_predictions(
            len(arrays.timestamps_ns), folds, fold_ensembles
        )
        trades = simulate_policy(
            arrays,
            years=years,
            values=dense_values,
            uncertainty=dense_uncertainty,
            baseline_scores=None,
        )
        metrics_1x = calculate_metrics(arrays, trades, years, cost_column="pnl_1x")
        metrics_2x = calculate_metrics(arrays, trades, years, cost_column="pnl_2x")
        all_metrics[variant] = {"cost_1x": metrics_1x, "cost_2x": metrics_2x}
        test_indices = np.concatenate([fold.test_indices for fold in folds])
        frame = pd.DataFrame(
            {
                "timestamp": np.repeat(pd.to_datetime(arrays.timestamps_ns[test_indices], utc=True), 4),
                "asset": np.tile(np.asarray(ASSETS), len(test_indices)),
                "variant": variant,
            }
        )
        flat_values = dense_values[test_indices].reshape(-1, 6)
        flat_sigma = dense_uncertainty[test_indices].reshape(-1, 6)
        for output_index, name in enumerate(OUTPUT_NAMES):
            frame[name] = flat_values[:, output_index]
            frame[f"{name}_uncertainty"] = flat_sigma[:, output_index]
        prediction_rows.append(frame)
        if not trades.empty:
            trades = trades.assign(strategy=variant)
            trade_rows.append(trades)
    baseline = _baseline_scores(arrays)
    baseline_trades = simulate_policy(
        arrays,
        years=years,
        values=None,
        uncertainty=None,
        baseline_scores=baseline,
    )
    all_metrics["breakout_momentum_baseline"] = {
        "cost_1x": calculate_metrics(arrays, baseline_trades, years, cost_column="pnl_1x"),
        "cost_2x": calculate_metrics(arrays, baseline_trades, years, cost_column="pnl_2x"),
    }
    if not baseline_trades.empty:
        trade_rows.append(baseline_trades.assign(strategy="breakout_momentum_baseline"))
    predictions = pd.concat(prediction_rows, ignore_index=True) if prediction_rows else pd.DataFrame()
    trades = pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame()
    predictions.to_parquet(output_dir / "predictions.parquet", index=False)
    trades.to_parquet(output_dir / "trades.parquet", index=False)
    (output_dir / "training_audit.json").write_text(
        json.dumps(training_audit, ensure_ascii=False, indent=2, default=float) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": PROTOCOL_SHA256,
        "tensor_sha256": sha256_file(tensor_path),
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "years": list(years),
        "seeds": list(seeds),
        "variants": list(variants),
        "maximum_epochs": maximum_epochs,
        "metrics": all_metrics,
        "artifacts": {},
    }
    for name in ("predictions.parquet", "trades.parquet", "training_audit.json"):
        path = output_dir / name
        result["artifacts"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(
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
    result = run_experiment(
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
