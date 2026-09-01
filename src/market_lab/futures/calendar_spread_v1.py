"""Sealed development experiment for equal-quantity MOEX calendar spreads."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import warnings
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from market_lab.futures import moex_calendar_spread_source as source
from market_lab.futures.execution_dataset import build_portfolio_market
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = source.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/calendar_spread_v1.yaml"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
STRATEGY_IDS: Final[tuple[str, ...]] = (
    "volatile_corridor_far_stop",
    "all_regime_corridor_20",
    "fast_corridor_10",
    "slow_corridor_40",
    "volatile_breakout_20",
    "momentum_5",
    "curve_convergence_to_zero",
    "cross_asset_residual_fade",
    "cross_sectional_extremes",
    "mlp_cross_asset_5d",
)
SCENARIOS: Final[dict[str, tuple[int, float]]] = {
    "primary": (1, 1.0),
    "doubled": (2, 2.0),
    "stress": (4, 2.0),
}
ACTIVE_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "available_at",
    "spread_id",
    "logical_asset",
    "near_contract_id",
    "far_contract_id",
    "near_expiration",
    "far_expiration",
    "last",
    "bid",
    "ask",
    "amount",
    "volume",
    "num_trades",
    "days_to_near_expiration",
    "calendar_tenor_days",
    "quote_width",
    "quote_midpoint",
    "strict_positive_quote_width",
    "zero_locked_quote",
    "last_outside_range",
    "both_sizing_usable",
    "spec_observations_strictly_prior",
)
OBSERVATION_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "logical_asset",
    "canonical_contract_id",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "volume",
)
SPEC_COLUMNS: Final[tuple[str, ...]] = (
    "session_date",
    "asset_symbol",
    "contract_id",
    "sizing_point_value",
    "sizing_observed_session_date",
    "sizing_lag_sessions",
    "sizing_usable",
    "realized_accounting_point_value",
    "realized_available_after_session",
    "tick_size",
    "conservative_fee_per_side",
    "modeled_initial_margin",
    "spec_proxy_version",
    "approximate",
    "research_only",
    "historical_exchange_exact",
    "broker_exact",
)
MLP_FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    "z10",
    "z20",
    "z40",
    "momentum5",
    "volatility_ratio",
    "quote_width_ratio",
    "log_num_trades",
    "log_amount",
    "days_to_near_ratio",
    "cross_z20_SI",
    "cross_z20_RI",
    "cross_z20_BR",
    "cross_z20_MIX",
    "cross_momentum5_SI",
    "cross_momentum5_RI",
    "cross_momentum5_BR",
    "cross_momentum5_MIX",
    "asset_SI",
    "asset_RI",
    "asset_BR",
    "asset_MIX",
)


@dataclass(frozen=True, slots=True)
class EconomicProtocol:
    """Verified protocol identity without any market-value read."""

    payload: dict[str, Any]
    config_sha256: str
    output_directory: Path
    input_paths: dict[str, Path]


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    """Byte and temporal input evidence."""

    checks: dict[str, bool]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MarketPoint:
    """One factual outright-contract session used by the pair ledger."""

    session_date: pd.Timestamp
    asset: str
    contract_id: str
    open: float
    settle: float
    lagged_volume: float
    sizing_point_value: float
    accounting_point_value: float
    tick_size: float
    fee_per_contract: float
    initial_margin: float


@dataclass(slots=True)
class OpenPair:
    """One filled equal-quantity calendar-spread position."""

    plan_id: str
    asset: str
    spread_id: str
    direction: int
    quantity: int
    near_contract_id: str
    far_contract_id: str
    entry_decision_date: pd.Timestamp
    exit_decision_date: pd.Timestamp
    entry_execution_date: pd.Timestamp
    previous_near_settle: float
    previous_far_settle: float
    entry_pair_notional: float
    current_pair_notional: float
    current_buffered_margin: float
    gross_pnl: float
    costs: float
    retry_days: int
    entry_reason: str
    exit_reason: str


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Daily cash ledger, trade audit and execution diagnostics."""

    daily: pd.DataFrame
    trades: pd.DataFrame
    diagnostics: dict[str, Any]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar spread V1 {label} must be a mapping")
    return value


def _safe_project_path(value: object, required_root: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe calendar spread V1 path: {value}")
    if relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"calendar spread V1 path must start with {required_root}")
    return PROJECT_ROOT / relative


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"calendar spread V1 sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = CONFIG_PATH) -> EconomicProtocol:
    """Validate the frozen contract without opening market-value tables."""
    path = config_path.resolve()
    config_sha = source.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("calendar spread V1 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar spread V1 protocol must be a YAML object")
    dates = _mapping(payload.get("dates"), "dates")
    hypothesis = _mapping(payload.get("hypothesis"), "hypothesis")
    portfolio = _mapping(payload.get("portfolio"), "portfolio")
    execution = _mapping(payload.get("execution"), "execution")
    model = _mapping(payload.get("neural_model"), "neural model")
    output = _mapping(payload.get("output"), "output")
    strategy_rows = payload.get("strategies")
    if not isinstance(strategy_rows, list):
        raise ValueError("calendar spread V1 strategies must be a list")
    strategy_ids = tuple(str(_mapping(row, "strategy")["id"]) for row in strategy_rows)
    scenarios = {
        str(name): (
            int(_mapping(values, "scenario")["slippage_ticks_per_leg"]),
            float(_mapping(values, "scenario")["conservative_fee_multiplier"]),
        )
        for name, values in _mapping(execution.get("scenarios"), "scenarios").items()
    }
    if (
        payload.get("protocol_id") != "calendar_spread_economic_v1"
        or payload.get("status")
        != "predeclared_before_first_spread_change_return_target_signal_or_pnl"
        or payload.get("sealed_before_outcomes") is not True
        or payload.get("live_trading_allowed") is not False
        or hypothesis.get("primary_strategy") != STRATEGY_IDS[0]
        or int(hypothesis.get("family_size", -1)) != len(STRATEGY_IDS)
        or strategy_ids != STRATEGY_IDS
        or str(dates.get("protected_from")) != "2026-01-01"
        or str(dates.get("evaluation_start")) != "2024-01-01"
        or str(dates.get("evaluation_end")) != "2025-12-31"
        or scenarios != SCENARIOS
        or portfolio.get("equal_contract_quantity_per_spread_leg") is not True
        or float(portfolio.get("maximum_total_gross_notional_multiple", 0.0)) != 1.60
        or float(execution.get("maximum_participation_each_leg", 0.0)) != 0.01
        or model.get("hyperparameter_search") is not False
        or int(model.get("random_state", -1)) != 1729
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar spread V1 protocol invariants drifted")
    input_paths = {
        str(name): _safe_project_path(_mapping(declaration, f"input {name}")["path"], "data")
        for name, declaration in _mapping(payload.get("inputs"), "inputs").items()
    }
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        dependency = PROJECT_ROOT / str(relative)
        if source.sha256_file(dependency) != str(expected).lower():
            raise ValueError(f"calendar spread V1 dependency drift: {relative}")
    return EconomicProtocol(
        payload=payload,
        config_sha256=config_sha,
        output_directory=_safe_project_path(output["directory"], "runs"),
        input_paths=input_paths,
    )


def verify_inputs(protocol: EconomicProtocol) -> VerifiedInputs:
    """Verify byte identities and timestamp columns before loading any price column."""
    declarations = _mapping(protocol.payload["inputs"], "inputs")
    checks: dict[str, bool] = {}
    metadata: dict[str, Any] = {}
    for name, path in protocol.input_paths.items():
        declaration = _mapping(declarations[name], f"input {name}")
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and source.sha256_file(path) == str(declaration["sha256"])
        item: dict[str, Any] = {
            "path": str(declaration["path"]),
            "bytes": path.stat().st_size if exists else None,
            "sha256": source.sha256_file(path) if exists else None,
        }
        if path.suffix == ".parquet" and exists:
            parquet = pq.ParquetFile(path)
            item["rows"] = parquet.metadata.num_rows
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
        metadata[name] = item
    if not all(checks.values()):
        raise ValueError(f"calendar spread V1 input identity failed: {checks}")
    derived = json.loads(protocol.input_paths["derived_manifest"].read_text(encoding="utf-8-sig"))
    checks["derived_source_only"] = derived.get("source_only") is True
    checks["derived_outcomes_absent"] = (
        derived.get("contains_returns_targets_labels_signals_equity_or_pnl") is False
    )
    checks["derived_live_forbidden"] = derived.get("live_trading_allowed") is False
    checks["derived_protocol_exact"] = (
        derived.get("protocol_sha256")
        == "657fd42b472797028f5b0194c7b159ac1538ddab5caea8f9c416f0a403e34cd0"
    )
    checks["derived_active_exact"] = (
        derived.get("artifacts", {}).get("active", {}).get("sha256")
        == declarations["active_spreads"]["sha256"]
    )
    date_specs = {
        "active_spreads": "trade_date",
        "contract_observations": "trade_date",
        "spec_proxy": "session_date",
    }
    for name, column in date_specs.items():
        values = pd.to_datetime(
            pd.read_parquet(protocol.input_paths[name], columns=[column])[column],
            errors="raise",
        ).dt.normalize()
        declaration = _mapping(declarations[name], name)
        checks[f"{name}_date_min"] = values.min() == pd.Timestamp(declaration["minimum_timestamp"])
        checks[f"{name}_date_max"] = values.max() == pd.Timestamp(declaration["maximum_timestamp"])
        checks[f"{name}_protected"] = bool(values.lt(PROTECTED_FROM).all())
        metadata[name]["minimum_timestamp"] = values.min().date().isoformat()
        metadata[name]["maximum_timestamp"] = values.max().date().isoformat()
    if not all(checks.values()):
        raise ValueError(f"calendar spread V1 temporal/source audit failed: {checks}")
    return VerifiedInputs(checks=checks, metadata=metadata)


def _rolling_prior(values: pd.Series, groups: pd.Series, window: int, operation: str) -> pd.Series:
    shifted = values.groupby(groups, sort=False).shift(1)
    grouped = shifted.groupby(groups, sort=False)
    if operation == "mean":
        return grouped.transform(lambda item: item.rolling(window, min_periods=window).mean())
    if operation == "std":
        return grouped.transform(lambda item: item.rolling(window, min_periods=window).std(ddof=1))
    if operation == "median":
        return grouped.transform(lambda item: item.rolling(window, min_periods=window).median())
    raise ValueError(f"unknown rolling operation: {operation}")


def build_feature_frame(active: pd.DataFrame) -> pd.DataFrame:
    """Construct same-spread prior-window and exact-date cross-asset features."""
    missing = set(ACTIVE_COLUMNS) - set(active.columns)
    if missing:
        raise ValueError(f"calendar spread active frame lacks: {sorted(missing)}")
    frame = active.loc[:, ACTIVE_COLUMNS].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    for column in ("near_expiration", "far_expiration"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame["trade_date"].ge(PROTECTED_FROM).any():
        raise ValueError("calendar spread feature frame touches protected data")
    local_available_date = (
        frame["available_at"].dt.tz_convert("Europe/Moscow").dt.tz_localize(None).dt.normalize()
    )
    if local_available_date.le(frame["trade_date"]).any():
        raise ValueError("calendar spread archive availability is not after trade date")
    if frame.duplicated(["trade_date", "logical_asset"]).any():
        raise ValueError("calendar spread active identity is duplicated")
    if set(frame["logical_asset"].astype(str)) != set(ASSETS):
        raise ValueError("calendar spread active universe drifted")
    numeric_columns = (
        "last",
        "bid",
        "ask",
        "amount",
        "volume",
        "num_trades",
        "days_to_near_expiration",
        "calendar_tenor_days",
        "quote_width",
        "quote_midpoint",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    finite_midpoint = frame["quote_midpoint"].notna() & np.isfinite(frame["quote_midpoint"])
    if not finite_midpoint.all():
        raise ValueError("calendar spread active midpoint is incomplete")
    frame = frame.sort_values(["logical_asset", "trade_date"], kind="mergesort", ignore_index=True)
    groups = frame["spread_id"].astype(str)
    midpoint = frame["quote_midpoint"].astype(float)
    for window in (10, 20, 40):
        mean = _rolling_prior(midpoint, groups, window, "mean")
        std = _rolling_prior(midpoint, groups, window, "std").where(lambda x: x > 1e-12)
        frame[f"mean{window}"] = mean
        frame[f"std{window}"] = std
        frame[f"z{window}"] = (midpoint - mean) / std
    change = midpoint.groupby(groups, sort=False).diff()
    frame["change1"] = change
    frame["change5"] = midpoint.groupby(groups, sort=False).diff(5)
    change_std = _rolling_prior(change, groups, 20, "std").where(lambda x: x > 1e-12)
    frame["change_std20"] = change_std
    frame["momentum5"] = frame["change5"] / (change_std * math.sqrt(5.0))
    vol10 = change.groupby(groups, sort=False).transform(
        lambda item: item.rolling(10, min_periods=10).std(ddof=1)
    )
    prior_vol_median = _rolling_prior(vol10, groups, 20, "median")
    frame["volatility10"] = vol10
    frame["volatility_prior_median20"] = prior_vol_median
    frame["volatility_ratio"] = vol10 / prior_vol_median.where(prior_vol_median > 1e-12)
    frame["high_volatility"] = vol10.notna() & prior_vol_median.notna() & vol10.ge(prior_vol_median)
    days = frame["days_to_near_expiration"].clip(lower=1.0)
    frame["zero_convergence_score"] = midpoint / (change_std * np.sqrt(days))
    frame["quote_width_ratio"] = frame["quote_width"] / change_std
    frame["log_num_trades"] = np.log1p(frame["num_trades"].clip(lower=0.0))
    frame["log_amount"] = np.log1p(frame["amount"].clip(lower=0.0))
    frame["days_to_near_ratio"] = frame["days_to_near_expiration"] / frame[
        "calendar_tenor_days"
    ].where(frame["calendar_tenor_days"] > 0.0)
    for value_column, prefix in (("z20", "cross_z20"), ("momentum5", "cross_momentum5")):
        pivot = frame.pivot(
            index="trade_date", columns="logical_asset", values=value_column
        ).reindex(columns=ASSETS)
        for asset in ASSETS:
            frame[f"{prefix}_{asset}"] = frame["trade_date"].map(pivot[asset])
    for asset in ASSETS:
        frame[f"asset_{asset}"] = frame["logical_asset"].eq(asset).astype(float)
    z_columns = [f"cross_z20_{asset}" for asset in ASSETS]
    cross_z = frame[z_columns]
    frame["cross_asset_count"] = cross_z.notna().sum(axis=1)
    residuals: list[float] = []
    extrema: list[bool] = []
    for row in frame.itertuples(index=False):
        asset = str(row.logical_asset)
        own = float(row.z20) if pd.notna(row.z20) else math.nan
        values = {item: getattr(row, f"cross_z20_{item}") for item in ASSETS}
        other = [float(value) for key, value in values.items() if key != asset and pd.notna(value)]
        residuals.append(
            own - float(np.median(other)) if math.isfinite(own) and len(other) >= 2 else math.nan
        )
        finite_values = [float(value) for value in values.values() if pd.notna(value)]
        is_extreme = False
        if math.isfinite(own) and len(finite_values) >= 3:
            spread = max(finite_values) - min(finite_values)
            is_extreme = spread >= 2.5 and (
                math.isclose(own, max(finite_values), abs_tol=1e-12)
                or math.isclose(own, min(finite_values), abs_tol=1e-12)
            )
        extrema.append(is_extreme)
    frame["cross_asset_residual"] = residuals
    frame["cross_sectional_extreme"] = extrema
    future_midpoint = midpoint.groupby(groups, sort=False).shift(-5)
    future_date = frame["trade_date"].groupby(groups, sort=False).shift(-5)
    frame["mlp_target"] = (future_midpoint - midpoint) / change_std
    frame["mlp_target_end_date"] = future_date
    return frame


def build_mlp_predictions(
    features: pd.DataFrame, model_settings: Mapping[str, Any]
) -> pd.DataFrame:
    """Fit one expanding model per month with strictly completed five-row labels."""
    frame = features.copy()
    frame["mlp_prediction"] = np.nan
    frame["mlp_train_samples"] = 0
    frame["mlp_train_max_target_date"] = pd.NaT
    frame["mlp_refit_date"] = pd.NaT
    target_clip = tuple(float(value) for value in model_settings["target_clip"])
    minimum = int(model_settings["minimum_training_samples"])
    periods = frame["trade_date"].dt.to_period("M")
    for period in sorted(periods.unique()):
        prediction_index = frame.index[periods.eq(period)]
        if prediction_index.empty:
            continue
        refit_date = pd.Timestamp(frame.loc[prediction_index, "trade_date"].min())
        target_end = pd.to_datetime(frame["mlp_target_end_date"], errors="coerce")
        training = (
            frame["mlp_target"].notna()
            & np.isfinite(frame["mlp_target"])
            & target_end.notna()
            & target_end.lt(refit_date)
        )
        train_index = frame.index[training]
        if len(train_index) < minimum:
            continue
        x_train = frame.loc[train_index, MLP_FEATURE_COLUMNS].astype(float)
        y_train = frame.loc[train_index, "mlp_target"].astype(float).clip(*target_clip)
        x_prediction = frame.loc[prediction_index, MLP_FEATURE_COLUMNS].astype(float)
        pipeline = Pipeline(
            steps=(
                (
                    "imputer",
                    SimpleImputer(strategy="median", add_indicator=True),
                ),
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPRegressor(
                        hidden_layer_sizes=tuple(
                            int(value) for value in model_settings["hidden_layer_sizes"]
                        ),
                        activation=str(model_settings["activation"]),
                        solver=str(model_settings["solver"]),
                        alpha=float(model_settings["alpha"]),
                        learning_rate_init=float(model_settings["learning_rate_init"]),
                        max_iter=int(model_settings["maximum_iterations"]),
                        random_state=int(model_settings["random_state"]),
                        shuffle=bool(model_settings["shuffle"]),
                        early_stopping=bool(model_settings["early_stopping"]),
                    ),
                ),
            )
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            pipeline.fit(x_train, y_train)
        prediction = np.clip(pipeline.predict(x_prediction), *target_clip)
        frame.loc[prediction_index, "mlp_prediction"] = prediction
        frame.loc[prediction_index, "mlp_train_samples"] = len(train_index)
        frame.loc[prediction_index, "mlp_train_max_target_date"] = target_end.loc[train_index].max()
        frame.loc[prediction_index, "mlp_refit_date"] = refit_date
    available = frame["mlp_prediction"].notna()
    if (
        frame.loc[available, "mlp_train_max_target_date"]
        .ge(frame.loc[available, "mlp_refit_date"])
        .any()
    ):
        raise ValueError("calendar spread MLP target leakage detected")
    return frame


def _strategy_mapping(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = payload["strategies"]
    return {str(row["id"]): _mapping(row, "strategy") for row in rows}


def build_trade_plans(features: pd.DataFrame, protocol_payload: Mapping[str, Any]) -> pd.DataFrame:
    """Create outcome-independent entry/exit decision intervals for all ten rules."""
    definitions = _strategy_mapping(protocol_payload)
    rules = _mapping(protocol_payload["features"], "features")
    minimum_days = float(rules["minimum_days_to_near_expiration_for_entry"])
    forced_exit_days = float(rules["forced_exit_days_to_near_expiration"])
    width_limit = float(rules["quote_width_maximum_change_sigma"])
    records: list[dict[str, Any]] = []
    for strategy_id in STRATEGY_IDS:
        definition = definitions[strategy_id]
        score_column = str(definition["score"])
        scale_column = str(definition["scale"])
        follow = str(definition["direction"]) == "follow"
        for asset in ASSETS:
            part = features.loc[features["logical_asset"].eq(asset)].sort_values(
                "trade_date", kind="mergesort"
            )
            terminal_date = pd.Timestamp(part["trade_date"].max())
            holding: dict[str, Any] | None = None
            last_record: dict[str, Any] | None = None
            for row in part.to_dict(orient="records"):
                last_record = row
                score = float(row[score_column]) if pd.notna(row[score_column]) else math.nan
                scale = float(row[scale_column]) if pd.notna(row[scale_column]) else math.nan
                midpoint = float(row["quote_midpoint"])
                exited = False
                if holding is not None:
                    holding["observations"] += 1
                    reason: str | None = None
                    if str(row["spread_id"]) != holding["spread_id"]:
                        reason = "active_spread_changed"
                    elif float(row["days_to_near_expiration"]) <= forced_exit_days:
                        reason = "expiry_buffer"
                    elif holding["observations"] >= int(definition["maximum_holding_observations"]):
                        reason = "maximum_holding"
                    elif math.isfinite(score):
                        if follow:
                            if holding["direction"] * score <= float(definition["exit_abs"]):
                                reason = "signal_faded"
                            adverse = (
                                holding["direction"]
                                * (midpoint - holding["entry_midpoint"])
                                / holding["entry_scale"]
                            )
                            if adverse <= -float(definition["stop_abs"]):
                                reason = "distant_adverse_stop"
                        else:
                            if abs(score) <= float(definition["exit_abs"]):
                                reason = "corridor_take_profit"
                            elif abs(score) >= float(definition["stop_abs"]):
                                reason = "distant_score_stop"
                    if reason is not None:
                        records.append(
                            {
                                **holding["entry"],
                                "exit_decision_date": row["trade_date"],
                                "exit_decision_available_at": row["available_at"],
                                "exit_score": score,
                                "exit_midpoint": midpoint,
                                "exit_reason": reason,
                                "holding_observations": holding["observations"],
                            }
                        )
                        holding = None
                        exited = True
                if holding is not None or exited:
                    continue
                quality = (
                    math.isfinite(score)
                    and math.isfinite(scale)
                    and scale > 1e-12
                    and bool(row["strict_positive_quote_width"])
                    and float(row["quote_width"]) <= width_limit * scale
                    and float(row["days_to_near_expiration"]) >= minimum_days
                    and pd.Timestamp(row["trade_date"]) < terminal_date
                    and abs(score) >= float(definition["entry_abs"])
                    and (
                        not bool(definition["high_volatility_only"]) or bool(row["high_volatility"])
                    )
                    and (
                        not bool(definition["cross_sectional_extreme_only"])
                        or bool(row["cross_sectional_extreme"])
                    )
                )
                if not quality:
                    continue
                direction = int(math.copysign(1, score))
                if not follow:
                    direction *= -1
                plan_id = f"{strategy_id}:{asset}:{len(records):06d}"
                entry = {
                    "plan_id": plan_id,
                    "strategy_id": strategy_id,
                    "asset": asset,
                    "spread_id": str(row["spread_id"]),
                    "direction": direction,
                    "near_contract_id": str(row["near_contract_id"]),
                    "far_contract_id": str(row["far_contract_id"]),
                    "entry_decision_date": row["trade_date"],
                    "entry_decision_available_at": row["available_at"],
                    "entry_score": score,
                    "entry_midpoint": midpoint,
                    "entry_scale": scale,
                    "entry_reason": "predeclared_signal_threshold",
                }
                holding = {
                    "spread_id": str(row["spread_id"]),
                    "direction": direction,
                    "entry_midpoint": midpoint,
                    "entry_scale": scale,
                    "entry": entry,
                    "observations": 0,
                }
            if holding is not None and last_record is not None:
                records.append(
                    {
                        **holding["entry"],
                        "exit_decision_date": last_record["trade_date"],
                        "exit_decision_available_at": last_record["available_at"],
                        "exit_score": (
                            float(last_record[score_column])
                            if pd.notna(last_record[score_column])
                            else math.nan
                        ),
                        "exit_midpoint": float(last_record["quote_midpoint"]),
                        "exit_reason": "terminal_source_row",
                        "holding_observations": holding["observations"],
                    }
                )
    plans = pd.DataFrame.from_records(records)
    if plans.empty:
        raise ValueError("calendar spread V1 generated no plans")
    for column in ("entry_decision_date", "exit_decision_date"):
        plans[column] = pd.to_datetime(plans[column], errors="raise").dt.normalize()
    if plans["entry_decision_date"].gt(plans["exit_decision_date"]).any():
        raise ValueError("calendar spread plan exits before its decision entry")
    if plans["exit_decision_date"].ge(PROTECTED_FROM).any():
        raise ValueError("calendar spread plans touch protected data")
    return plans.sort_values(
        ["strategy_id", "asset", "entry_decision_date"],
        kind="mergesort",
        ignore_index=True,
    )


def load_market(protocol: EconomicProtocol) -> pd.DataFrame:
    """Build the exact outright-leg accounting market from pinned source tables."""
    observations = pd.read_parquet(
        protocol.input_paths["contract_observations"], columns=OBSERVATION_COLUMNS
    ).rename(
        columns={
            "trade_date": "session_date",
            "logical_asset": "asset_code",
            "canonical_contract_id": "contract_id",
        }
    )
    specs = pd.read_parquet(protocol.input_paths["spec_proxy"], columns=SPEC_COLUMNS)
    market = build_portfolio_market(observations, specs)
    market["session_date"] = pd.to_datetime(market["session_date"], errors="raise").dt.normalize()
    market["asset_code"] = market["asset_code"].astype(str).str.upper().replace({"RTS": "RI"})
    market = market.loc[
        market["asset_code"].isin(ASSETS) & market["session_date"].lt(PROTECTED_FROM)
    ].copy()
    if market.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("calendar spread leg market has duplicate contract sessions")
    market = market.sort_values(
        ["contract_id", "session_date"], kind="mergesort", ignore_index=True
    )
    market["lagged_volume"] = market.groupby("contract_id", sort=False)["volume"].shift(1)
    return market


def _finite_positive(value: object) -> bool:
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) > 0.0)


def _finite_nonnegative(value: object) -> bool:
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) >= 0.0)


def _market_points(market: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], MarketPoint]:
    points: dict[tuple[pd.Timestamp, str], MarketPoint] = {}
    for row in market.itertuples(index=False):
        point = MarketPoint(
            session_date=pd.Timestamp(row.session_date),
            asset=str(row.asset_code),
            contract_id=str(row.contract_id),
            open=float(row.open) if pd.notna(row.open) else math.nan,
            settle=float(row.settle) if pd.notna(row.settle) else math.nan,
            lagged_volume=(float(row.lagged_volume) if pd.notna(row.lagged_volume) else math.nan),
            sizing_point_value=(
                float(row.sizing_point_value) if pd.notna(row.sizing_point_value) else math.nan
            ),
            accounting_point_value=(
                float(row.accounting_point_value)
                if pd.notna(row.accounting_point_value)
                else math.nan
            ),
            tick_size=float(row.tick_size) if pd.notna(row.tick_size) else math.nan,
            fee_per_contract=(
                float(row.fee_per_contract) if pd.notna(row.fee_per_contract) else math.nan
            ),
            initial_margin=(
                float(row.initial_margin) if pd.notna(row.initial_margin) else math.nan
            ),
        )
        points[(point.session_date, point.contract_id)] = point
    return points


def _valid_execution_point(point: MarketPoint | None, *, require_settle: bool) -> bool:
    if point is None:
        return False
    values = (
        point.open,
        point.sizing_point_value,
        point.accounting_point_value,
        point.tick_size,
        point.initial_margin,
    )
    return bool(
        all(_finite_positive(value) for value in values)
        and _finite_nonnegative(point.fee_per_contract)
        and _finite_nonnegative(point.lagged_volume)
        and (not require_settle or _finite_positive(point.settle))
    )


def attach_entry_execution_dates(plans: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Map each decision to the first strictly later common factual leg open."""
    valid = market.loc[market["open"].map(_finite_positive), ["session_date", "contract_id"]]
    dates_by_contract = {
        str(contract): pd.DatetimeIndex(group["session_date"].sort_values().unique())
        for contract, group in valid.groupby("contract_id", sort=False)
    }
    cache: dict[tuple[str, str], pd.DatetimeIndex] = {}
    execution_dates: list[pd.Timestamp | pd.NaT] = []
    for row in plans.itertuples(index=False):
        key = (str(row.near_contract_id), str(row.far_contract_id))
        if key not in cache:
            near = dates_by_contract.get(key[0], pd.DatetimeIndex([]))
            far = dates_by_contract.get(key[1], pd.DatetimeIndex([]))
            cache[key] = near.intersection(far).sort_values()
        dates = cache[key]
        position = dates.searchsorted(pd.Timestamp(row.entry_decision_date), side="right")
        candidate = dates[position] if position < len(dates) else pd.NaT
        if pd.notna(candidate) and candidate > pd.Timestamp(row.exit_decision_date):
            candidate = pd.NaT
        execution_dates.append(candidate)
    output = plans.copy()
    output["entry_execution_date"] = pd.to_datetime(execution_dates)
    return output


def _pair_cost(
    near: MarketPoint,
    far: MarketPoint,
    quantity: int,
    slippage_ticks: int,
    fee_multiplier: float,
) -> tuple[float, float, float]:
    commission = quantity * fee_multiplier * (near.fee_per_contract + far.fee_per_contract)
    slippage = (
        quantity
        * slippage_ticks
        * (
            near.tick_size * near.accounting_point_value
            + far.tick_size * far.accounting_point_value
        )
    )
    return float(commission + slippage), float(commission), float(slippage)


def _pair_move(
    direction: int,
    quantity: int,
    near_from: float,
    near_to: float,
    near_point_value: float,
    far_from: float,
    far_to: float,
    far_point_value: float,
) -> float:
    """Cash PnL for long-far/short-near when direction is +1."""
    far_pnl = direction * quantity * (far_to - far_from) * far_point_value
    near_pnl = -direction * quantity * (near_to - near_from) * near_point_value
    return float(far_pnl + near_pnl)


def simulate_strategy(
    strategy_id: str,
    plans: pd.DataFrame,
    market: pd.DataFrame,
    protocol_payload: Mapping[str, Any],
    scenario_name: str,
) -> SimulationResult:
    """Run the conservative equal-quantity two-leg cash ledger."""
    if scenario_name not in SCENARIOS:
        raise ValueError(f"unknown calendar spread cost scenario: {scenario_name}")
    slippage_ticks, fee_multiplier = SCENARIOS[scenario_name]
    portfolio = _mapping(protocol_payload["portfolio"], "portfolio")
    execution = _mapping(protocol_payload["execution"], "execution")
    initial_cash = float(portfolio["initial_cash_rub"])
    pair_fraction = float(portfolio["target_pair_gross_fraction_of_current_cash"])
    gross_limit = float(portfolio["maximum_total_gross_notional_multiple"])
    margin_buffer = float(portfolio["initial_margin_buffer_multiple"])
    participation = float(execution["maximum_participation_each_leg"])
    points = _market_points(market)
    session_dates = pd.DatetimeIndex(market["session_date"].drop_duplicates().sort_values())
    start = pd.Timestamp(protocol_payload["dates"]["development_start"])
    end = pd.Timestamp(protocol_payload["dates"]["execution_market_maximum"])
    session_dates = session_dates[(session_dates >= start) & (session_dates <= end)]
    selected = plans.loc[plans["strategy_id"].eq(strategy_id)].copy()
    entries: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for row in selected.to_dict(orient="records"):
        if pd.notna(row["entry_execution_date"]):
            entries[pd.Timestamp(row["entry_execution_date"])].append(row)
    for date in entries:
        entries[date].sort(key=lambda item: ASSETS.index(str(item["asset"])))
    positions: dict[str, OpenPair] = {}
    trade_records: list[dict[str, Any]] = []
    daily_records: list[dict[str, Any]] = []
    cash = initial_cash
    total_cost = 0.0
    total_commission = 0.0
    total_slippage = 0.0
    counters: defaultdict[str, int] = defaultdict(int)
    maximum_gross_multiple = 0.0
    maximum_buffered_margin_multiple = 0.0

    def point(date: pd.Timestamp, contract: str) -> MarketPoint | None:
        return points.get((date, contract))

    for date in session_dates:
        starting_cash = cash
        session_pnl = 0.0
        session_cost = 0.0
        exited_assets: set[str] = set()
        for asset in ASSETS:
            position = positions.get(asset)
            if position is None or date <= position.exit_decision_date:
                continue
            near = point(date, position.near_contract_id)
            far = point(date, position.far_contract_id)
            if not (
                _valid_execution_point(near, require_settle=False)
                and _valid_execution_point(far, require_settle=False)
            ):
                position.retry_days += 1
                counters["exit_missing_dependency_retries"] += 1
                continue
            assert near is not None and far is not None
            capacity = min(
                math.floor(participation * near.lagged_volume),
                math.floor(participation * far.lagged_volume),
            )
            if capacity < position.quantity:
                position.retry_days += 1
                counters["exit_capacity_retries"] += 1
                continue
            gap_pnl = _pair_move(
                position.direction,
                position.quantity,
                position.previous_near_settle,
                near.open,
                near.accounting_point_value,
                position.previous_far_settle,
                far.open,
                far.accounting_point_value,
            )
            cost, commission, slippage = _pair_cost(
                near, far, position.quantity, slippage_ticks, fee_multiplier
            )
            cash += gap_pnl - cost
            session_pnl += gap_pnl - cost
            session_cost += cost
            total_cost += cost
            total_commission += commission
            total_slippage += slippage
            position.gross_pnl += gap_pnl
            position.costs += cost
            trade_records.append(
                {
                    "strategy_id": strategy_id,
                    "scenario": scenario_name,
                    "plan_id": position.plan_id,
                    "asset": asset,
                    "spread_id": position.spread_id,
                    "direction": position.direction,
                    "quantity": position.quantity,
                    "near_contract_id": position.near_contract_id,
                    "far_contract_id": position.far_contract_id,
                    "entry_decision_date": position.entry_decision_date,
                    "entry_execution_date": position.entry_execution_date,
                    "exit_decision_date": position.exit_decision_date,
                    "exit_execution_date": date,
                    "entry_reason": position.entry_reason,
                    "exit_reason": position.exit_reason,
                    "entry_pair_notional": position.entry_pair_notional,
                    "gross_pnl": position.gross_pnl,
                    "cost": position.costs,
                    "net_pnl": position.gross_pnl - position.costs,
                    "exit_retry_days": position.retry_days,
                    "status": "completed",
                }
            )
            del positions[asset]
            exited_assets.add(asset)
            counters["completed_trades"] += 1
        for plan in entries.get(date, []):
            asset = str(plan["asset"])
            if asset in positions:
                counters["entry_skipped_overlap"] += 1
                trade_records.append(
                    {
                        "strategy_id": strategy_id,
                        "scenario": scenario_name,
                        "plan_id": plan["plan_id"],
                        "asset": asset,
                        "status": "skipped_overlap",
                    }
                )
                continue
            near = point(date, str(plan["near_contract_id"]))
            far = point(date, str(plan["far_contract_id"]))
            if not (
                _valid_execution_point(near, require_settle=True)
                and _valid_execution_point(far, require_settle=True)
            ):
                counters["entry_skipped_missing_dependency"] += 1
                trade_records.append(
                    {
                        "strategy_id": strategy_id,
                        "scenario": scenario_name,
                        "plan_id": plan["plan_id"],
                        "asset": asset,
                        "status": "skipped_missing_dependency",
                    }
                )
                continue
            assert near is not None and far is not None
            pair_notional = abs(near.open * near.sizing_point_value) + abs(
                far.open * far.sizing_point_value
            )
            pair_margin = margin_buffer * (near.initial_margin + far.initial_margin)
            if not (_finite_positive(pair_notional) and _finite_positive(pair_margin)):
                counters["entry_skipped_unsized"] += 1
                continue
            desired = math.floor(max(cash, 0.0) * pair_fraction / pair_notional)
            capacity = min(
                math.floor(participation * near.lagged_volume),
                math.floor(participation * far.lagged_volume),
            )
            existing_gross = sum(item.current_pair_notional for item in positions.values())
            existing_margin = sum(item.current_buffered_margin for item in positions.values())
            gross_capacity = math.floor(
                max(gross_limit * max(cash, 0.0) - existing_gross, 0.0) / pair_notional
            )
            margin_capacity = math.floor(max(max(cash, 0.0) - existing_margin, 0.0) / pair_margin)
            quantity = min(desired, capacity, gross_capacity, margin_capacity)
            if quantity < 1:
                counters["entry_skipped_zero_capacity_or_size"] += 1
                trade_records.append(
                    {
                        "strategy_id": strategy_id,
                        "scenario": scenario_name,
                        "plan_id": plan["plan_id"],
                        "asset": asset,
                        "status": "skipped_zero_capacity_or_size",
                    }
                )
                continue
            if quantity < desired:
                counters["entry_clipped"] += 1
            cost, commission, slippage = _pair_cost(
                near, far, quantity, slippage_ticks, fee_multiplier
            )
            cash -= cost
            session_pnl -= cost
            session_cost += cost
            total_cost += cost
            total_commission += commission
            total_slippage += slippage
            positions[asset] = OpenPair(
                plan_id=str(plan["plan_id"]),
                asset=asset,
                spread_id=str(plan["spread_id"]),
                direction=int(plan["direction"]),
                quantity=quantity,
                near_contract_id=str(plan["near_contract_id"]),
                far_contract_id=str(plan["far_contract_id"]),
                entry_decision_date=pd.Timestamp(plan["entry_decision_date"]),
                exit_decision_date=pd.Timestamp(plan["exit_decision_date"]),
                entry_execution_date=date,
                previous_near_settle=near.open,
                previous_far_settle=far.open,
                entry_pair_notional=quantity * pair_notional,
                current_pair_notional=quantity * pair_notional,
                current_buffered_margin=quantity * pair_margin,
                gross_pnl=0.0,
                costs=cost,
                retry_days=0,
                entry_reason=str(plan["entry_reason"]),
                exit_reason=str(plan["exit_reason"]),
            )
            counters["filled_entries"] += 1
        for asset in ASSETS:
            position = positions.get(asset)
            if position is None:
                continue
            near = point(date, position.near_contract_id)
            far = point(date, position.far_contract_id)
            if near is None and far is None:
                continue
            if near is None or far is None:
                counters["unpaired_factual_mark_days"] += 1
                continue
            if not (
                _finite_positive(near.settle)
                and _finite_positive(far.settle)
                and _finite_positive(near.accounting_point_value)
                and _finite_positive(far.accounting_point_value)
            ):
                counters["incomplete_factual_mark_days"] += 1
                continue
            mark_pnl = _pair_move(
                position.direction,
                position.quantity,
                position.previous_near_settle,
                near.settle,
                near.accounting_point_value,
                position.previous_far_settle,
                far.settle,
                far.accounting_point_value,
            )
            cash += mark_pnl
            session_pnl += mark_pnl
            position.gross_pnl += mark_pnl
            position.previous_near_settle = near.settle
            position.previous_far_settle = far.settle
            if _finite_positive(near.sizing_point_value) and _finite_positive(
                far.sizing_point_value
            ):
                position.current_pair_notional = position.quantity * (
                    abs(near.settle * near.sizing_point_value)
                    + abs(far.settle * far.sizing_point_value)
                )
            if _finite_positive(near.initial_margin) and _finite_positive(far.initial_margin):
                position.current_buffered_margin = (
                    position.quantity * margin_buffer * (near.initial_margin + far.initial_margin)
                )
        gross = sum(item.current_pair_notional for item in positions.values())
        buffered_margin = sum(item.current_buffered_margin for item in positions.values())
        denominator = max(abs(cash), 1e-12)
        maximum_gross_multiple = max(maximum_gross_multiple, gross / denominator)
        maximum_buffered_margin_multiple = max(
            maximum_buffered_margin_multiple, buffered_margin / denominator
        )
        if cash <= 0.0 or not math.isfinite(cash):
            counters["nonpositive_or_nonfinite_cash_days"] += 1
        daily_records.append(
            {
                "strategy_id": strategy_id,
                "scenario": scenario_name,
                "session_date": date,
                "starting_cash": starting_cash,
                "session_net_pnl": session_pnl,
                "session_cost": session_cost,
                "ending_cash": cash,
                "open_positions": len(positions),
                "gross_notional": gross,
                "buffered_margin": buffered_margin,
            }
        )
    for position in positions.values():
        trade_records.append(
            {
                "strategy_id": strategy_id,
                "scenario": scenario_name,
                "plan_id": position.plan_id,
                "asset": position.asset,
                "spread_id": position.spread_id,
                "direction": position.direction,
                "quantity": position.quantity,
                "near_contract_id": position.near_contract_id,
                "far_contract_id": position.far_contract_id,
                "entry_decision_date": position.entry_decision_date,
                "entry_execution_date": position.entry_execution_date,
                "exit_decision_date": position.exit_decision_date,
                "entry_reason": position.entry_reason,
                "exit_reason": position.exit_reason,
                "gross_pnl": position.gross_pnl,
                "cost": position.costs,
                "net_pnl": position.gross_pnl - position.costs,
                "exit_retry_days": position.retry_days,
                "status": "open_unresolved_terminal",
            }
        )
    counters["terminal_open_positions"] = len(positions)
    diagnostics = {
        **{key: int(value) for key, value in sorted(counters.items())},
        "plans": int(len(selected)),
        "plans_without_entry_execution_date": int(selected["entry_execution_date"].isna().sum()),
        "total_cost": float(total_cost),
        "total_commission": float(total_commission),
        "total_slippage": float(total_slippage),
        "maximum_gross_notional_multiple": float(maximum_gross_multiple),
        "maximum_buffered_margin_multiple": float(maximum_buffered_margin_multiple),
        "ending_cash": float(cash),
        "execution_complete": bool(
            len(positions) == 0
            and selected["entry_execution_date"].notna().all()
            and counters["unpaired_factual_mark_days"] == 0
            and counters["incomplete_factual_mark_days"] == 0
            and counters["nonpositive_or_nonfinite_cash_days"] == 0
        ),
    }
    return SimulationResult(
        daily=pd.DataFrame.from_records(daily_records),
        trades=pd.DataFrame.from_records(trade_records),
        diagnostics=diagnostics,
    )


def _period_metrics(
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    frame = daily.loc[daily["session_date"].between(start, end)].copy()
    if frame.empty:
        return {
            "sessions": 0,
            "total_return": None,
            "cagr": None,
            "sharpe": None,
            "maximum_drawdown": None,
            "annual_returns": {},
            "completed_trades": 0,
        }
    returns = frame["ending_cash"].astype(float) / frame["starting_cash"].astype(float) - 1.0
    curve = (1.0 + returns).cumprod()
    total_return = float(curve.iloc[-1] - 1.0)
    cagr = float((1.0 + total_return) ** (252.0 / len(frame)) - 1.0)
    standard_deviation = float(returns.std(ddof=1))
    sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(252.0))
        if standard_deviation > 1e-15
        else 0.0
    )
    drawdown = curve / curve.cummax() - 1.0
    annual_returns: dict[str, float] = {}
    dates = pd.to_datetime(frame["session_date"], errors="raise")
    for year in sorted(dates.dt.year.unique()):
        values = returns.loc[dates.dt.year.eq(year)]
        annual_returns[str(int(year))] = float((1.0 + values).prod() - 1.0)
    completed = trades.loc[
        trades.get("status", pd.Series(index=trades.index, dtype="string")).eq("completed")
    ].copy()
    if not completed.empty and "entry_execution_date" in completed:
        entry_dates = pd.to_datetime(completed["entry_execution_date"], errors="coerce")
        completed = completed.loc[entry_dates.between(start, end)]
    pnl = pd.to_numeric(completed.get("net_pnl"), errors="coerce")
    positive = pnl.loc[pnl > 0.0].sum()
    negative = -pnl.loc[pnl < 0.0].sum()
    return {
        "sessions": int(len(frame)),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "annual_returns": annual_returns,
        "positive_years": int(sum(value > 0.0 for value in annual_returns.values())),
        "worst_year": min(annual_returns.values()) if annual_returns else None,
        "completed_trades": int(len(completed)),
        "win_rate": float((pnl > 0.0).mean()) if len(pnl) else None,
        "profit_factor": float(positive / negative) if negative > 0.0 else None,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if pd.isna(value) if not isinstance(value, (str, bytes, bool)) else False:
        return None
    return value


def _promotion(metrics: Mapping[str, Any], validation: Mapping[str, Any]) -> dict[str, Any]:
    primary = metrics[STRATEGY_IDS[0]]["primary"]
    evaluation = primary["periods"]["evaluation"]
    stress = metrics[STRATEGY_IDS[0]]["stress"]["periods"]["evaluation"]
    conditions = {
        "execution_complete_all_primary_strategy_scenarios": all(
            bool(metrics[STRATEGY_IDS[0]][scenario]["diagnostics"]["execution_complete"])
            for scenario in SCENARIOS
        ),
        "evaluation_CAGR_at_least_10_percent": float(evaluation["cagr"])
        >= float(validation["minimum_evaluation_CAGR"]),
        "evaluation_sharpe_at_least_1": float(evaluation["sharpe"])
        >= float(validation["minimum_evaluation_sharpe"]),
        "evaluation_MDD_at_most_15_percent": float(evaluation["maximum_drawdown"])
        <= float(validation["maximum_evaluation_drawdown"]),
        "both_evaluation_years_positive": int(evaluation["positive_years"])
        >= int(validation["minimum_positive_evaluation_years"]),
        "stress_evaluation_total_return_positive": float(stress["total_return"]) > 0.0,
        "minimum_completed_evaluation_trades": int(evaluation["completed_trades"])
        >= int(validation["minimum_completed_evaluation_trades"]),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "best_of_family_remains_exploratory": True,
        "independent_confirmation_required": True,
        "live_trading_allowed": False,
    }


def _report_text(payload: Mapping[str, Any]) -> str:
    promotion = payload["promotion"]
    lines = [
        "# Calendar spread economic V1",
        "",
        f"Verdict: **{promotion['verdict']}** (research-only; live forbidden).",
        "",
        "Primary strategy was fixed before outcomes. The best of ten is exploratory only.",
        "",
        "| Strategy | Eval return | Eval CAGR | Eval Sharpe | Eval MDD | Trades | Stress return |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in STRATEGY_IDS:
        primary = payload["strategies"][strategy]["primary"]["periods"]["evaluation"]
        stress = payload["strategies"][strategy]["stress"]["periods"]["evaluation"]
        lines.append(
            f"| {strategy} | {primary['total_return']:.4%} | {primary['cagr']:.4%} | "
            f"{primary['sharpe']:.3f} | {primary['maximum_drawdown']:.4%} | "
            f"{primary['completed_trades']} | {stress['total_return']:.4%} |"
        )
    lines.extend(
        [
            "",
            "Execution is a synchronized next-open two-leg proxy with equal quantities, "
            "not historical spread-order queue evidence. All specs and fees remain approximate.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, compression="zstd")


def run_experiment(protocol: EconomicProtocol | None = None) -> Path:
    """Execute the sealed ten-strategy development family into one immutable run."""
    protocol = protocol or load_protocol()
    verified = verify_inputs(protocol)
    active = pd.read_parquet(protocol.input_paths["active_spreads"], columns=ACTIVE_COLUMNS)
    features = build_feature_frame(active)
    features = build_mlp_predictions(features, protocol.payload["neural_model"])
    plans = build_trade_plans(features, protocol.payload)
    market = load_market(protocol)
    plans = attach_entry_execution_dates(plans, market)
    all_daily: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []
    metrics: dict[str, dict[str, Any]] = {}
    development_start = pd.Timestamp(protocol.payload["dates"]["development_start"])
    development_end = pd.Timestamp(protocol.payload["dates"]["development_end"])
    evaluation_start = pd.Timestamp(protocol.payload["dates"]["evaluation_start"])
    evaluation_end = pd.Timestamp(protocol.payload["dates"]["evaluation_end"])
    execution_end = pd.Timestamp(protocol.payload["dates"]["execution_market_maximum"])
    for strategy_id in STRATEGY_IDS:
        metrics[strategy_id] = {}
        for scenario_name in SCENARIOS:
            result = simulate_strategy(strategy_id, plans, market, protocol.payload, scenario_name)
            all_daily.append(result.daily)
            all_trades.append(result.trades)
            metrics[strategy_id][scenario_name] = {
                "diagnostics": result.diagnostics,
                "periods": {
                    "development": _period_metrics(
                        result.daily,
                        result.trades,
                        development_start,
                        development_end,
                    ),
                    "evaluation": _period_metrics(
                        result.daily,
                        result.trades,
                        evaluation_start,
                        evaluation_end,
                    ),
                    "full": _period_metrics(
                        result.daily, result.trades, development_start, execution_end
                    ),
                },
            }
    daily = pd.concat(all_daily, ignore_index=True)
    trades = pd.concat(all_trades, ignore_index=True, sort=False)
    validation = _mapping(protocol.payload["validation"], "validation")
    promotion = _promotion(metrics, validation)
    evaluation_ranking = sorted(
        (
            {
                "strategy_id": strategy,
                "evaluation_primary_total_return": metrics[strategy]["primary"]["periods"][
                    "evaluation"
                ]["total_return"],
            }
            for strategy in STRATEGY_IDS
        ),
        key=lambda item: float(item["evaluation_primary_total_return"]),
        reverse=True,
    )
    model_predictions = features.loc[
        features["mlp_prediction"].notna(),
        [
            "trade_date",
            "logical_asset",
            "spread_id",
            "mlp_prediction",
            "mlp_train_samples",
            "mlp_train_max_target_date",
            "mlp_refit_date",
        ],
    ].copy()
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "development_family": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
        "contains_2026_market_values_returns_targets_or_pnl": False,
        "input_checks": verified.checks,
        "input_metadata": verified.metadata,
        "counts": {
            "active_rows": int(len(active)),
            "feature_rows": int(len(features)),
            "plans": int(len(plans)),
            "plans_by_strategy": {
                strategy: int(plans["strategy_id"].eq(strategy).sum()) for strategy in STRATEGY_IDS
            },
            "model_predictions": int(len(model_predictions)),
            "daily_rows": int(len(daily)),
            "trade_audit_rows": int(len(trades)),
        },
        "strategies": metrics,
        "exploratory_evaluation_ranking": evaluation_ranking,
        "promotion": promotion,
        "limitations": protocol.payload["limitations"],
    }
    output = protocol.output_directory
    if output.exists():
        raise FileExistsError(f"calendar spread V1 output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "plans.parquet", plans)
        _write_parquet(temporary / "model_predictions.parquet", model_predictions)
        _write_parquet(temporary / "daily.parquet", daily)
        _write_parquet(temporary / "trades.parquet", trades)
        write_json(temporary / "metrics.json", _json_safe(payload))
        atomic_write_bytes(temporary / "report.md", _report_text(payload).encode("utf-8-sig"))
        audit = {
            "checks": {
                **verified.checks,
                "ten_strategies_present": set(metrics) == set(STRATEGY_IDS),
                "three_cost_scenarios_present": all(
                    set(value) == set(SCENARIOS) for value in metrics.values()
                ),
                "mlp_training_targets_strictly_prior": bool(
                    model_predictions["mlp_train_max_target_date"]
                    .lt(model_predictions["mlp_refit_date"])
                    .all()
                ),
                "mlp_predictions_nonempty": bool(len(model_predictions) > 0),
                "plans_before_protected": bool(
                    plans["exit_decision_date"].lt(PROTECTED_FROM).all()
                ),
                "daily_before_protected": bool(daily["session_date"].lt(PROTECTED_FROM).all()),
                "equal_quantity_ledger_declared": True,
                "live_forbidden": True,
            }
        }
        write_json(temporary / "audit.json", audit)
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            declaration: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": source.sha256_file(path),
            }
            if path.suffix == ".parquet":
                declaration["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = declaration
        manifest = {
            "schema_version": 1,
            "bundle_id": output.name,
            "protocol_sha256": protocol.config_sha256,
            "research_only": True,
            "live_trading_allowed": False,
            "contains_2026_market_values_returns_targets_or_pnl": False,
            "artifacts": artifacts,
        }
        write_json(temporary / "manifest.json", manifest)
        manifest_sha = source.sha256_file(temporary / "manifest.json")
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def audit_bundle(protocol: EconomicProtocol | None = None) -> dict[str, bool]:
    """Recheck the immutable run's protocol, bytes, rows and protected boundary."""
    protocol = protocol or load_protocol()
    verify_inputs(protocol)
    output = protocol.output_directory
    manifest_path = output / "manifest.json"
    sidecar = output / "manifest.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar.read_text(encoding="utf-8-sig").split()[0]
        == source.sha256_file(manifest_path),
        "protocol_sha_exact": manifest.get("protocol_sha256") == protocol.config_sha256,
        "live_forbidden": manifest.get("live_trading_allowed") is False,
        "protected_absent_declared": manifest.get(
            "contains_2026_market_values_returns_targets_or_pnl"
        )
        is False,
    }
    for name, declaration in manifest.get("artifacts", {}).items():
        path = output / name
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == int(
            declaration["bytes"]
        )
        checks[f"{name}_sha256"] = path.is_file() and source.sha256_file(path) == str(
            declaration["sha256"]
        )
        if "rows" in declaration:
            checks[f"{name}_rows"] = path.is_file() and pq.ParquetFile(
                path
            ).metadata.num_rows == int(declaration["rows"])
    for name, column in (
        ("plans.parquet", "exit_decision_date"),
        ("daily.parquet", "session_date"),
        ("trades.parquet", "entry_execution_date"),
    ):
        path = output / name
        values = pd.to_datetime(pd.read_parquet(path, columns=[column])[column], errors="coerce")
        checks[f"{name}_protected"] = bool(values.dropna().lt(PROTECTED_FROM).all())
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    checks["initial_audit_all_true"] = all(audit.get("checks", {}).values())
    if not all(checks.values()):
        raise ValueError(f"calendar spread V1 bundle audit failed: {checks}")
    return checks


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.audit_only:
        print(json.dumps(audit_bundle(), ensure_ascii=False, indent=2))
    else:
        print(run_experiment())


if __name__ == "__main__":
    main()
