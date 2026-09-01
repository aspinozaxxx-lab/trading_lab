"""Causal cross-market intraday research using MOEX curve coefficients.

The module contains outcome-agnostic transformations, a purged monthly walk-forward
model, a causal risk mapper and an explicit next-open research ledger.  File-system
identity checks and canonical run publication live in the V32 runner.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
TEN_MINUTES: Final[pd.Timedelta] = pd.Timedelta(minutes=10)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01", tz="UTC")
MODEL_FULL_MLP: Final[str] = "curve_market_mlp"
MODEL_MARKET_MLP: Final[str] = "market_only_mlp"
MODEL_FULL_RIDGE: Final[str] = "curve_market_ridge"
MODEL_IDS: Final[tuple[str, ...]] = (
    MODEL_FULL_MLP,
    MODEL_MARKET_MLP,
    MODEL_FULL_RIDGE,
)
LEDGER_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "local_date",
    "bar_pnl",
    "bar_cost",
    "equity",
    "gross_notional",
    "gross_multiple",
    "buffered_margin",
    "buffered_margin_multiple",
    *(f"position_{asset.lower()}" for asset in ASSETS),
)
ORDER_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "asset",
    "contract_id",
    "requested_quantity_delta",
    "filled_quantity_delta",
    "participation",
    "commission_cost",
    "slippage_cost",
    "total_cost",
    "capacity_clipped",
    "filled",
    "reason",
)
UNRESOLVED_COLUMNS: Final[tuple[str, ...]] = ("timestamp", "asset", "reason")


def source_feature_columns() -> tuple[str, ...]:
    """Return the frozen maturity-agnostic coefficient feature set."""

    columns: list[str] = []
    for source_asset in ("ri", "mix", "si", "br"):
        columns.extend(
            (
                f"context_{source_asset}_series_count",
                f"context_{source_asset}_series_count_delta",
            )
        )
        for coefficient in ("s", "a", "b", "c", "d", "e"):
            columns.extend(
                (
                    f"context_{source_asset}_{coefficient}_median",
                    f"context_{source_asset}_{coefficient}_iqr",
                    f"context_{source_asset}_{coefficient}_median_delta",
                )
            )
    for coefficient in ("s", "a", "b", "c", "d", "e"):
        columns.extend(
            (
                f"cross_asset_{coefficient}_median",
                f"cross_asset_{coefficient}_dispersion",
            )
        )
    return tuple(columns)


def market_feature_columns() -> tuple[str, ...]:
    """Return the frozen four-market feature set visible at a completed bucket."""

    columns: list[str] = []
    for asset in ASSETS:
        lower = asset.lower()
        columns.extend(f"market_{lower}_return_{lookback}" for lookback in (1, 3, 6, 18))
        columns.extend(
            (
                f"market_{lower}_realized_vol_6",
                f"market_{lower}_realized_vol_18",
                f"market_{lower}_range",
                f"market_{lower}_body",
                f"market_{lower}_volume_log_deviation_18",
            )
        )
    for lookback in (1, 3, 6, 18):
        columns.extend(
            (
                f"market_cross_return_{lookback}_mean",
                f"market_cross_return_{lookback}_dispersion",
            )
        )
    columns.extend(("market_time_sin", "market_time_cos", "source_age_minutes"))
    return tuple(columns)


def risk_covariance_columns() -> tuple[str, ...]:
    """Stable flattened order of the causal four-by-four covariance matrix."""

    return tuple(f"risk_cov_{left.lower()}_{right.lower()}" for left in ASSETS for right in ASSETS)


@dataclass(frozen=True, slots=True)
class FeatureSettings:
    """Frozen label/window and gap-tolerant feature settings."""

    return_lookbacks: tuple[int, ...] = (1, 3, 6, 18)
    realized_volatility_lookbacks: tuple[int, ...] = (6, 18)
    volume_lookback: int = 18
    label_horizon_bars: int = 6
    first_decision_local: str = "10:10:00"
    last_decision_local: str = "17:30:00"
    forced_flat_local: str = "18:30:00"
    covariance_observations: int = 132
    covariance_minimum_observations: int = 66
    covariance_diagonal_shrinkage: float = 0.50
    annualization_bars: int = 11_088

    def __post_init__(self) -> None:
        if self.return_lookbacks != (1, 3, 6, 18):
            raise ValueError("V32 return lookbacks are frozen")
        if self.realized_volatility_lookbacks != (6, 18):
            raise ValueError("V32 volatility lookbacks are frozen")
        if self.label_horizon_bars != 6:
            raise ValueError("V32 label horizon must equal six ten-minute bars")
        if not 0.0 <= self.covariance_diagonal_shrinkage <= 1.0:
            raise ValueError("covariance shrinkage must be in [0, 1]")
        if self.covariance_minimum_observations > self.covariance_observations:
            raise ValueError("minimum covariance history exceeds its window")


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Frozen nested walk-forward model and calibration settings."""

    evaluation_start: str = "2022-04-01"
    evaluation_end: str = "2024-05-31"
    calibration_months: int = 3
    purge_calendar_days: int = 1
    minimum_core_source_events: int = 80
    minimum_calibration_source_events: int = 40
    minimum_calibration_actions: int = 200
    minimum_positive_calibration_months: int = 2
    threshold_cost_multiples: tuple[float, ...] = (1.5, 2.5, 4.0)
    hidden_layers: tuple[int, ...] = (32, 16)
    activation: str = "tanh"
    alpha: float = 0.001
    learning_rate_init: float = 0.001
    maximum_iterations: int = 120
    batch_size: int = 256
    seeds: tuple[int, ...] = (1729, 2718, 3141)
    ridge_alpha: float = 10.0

    def __post_init__(self) -> None:
        if self.calibration_months != 3 or self.purge_calendar_days != 1:
            raise ValueError("V32 split timing is frozen")
        if self.threshold_cost_multiples != (1.5, 2.5, 4.0):
            raise ValueError("V32 threshold candidates are frozen")
        if self.hidden_layers != (32, 16) or self.seeds != (1729, 2718, 3141):
            raise ValueError("V32 MLP architecture or ensemble seeds drifted")
        if self.activation != "tanh" or self.maximum_iterations != 120:
            raise ValueError("V32 MLP training contract drifted")


@dataclass(frozen=True, slots=True)
class RiskSettings:
    """Aggressive but bounded portfolio mapping settings."""

    annual_target_volatility: float = 0.30
    maximum_gross: float = 1.60
    maximum_asset_weight: float = 0.60
    score_clip: float = 2.0

    def __post_init__(self) -> None:
        if not 0.0 < self.annual_target_volatility <= 0.30:
            raise ValueError("V32 target volatility must be in (0, 0.30]")
        if not 0.0 < self.maximum_gross <= 1.60:
            raise ValueError("V32 gross cap must be in (0, 1.60]")
        if not 0.0 < self.maximum_asset_weight <= 0.60:
            raise ValueError("V32 asset cap must be in (0, 0.60]")


@dataclass(frozen=True, slots=True)
class LedgerSettings:
    """Next-open integer execution and research-cost assumptions."""

    initial_cash: float = 1_000_000.0
    slippage_ticks: int = 1
    fee_multiplier: float = 1.0
    signal_participation: float = 0.0025
    factual_participation_cap: float = 0.01
    maximum_gross: float = 1.60
    margin_buffer_multiple: float = 2.0

    def __post_init__(self) -> None:
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("slippage_ticks must be 1, 2 or 4")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("fee_multiplier must be 1.0 or 2.0")
        if not 0.0 < self.signal_participation <= 0.0025:
            raise ValueError("signal participation exceeds the frozen bound")
        if not 0.0 < self.factual_participation_cap <= 0.01:
            raise ValueError("factual participation exceeds one percent")
        if self.maximum_gross > 1.60 or self.margin_buffer_multiple < 2.0:
            raise ValueError("V32 gross or margin guard was weakened")


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    predictions: pd.DataFrame
    folds: pd.DataFrame


@dataclass(frozen=True, slots=True)
class SimulationResult:
    ledger: pd.DataFrame
    orders: pd.DataFrame
    unresolved: pd.DataFrame
    metrics: dict[str, object]
    execution_complete: bool


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _as_utc(values: pd.Series, label: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="raise", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{label} contains missing timestamps")
    return parsed


def _rolling_valid(series: pd.Series, window: int, operation: str) -> pd.Series:
    """Roll over the last observed exact intraday returns without filling gaps."""

    valid = pd.to_numeric(series, errors="coerce").dropna()
    output = pd.Series(np.nan, index=series.index, dtype=float)
    if operation == "sum":
        rolled = valid.rolling(window, min_periods=window).sum()
    elif operation == "std":
        rolled = valid.rolling(window, min_periods=window).std(ddof=1)
    elif operation == "median":
        rolled = valid.rolling(window, min_periods=window).median()
    else:
        raise ValueError(f"unknown rolling operation: {operation}")
    output.loc[valid.index] = rolled
    return output


def _valid_one_bar_returns(panel: pd.DataFrame) -> pd.DataFrame:
    timestamps = _as_utc(panel["timestamp"], "panel.timestamp")
    exact = timestamps.diff().eq(TEN_MINUTES)
    returns = pd.DataFrame(index=panel.index, columns=ASSETS, dtype=float)
    for asset in ASSETS:
        contract = panel[f"{asset}_contract_id"].astype("string")
        same_contract = contract.eq(contract.shift(1)) & contract.notna()
        close = pd.to_numeric(panel[f"{asset}_close"], errors="coerce")
        prior = close.shift(1)
        valid = exact & same_contract & close.gt(0.0) & prior.gt(0.0)
        returns.loc[valid, asset] = np.log(close.loc[valid] / prior.loc[valid])
    return returns


def _add_market_features(
    panel: pd.DataFrame, settings: FeatureSettings
) -> tuple[pd.DataFrame, pd.DataFrame]:
    output = panel.copy()
    one_bar = _valid_one_bar_returns(output)
    for asset in ASSETS:
        lower = asset.lower()
        for lookback in settings.return_lookbacks:
            output[f"market_{lower}_return_{lookback}"] = _rolling_valid(
                one_bar[asset], lookback, "sum"
            )
        for lookback in settings.realized_volatility_lookbacks:
            output[f"market_{lower}_realized_vol_{lookback}"] = _rolling_valid(
                one_bar[asset], lookback, "std"
            )
        opened = pd.to_numeric(output[f"{asset}_open"], errors="coerce")
        high = pd.to_numeric(output[f"{asset}_high"], errors="coerce")
        low = pd.to_numeric(output[f"{asset}_low"], errors="coerce")
        close = pd.to_numeric(output[f"{asset}_close"], errors="coerce")
        volume = pd.to_numeric(output[f"{asset}_volume"], errors="coerce")
        output[f"market_{lower}_range"] = (high - low) / close.where(close.gt(0.0))
        output[f"market_{lower}_body"] = (close - opened) / opened.where(opened.gt(0.0))
        log_volume = np.log1p(volume.where(volume.ge(0.0)))
        output[f"market_{lower}_volume_log_deviation_18"] = log_volume - _rolling_valid(
            log_volume, settings.volume_lookback, "median"
        )
    for lookback in settings.return_lookbacks:
        columns = [f"market_{asset.lower()}_return_{lookback}" for asset in ASSETS]
        output[f"market_cross_return_{lookback}_mean"] = output[columns].mean(axis=1, skipna=False)
        output[f"market_cross_return_{lookback}_dispersion"] = output[columns].std(
            axis=1, ddof=0, skipna=False
        )
    return output, one_bar


def _label_structure(panel: pd.DataFrame, settings: FeatureSettings) -> pd.DataFrame:
    timestamps = _as_utc(panel["timestamp"], "panel.timestamp")
    horizon = settings.label_horizon_bars
    exact = pd.Series(True, index=panel.index, dtype=bool)
    for offset in range(1, horizon + 2):
        exact &= timestamps.shift(-offset).eq(timestamps + offset * TEN_MINUTES)
    same_contract = pd.Series(True, index=panel.index, dtype=bool)
    for asset in ASSETS:
        contract = panel[f"{asset}_contract_id"].astype("string")
        for offset in range(1, horizon + 2):
            same_contract &= contract.shift(-offset).eq(contract)
    structure = pd.DataFrame(index=panel.index)
    structure["decision_at"] = timestamps + TEN_MINUTES
    structure["entry_at"] = timestamps.shift(-1)
    structure["target_end_at"] = timestamps.shift(-(horizon + 1))
    structure["exact_label_path"] = exact & same_contract
    for asset in ASSETS:
        entry = pd.to_numeric(panel[f"{asset}_open"].shift(-1), errors="coerce")
        exit_price = pd.to_numeric(panel[f"{asset}_open"].shift(-(horizon + 1)), errors="coerce")
        valid = structure["exact_label_path"] & entry.gt(0.0) & exit_price.gt(0.0)
        structure[f"target_{asset.lower()}_return"] = np.where(
            valid, np.log(exit_price / entry), np.nan
        )
    return structure


def _attach_risk_covariance(
    learning: pd.DataFrame,
    one_bar: pd.DataFrame,
    settings: FeatureSettings,
) -> pd.DataFrame:
    valid = one_bar.notna().all(axis=1)
    valid_indices = np.flatnonzero(valid.to_numpy(dtype=bool))
    valid_values = one_bar.loc[valid, list(ASSETS)].to_numpy(dtype=float)
    output = learning.copy()
    covariance_columns = risk_covariance_columns()
    output.loc[:, list(covariance_columns)] = np.nan
    shrink = settings.covariance_diagonal_shrinkage
    for row_index in output.index:
        location = int(np.searchsorted(valid_indices, int(row_index), side="right"))
        start = max(0, location - settings.covariance_observations)
        history = valid_values[start:location]
        if len(history) < settings.covariance_minimum_observations:
            continue
        covariance = np.cov(history, rowvar=False, ddof=1) * settings.annualization_bars
        diagonal = np.diag(np.diag(covariance))
        covariance = (1.0 - shrink) * covariance + shrink * diagonal
        if not np.isfinite(covariance).all() or (np.diag(covariance) <= 0.0).any():
            continue
        output.loc[row_index, covariance_columns] = covariance.reshape(-1)
    return output


def build_learning_frame(
    common_panel: pd.DataFrame,
    curve_context: pd.DataFrame,
    settings: FeatureSettings | None = None,
) -> pd.DataFrame:
    """Build exact event-day decisions and six-bar labels from verified inputs."""

    settings = settings or FeatureSettings()
    required_panel = {"timestamp", "local_date"}
    for asset in ASSETS:
        required_panel.update(
            {
                f"{asset}_contract_id",
                f"{asset}_open",
                f"{asset}_high",
                f"{asset}_low",
                f"{asset}_close",
                f"{asset}_volume",
                f"{asset}_source_end_timestamp",
                f"{asset}_sizing_notional",
                f"{asset}_sizing_tick_cash_value",
                f"{asset}_conservative_fee_per_side",
                f"{asset}_sizing_point_value",
                f"{asset}_modeled_initial_margin",
                f"{asset}_sizing_usable",
            }
        )
    _require_columns(common_panel, required_panel, "common_panel")
    _require_columns(
        curve_context,
        {"event_at", "available_at", *source_feature_columns()},
        "curve_context",
    )
    panel = common_panel.sort_values("timestamp", kind="stable").reset_index(drop=True)
    panel["timestamp"] = _as_utc(panel["timestamp"], "common_panel.timestamp")
    if panel["timestamp"].duplicated().any():
        raise ValueError("common panel duplicates timestamps")
    if len(panel) and panel["timestamp"].max() >= PROTECTED_FROM:
        raise ValueError("common panel touches protected 2026")
    panel, one_bar = _add_market_features(panel, settings)
    structure = _label_structure(panel, settings)
    panel = pd.concat((panel, structure), axis=1)
    decision_local = panel["decision_at"].dt.tz_convert("Europe/Moscow")
    panel["decision_local_date"] = decision_local.dt.tz_localize(None).dt.normalize()
    panel["decision_local_time"] = decision_local.dt.time

    context = curve_context.copy()
    context["event_at"] = _as_utc(context["event_at"], "curve_context.event_at")
    context["available_at"] = _as_utc(context["available_at"], "curve_context.available_at")
    if context["event_at"].duplicated().any():
        raise ValueError("curve context duplicates events")
    context["decision_local_date"] = (
        context["available_at"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    if context["decision_local_date"].duplicated().any():
        raise ValueError("curve context has more than one event per Moscow date")
    context = context.rename(
        columns={"event_at": "source_event_at", "available_at": "source_available_at"}
    )
    merged = panel.merge(context, on="decision_local_date", how="left", validate="many_to_one")
    merged.index = panel.index
    merged["source_age_minutes"] = (
        merged["decision_at"] - merged["source_available_at"]
    ).dt.total_seconds() / 60.0
    minute = decision_local.dt.hour * 60 + decision_local.dt.minute
    phase = 2.0 * math.pi * minute / (24.0 * 60.0)
    merged["market_time_sin"] = np.sin(phase)
    merged["market_time_cos"] = np.cos(phase)

    sizing_valid = pd.Series(True, index=merged.index, dtype=bool)
    for asset in ASSETS:
        source_end = _as_utc(
            merged[f"{asset}_source_end_timestamp"],
            f"common_panel.{asset}_source_end_timestamp",
        )
        if source_end.gt(merged["decision_at"]).any():
            raise ValueError(f"{asset} bar was not complete by the decision timestamp")
        usable = merged[f"{asset}_sizing_usable"].astype("boolean").fillna(False)
        sizing_valid &= usable
        for field in (
            "sizing_notional",
            "sizing_tick_cash_value",
            "sizing_point_value",
            "modeled_initial_margin",
        ):
            value = pd.to_numeric(merged[f"{asset}_{field}"], errors="coerce")
            sizing_valid &= np.isfinite(value) & value.gt(0.0)
        fee = pd.to_numeric(merged[f"{asset}_conservative_fee_per_side"], errors="coerce")
        sizing_valid &= np.isfinite(fee) & fee.ge(0.0)

    first_time = pd.Timestamp(settings.first_decision_local).time()
    last_time = pd.Timestamp(settings.last_decision_local).time()
    target_columns = [f"target_{asset.lower()}_return" for asset in ASSETS]
    eligible = (
        merged["exact_label_path"]
        & merged["source_available_at"].notna()
        & merged["source_available_at"].le(merged["decision_at"])
        & merged["decision_local_time"].ge(first_time)
        & merged["decision_local_time"].le(last_time)
        & merged[target_columns].notna().all(axis=1)
        & sizing_valid
    )
    learning = merged.loc[eligible].copy()
    if learning.empty:
        raise ValueError("no V32 structurally eligible learning rows")
    learning = _attach_risk_covariance(learning, one_bar, settings)
    learning["source_event_date"] = (
        learning["source_event_at"].dt.tz_convert("Europe/Moscow").dt.date.astype(str)
    )
    learning["stress_roundtrip_cost_multiple"] = 1.0
    for asset in ASSETS:
        notional = pd.to_numeric(learning[f"{asset}_sizing_notional"], errors="coerce")
        tick_cash = pd.to_numeric(learning[f"{asset}_sizing_tick_cash_value"], errors="coerce")
        fee = pd.to_numeric(learning[f"{asset}_conservative_fee_per_side"], errors="coerce")
        usable = learning[f"{asset}_sizing_usable"].astype("boolean").fillna(False)
        cost = 2.0 * (4.0 * tick_cash + 2.0 * fee) / notional.where(notional.gt(0.0))
        learning[f"stress_roundtrip_cost_{asset.lower()}"] = cost.where(usable)
    return learning.reset_index(drop=True)


def _month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(
        pd.date_range(start.normalize().replace(day=1), end.normalize().replace(day=1), freq="MS")
    )


def _model_arrays(
    core: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: tuple[str, ...],
    model_id: str,
    settings: ModelSettings,
) -> tuple[np.ndarray, np.ndarray]:
    x_core = core.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    x_calibration = (
        calibration.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    )
    x_test = test.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    target_columns = [f"target_{asset.lower()}_return" for asset in ASSETS]
    y_core = core.loc[:, target_columns].to_numpy(dtype=float)
    imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
    scaler = StandardScaler()
    transformed_core = scaler.fit_transform(imputer.fit_transform(x_core))
    transformed_calibration = scaler.transform(imputer.transform(x_calibration))
    transformed_test = scaler.transform(imputer.transform(x_test))
    target_mean = y_core.mean(axis=0)
    target_scale = y_core.std(axis=0, ddof=1)
    target_scale = np.where(np.isfinite(target_scale) & (target_scale > 1e-12), target_scale, 1.0)
    standardized_y = (y_core - target_mean) / target_scale
    calibration_predictions: list[np.ndarray] = []
    test_predictions: list[np.ndarray] = []
    if model_id == MODEL_FULL_RIDGE:
        model = Ridge(alpha=settings.ridge_alpha, fit_intercept=True)
        model.fit(transformed_core, standardized_y)
        calibration_predictions.append(model.predict(transformed_calibration))
        test_predictions.append(model.predict(transformed_test))
    else:
        for seed in settings.seeds:
            model = MLPRegressor(
                hidden_layer_sizes=settings.hidden_layers,
                activation=settings.activation,
                solver="adam",
                alpha=settings.alpha,
                batch_size=settings.batch_size,
                learning_rate_init=settings.learning_rate_init,
                max_iter=settings.maximum_iterations,
                shuffle=True,
                random_state=seed,
                tol=1e-5,
                n_iter_no_change=settings.maximum_iterations + 1,
                early_stopping=False,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=ConvergenceWarning)
                model.fit(transformed_core, standardized_y)
            calibration_predictions.append(model.predict(transformed_calibration))
            test_predictions.append(model.predict(transformed_test))
    calibration_prediction = np.mean(calibration_predictions, axis=0) * target_scale + target_mean
    test_prediction = np.mean(test_predictions, axis=0) * target_scale + target_mean
    return calibration_prediction, test_prediction


def select_threshold_multiple(
    calibration: pd.DataFrame,
    predictions: np.ndarray,
    settings: ModelSettings,
) -> tuple[float | None, list[dict[str, object]]]:
    """Select one cost hurdle only inside the preceding calibration months."""

    if predictions.shape != (len(calibration), len(ASSETS)):
        raise ValueError("calibration prediction shape mismatch")
    target = calibration[[f"target_{asset.lower()}_return" for asset in ASSETS]].to_numpy(
        dtype=float
    )
    costs = calibration[[f"stress_roundtrip_cost_{asset.lower()}" for asset in ASSETS]].to_numpy(
        dtype=float
    )
    dates = pd.to_datetime(calibration["decision_at"], utc=True).dt.tz_convert("Europe/Moscow")
    candidates: list[dict[str, object]] = []
    for multiple in settings.threshold_cost_multiples:
        valid = np.isfinite(predictions) & np.isfinite(target) & np.isfinite(costs) & (costs > 0.0)
        active = valid & (np.abs(predictions) >= multiple * costs)
        action_count = int(active.sum())
        signed = np.where(active, np.sign(predictions) * target - costs, 0.0)
        active_per_row = active.sum(axis=1)
        row_proxy = np.divide(
            signed.sum(axis=1),
            active_per_row,
            out=np.zeros(len(calibration), dtype=float),
            where=active_per_row > 0,
        )
        daily = pd.Series(row_proxy).groupby(dates.dt.date.to_numpy()).mean()
        month_keys = dates.dt.tz_localize(None).dt.to_period("M").astype(str).to_numpy()
        monthly = pd.Series(row_proxy).groupby(month_keys).mean()
        standard_deviation = float(daily.std(ddof=1)) if len(daily) > 1 else float("nan")
        score = (
            float(daily.mean() / standard_deviation * math.sqrt(252.0))
            if np.isfinite(standard_deviation) and standard_deviation > 0.0
            else float("-inf")
        )
        positive_months = int(monthly.gt(0.0).sum())
        eligible = bool(
            action_count >= settings.minimum_calibration_actions
            and positive_months >= settings.minimum_positive_calibration_months
            and np.isfinite(score)
        )
        candidates.append(
            {
                "threshold_multiple": float(multiple),
                "action_count": action_count,
                "positive_calibration_months": positive_months,
                "calibration_score": score,
                "eligible": eligible,
            }
        )
    admitted = [item for item in candidates if bool(item["eligible"])]
    if not admitted:
        return None, candidates
    chosen = max(
        admitted,
        key=lambda item: (float(item["calibration_score"]), float(item["threshold_multiple"])),
    )
    return float(chosen["threshold_multiple"]), candidates


def run_monthly_walk_forward(
    learning_frame: pd.DataFrame,
    settings: ModelSettings | None = None,
) -> WalkForwardResult:
    """Run monthly expanding core fit, prior-three-month calibration and test."""

    settings = settings or ModelSettings()
    required = {
        "decision_at",
        "target_end_at",
        "source_event_date",
        *source_feature_columns(),
        *market_feature_columns(),
    }
    for asset in ASSETS:
        required.update(
            {
                f"target_{asset.lower()}_return",
                f"stress_roundtrip_cost_{asset.lower()}",
            }
        )
    _require_columns(learning_frame, required, "learning_frame")
    frame = learning_frame.copy()
    frame["decision_at"] = _as_utc(frame["decision_at"], "learning_frame.decision_at")
    frame["target_end_at"] = _as_utc(frame["target_end_at"], "learning_frame.target_end_at")
    frame = frame.sort_values("decision_at", kind="stable").reset_index(drop=True)
    evaluation_start = pd.Timestamp(settings.evaluation_start, tz="Europe/Moscow").tz_convert("UTC")
    evaluation_end = (
        pd.Timestamp(settings.evaluation_end, tz="Europe/Moscow")
        + pd.offsets.MonthEnd(0)
        + pd.Timedelta(days=1)
    ).tz_convert("UTC")
    full_features = (*source_feature_columns(), *market_feature_columns())
    market_features = market_feature_columns()
    predictions: list[pd.DataFrame] = []
    fold_records: list[dict[str, object]] = []
    for test_start_naive in _month_starts(
        evaluation_start.tz_convert("Europe/Moscow").tz_localize(None),
        (evaluation_end - pd.Timedelta(seconds=1)).tz_convert("Europe/Moscow").tz_localize(None),
    ):
        test_start = test_start_naive.tz_localize("Europe/Moscow").tz_convert("UTC")
        test_end = (
            (test_start_naive + pd.offsets.MonthBegin(1))
            .tz_localize("Europe/Moscow")
            .tz_convert("UTC")
        )
        if test_start < evaluation_start or test_start >= evaluation_end:
            continue
        calibration_start_naive = test_start_naive - pd.DateOffset(
            months=settings.calibration_months
        )
        calibration_start = calibration_start_naive.tz_localize("Europe/Moscow").tz_convert("UTC")
        purge = pd.Timedelta(days=settings.purge_calendar_days)
        core = frame.loc[frame["target_end_at"].lt(calibration_start - purge)].copy()
        calibration = frame.loc[
            frame["decision_at"].ge(calibration_start)
            & frame["target_end_at"].lt(test_start - purge)
        ].copy()
        test = frame.loc[
            frame["decision_at"].ge(test_start) & frame["decision_at"].lt(test_end)
        ].copy()
        core_events = int(core["source_event_date"].nunique())
        calibration_events = int(calibration["source_event_date"].nunique())
        if (
            test.empty
            or core_events < settings.minimum_core_source_events
            or calibration_events < settings.minimum_calibration_source_events
        ):
            fold_records.append(
                {
                    "test_month": test_start_naive.strftime("%Y-%m"),
                    "status": "sleep_insufficient_nested_history",
                    "core_rows": int(len(core)),
                    "core_source_events": core_events,
                    "calibration_rows": int(len(calibration)),
                    "calibration_source_events": calibration_events,
                    "test_rows": int(len(test)),
                }
            )
            continue
        for model_id in MODEL_IDS:
            feature_columns = market_features if model_id == MODEL_MARKET_MLP else full_features
            calibration_prediction, test_prediction = _model_arrays(
                core, calibration, test, feature_columns, model_id, settings
            )
            threshold, candidates = select_threshold_multiple(
                calibration, calibration_prediction, settings
            )
            fold_records.append(
                {
                    "test_month": test_start_naive.strftime("%Y-%m"),
                    "model_id": model_id,
                    "status": "predicted" if threshold is not None else "sleep_calibration_gate",
                    "core_rows": int(len(core)),
                    "core_source_events": core_events,
                    "calibration_rows": int(len(calibration)),
                    "calibration_source_events": calibration_events,
                    "test_rows": int(len(test)),
                    "threshold_multiple": threshold,
                    "threshold_candidates": candidates,
                    "core_max_target_end_at": core["target_end_at"].max(),
                    "calibration_min_decision_at": calibration["decision_at"].min(),
                    "calibration_max_target_end_at": calibration["target_end_at"].max(),
                    "test_min_decision_at": test["decision_at"].min(),
                }
            )
            predicted = test[
                [
                    "decision_at",
                    "entry_at",
                    "target_end_at",
                    "decision_local_date",
                    "source_event_at",
                    "source_available_at",
                    "source_event_date",
                ]
            ].copy()
            for asset_index, asset in enumerate(ASSETS):
                lower = asset.lower()
                asset_frame = predicted.copy()
                asset_frame["model_id"] = model_id
                asset_frame["asset"] = asset
                asset_frame["predicted_return"] = test_prediction[:, asset_index]
                asset_frame["realized_label_return"] = test[f"target_{lower}_return"].to_numpy(
                    dtype=float
                )
                asset_frame["stress_roundtrip_cost_return"] = test[
                    f"stress_roundtrip_cost_{lower}"
                ].to_numpy(dtype=float)
                asset_frame["threshold_multiple"] = threshold
                if threshold is None:
                    asset_frame["entry_hurdle_return"] = np.nan
                    asset_frame["active_signal"] = False
                    asset_frame["score"] = 0.0
                else:
                    hurdle = threshold * asset_frame["stress_roundtrip_cost_return"]
                    asset_frame["entry_hurdle_return"] = hurdle
                    active = (
                        np.isfinite(asset_frame["predicted_return"])
                        & np.isfinite(hurdle)
                        & hurdle.gt(0.0)
                        & asset_frame["predicted_return"].abs().ge(hurdle)
                    )
                    asset_frame["active_signal"] = active
                    asset_frame["score"] = np.where(
                        active,
                        np.clip(asset_frame["predicted_return"] / hurdle, -2.0, 2.0),
                        0.0,
                    )
                predictions.append(asset_frame)
    prediction_frame = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    folds = pd.DataFrame(fold_records)
    return WalkForwardResult(predictions=prediction_frame, folds=folds)


def _bounded_risk_weights(
    scores: np.ndarray,
    covariance: np.ndarray,
    settings: RiskSettings,
) -> np.ndarray:
    active = np.isfinite(scores) & (np.abs(scores) > 0.0)
    weights = np.zeros(len(ASSETS), dtype=float)
    if not active.any() or covariance.shape != (len(ASSETS), len(ASSETS)):
        return weights
    if not np.isfinite(covariance).all() or (np.diag(covariance) <= 0.0).any():
        return weights
    raw = np.zeros(len(ASSETS), dtype=float)
    raw[active] = np.clip(scores[active], -settings.score_clip, settings.score_clip) / np.sqrt(
        np.diag(covariance)[active]
    )
    volatility = float(math.sqrt(max(float(raw @ covariance @ raw), 0.0)))
    if not np.isfinite(volatility) or volatility <= 0.0:
        return weights
    weights = raw * (settings.annual_target_volatility / volatility)
    scale = min(
        1.0,
        settings.maximum_gross / max(float(np.abs(weights).sum()), 1e-12),
        settings.maximum_asset_weight / max(float(np.abs(weights).max()), 1e-12),
    )
    weights *= scale
    weights[np.abs(weights) < 1e-12] = 0.0
    return weights


def build_weight_targets(
    predictions: pd.DataFrame,
    learning_frame: pd.DataFrame,
    model_id: str,
    feature_settings: FeatureSettings | None = None,
    risk_settings: RiskSettings | None = None,
) -> pd.DataFrame:
    """Convert predictions into causal covariance-aware next-open weights."""

    feature_settings = feature_settings or FeatureSettings()
    risk_settings = risk_settings or RiskSettings()
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown V32 model: {model_id}")
    selected = predictions.loc[predictions["model_id"].eq(model_id)].copy()
    if selected.empty:
        return pd.DataFrame()
    score_matrix = selected.pivot(index="decision_at", columns="asset", values="score").reindex(
        columns=ASSETS
    )
    source = learning_frame.set_index("decision_at", drop=False)
    records: list[dict[str, object]] = []
    covariance_columns = risk_covariance_columns()
    for decision_at, score_row in score_matrix.sort_index().iterrows():
        if decision_at not in source.index:
            raise ValueError("prediction decision is absent from learning frame")
        row = source.loc[decision_at]
        if isinstance(row, pd.DataFrame):
            raise ValueError("learning frame duplicates a decision timestamp")
        covariance = (
            row.loc[list(covariance_columns)]
            .to_numpy(dtype=float)
            .reshape(len(ASSETS), len(ASSETS))
        )
        weights = _bounded_risk_weights(score_row.to_numpy(dtype=float), covariance, risk_settings)
        for index, asset in enumerate(ASSETS):
            records.append(
                {
                    "model_id": model_id,
                    "decision_at": pd.Timestamp(decision_at),
                    "entry_at": pd.Timestamp(row["entry_at"]),
                    "local_date": pd.Timestamp(row["decision_local_date"]),
                    "asset": asset,
                    "contract_id": str(row[f"{asset}_contract_id"]),
                    "target_weight": float(weights[index]),
                    "score": float(score_row[asset]),
                    "signal_volume": float(row[f"{asset}_volume"]),
                    "sizing_notional": float(row[f"{asset}_sizing_notional"]),
                    "sizing_point_value": float(row[f"{asset}_sizing_point_value"]),
                    "sizing_tick_cash_value": float(row[f"{asset}_sizing_tick_cash_value"]),
                    "conservative_fee_per_side": float(row[f"{asset}_conservative_fee_per_side"]),
                    "modeled_initial_margin": float(row[f"{asset}_modeled_initial_margin"]),
                }
            )
    targets = pd.DataFrame(records)
    if targets.empty:
        return targets
    targets["entry_at"] = _as_utc(targets["entry_at"], "targets.entry_at")
    forced_records: list[dict[str, object]] = []
    for local_date, group in targets.groupby("local_date", sort=True):
        flat_time = pd.Timestamp(feature_settings.forced_flat_local)
        flat_at = pd.Timestamp(local_date).tz_localize("Europe/Moscow") + pd.Timedelta(
            hours=flat_time.hour, minutes=flat_time.minute, seconds=flat_time.second
        )
        flat_at = flat_at.tz_convert("UTC")
        last = group.sort_values("decision_at", kind="stable").groupby("asset").tail(1)
        for item in last.to_dict("records"):
            item["decision_at"] = flat_at
            item["entry_at"] = flat_at
            item["target_weight"] = 0.0
            item["score"] = 0.0
            item["forced_flat"] = True
            forced_records.append(item)
    targets["forced_flat"] = False
    targets = pd.concat((targets, pd.DataFrame(forced_records)), ignore_index=True)
    if targets.duplicated(["entry_at", "asset"]).any():
        raise ValueError("V32 targets duplicate entry timestamp and asset")
    gross = targets.groupby("entry_at")["target_weight"].apply(lambda values: values.abs().sum())
    if gross.gt(risk_settings.maximum_gross + 1e-9).any():
        raise ValueError("V32 weight targets exceed gross cap")
    return targets.sort_values(["entry_at", "asset"], kind="stable").reset_index(drop=True)


def _long_market(common_panel: pd.DataFrame) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    base = common_panel.loc[:, ["timestamp", "local_date"]].copy()
    base["timestamp"] = _as_utc(base["timestamp"], "common_panel.timestamp")
    for asset in ASSETS:
        fields = {
            f"{asset}_contract_id": "contract_id",
            f"{asset}_open": "open",
            f"{asset}_volume": "volume",
            f"{asset}_sizing_point_value": "sizing_point_value",
            f"{asset}_sizing_tick_cash_value": "sizing_tick_cash_value",
            f"{asset}_conservative_fee_per_side": "conservative_fee_per_side",
            f"{asset}_modeled_initial_margin": "modeled_initial_margin",
            f"{asset}_sizing_notional": "sizing_notional",
        }
        selected = pd.concat((base, common_panel.loc[:, list(fields)]), axis=1).rename(
            columns=fields
        )
        selected["asset"] = asset
        records.append(selected)
    market = pd.concat(records, ignore_index=True)
    market["contract_id"] = market["contract_id"].astype(str)
    for column in (
        "open",
        "volume",
        "sizing_point_value",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "sizing_notional",
    ):
        market[column] = pd.to_numeric(market[column], errors="coerce")
    return market.sort_values(["timestamp", "asset"], kind="stable").reset_index(drop=True)


def _annual_returns(daily_returns: pd.Series) -> dict[str, float]:
    if daily_returns.empty:
        return {}
    years = pd.Index(pd.to_datetime(daily_returns.index).year)
    return {
        str(int(year)): float((1.0 + daily_returns.loc[years == year]).prod() - 1.0)
        for year in sorted(set(years))
    }


def _ledger_metrics(
    ledger: pd.DataFrame,
    orders: pd.DataFrame,
    unresolved: pd.DataFrame,
    settings: LedgerSettings,
) -> dict[str, object]:
    if ledger.empty:
        return {
            "initial_cash": settings.initial_cash,
            "ending_equity": settings.initial_cash,
            "total_return": 0.0,
            "cagr": 0.0,
            "annualized_sharpe": 0.0,
            "maximum_drawdown": 0.0,
            "annual_returns": {},
            "positive_years": 0,
            "filled_order_legs": 0,
            "total_cost": 0.0,
            "execution_complete": unresolved.empty,
        }
    ending = ledger.groupby("local_date", sort=True).tail(1).set_index("local_date")["equity"]
    previous = ending.shift(1).fillna(settings.initial_cash)
    daily = ending / previous - 1.0
    total_return = float(ending.iloc[-1] / settings.initial_cash - 1.0)
    elapsed_days = max(
        int((pd.Timestamp(ending.index[-1]) - pd.Timestamp(ending.index[0])).days), 1
    )
    cagr = (
        float((1.0 + total_return) ** (365.25 / elapsed_days) - 1.0)
        if total_return > -1.0
        else -1.0
    )
    standard_deviation = float(daily.std(ddof=1)) if len(daily) > 1 else float("nan")
    sharpe = (
        float(daily.mean() / standard_deviation * math.sqrt(252.0))
        if np.isfinite(standard_deviation) and standard_deviation > 0.0
        else 0.0
    )
    equity = pd.Series(
        np.concatenate(([settings.initial_cash], ledger["equity"].to_numpy(dtype=float)))
    )
    drawdown = equity / equity.cummax() - 1.0
    annual = _annual_returns(daily)
    return {
        "initial_cash": settings.initial_cash,
        "ending_equity": float(ending.iloc[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "annualized_sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": float(min(annual.values())) if annual else 0.0,
        "filled_order_legs": int(orders["filled"].sum()) if len(orders) else 0,
        "capacity_clips": int(orders["capacity_clipped"].sum()) if len(orders) else 0,
        "total_cost": float(orders.loc[orders["filled"], "total_cost"].sum())
        if len(orders)
        else 0.0,
        "maximum_participation": float(orders["participation"].max()) if len(orders) else 0.0,
        "maximum_gross_multiple": float(ledger["gross_multiple"].max()),
        "maximum_buffered_margin_multiple": float(ledger["buffered_margin_multiple"].max()),
        "unresolved_count": int(len(unresolved)),
        "execution_complete": bool(unresolved.empty),
    }


def simulate_next_open_portfolio(
    common_panel: pd.DataFrame,
    targets: pd.DataFrame,
    settings: LedgerSettings | None = None,
) -> SimulationResult:
    """Execute causal target weights at the next exact common-bucket open."""

    settings = settings or LedgerSettings()
    if targets.empty:
        ledger = pd.DataFrame(columns=LEDGER_COLUMNS)
        orders = pd.DataFrame(columns=ORDER_COLUMNS)
        unresolved_frame = pd.DataFrame(columns=UNRESOLVED_COLUMNS)
        metrics = _ledger_metrics(ledger, orders, unresolved_frame, settings)
        return SimulationResult(ledger, orders, unresolved_frame, metrics, True)
    required_targets = {
        "entry_at",
        "asset",
        "contract_id",
        "target_weight",
        "signal_volume",
        "sizing_notional",
        "sizing_point_value",
        "sizing_tick_cash_value",
        "conservative_fee_per_side",
        "modeled_initial_margin",
        "forced_flat",
    }
    _require_columns(targets, required_targets, "targets")
    target = targets.copy()
    target["entry_at"] = _as_utc(target["entry_at"], "targets.entry_at")
    if target["entry_at"].max() >= PROTECTED_FROM:
        raise ValueError("targets touch protected 2026")
    market = _long_market(common_panel)
    start = target["entry_at"].min() - TEN_MINUTES
    end = target["entry_at"].max()
    market = market.loc[market["timestamp"].between(start, end)].copy()
    market_by_time = {
        timestamp: group.set_index("asset") for timestamp, group in market.groupby("timestamp")
    }
    targets_by_time = {
        timestamp: group.set_index("asset") for timestamp, group in target.groupby("entry_at")
    }
    positions = {asset: 0 for asset in ASSETS}
    contracts: dict[str, str | None] = {asset: None for asset in ASSETS}
    point_values = {asset: float("nan") for asset in ASSETS}
    last_opens = {asset: float("nan") for asset in ASSETS}
    cash = float(settings.initial_cash)
    previous_timestamp: pd.Timestamp | None = None
    ledger_records: list[dict[str, object]] = []
    order_records: list[dict[str, object]] = []
    unresolved_records: list[dict[str, object]] = []

    def unresolved(timestamp: pd.Timestamp, asset: str, reason: str) -> None:
        unresolved_records.append({"timestamp": timestamp, "asset": asset, "reason": reason})

    for timestamp in sorted(market_by_time):
        rows = market_by_time[timestamp]
        if set(rows.index) != set(ASSETS):
            continue
        open_position = any(quantity != 0 for quantity in positions.values())
        if (
            previous_timestamp is not None
            and timestamp - previous_timestamp != TEN_MINUTES
            and open_position
        ):
            unresolved(timestamp, "PORTFOLIO", "missing_exact_mark_successor")
            break
        bar_pnl = 0.0
        for asset in ASSETS:
            quantity = positions[asset]
            if quantity == 0:
                continue
            row = rows.loc[asset]
            if str(row["contract_id"]) != contracts[asset]:
                unresolved(timestamp, asset, "contract_changed_while_open")
                break
            current_open = float(row["open"])
            if not np.isfinite(current_open) or current_open <= 0.0:
                unresolved(timestamp, asset, "missing_factual_open_mark")
                break
            bar_pnl += quantity * (current_open - last_opens[asset]) * point_values[asset]
        if unresolved_records:
            break
        cash += bar_pnl
        bar_cost = 0.0
        target_rows = targets_by_time.get(timestamp)
        if target_rows is not None:
            # De-risking legs are always attempted before risk-increasing legs.
            planned: list[tuple[int, str, int, pd.Series, pd.Series]] = []
            for asset in ASSETS:
                specification = target_rows.loc[asset]
                market_row = rows.loc[asset]
                if str(specification["contract_id"]) != str(market_row["contract_id"]):
                    unresolved(timestamp, asset, "target_contract_mismatch")
                    break
                notional = float(specification["sizing_notional"])
                signal_volume = float(specification["signal_volume"])
                if not np.isfinite(notional) or notional <= 0.0 or not np.isfinite(signal_volume):
                    unresolved(timestamp, asset, "missing_causal_sizing_dependency")
                    break
                desired = math.trunc(cash * float(specification["target_weight"]) / notional)
                signal_cap = max(math.floor(settings.signal_participation * signal_volume), 0)
                desired = int(np.clip(desired, -signal_cap, signal_cap))
                delta = desired - positions[asset]
                de_risk = int(
                    abs(desired) < abs(positions[asset])
                    or (
                        positions[asset] != 0
                        and desired != 0
                        and np.sign(desired) != np.sign(positions[asset])
                    )
                )
                planned.append((0 if de_risk else 1, asset, delta, specification, market_row))
            if unresolved_records:
                break
            for _, asset, requested_delta, specification, market_row in sorted(planned):
                if requested_delta == 0:
                    continue
                factual_volume = float(market_row["volume"])
                if not np.isfinite(factual_volume) or factual_volume < 0.0:
                    unresolved(timestamp, asset, "missing_factual_entry_volume")
                    break
                capacity = max(math.floor(settings.factual_participation_cap * factual_volume), 0)
                desired_after = positions[asset] + requested_delta
                de_risk = bool(
                    abs(desired_after) < abs(positions[asset])
                    or (
                        positions[asset] != 0
                        and desired_after != 0
                        and np.sign(desired_after) != np.sign(positions[asset])
                    )
                )
                capacity_clipped = False
                delta = requested_delta
                if abs(delta) > capacity:
                    if de_risk:
                        unresolved(timestamp, asset, "insufficient_exit_capacity")
                        break
                    delta = int(np.sign(delta) * capacity)
                    capacity_clipped = True
                if delta == 0:
                    order_records.append(
                        {
                            "timestamp": timestamp,
                            "asset": asset,
                            "contract_id": str(market_row["contract_id"]),
                            "requested_quantity_delta": requested_delta,
                            "filled_quantity_delta": 0,
                            "participation": 0.0,
                            "commission_cost": 0.0,
                            "slippage_cost": 0.0,
                            "total_cost": 0.0,
                            "capacity_clipped": capacity_clipped,
                            "filled": False,
                            "reason": "zero_factual_capacity",
                        }
                    )
                    continue
                candidate_positions = positions.copy()
                candidate_positions[asset] += delta
                gross = 0.0
                buffered_margin = 0.0
                for candidate_asset in ASSETS:
                    candidate_row = rows.loc[candidate_asset]
                    candidate_notional = float(candidate_row["sizing_notional"])
                    candidate_margin = float(candidate_row["modeled_initial_margin"])
                    if (
                        not np.isfinite(candidate_notional)
                        or candidate_notional <= 0.0
                        or not np.isfinite(candidate_margin)
                        or candidate_margin <= 0.0
                    ):
                        unresolved(timestamp, candidate_asset, "missing_factual_risk_dependency")
                        break
                    gross += abs(candidate_positions[candidate_asset]) * candidate_notional
                    buffered_margin += (
                        abs(candidate_positions[candidate_asset])
                        * candidate_margin
                        * settings.margin_buffer_multiple
                    )
                if unresolved_records:
                    break
                if gross > settings.maximum_gross * max(cash, 1e-12) + 1e-9:
                    unresolved(timestamp, asset, "gross_limit_breach_at_order")
                    break
                if buffered_margin > cash + 1e-9:
                    unresolved(timestamp, asset, "buffered_margin_breach_at_order")
                    break
                tick_cash = float(specification["sizing_tick_cash_value"])
                fee = float(specification["conservative_fee_per_side"])
                point_value = float(specification["sizing_point_value"])
                if (
                    not np.isfinite(tick_cash)
                    or tick_cash <= 0.0
                    or not np.isfinite(fee)
                    or fee < 0.0
                    or not np.isfinite(point_value)
                    or point_value <= 0.0
                ):
                    unresolved(timestamp, asset, "missing_cost_dependency")
                    break
                commission = abs(delta) * settings.fee_multiplier * fee
                slippage = abs(delta) * settings.slippage_ticks * tick_cash
                total_cost = commission + slippage
                cash -= total_cost
                bar_cost += total_cost
                positions[asset] += delta
                if positions[asset] == 0:
                    contracts[asset] = None
                    point_values[asset] = float("nan")
                    last_opens[asset] = float("nan")
                else:
                    contracts[asset] = str(market_row["contract_id"])
                    point_values[asset] = point_value
                    last_opens[asset] = float(market_row["open"])
                order_records.append(
                    {
                        "timestamp": timestamp,
                        "asset": asset,
                        "contract_id": str(market_row["contract_id"]),
                        "requested_quantity_delta": requested_delta,
                        "filled_quantity_delta": delta,
                        "participation": abs(delta) / max(factual_volume, 1.0),
                        "commission_cost": commission,
                        "slippage_cost": slippage,
                        "total_cost": total_cost,
                        "capacity_clipped": capacity_clipped,
                        "filled": True,
                        "reason": "filled",
                    }
                )
            if unresolved_records:
                break
        for asset in ASSETS:
            if positions[asset] != 0:
                current_open = float(rows.loc[asset, "open"])
                last_opens[asset] = current_open
                contracts[asset] = str(rows.loc[asset, "contract_id"])
        gross = sum(
            abs(positions[asset]) * float(rows.loc[asset, "sizing_notional"]) for asset in ASSETS
        )
        buffered_margin = sum(
            abs(positions[asset])
            * float(rows.loc[asset, "modeled_initial_margin"])
            * settings.margin_buffer_multiple
            for asset in ASSETS
        )
        ledger_records.append(
            {
                "timestamp": timestamp,
                "local_date": pd.Timestamp(rows.iloc[0]["local_date"]),
                "bar_pnl": bar_pnl,
                "bar_cost": bar_cost,
                "equity": cash,
                "gross_notional": gross,
                "gross_multiple": gross / max(cash, 1e-12),
                "buffered_margin": buffered_margin,
                "buffered_margin_multiple": buffered_margin / max(cash, 1e-12),
                **{f"position_{asset.lower()}": positions[asset] for asset in ASSETS},
            }
        )
        previous_timestamp = timestamp
    if not unresolved_records and any(quantity != 0 for quantity in positions.values()):
        unresolved_records.append(
            {
                "timestamp": previous_timestamp,
                "asset": "PORTFOLIO",
                "reason": "terminal_position_not_flat",
            }
        )
    ledger = pd.DataFrame(ledger_records, columns=LEDGER_COLUMNS)
    orders = pd.DataFrame(order_records, columns=ORDER_COLUMNS)
    unresolved_frame = pd.DataFrame(unresolved_records, columns=UNRESOLVED_COLUMNS)
    metrics = _ledger_metrics(ledger, orders, unresolved_frame, settings)
    return SimulationResult(
        ledger=ledger,
        orders=orders,
        unresolved=unresolved_frame,
        metrics=metrics,
        execution_complete=unresolved_frame.empty,
    )


__all__ = [
    "ASSETS",
    "FeatureSettings",
    "LedgerSettings",
    "MODEL_FULL_MLP",
    "MODEL_FULL_RIDGE",
    "MODEL_IDS",
    "MODEL_MARKET_MLP",
    "ModelSettings",
    "PROTECTED_FROM",
    "RiskSettings",
    "SimulationResult",
    "TEN_MINUTES",
    "WalkForwardResult",
    "build_learning_frame",
    "build_weight_targets",
    "market_feature_columns",
    "risk_covariance_columns",
    "run_monthly_walk_forward",
    "select_threshold_multiple",
    "simulate_next_open_portfolio",
    "source_feature_columns",
]
