"""Execution-aware RI/MIX relative-corridor barrier research for V34."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from market_lab.futures.curve_regime_intraday import (
    ASSETS,
    LEDGER_COLUMNS,
    ORDER_COLUMNS,
    PROTECTED_FROM,
    TEN_MINUTES,
    FeatureSettings,
    _as_utc,
    _ledger_metrics,
    _require_columns,
    _rolling_valid,
    _valid_one_bar_returns,
    build_learning_frame,
    market_feature_columns,
    source_feature_columns,
)

MODEL_CURVE_META: Final[str] = "curve_market_barrier_mlp"
MODEL_MARKET_META: Final[str] = "market_only_barrier_mlp"
MODEL_FIXED_RULE: Final[str] = "fixed_relative_corridor"
MODEL_IDS: Final[tuple[str, ...]] = (
    MODEL_CURVE_META,
    MODEL_MARKET_META,
    MODEL_FIXED_RULE,
)
PAIR_ASSETS: Final[tuple[str, str]] = ("RI", "MIX")


def corridor_feature_columns() -> tuple[str, ...]:
    return (
        "corridor_z",
        "corridor_abs_z",
        "corridor_beta",
        "corridor_residual_sigma",
        "corridor_take_profit_barrier",
        "corridor_stop_barrier",
        "corridor_side",
    )


@dataclass(frozen=True, slots=True)
class CorridorSettings:
    beta_observations: int = 132
    beta_minimum_observations: int = 66
    residual_observations: int = 18
    minimum_absolute_z: float = 1.50
    take_profit_sigma_multiple: float = 1.00
    stop_to_take_profit_multiple: float = 3.00
    barrier_scale_bars: int = 6
    maximum_holding_bars: int = 12
    minimum_signal_volume: float = 1_000.0
    first_decision_local: str = "10:10:00"
    last_decision_local: str = "16:30:00"

    def __post_init__(self) -> None:
        if self.beta_observations != 132 or self.beta_minimum_observations != 66:
            raise ValueError("V34 beta history is frozen")
        if self.residual_observations != 18 or self.minimum_absolute_z != 1.50:
            raise ValueError("V34 corridor admission is frozen")
        if self.take_profit_sigma_multiple != 1.0:
            raise ValueError("V34 take-profit barrier is frozen")
        if self.stop_to_take_profit_multiple != 3.0:
            raise ValueError("V34 distant-stop multiple is frozen")
        if self.barrier_scale_bars != 6 or self.maximum_holding_bars != 12:
            raise ValueError("V34 barrier horizon is frozen")
        if self.minimum_signal_volume != 1_000.0:
            raise ValueError("V34 signal liquidity floor is frozen")


@dataclass(frozen=True, slots=True)
class MetaModelSettings:
    evaluation_start: str = "2022-04-01"
    evaluation_end: str = "2024-05-31"
    calibration_months: int = 3
    purge_calendar_days: int = 1
    minimum_core_source_events: int = 80
    minimum_calibration_source_events: int = 40
    minimum_core_candidates: int = 200
    minimum_calibration_candidates: int = 50
    minimum_calibration_trades: int = 30
    minimum_positive_calibration_months: int = 2
    probability_thresholds: tuple[float, ...] = (0.55, 0.65, 0.75)
    maximum_trades_per_day: int = 2
    hidden_layers: tuple[int, ...] = (24, 12)
    activation: str = "tanh"
    alpha: float = 0.002
    learning_rate_init: float = 0.001
    maximum_iterations: int = 80
    batch_size: int = 128
    seeds: tuple[int, ...] = (3401, 3402, 3403)

    def __post_init__(self) -> None:
        if self.calibration_months != 3 or self.purge_calendar_days != 1:
            raise ValueError("V34 nested timing is frozen")
        if self.probability_thresholds != (0.55, 0.65, 0.75):
            raise ValueError("V34 probability thresholds are frozen")
        if self.maximum_trades_per_day != 2:
            raise ValueError("V34 daily trade cap is frozen")
        if self.hidden_layers != (24, 12) or self.seeds != (3401, 3402, 3403):
            raise ValueError("V34 MLP architecture or seeds drifted")
        if self.maximum_iterations != 80 or self.activation != "tanh":
            raise ValueError("V34 MLP training contract drifted")


@dataclass(frozen=True, slots=True)
class PairRiskSettings:
    risk_budget_per_trade: float = 0.0075
    maximum_pair_gross: float = 1.20
    maximum_asset_weight: float = 0.60

    def __post_init__(self) -> None:
        if self.risk_budget_per_trade != 0.0075:
            raise ValueError("V34 trade risk budget is frozen")
        if self.maximum_pair_gross != 1.20 or self.maximum_asset_weight != 0.60:
            raise ValueError("V34 pair exposure caps are frozen")


@dataclass(frozen=True, slots=True)
class PairExecutionSettings:
    initial_cash: float = 1_000_000.0
    slippage_ticks: int = 1
    fee_multiplier: float = 1.0
    signal_participation: float = 0.0025
    factual_participation_cap: float = 0.01
    margin_buffer_multiple: float = 2.0
    maximum_exit_retry_bars: int = 6
    maximum_trades_per_day: int = 2

    def __post_init__(self) -> None:
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("V34 slippage ticks must be 1, 2 or 4")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("V34 fee multiplier must be 1 or 2")
        if self.signal_participation != 0.0025 or self.factual_participation_cap != 0.01:
            raise ValueError("V34 participation settings drifted")
        if self.margin_buffer_multiple != 2.0 or self.maximum_exit_retry_bars != 6:
            raise ValueError("V34 margin or retry settings drifted")
        if self.maximum_trades_per_day != 2:
            raise ValueError("V34 daily execution cap drifted")


@dataclass(frozen=True, slots=True)
class BarrierWalkForwardResult:
    predictions: pd.DataFrame
    folds: pd.DataFrame


@dataclass(frozen=True, slots=True)
class PairSimulationResult:
    ledger: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
    skipped_entries: pd.DataFrame
    unresolved: pd.DataFrame
    metrics: dict[str, object]
    execution_complete: bool


def _month_starts(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    return list(
        pd.date_range(start.normalize().replace(day=1), end.normalize().replace(day=1), freq="MS")
    )


def _corridor_state(common_panel: pd.DataFrame, settings: CorridorSettings) -> pd.DataFrame:
    panel = common_panel.sort_values("timestamp", kind="stable").reset_index(drop=True)
    panel["timestamp"] = _as_utc(panel["timestamp"], "common_panel.timestamp")
    returns = _valid_one_bar_returns(panel)
    valid = returns[list(PAIR_ASSETS)].notna().all(axis=1)
    valid_indices = np.flatnonzero(valid.to_numpy(dtype=bool))
    valid_values = returns.loc[valid, list(PAIR_ASSETS)].to_numpy(dtype=float)
    beta = pd.Series(np.nan, index=panel.index, dtype=float)
    for position, row_index in enumerate(valid_indices):
        start = max(0, position + 1 - settings.beta_observations)
        history = valid_values[start : position + 1]
        if len(history) < settings.beta_minimum_observations:
            continue
        covariance = np.cov(history, rowvar=False, ddof=1)
        denominator = float(covariance[1, 1])
        if not np.isfinite(covariance).all() or denominator <= 1e-12:
            continue
        beta.loc[int(row_index)] = float(np.clip(covariance[0, 1] / denominator, 0.25, 4.0))
    residual = returns["RI"] - beta * returns["MIX"]
    residual_sum = _rolling_valid(residual, settings.residual_observations, "sum")
    residual_sigma = _rolling_valid(residual, settings.residual_observations, "std")
    denominator = residual_sigma * math.sqrt(settings.residual_observations)
    corridor_z = residual_sum / denominator.where(denominator.gt(1e-12))
    state = pd.DataFrame(
        {
            "decision_at": panel["timestamp"] + TEN_MINUTES,
            "corridor_z": corridor_z,
            "corridor_abs_z": corridor_z.abs(),
            "corridor_beta": beta,
            "corridor_residual_sigma": residual_sigma,
        }
    )
    state["corridor_take_profit_barrier"] = (
        settings.take_profit_sigma_multiple
        * state["corridor_residual_sigma"]
        * math.sqrt(settings.barrier_scale_bars)
    )
    state["corridor_stop_barrier"] = (
        settings.stop_to_take_profit_multiple * state["corridor_take_profit_barrier"]
    )
    state["corridor_side"] = -np.sign(state["corridor_z"])
    return state


def _future_barrier_path(
    row: pd.Series,
    common: pd.DataFrame,
    timestamp_to_index: dict[pd.Timestamp, int],
    settings: CorridorSettings,
) -> dict[str, object] | None:
    entry_at = pd.Timestamp(row["entry_at"])
    if entry_at not in timestamp_to_index:
        return None
    entry_index = timestamp_to_index[entry_at]
    final_index = entry_index + settings.maximum_holding_bars
    if final_index >= len(common):
        return None
    expected = [
        entry_at + offset * TEN_MINUTES for offset in range(settings.maximum_holding_bars + 1)
    ]
    actual = list(common.loc[entry_index:final_index, "timestamp"])
    if actual != expected:
        return None
    for asset in PAIR_ASSETS:
        contract = common.loc[entry_index:final_index, f"{asset}_contract_id"].astype(str)
        if contract.nunique() != 1 or contract.iloc[0] != str(row[f"{asset}_contract_id"]):
            return None
    ri_entry = float(common.loc[entry_index, "RI_open"])
    mix_entry = float(common.loc[entry_index, "MIX_open"])
    if ri_entry <= 0.0 or mix_entry <= 0.0:
        return None
    beta = float(row["corridor_beta"])
    side = float(row["corridor_side"])
    take_profit = float(row["corridor_take_profit_barrier"])
    stop = float(row["corridor_stop_barrier"])
    exit_reason = "time_exit"
    holding_bars = settings.maximum_holding_bars
    for offset in range(1, settings.maximum_holding_bars + 1):
        monitor_index = entry_index + offset - 1
        ri_close = float(common.loc[monitor_index, "RI_close"])
        mix_close = float(common.loc[monitor_index, "MIX_close"])
        if ri_close <= 0.0 or mix_close <= 0.0:
            return None
        spread = side * (math.log(ri_close / ri_entry) - beta * math.log(mix_close / mix_entry))
        if spread >= take_profit:
            exit_reason = "take_profit"
            holding_bars = offset
            break
        if spread <= -stop:
            exit_reason = "distant_stop"
            holding_bars = offset
            break
    exit_index = entry_index + holding_bars
    exit_at = pd.Timestamp(common.loc[exit_index, "timestamp"])
    ri_exit = float(common.loc[exit_index, "RI_open"])
    mix_exit = float(common.loc[exit_index, "MIX_open"])
    realized_spread_return = side * (
        math.log(ri_exit / ri_entry) - beta * math.log(mix_exit / mix_entry)
    )
    stress_cost = float(row["stress_roundtrip_cost_ri"]) + abs(beta) * float(
        row["stress_roundtrip_cost_mix"]
    )
    net_return = realized_spread_return - stress_cost
    return {
        "barrier_exit_at": exit_at,
        "barrier_holding_bars": holding_bars,
        "barrier_exit_reason": exit_reason,
        "barrier_realized_spread_return": realized_spread_return,
        "barrier_stress_cost_return": stress_cost,
        "barrier_net_stress_return": net_return,
        "barrier_target": int(exit_reason == "take_profit" and net_return > 0.0),
    }


def build_corridor_candidates(
    common_panel: pd.DataFrame,
    curve_context: pd.DataFrame,
    corridor_settings: CorridorSettings | None = None,
    feature_settings: FeatureSettings | None = None,
) -> pd.DataFrame:
    """Build causal RI/MIX corridor states and next-open barrier outcomes."""

    corridor_settings = corridor_settings or CorridorSettings()
    feature_settings = feature_settings or FeatureSettings()
    learning = build_learning_frame(common_panel, curve_context, feature_settings)
    state = _corridor_state(common_panel, corridor_settings)
    merged = learning.merge(state, on="decision_at", how="left", validate="one_to_one")
    decision_local = merged["decision_at"].dt.tz_convert("Europe/Moscow")
    first = pd.Timestamp(corridor_settings.first_decision_local).time()
    last = pd.Timestamp(corridor_settings.last_decision_local).time()
    time_ok = decision_local.dt.time.ge(first) & decision_local.dt.time.le(last)
    usable = (
        time_ok
        & merged["corridor_abs_z"].ge(corridor_settings.minimum_absolute_z)
        & merged["corridor_side"].abs().eq(1.0)
        & merged["RI_volume"].ge(corridor_settings.minimum_signal_volume)
        & merged["MIX_volume"].ge(corridor_settings.minimum_signal_volume)
        & merged[list(corridor_feature_columns())].notna().all(axis=1)
    )
    candidate = merged.loc[usable].copy()
    common = common_panel.sort_values("timestamp", kind="stable").reset_index(drop=True)
    common["timestamp"] = _as_utc(common["timestamp"], "common_panel.timestamp")
    timestamp_to_index = {timestamp: index for index, timestamp in enumerate(common["timestamp"])}
    path_records: list[dict[str, object]] = []
    admitted_indices: list[int] = []
    for row_index, row in candidate.iterrows():
        record = _future_barrier_path(
            row,
            common,
            timestamp_to_index,
            corridor_settings,
        )
        if record is None:
            continue
        admitted_indices.append(row_index)
        path_records.append(record)
    candidate = candidate.loc[admitted_indices].copy()
    if candidate.empty:
        raise ValueError("V34 produced no exact corridor candidates")
    candidate = candidate.reset_index(drop=True)
    paths = pd.DataFrame(path_records)
    candidate = pd.concat((candidate, paths), axis=1)
    candidate["target_end_at"] = _as_utc(candidate["barrier_exit_at"], "candidate.barrier_exit_at")
    if candidate["target_end_at"].ge(PROTECTED_FROM).any():
        raise ValueError("V34 barrier targets touch protected 2026")
    return candidate.sort_values("decision_at", kind="stable").reset_index(drop=True)


def _select_nonoverlapping_rows(
    frame: pd.DataFrame,
    active: np.ndarray,
    maximum_trades_per_day: int,
) -> pd.DataFrame:
    selected = frame.loc[active].sort_values("entry_at", kind="stable")
    records: list[pd.Series] = []
    for _, group in selected.groupby("decision_local_date", sort=True):
        next_available: pd.Timestamp | None = None
        count = 0
        for _, row in group.iterrows():
            if count >= maximum_trades_per_day:
                break
            entry_at = pd.Timestamp(row["entry_at"])
            if next_available is not None and entry_at < next_available:
                continue
            records.append(row)
            count += 1
            next_available = pd.Timestamp(row["barrier_exit_at"]) + TEN_MINUTES
    return pd.DataFrame(records).reset_index(drop=True) if records else pd.DataFrame()


def select_probability_threshold(
    calibration: pd.DataFrame,
    probabilities: np.ndarray,
    settings: MetaModelSettings,
) -> tuple[float | None, list[dict[str, object]]]:
    """Choose a probability gate only on nonoverlapping prior calibration trades."""

    if probabilities.shape != (len(calibration),):
        raise ValueError("V34 calibration probability shape mismatch")
    candidates: list[dict[str, object]] = []
    for threshold in settings.probability_thresholds:
        active = np.isfinite(probabilities) & (probabilities >= threshold)
        trades = _select_nonoverlapping_rows(
            calibration,
            active,
            settings.maximum_trades_per_day,
        )
        if trades.empty:
            daily = pd.Series(dtype=float)
            monthly = pd.Series(dtype=float)
        else:
            daily = trades.groupby("decision_local_date")["barrier_net_stress_return"].sum()
            month_key = pd.to_datetime(trades["decision_local_date"]).dt.to_period("M").astype(str)
            monthly = trades["barrier_net_stress_return"].groupby(month_key).sum()
        standard_deviation = float(daily.std(ddof=1)) if len(daily) > 1 else float("nan")
        score = (
            float(daily.mean() / standard_deviation * math.sqrt(252.0))
            if np.isfinite(standard_deviation) and standard_deviation > 0.0
            else float("-inf")
        )
        positive_months = int(monthly.gt(0.0).sum())
        eligible = bool(
            len(trades) >= settings.minimum_calibration_trades
            and positive_months >= settings.minimum_positive_calibration_months
            and np.isfinite(score)
        )
        candidates.append(
            {
                "probability_threshold": float(threshold),
                "calibration_trades": int(len(trades)),
                "positive_calibration_months": positive_months,
                "calibration_score": score,
                "eligible": eligible,
            }
        )
    admitted = [record for record in candidates if bool(record["eligible"])]
    if not admitted:
        return None, candidates
    chosen = max(
        admitted,
        key=lambda record: (
            float(record["calibration_score"]),
            float(record["probability_threshold"]),
        ),
    )
    return float(chosen["probability_threshold"]), candidates


def _fit_probability_ensemble(
    core: pd.DataFrame,
    calibration: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: tuple[str, ...],
    settings: MetaModelSettings,
) -> tuple[np.ndarray, np.ndarray]:
    x_core = core.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    x_calibration = (
        calibration.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    )
    x_test = test.loc[:, feature_columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    y_core = core["barrier_target"].to_numpy(dtype=int)
    if set(np.unique(y_core)) != {0, 1}:
        raise ValueError("V34 classifier core does not contain both barrier classes")
    imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
    scaler = StandardScaler()
    transformed_core = scaler.fit_transform(imputer.fit_transform(x_core))
    transformed_calibration = scaler.transform(imputer.transform(x_calibration))
    transformed_test = scaler.transform(imputer.transform(x_test))
    calibration_probabilities: list[np.ndarray] = []
    test_probabilities: list[np.ndarray] = []
    for seed in settings.seeds:
        model = MLPClassifier(
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
            model.fit(transformed_core, y_core)
        calibration_probabilities.append(model.predict_proba(transformed_calibration)[:, 1])
        test_probabilities.append(model.predict_proba(transformed_test)[:, 1])
    return np.mean(calibration_probabilities, axis=0), np.mean(test_probabilities, axis=0)


def _prediction_columns(frame: pd.DataFrame) -> list[str]:
    columns = [
        "decision_at",
        "entry_at",
        "barrier_exit_at",
        "decision_local_date",
        "source_event_at",
        "source_available_at",
        "source_event_date",
        "RI_contract_id",
        "MIX_contract_id",
        "RI_volume",
        "MIX_volume",
        "RI_sizing_notional",
        "MIX_sizing_notional",
        "RI_sizing_point_value",
        "MIX_sizing_point_value",
        "RI_sizing_tick_cash_value",
        "MIX_sizing_tick_cash_value",
        "RI_conservative_fee_per_side",
        "MIX_conservative_fee_per_side",
        "RI_modeled_initial_margin",
        "MIX_modeled_initial_margin",
        *corridor_feature_columns(),
        "barrier_holding_bars",
        "barrier_exit_reason",
        "barrier_realized_spread_return",
        "barrier_stress_cost_return",
        "barrier_net_stress_return",
        "barrier_target",
    ]
    _require_columns(frame, columns, "V34 candidate frame")
    return columns


def run_barrier_walk_forward(
    candidates: pd.DataFrame,
    settings: MetaModelSettings | None = None,
) -> BarrierWalkForwardResult:
    """Run frozen monthly meta-label fits and a fixed-rule ablation."""

    settings = settings or MetaModelSettings()
    required = {
        "decision_at",
        "target_end_at",
        "source_event_date",
        "barrier_target",
        *source_feature_columns(),
        *market_feature_columns(),
        *corridor_feature_columns(),
    }
    _require_columns(candidates, required, "V34 candidates")
    frame = candidates.copy()
    frame["decision_at"] = _as_utc(frame["decision_at"], "candidates.decision_at")
    frame["target_end_at"] = _as_utc(frame["target_end_at"], "candidates.target_end_at")
    frame = frame.sort_values("decision_at", kind="stable").reset_index(drop=True)
    evaluation_start = pd.Timestamp(settings.evaluation_start, tz="Europe/Moscow").tz_convert("UTC")
    evaluation_end = (
        pd.Timestamp(settings.evaluation_end, tz="Europe/Moscow")
        + pd.offsets.MonthEnd(0)
        + pd.Timedelta(days=1)
    ).tz_convert("UTC")
    full_features = (
        *source_feature_columns(),
        *market_feature_columns(),
        *corridor_feature_columns(),
    )
    market_features = (*market_feature_columns(), *corridor_feature_columns())
    predictions: list[pd.DataFrame] = []
    folds: list[dict[str, object]] = []
    base_columns = _prediction_columns(frame)
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
        calibration_start = (
            (test_start_naive - pd.DateOffset(months=settings.calibration_months))
            .tz_localize("Europe/Moscow")
            .tz_convert("UTC")
        )
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
        history_ok = bool(
            not test.empty
            and core_events >= settings.minimum_core_source_events
            and calibration_events >= settings.minimum_calibration_source_events
            and len(core) >= settings.minimum_core_candidates
            and len(calibration) >= settings.minimum_calibration_candidates
            and core["barrier_target"].nunique() == 2
        )
        for model_id in (MODEL_CURVE_META, MODEL_MARKET_META):
            fold: dict[str, object] = {
                "test_month": test_start_naive.strftime("%Y-%m"),
                "model_id": model_id,
                "core_rows": int(len(core)),
                "core_source_events": core_events,
                "calibration_rows": int(len(calibration)),
                "calibration_source_events": calibration_events,
                "test_rows": int(len(test)),
            }
            if not history_ok:
                fold["status"] = "sleep_insufficient_nested_history"
                folds.append(fold)
                continue
            feature_columns = market_features if model_id == MODEL_MARKET_META else full_features
            calibration_probability, test_probability = _fit_probability_ensemble(
                core,
                calibration,
                test,
                feature_columns,
                settings,
            )
            threshold, threshold_candidates = select_probability_threshold(
                calibration,
                calibration_probability,
                settings,
            )
            fold.update(
                {
                    "status": "predicted" if threshold is not None else "sleep_calibration_gate",
                    "probability_threshold": threshold,
                    "threshold_candidates": threshold_candidates,
                    "core_max_target_end_at": core["target_end_at"].max(),
                    "calibration_min_decision_at": calibration["decision_at"].min(),
                    "calibration_max_target_end_at": calibration["target_end_at"].max(),
                    "test_min_decision_at": test["decision_at"].min(),
                }
            )
            folds.append(fold)
            predicted = test.loc[:, base_columns].copy()
            predicted["model_id"] = model_id
            predicted["predicted_take_profit_probability"] = test_probability
            predicted["probability_threshold"] = threshold
            predicted["active_signal"] = bool(threshold is not None) & (
                predicted["predicted_take_profit_probability"]
                >= (threshold if threshold is not None else np.inf)
            )
            predictions.append(predicted)
    evaluation = frame.loc[
        frame["decision_at"].ge(evaluation_start) & frame["decision_at"].lt(evaluation_end)
    ].copy()
    fixed = evaluation.loc[:, base_columns].copy()
    fixed["model_id"] = MODEL_FIXED_RULE
    fixed["predicted_take_profit_probability"] = 1.0
    fixed["probability_threshold"] = 0.0
    fixed["active_signal"] = True
    predictions.append(fixed)
    prediction_frame = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return BarrierWalkForwardResult(
        predictions=prediction_frame,
        folds=pd.DataFrame(folds),
    )


PAIR_ORDER_COLUMNS: Final[tuple[str, ...]] = (
    *ORDER_COLUMNS,
    "trade_id",
    "phase",
    "retry_index",
)
PAIR_TRADE_COLUMNS: Final[tuple[str, ...]] = (
    "trade_id",
    "model_id",
    "decision_at",
    "entry_at",
    "planned_exit_at",
    "actual_exit_at",
    "barrier_exit_reason",
    "exit_retry_index",
    "corridor_side",
    "corridor_beta",
    "quantity_ri",
    "quantity_mix",
    "entry_price_ri",
    "entry_price_mix",
    "exit_price_ri",
    "exit_price_mix",
    "gross_pnl",
    "entry_cost",
    "exit_cost",
    "net_pnl",
    "equity_before_entry",
    "equity_after_exit",
)
PAIR_SKIPPED_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "model_id",
    "reason",
)


def _pair_quantity_plan(
    candidate: pd.Series,
    market_rows: pd.DataFrame,
    equity: float,
    risk: PairRiskSettings,
    execution: PairExecutionSettings,
) -> tuple[dict[str, int] | None, dict[str, int], str | None]:
    """Map the frozen stop budget to two integer legs and atomic capacity."""

    beta = abs(float(candidate["corridor_beta"]))
    stop = float(candidate["corridor_stop_barrier"])
    if not np.isfinite(beta) or beta <= 0.0 or not np.isfinite(stop) or stop <= 0.0:
        return None, {}, "invalid_pair_risk_state"
    notionals: dict[str, float] = {}
    margins: dict[str, float] = {}
    signal_volumes: dict[str, float] = {}
    factual_volumes: dict[str, float] = {}
    for asset in PAIR_ASSETS:
        market_row = market_rows.loc[asset]
        notional = float(market_row["sizing_notional"])
        margin = float(market_row["modeled_initial_margin"])
        signal_volume = float(candidate[f"{asset}_volume"])
        factual_volume = float(market_row["volume"])
        if (
            not np.isfinite(notional)
            or notional <= 0.0
            or not np.isfinite(margin)
            or margin <= 0.0
            or not np.isfinite(signal_volume)
            or signal_volume < 0.0
            or not np.isfinite(factual_volume)
            or factual_volume < 0.0
        ):
            return None, {}, "missing_pair_sizing_dependency"
        notionals[asset] = notional
        margins[asset] = margin
        signal_volumes[asset] = signal_volume
        factual_volumes[asset] = factual_volume
    base_notional = min(
        equity * risk.risk_budget_per_trade / stop,
        equity * risk.maximum_asset_weight,
        equity * risk.maximum_asset_weight / beta,
        equity * risk.maximum_pair_gross / (1.0 + beta),
    )
    desired_absolute = {
        "RI": math.floor(base_notional / notionals["RI"]),
        "MIX": math.floor(beta * base_notional / notionals["MIX"]),
    }
    if min(desired_absolute.values()) < 1:
        return None, desired_absolute, "integer_pair_below_one_contract"
    signal_caps = {
        asset: max(math.floor(execution.signal_participation * signal_volumes[asset]), 0)
        for asset in PAIR_ASSETS
    }
    factual_caps = {
        asset: max(math.floor(execution.factual_participation_cap * factual_volumes[asset]), 0)
        for asset in PAIR_ASSETS
    }
    scale = min(
        1.0,
        *(signal_caps[asset] / desired_absolute[asset] for asset in PAIR_ASSETS),
        *(factual_caps[asset] / desired_absolute[asset] for asset in PAIR_ASSETS),
    )
    absolute = {asset: math.floor(desired_absolute[asset] * scale) for asset in PAIR_ASSETS}
    if min(absolute.values()) < 1:
        return None, desired_absolute, "atomic_entry_capacity_below_one_pair"
    buffered_margin = sum(
        absolute[asset] * margins[asset] * execution.margin_buffer_multiple for asset in PAIR_ASSETS
    )
    if buffered_margin > equity:
        margin_scale = equity / buffered_margin
        absolute = {asset: math.floor(absolute[asset] * margin_scale) for asset in PAIR_ASSETS}
    if min(absolute.values()) < 1:
        return None, desired_absolute, "buffered_margin_below_one_pair"
    side = int(float(candidate["corridor_side"]))
    quantities = {"RI": side * absolute["RI"], "MIX": -side * absolute["MIX"]}
    return quantities, desired_absolute, None


def _pair_order_record(
    *,
    timestamp: pd.Timestamp,
    asset: str,
    contract_id: str,
    requested: int,
    filled: int,
    factual_volume: float,
    commission: float,
    slippage: float,
    capacity_clipped: bool,
    reason: str,
    trade_id: str,
    phase: str,
    retry_index: int,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "asset": asset,
        "contract_id": contract_id,
        "requested_quantity_delta": requested,
        "filled_quantity_delta": filled,
        "participation": abs(filled) / max(factual_volume, 1.0),
        "commission_cost": commission,
        "slippage_cost": slippage,
        "total_cost": commission + slippage,
        "capacity_clipped": capacity_clipped,
        "filled": filled != 0,
        "reason": reason,
        "trade_id": trade_id,
        "phase": phase,
        "retry_index": retry_index,
    }


def simulate_atomic_pair_portfolio(
    common_panel: pd.DataFrame,
    predictions: pd.DataFrame,
    model_id: str,
    risk_settings: PairRiskSettings | None = None,
    execution_settings: PairExecutionSettings | None = None,
) -> PairSimulationResult:
    """Execute one non-overlapping RI/MIX pair with atomic entry and exit legs."""

    risk = risk_settings or PairRiskSettings()
    execution = execution_settings or PairExecutionSettings()
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown V34 model: {model_id}")
    required_market = {"timestamp", "local_date"}
    for asset in PAIR_ASSETS:
        required_market.update(
            {
                f"{asset}_contract_id",
                f"{asset}_open",
                f"{asset}_volume",
                f"{asset}_sizing_notional",
                f"{asset}_sizing_point_value",
                f"{asset}_sizing_tick_cash_value",
                f"{asset}_conservative_fee_per_side",
                f"{asset}_modeled_initial_margin",
            }
        )
    _require_columns(common_panel, required_market, "V34 execution panel")
    required_predictions = {
        "model_id",
        "active_signal",
        "decision_at",
        "entry_at",
        "barrier_exit_at",
        "barrier_exit_reason",
        "decision_local_date",
        "corridor_side",
        "corridor_beta",
        "corridor_stop_barrier",
        *(f"{asset}_contract_id" for asset in PAIR_ASSETS),
        *(f"{asset}_volume" for asset in PAIR_ASSETS),
    }
    _require_columns(predictions, required_predictions, "V34 predictions")
    panel = common_panel.sort_values("timestamp", kind="stable").reset_index(drop=True).copy()
    panel["timestamp"] = _as_utc(panel["timestamp"], "V34 execution timestamp")
    if panel["timestamp"].duplicated().any():
        raise ValueError("V34 execution panel duplicates timestamps")
    if len(panel) and panel["timestamp"].max() >= PROTECTED_FROM:
        raise ValueError("V34 execution panel touches protected 2026")
    market_by_time: dict[pd.Timestamp, pd.DataFrame] = {}
    for timestamp, raw in panel.groupby("timestamp", sort=True):
        rows: list[dict[str, object]] = []
        source = raw.iloc[0]
        for asset in PAIR_ASSETS:
            rows.append(
                {
                    "asset": asset,
                    "contract_id": str(source[f"{asset}_contract_id"]),
                    "open": source[f"{asset}_open"],
                    "volume": source[f"{asset}_volume"],
                    "sizing_notional": source[f"{asset}_sizing_notional"],
                    "sizing_point_value": source[f"{asset}_sizing_point_value"],
                    "sizing_tick_cash_value": source[f"{asset}_sizing_tick_cash_value"],
                    "conservative_fee_per_side": source[f"{asset}_conservative_fee_per_side"],
                    "modeled_initial_margin": source[f"{asset}_modeled_initial_margin"],
                    "local_date": source["local_date"],
                }
            )
        market_by_time[pd.Timestamp(timestamp)] = pd.DataFrame(rows).set_index("asset")
    selected = predictions.loc[
        predictions["model_id"].eq(model_id)
        & predictions["active_signal"].astype("boolean").fillna(False)
    ].copy()
    for column in ("decision_at", "entry_at", "barrier_exit_at"):
        selected[column] = _as_utc(selected[column], f"V34 predictions.{column}")
    if len(selected) and selected[["entry_at", "barrier_exit_at"]].max().max() >= PROTECTED_FROM:
        raise ValueError("V34 predictions touch protected 2026")
    selected = selected.sort_values(["entry_at", "decision_at"], kind="stable")
    candidates_by_time = {
        timestamp: group for timestamp, group in selected.groupby("entry_at", sort=True)
    }

    cash = float(execution.initial_cash)
    positions = {asset: 0 for asset in PAIR_ASSETS}
    point_values = {asset: float("nan") for asset in PAIR_ASSETS}
    last_opens = {asset: float("nan") for asset in PAIR_ASSETS}
    contracts: dict[str, str | None] = {asset: None for asset in PAIR_ASSETS}
    daily_counts: dict[pd.Timestamp, int] = {}
    open_trade: dict[str, object] | None = None
    previous_timestamp: pd.Timestamp | None = None
    ledger_records: list[dict[str, object]] = []
    order_records: list[dict[str, object]] = []
    trade_records: list[dict[str, object]] = []
    skipped_records: list[dict[str, object]] = []
    unresolved_records: list[dict[str, object]] = []
    trade_serial = 0

    def unresolved(timestamp: pd.Timestamp, asset: str, reason: str) -> None:
        unresolved_records.append({"timestamp": timestamp, "asset": asset, "reason": reason})

    for timestamp in sorted(market_by_time):
        rows = market_by_time[timestamp]
        if open_trade is not None and (
            previous_timestamp is None or timestamp - previous_timestamp != TEN_MINUTES
        ):
            unresolved(timestamp, "PAIR", "missing_exact_mark_successor")
            break
        bar_pnl = 0.0
        bar_cost = 0.0
        if open_trade is not None:
            for asset in PAIR_ASSETS:
                row = rows.loc[asset]
                current_open = float(row["open"])
                if str(row["contract_id"]) != contracts[asset]:
                    unresolved(timestamp, asset, "contract_changed_while_pair_open")
                    break
                if not np.isfinite(current_open) or current_open <= 0.0:
                    unresolved(timestamp, asset, "missing_factual_open_mark")
                    break
                asset_pnl = (
                    positions[asset] * (current_open - last_opens[asset]) * point_values[asset]
                )
                bar_pnl += asset_pnl
                last_opens[asset] = current_open
            if unresolved_records:
                break
            cash += bar_pnl
            open_trade["gross_pnl"] = float(open_trade["gross_pnl"]) + bar_pnl

        stop_after_record = False
        if open_trade is not None and timestamp >= pd.Timestamp(open_trade["planned_exit_at"]):
            elapsed = timestamp - pd.Timestamp(open_trade["planned_exit_at"])
            exact_retry = elapsed % TEN_MINUTES == pd.Timedelta(0)
            retry_index = int(elapsed / TEN_MINUTES) if exact_retry else -1
            if not exact_retry or retry_index > execution.maximum_exit_retry_bars:
                unresolved(timestamp, "PAIR", "atomic_exit_retry_schedule_broken")
                stop_after_record = True
            else:
                capacities: dict[str, int] = {}
                dependencies_ok = True
                for asset in PAIR_ASSETS:
                    volume = float(rows.loc[asset, "volume"])
                    if not np.isfinite(volume) or volume < 0.0:
                        unresolved(timestamp, asset, "missing_factual_exit_volume")
                        dependencies_ok = False
                        break
                    capacities[asset] = max(
                        math.floor(execution.factual_participation_cap * volume), 0
                    )
                enough = dependencies_ok and all(
                    capacities[asset] >= abs(positions[asset]) for asset in PAIR_ASSETS
                )
                if enough:
                    exit_cost = 0.0
                    exit_prices: dict[str, float] = {}
                    cost_dependencies: dict[str, tuple[float, float]] = {}
                    for asset in PAIR_ASSETS:
                        row = rows.loc[asset]
                        tick_cash = float(row["sizing_tick_cash_value"])
                        fee = float(row["conservative_fee_per_side"])
                        if (
                            not np.isfinite(tick_cash)
                            or tick_cash <= 0.0
                            or not np.isfinite(fee)
                            or fee < 0.0
                        ):
                            unresolved(timestamp, asset, "missing_exit_cost_dependency")
                            dependencies_ok = False
                            break
                        cost_dependencies[asset] = (tick_cash, fee)
                    if not dependencies_ok:
                        stop_after_record = True
                    else:
                        for asset in PAIR_ASSETS:
                            row = rows.loc[asset]
                            delta = -positions[asset]
                            tick_cash, fee = cost_dependencies[asset]
                            commission = abs(delta) * execution.fee_multiplier * fee
                            slippage = abs(delta) * execution.slippage_ticks * tick_cash
                            exit_cost += commission + slippage
                            exit_prices[asset] = float(row["open"])
                            order_records.append(
                                _pair_order_record(
                                    timestamp=timestamp,
                                    asset=asset,
                                    contract_id=str(row["contract_id"]),
                                    requested=delta,
                                    filled=delta,
                                    factual_volume=float(row["volume"]),
                                    commission=commission,
                                    slippage=slippage,
                                    capacity_clipped=False,
                                    reason="filled",
                                    trade_id=str(open_trade["trade_id"]),
                                    phase="atomic_exit",
                                    retry_index=retry_index,
                                )
                            )
                    if dependencies_ok:
                        cash -= exit_cost
                        bar_cost += exit_cost
                        open_trade["actual_exit_at"] = timestamp
                        open_trade["exit_retry_index"] = retry_index
                        open_trade["exit_price_ri"] = exit_prices["RI"]
                        open_trade["exit_price_mix"] = exit_prices["MIX"]
                        open_trade["exit_cost"] = exit_cost
                        open_trade["net_pnl"] = (
                            float(open_trade["gross_pnl"])
                            - float(open_trade["entry_cost"])
                            - exit_cost
                        )
                        open_trade["equity_after_exit"] = cash
                        trade_records.append(open_trade.copy())
                        for asset in PAIR_ASSETS:
                            positions[asset] = 0
                            point_values[asset] = float("nan")
                            last_opens[asset] = float("nan")
                            contracts[asset] = None
                        open_trade = None
                else:
                    for asset in PAIR_ASSETS:
                        row = rows.loc[asset]
                        requested = -positions[asset]
                        order_records.append(
                            _pair_order_record(
                                timestamp=timestamp,
                                asset=asset,
                                contract_id=str(row["contract_id"]),
                                requested=requested,
                                filled=0,
                                factual_volume=float(row["volume"]),
                                commission=0.0,
                                slippage=0.0,
                                capacity_clipped=True,
                                reason="atomic_exit_capacity_retry",
                                trade_id=str(open_trade["trade_id"]),
                                phase="atomic_exit",
                                retry_index=retry_index,
                            )
                        )
                    if retry_index == execution.maximum_exit_retry_bars:
                        unresolved(timestamp, "PAIR", "atomic_exit_retry_exhausted")
                        stop_after_record = True

        candidate_rows = candidates_by_time.get(timestamp)
        if candidate_rows is not None:
            for _, candidate in candidate_rows.iterrows():
                reason: str | None = None
                local_date = pd.Timestamp(candidate["decision_local_date"])
                if open_trade is not None:
                    reason = "existing_pair_open"
                elif daily_counts.get(local_date, 0) >= execution.maximum_trades_per_day:
                    reason = "daily_trade_cap"
                elif any(
                    str(candidate[f"{asset}_contract_id"]) != str(rows.loc[asset, "contract_id"])
                    for asset in PAIR_ASSETS
                ):
                    reason = "entry_contract_mismatch"
                quantities: dict[str, int] | None = None
                desired: dict[str, int] = {}
                if reason is None:
                    quantities, desired, reason = _pair_quantity_plan(
                        candidate,
                        rows,
                        cash,
                        risk,
                        execution,
                    )
                if reason is not None or quantities is None:
                    skipped_records.append(
                        {"timestamp": timestamp, "model_id": model_id, "reason": reason}
                    )
                    continue
                trade_serial += 1
                trade_id = f"{model_id}:{trade_serial:06d}"
                entry_cost = 0.0
                dependency_error: str | None = None
                entry_orders: list[dict[str, object]] = []
                for asset in PAIR_ASSETS:
                    row = rows.loc[asset]
                    opened = float(row["open"])
                    point_value = float(row["sizing_point_value"])
                    tick_cash = float(row["sizing_tick_cash_value"])
                    fee = float(row["conservative_fee_per_side"])
                    if (
                        not np.isfinite(opened)
                        or opened <= 0.0
                        or not np.isfinite(point_value)
                        or point_value <= 0.0
                        or not np.isfinite(tick_cash)
                        or tick_cash <= 0.0
                        or not np.isfinite(fee)
                        or fee < 0.0
                    ):
                        dependency_error = "missing_entry_price_or_cost_dependency"
                        break
                    quantity = quantities[asset]
                    commission = abs(quantity) * execution.fee_multiplier * fee
                    slippage = abs(quantity) * execution.slippage_ticks * tick_cash
                    entry_cost += commission + slippage
                    factual_volume = float(row["volume"])
                    entry_orders.append(
                        _pair_order_record(
                            timestamp=timestamp,
                            asset=asset,
                            contract_id=str(row["contract_id"]),
                            requested=int(np.sign(quantity) * desired[asset]),
                            filled=quantity,
                            factual_volume=factual_volume,
                            commission=commission,
                            slippage=slippage,
                            capacity_clipped=abs(quantity) < desired[asset],
                            reason="filled",
                            trade_id=trade_id,
                            phase="atomic_entry",
                            retry_index=0,
                        )
                    )
                if dependency_error is not None:
                    skipped_records.append(
                        {
                            "timestamp": timestamp,
                            "model_id": model_id,
                            "reason": dependency_error,
                        }
                    )
                    continue
                equity_before_entry = cash
                cash -= entry_cost
                bar_cost += entry_cost
                order_records.extend(entry_orders)
                for asset in PAIR_ASSETS:
                    row = rows.loc[asset]
                    positions[asset] = quantities[asset]
                    point_values[asset] = float(row["sizing_point_value"])
                    last_opens[asset] = float(row["open"])
                    contracts[asset] = str(row["contract_id"])
                daily_counts[local_date] = daily_counts.get(local_date, 0) + 1
                open_trade = {
                    "trade_id": trade_id,
                    "model_id": model_id,
                    "decision_at": pd.Timestamp(candidate["decision_at"]),
                    "entry_at": timestamp,
                    "planned_exit_at": pd.Timestamp(candidate["barrier_exit_at"]),
                    "actual_exit_at": pd.NaT,
                    "barrier_exit_reason": str(candidate["barrier_exit_reason"]),
                    "exit_retry_index": -1,
                    "corridor_side": float(candidate["corridor_side"]),
                    "corridor_beta": float(candidate["corridor_beta"]),
                    "quantity_ri": quantities["RI"],
                    "quantity_mix": quantities["MIX"],
                    "entry_price_ri": float(rows.loc["RI", "open"]),
                    "entry_price_mix": float(rows.loc["MIX", "open"]),
                    "exit_price_ri": float("nan"),
                    "exit_price_mix": float("nan"),
                    "gross_pnl": 0.0,
                    "entry_cost": entry_cost,
                    "exit_cost": float("nan"),
                    "net_pnl": float("nan"),
                    "equity_before_entry": equity_before_entry,
                    "equity_after_exit": float("nan"),
                }

        gross = sum(
            abs(positions[asset]) * float(rows.loc[asset, "sizing_notional"])
            for asset in PAIR_ASSETS
        )
        buffered_margin = sum(
            abs(positions[asset])
            * float(rows.loc[asset, "modeled_initial_margin"])
            * execution.margin_buffer_multiple
            for asset in PAIR_ASSETS
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
                **{f"position_{asset.lower()}": positions.get(asset, 0) for asset in ASSETS},
            }
        )
        previous_timestamp = timestamp
        if stop_after_record:
            break
    if not unresolved_records and open_trade is not None:
        unresolved(
            previous_timestamp or pd.Timestamp.min.tz_localize("UTC"),
            "PAIR",
            "terminal_pair_not_flat",
        )
    ledger = pd.DataFrame(ledger_records, columns=LEDGER_COLUMNS)
    orders = pd.DataFrame(order_records, columns=PAIR_ORDER_COLUMNS)
    trades = pd.DataFrame(trade_records, columns=PAIR_TRADE_COLUMNS)
    skipped = pd.DataFrame(skipped_records, columns=PAIR_SKIPPED_COLUMNS)
    unresolved_frame = pd.DataFrame(
        unresolved_records,
        columns=("timestamp", "asset", "reason"),
    )
    metrics = _ledger_metrics(ledger, orders, unresolved_frame, execution)
    metrics.update(
        {
            "completed_pair_trades": int(len(trades)),
            "winning_pair_trades": int(trades["net_pnl"].gt(0.0).sum()) if len(trades) else 0,
            "take_profit_trades": int(trades["barrier_exit_reason"].eq("take_profit").sum())
            if len(trades)
            else 0,
            "distant_stop_trades": int(trades["barrier_exit_reason"].eq("distant_stop").sum())
            if len(trades)
            else 0,
            "time_exit_trades": int(trades["barrier_exit_reason"].eq("time_exit").sum())
            if len(trades)
            else 0,
            "exit_retry_trades": int(trades["exit_retry_index"].gt(0).sum()) if len(trades) else 0,
            "skipped_entries": int(len(skipped)),
        }
    )
    return PairSimulationResult(
        ledger=ledger,
        orders=orders,
        trades=trades,
        skipped_entries=skipped,
        unresolved=unresolved_frame,
        metrics=metrics,
        execution_complete=unresolved_frame.empty,
    )


__all__ = [
    "MODEL_CURVE_META",
    "MODEL_FIXED_RULE",
    "MODEL_IDS",
    "MODEL_MARKET_META",
    "BarrierWalkForwardResult",
    "CorridorSettings",
    "MetaModelSettings",
    "PairExecutionSettings",
    "PairRiskSettings",
    "PairSimulationResult",
    "build_corridor_candidates",
    "corridor_feature_columns",
    "run_barrier_walk_forward",
    "select_probability_threshold",
    "simulate_atomic_pair_portfolio",
]
