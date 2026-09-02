"""Causal V37 thirty-stock breakout features, fixed neural gate, and ledger."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from market_lab.stocks import cross_sectional_intraday as v35

PROTECTED_BOUNDARY: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
EXPECTED_SOURCE_PROTOCOL: Final[str] = "stock-intraday-pre2026-source-v1"
SOURCE_COLUMNS: Final[tuple[str, ...]] = v35.SOURCE_COLUMNS
AGGREGATE_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "market_return_1",
    "market_return_3",
    "market_return_6",
    "positive_breadth_1",
    "positive_breadth_3",
    "positive_breadth_6",
    "dispersion_1",
    "dispersion_3",
    "dispersion_6",
    "long_breakout_mean",
    "short_breakout_mean",
    "mean_market_correlation",
    "selected_value_rank_min",
    "selected_value_rank_mean",
    "selected_volatility_mean",
    "selected_volatility_max",
    "direction",
    "time_sine",
    "time_cosine",
)


@dataclass(frozen=True, slots=True)
class BreakoutPanel:
    timestamps: pd.DatetimeIndex
    tickers: tuple[str, ...]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        shape = (len(self.timestamps), len(self.tickers))
        for name in ("opens", "highs", "lows", "closes", "values"):
            if getattr(self, name).shape != shape:
                raise ValueError(f"V37 {name} shape mismatch")
        if self.timestamps.tz is None or self.timestamps.max() >= PROTECTED_BOUNDARY:
            raise ValueError("V37 panel timezone or protected boundary invalid")
        if self.timestamps.has_duplicates or not self.timestamps.is_monotonic_increasing:
            raise ValueError("V37 panel timestamps must be unique and sorted")


@dataclass(frozen=True, slots=True)
class BreakoutCandidates:
    frame: pd.DataFrame
    full_features: np.ndarray
    aggregate_features: np.ndarray
    full_feature_names: tuple[str, ...]
    aggregate_feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        rows = len(self.frame)
        if self.full_features.shape[0] != rows or self.aggregate_features.shape[0] != rows:
            raise ValueError("V37 feature row count mismatch")
        if self.full_features.shape[1] != len(self.full_feature_names):
            raise ValueError("V37 full feature-name mismatch")
        if self.aggregate_features.shape[1] != len(self.aggregate_feature_names):
            raise ValueError("V37 aggregate feature-name mismatch")


def validate_source(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    source = config["source"]
    manifest_path = (project_root / source["manifest_path"]).resolve()
    if (
        manifest_path.stat().st_size != int(source["manifest_bytes"])
        or v35.sha256_file(manifest_path) != source["manifest_sha256"]
    ):
        raise ValueError("V37 source manifest identity mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    artifacts = manifest.get("artifacts", [])
    if (
        manifest.get("protocol") != EXPECTED_SOURCE_PROTOCOL
        or manifest.get("contains_returns_labels_targets_or_pnl") is not False
        or int(manifest.get("total_rows", -1)) != int(source["expected_rows"])
        or len(artifacts) != int(source["expected_tickers"])
        or {item["ticker"] for item in artifacts} != set(config["universe"]["tickers"])
        or max(pd.Timestamp(item["maximum_timestamp"]) for item in artifacts)
        >= PROTECTED_BOUNDARY
    ):
        raise ValueError("V37 source manifest invariant mismatch")
    return manifest


def preflight_source(config: dict[str, Any], project_root: Path) -> dict[str, bool]:
    manifest = validate_source(config, project_root)
    source_root = (project_root / config["source"]["directory"]).resolve()
    checks: dict[str, bool] = {
        "manifest_exact": True,
        "source_loader_exact": v35.sha256_file(
            project_root / config["source"]["source_loader"]
        )
        == config["source"]["source_loader_sha256"],
    }
    rows = 0
    for item in manifest["artifacts"]:
        path = source_root / item["path"]
        exact = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and v35.sha256_file(path) == item["sha256"]
        )
        checks[f"artifact_{item['ticker']}_exact"] = exact
        rows += int(item["rows"])
    checks["rows_exact"] = rows == int(config["source"]["expected_rows"])
    checks["protected_boundary_exact"] = (
        max(pd.Timestamp(item["maximum_timestamp"]) for item in manifest["artifacts"])
        == pd.Timestamp(config["source"]["maximum_timestamp_utc"])
        < PROTECTED_BOUNDARY
    )
    return checks


def load_panel(config: dict[str, Any], project_root: Path) -> BreakoutPanel:
    manifest = validate_source(config, project_root)
    source_root = (project_root / config["source"]["directory"]).resolve()
    items = {item["ticker"]: item for item in manifest["artifacts"]}
    tickers = tuple(config["universe"]["tickers"])
    frames: dict[str, pd.DataFrame] = {}
    common: pd.DatetimeIndex | None = None
    for ticker in tickers:
        item = items[ticker]
        path = source_root / item["path"]
        if v35.sha256_file(path) != item["sha256"]:
            raise ValueError(f"V37 source artifact drift: {ticker}")
        frame = pd.read_parquet(
            path, columns=["timestamp", "open", "high", "low", "close", "value"]
        )
        timestamp = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
        if timestamp.has_duplicates or not timestamp.is_monotonic_increasing:
            raise ValueError(f"V37 timestamp order invalid: {ticker}")
        frame.index = timestamp
        frames[ticker] = frame
        common = timestamp if common is None else common.intersection(timestamp, sort=True)
    if common is None or common.empty:
        raise ValueError("V37 common thirty-stock panel is empty")
    common = common.sort_values()
    arrays = {
        name: np.empty((len(common), len(tickers)), dtype=np.float64)
        for name in ("opens", "highs", "lows", "closes", "values")
    }
    columns = {
        "opens": "open",
        "highs": "high",
        "lows": "low",
        "closes": "close",
        "values": "value",
    }
    for asset, ticker in enumerate(tickers):
        aligned = frames[ticker].reindex(common)
        for target, column in columns.items():
            arrays[target][:, asset] = pd.to_numeric(aligned[column], errors="coerce")
    return BreakoutPanel(common, tickers, **arrays)


def _exact_window(
    timestamps: pd.DatetimeIndex, local_dates: np.ndarray, bars: int
) -> np.ndarray:
    valid = np.zeros(len(timestamps), dtype=bool)
    if len(timestamps) > bars:
        valid[bars:] = (
            (timestamps[bars:] - timestamps[:-bars] == pd.Timedelta(minutes=10 * bars))
            & (local_dates[bars:] == local_dates[:-bars])
        )
    return valid


def _lag_return(values: np.ndarray, bars: int, exact: np.ndarray) -> np.ndarray:
    result = np.full_like(values, np.nan)
    if len(values) <= bars:
        return result
    ratio = np.divide(
        values[bars:],
        values[:-bars],
        out=np.full_like(values[bars:], np.nan),
        where=(values[bars:] > 0.0) & (values[:-bars] > 0.0),
    )
    result[bars:] = np.log(ratio)
    result[~exact] = np.nan
    return result


def _finite_mean(values: np.ndarray, default: float = math.nan) -> float:
    finite = values[np.isfinite(values)]
    return float(np.mean(finite)) if len(finite) else default


def _finite_max(values: np.ndarray, default: float = math.nan) -> float:
    finite = values[np.isfinite(values)]
    return float(np.max(finite)) if len(finite) else default


def _exit_path(
    panel: BreakoutPanel,
    entry_index: int,
    selected: np.ndarray,
    direction: int,
    local: pd.DatetimeIndex,
    local_dates: np.ndarray,
    config: dict[str, Any],
) -> tuple[int | None, str, float]:
    settings = config["exit"]
    entry_prices = panel.opens[entry_index, selected]
    if not np.isfinite(entry_prices).all() or (entry_prices <= 0.0).any():
        return None, "missing_entry_open", math.nan
    maximum = int(settings["maximum_holding_bars"])
    forced_time = pd.Timestamp(config["timing"]["forced_exit_local_open"]).time()
    forced_index: int | None = None
    for index in range(entry_index + 1, len(local)):
        if local_dates[index] != local_dates[entry_index]:
            break
        if local[index].time() >= forced_time:
            forced_index = index
            break
    terminal = min(entry_index + maximum, len(local) - 1)
    if forced_index is not None:
        terminal = min(terminal, forced_index)
    best = -math.inf
    for trigger_index in range(entry_index, terminal):
        if local_dates[trigger_index] != local_dates[entry_index]:
            return None, "path_crossed_session", math.nan
        close = panel.closes[trigger_index, selected]
        if not np.isfinite(close).all() or (close <= 0.0).any():
            return None, "missing_path_close", math.nan
        basket = float(np.mean(direction * (close / entry_prices - 1.0)))
        best = max(best, basket)
        stop = basket <= -float(settings["hard_stop_adverse_fraction_from_entry"])
        trailing = (
            best >= float(settings["trailing_activation_favorable_fraction"])
            and best - basket
            >= float(settings["trailing_retrace_fraction_from_best_completed_close"])
        )
        if stop or trailing:
            exit_index = trigger_index + 1
            if (
                exit_index >= len(local)
                or local_dates[exit_index] != local_dates[entry_index]
                or panel.timestamps[exit_index] - panel.timestamps[trigger_index]
                != pd.Timedelta(minutes=10)
            ):
                return None, "missing_trigger_successor", best
            return exit_index, "hard_stop" if stop else "trailing_profit", best
    if terminal <= entry_index or local_dates[terminal] != local_dates[entry_index]:
        return None, "missing_time_exit", best
    reason = "forced_session_exit" if forced_index == terminal else "maximum_holding_exit"
    return terminal, reason, best


def build_candidates(panel: BreakoutPanel, config: dict[str, Any]) -> BreakoutCandidates:
    timestamps = panel.timestamps
    local = timestamps.tz_convert(config["timing"]["timezone"])
    local_dates = np.asarray(local.date)
    exact = {bars: _exact_window(timestamps, local_dates, bars) for bars in (1, 3, 6, 36)}
    returns = {bars: _lag_return(panel.closes, bars, exact[bars]) for bars in (1, 3, 6)}
    prior_high = pd.DataFrame(panel.highs).shift(1).rolling(6, min_periods=6).max().to_numpy()
    prior_low = pd.DataFrame(panel.lows).shift(1).rolling(6, min_periods=6).min().to_numpy()
    prior_high[~exact[6]] = np.nan
    prior_low[~exact[6]] = np.nan
    long_break = panel.closes / prior_high - 1.0
    short_break = prior_low / panel.closes - 1.0
    value_rank = (
        pd.DataFrame(np.log(np.maximum(panel.values, 1.0)))
        .rank(axis=1, pct=True)
        .to_numpy()
    )
    market_1 = pd.DataFrame(returns[1]).mean(axis=1, skipna=True).to_numpy()
    correlations = np.full_like(panel.closes, np.nan)
    for asset in range(len(panel.tickers)):
        correlations[:, asset] = (
            pd.Series(returns[1][:, asset])
            .rolling(36, min_periods=24)
            .corr(pd.Series(market_1))
            .to_numpy()
        )
    correlations[~exact[36]] = np.nan
    volatility = pd.DataFrame(returns[1]).rolling(36, min_periods=24).std(ddof=1).to_numpy()
    volatility[~exact[36]] = np.nan
    start = pd.Timestamp(config["timing"]["decision_local_time_start"]).time()
    end = pd.Timestamp(config["timing"]["decision_local_time_end"]).time()
    threshold = float(config["candidate"]["breakout_fraction_beyond_prior_high_or_low"])
    breadth_threshold = float(config["candidate"]["breadth_confirmation_fraction"])
    value_floor = float(config["candidate"]["selected_minimum_cross_sectional_value_rank"])
    leg_count = int(config["candidate"]["selected_leg_count"])
    clip = float(config["features"]["finite_clipping"])
    rows: list[dict[str, Any]] = []
    full_features: list[np.ndarray] = []
    aggregate_features: list[np.ndarray] = []
    for index in range(6, len(timestamps) - 1):
        decision_at = timestamps[index] + pd.Timedelta(minutes=10)
        decision_local = decision_at.tz_convert(config["timing"]["timezone"])
        if decision_local.time() < start or decision_local.time() > end:
            continue
        if (
            timestamps[index + 1] - timestamps[index] != pd.Timedelta(minutes=10)
            or local_dates[index + 1] != local_dates[index]
            or not np.isfinite(returns[3][index]).all()
            or not np.isfinite(returns[6][index]).all()
            or not np.isfinite(value_rank[index]).all()
        ):
            continue
        breadth = float(np.mean(returns[3][index] > 0.0))
        long_mask = (
            np.isfinite(long_break[index])
            & (long_break[index] >= threshold)
            & (returns[3][index] > 0.0)
            & (value_rank[index] >= value_floor)
        )
        short_mask = (
            np.isfinite(short_break[index])
            & (short_break[index] >= threshold)
            & (returns[3][index] < 0.0)
            & (value_rank[index] >= value_floor)
        )
        long_candidates = (
            np.flatnonzero(long_mask)
            if breadth >= breadth_threshold
            else np.array([], dtype=int)
        )
        short_candidates = (
            np.flatnonzero(short_mask)
            if breadth <= 1.0 - breadth_threshold
            else np.array([], dtype=int)
        )
        long_strength = (
            float(np.mean(np.sort(long_break[index, long_candidates])[-leg_count:]))
            if len(long_candidates) >= leg_count
            else -math.inf
        )
        short_strength = (
            float(np.mean(np.sort(short_break[index, short_candidates])[-leg_count:]))
            if len(short_candidates) >= leg_count
            else -math.inf
        )
        if not np.isfinite(max(long_strength, short_strength)):
            continue
        direction = 1 if long_strength >= short_strength else -1
        candidates = long_candidates if direction == 1 else short_candidates
        strength = long_break[index] if direction == 1 else short_break[index]
        selected = candidates[np.argsort(strength[candidates], kind="stable")[-leg_count:]][::-1]
        entry_index = index + 1
        exit_index, exit_reason, best_return = _exit_path(
            panel, entry_index, selected, direction, local, local_dates, config
        )
        execution_observed = exit_index is not None
        if execution_observed:
            entry_open = panel.opens[entry_index, selected]
            exit_open = panel.opens[exit_index, selected]
            signal_values = panel.values[index, selected]
            entry_values = panel.values[entry_index, selected]
            exit_values = panel.values[exit_index, selected]
            observed = (
                np.isfinite(entry_open).all()
                and np.isfinite(exit_open).all()
                and np.isfinite(signal_values).all()
                and np.isfinite(entry_values).all()
                and np.isfinite(exit_values).all()
                and (entry_open > 0.0).all()
                and (exit_open > 0.0).all()
                and (signal_values > 0.0).all()
                and (entry_values > 0.0).all()
                and (exit_values > 0.0).all()
            )
            raw_leg_returns = (
                exit_open / entry_open - 1.0
                if observed
                else np.full(leg_count, np.nan)
            )
            signed_returns = direction * raw_leg_returns
            gross_return = float(np.mean(signed_returns)) if observed else math.nan
            execution_observed = bool(observed)
        else:
            signal_values = panel.values[index, selected]
            entry_values = panel.values[entry_index, selected]
            exit_values = np.full(leg_count, np.nan)
            raw_leg_returns = np.full(leg_count, np.nan)
            signed_returns = np.full(leg_count, np.nan)
            gross_return = math.nan
        market_returns = [float(np.mean(returns[bars][index])) for bars in (1, 3, 6)]
        breadth_values = [float(np.mean(returns[bars][index] > 0.0)) for bars in (1, 3, 6)]
        dispersion = [float(np.std(returns[bars][index], ddof=1)) for bars in (1, 3, 6)]
        minutes = decision_local.hour * 60 + decision_local.minute
        angle = 2.0 * math.pi * (minutes - 11 * 60) / (7.5 * 60.0)
        aggregate = np.asarray(
            market_returns
            + breadth_values
            + dispersion
            + [
                float(np.nanmean(long_break[index][long_mask])) if long_mask.any() else 0.0,
                float(np.nanmean(short_break[index][short_mask])) if short_mask.any() else 0.0,
                _finite_mean(correlations[index]),
                float(np.min(value_rank[index, selected])),
                float(np.mean(value_rank[index, selected])),
                _finite_mean(volatility[index, selected]),
                _finite_max(volatility[index, selected]),
                float(direction),
                math.sin(angle),
                math.cos(angle),
            ],
            dtype=np.float64,
        )
        full = np.concatenate(
            [
                returns[1][index],
                returns[3][index],
                returns[6][index],
                direction * np.maximum(long_break[index], short_break[index]),
                value_rank[index],
                correlations[index],
                aggregate,
            ]
        )
        full = np.where(np.isfinite(full), np.clip(full, -clip, clip), np.nan)
        aggregate = np.where(np.isfinite(aggregate), np.clip(aggregate, -clip, clip), np.nan)
        rows.append(
            {
                "candidate_id": len(rows),
                "source_bar_open_at": timestamps[index],
                "decision_at": decision_at,
                "entry_at": timestamps[entry_index],
                "exit_at": timestamps[exit_index] if exit_index is not None else pd.NaT,
                "session_date": str(local_dates[index]),
                "year": int(local[index].year),
                "direction": direction,
                "selected_tickers": [panel.tickers[position] for position in selected],
                "selected_indices": selected.tolist(),
                "signal_values": signal_values.tolist(),
                "entry_values": entry_values.tolist(),
                "exit_values": exit_values.tolist(),
                "raw_leg_returns": raw_leg_returns.tolist(),
                "signed_leg_returns": signed_returns.tolist(),
                "gross_basket_return": gross_return,
                "execution_observed": execution_observed,
                "exit_reason": exit_reason,
                "best_completed_close_return": best_return,
                "breakout_strength": max(long_strength, short_strength),
                "breadth": breadth,
            }
        )
        full_features.append(full.astype(np.float32))
        aggregate_features.append(aggregate.astype(np.float32))
    blocks = ("return1", "return3", "return6", "breakout", "value_rank", "market_corr")
    full_names = tuple(
        [f"{block}_{ticker}" for block in blocks for ticker in panel.tickers]
        + list(AGGREGATE_FEATURE_NAMES)
    )
    return BreakoutCandidates(
        pd.DataFrame(rows),
        np.asarray(full_features, dtype=np.float32).reshape(-1, len(full_names)),
        np.asarray(aggregate_features, dtype=np.float32).reshape(
            -1, len(AGGREGATE_FEATURE_NAMES)
        ),
        full_names,
        AGGREGATE_FEATURE_NAMES,
    )


def doubled_cost_label(candidates: pd.DataFrame, config: dict[str, Any]) -> np.ndarray:
    portfolio = config["portfolio"]
    base = (
        float(portfolio["one_way_commission_bps"])
        + float(portfolio["one_way_slippage_bps"])
    ) / 10_000.0
    round_trip = 2.0 * base * float(portfolio["doubled_cost_multiplier"])
    holding_minutes = (
        pd.to_datetime(candidates["exit_at"], utc=True)
        - pd.to_datetime(candidates["entry_at"], utc=True)
    ).dt.total_seconds().to_numpy() / 60.0
    direction = pd.to_numeric(candidates["direction"], errors="raise").to_numpy()
    borrow = np.where(
        direction < 0,
        float(portfolio["annual_short_borrow_rate"])
        * holding_minutes
        / (365.0 * 24.0 * 60.0),
        0.0,
    )
    gross = pd.to_numeric(candidates["gross_basket_return"], errors="coerce").to_numpy()
    return (np.isfinite(gross) & (gross - round_trip - borrow > 0.0)).astype(np.int8)


def _impute_scale(
    train: np.ndarray, test: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    medians = np.nanmedian(train, axis=0)
    medians = np.where(np.isfinite(medians), medians, 0.0)
    train_missing = ~np.isfinite(train)
    test_missing = ~np.isfinite(test)
    train_filled = np.where(train_missing, medians, train)
    test_filled = np.where(test_missing, medians, test)
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_filled)
    test_scaled = scaler.transform(test_filled)
    return (
        np.concatenate([train_scaled, train_missing.astype(float)], axis=1),
        np.concatenate([test_scaled, test_missing.astype(float)], axis=1),
    )


def neural_probabilities(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    test_features: np.ndarray,
    *,
    hidden_layers: tuple[int, ...],
    model_config: dict[str, Any],
) -> np.ndarray | None:
    if (
        len(train_features) < int(model_config["minimum_training_candidates"])
        or len(np.unique(train_labels)) < 2
    ):
        return None
    train_scaled, test_scaled = _impute_scale(train_features, test_features)
    outputs = []
    for seed in model_config["seeds"]:
        model = MLPClassifier(
            hidden_layer_sizes=hidden_layers,
            activation=str(model_config["activation"]),
            solver=str(model_config["solver"]),
            alpha=float(model_config["alpha"]),
            batch_size=int(model_config["batch_size"]),
            learning_rate_init=float(model_config["learning_rate_init"]),
            max_iter=int(model_config["maximum_iterations"]),
            early_stopping=bool(model_config["early_stopping"]),
            validation_fraction=float(model_config["validation_fraction_from_training_only"]),
            n_iter_no_change=int(model_config["no_improvement_iterations"]),
            random_state=int(seed),
        )
        model.fit(train_scaled, train_labels)
        outputs.append(model.predict_proba(test_scaled)[:, 1])
    return np.mean(outputs, axis=0)


def build_oos_predictions(
    candidates: BreakoutCandidates, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = candidates.frame
    labels = doubled_cost_label(frame, config)
    years = pd.to_numeric(frame["year"], errors="raise").to_numpy(dtype=int)
    model_config = config["model"]
    threshold = float(model_config["fixed_trade_probability_threshold"])
    variants = {
        "full_cross_stock_mlp": (
            candidates.full_features,
            tuple(int(value) for value in model_config["full_hidden_layers"]),
        ),
        "aggregate_only_mlp": (
            candidates.aggregate_features,
            tuple(int(value) for value in model_config["aggregate_hidden_layers"]),
        ),
    }
    predictions: list[pd.DataFrame] = []
    folds: list[dict[str, Any]] = []
    for oos_year in config["folds"]["expanding_oos_years"]:
        test_mask = years == int(oos_year)
        train_mask = years < int(oos_year)
        train_sessions = frame.loc[train_mask, "session_date"]
        if not train_sessions.empty:
            train_mask &= frame["session_date"].ne(train_sessions.max()).to_numpy()
        for variant, (features, hidden) in variants.items():
            probability = neural_probabilities(
                features[train_mask],
                labels[train_mask],
                features[test_mask],
                hidden_layers=hidden,
                model_config=model_config,
            )
            status = "active"
            if probability is None:
                probability = np.full(int(test_mask.sum()), np.nan)
                status = "sleep_insufficient_training"
            selected = frame.loc[
                test_mask,
                ["candidate_id", "session_date", "year", "decision_at", "entry_at", "exit_at"],
            ].copy()
            selected["variant"] = variant
            selected["probability"] = probability
            selected["threshold"] = threshold
            selected["active_signal"] = np.isfinite(probability) & (probability >= threshold)
            selected["fold_status"] = status
            predictions.append(selected)
            folds.append(
                {
                    "oos_year": int(oos_year),
                    "variant": variant,
                    "status": status,
                    "train_rows": int(train_mask.sum()),
                    "test_rows": int(test_mask.sum()),
                    "train_positive_labels": int(labels[train_mask].sum()),
                    "fixed_threshold": threshold,
                }
            )
    return (
        pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
        pd.DataFrame(folds),
    )


def scenario_parameters(config: dict[str, Any]) -> dict[str, dict[str, float]]:
    portfolio = config["portfolio"]
    base = (
        float(portfolio["one_way_commission_bps"])
        + float(portfolio["one_way_slippage_bps"])
    ) / 10_000.0
    return {
        "primary": {
            "one_way_cost_rate": base,
            "annual_borrow_rate": float(portfolio["annual_short_borrow_rate"]),
        },
        "doubled": {
            "one_way_cost_rate": base * float(portfolio["doubled_cost_multiplier"]),
            "annual_borrow_rate": float(portfolio["annual_short_borrow_rate"]),
        },
        "stress": {
            "one_way_cost_rate": base * float(portfolio["stress_cost_multiplier"]),
            "annual_borrow_rate": float(
                portfolio["stress_annual_short_borrow_rate"]
            ),
        },
    }


def simulate_ledger(
    candidates: pd.DataFrame,
    signal_ids: set[int],
    config: dict[str, Any],
    *,
    variant: str,
    scenario: str,
    parameters: dict[str, float],
    evaluation_sessions: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    portfolio = config["portfolio"]
    initial = float(portfolio["initial_capital_rub"])
    equity = initial
    next_free = pd.Timestamp.min.tz_localize("UTC")
    trades: list[dict[str, Any]] = []
    unresolved = capacity_rejected = overlapping = 0
    maximum_participation = turnover = total_cost = 0.0
    ordered = candidates.sort_values(["entry_at", "candidate_id"], kind="stable")
    for row in ordered.itertuples(index=False):
        if int(row.candidate_id) not in signal_ids:
            continue
        entry_at = pd.Timestamp(row.entry_at)
        if entry_at < next_free:
            overlapping += 1
            continue
        if not bool(row.execution_observed) or pd.isna(row.exit_at):
            unresolved += 1
            continue
        signal_values = np.asarray(row.signal_values, dtype=float)
        entry_values = np.asarray(row.entry_values, dtype=float)
        exit_values = np.asarray(row.exit_values, dtype=float)
        raw_returns = np.asarray(row.raw_leg_returns, dtype=float)
        signed_returns = np.asarray(row.signed_leg_returns, dtype=float)
        leg_count = len(signed_returns)
        desired_leg = equity * float(portfolio["target_basket_gross"]) / leg_count
        known_capacity = signal_values * float(portfolio["signal_value_participation"])
        leg_notional = min(desired_leg, float(np.min(known_capacity)))
        if not np.isfinite(leg_notional) or leg_notional <= 0.0:
            capacity_rejected += 1
            continue
        entry_participation = leg_notional / entry_values
        exit_notionals = leg_notional * np.maximum(1.0 + raw_returns, 0.0)
        exit_participation = exit_notionals / exit_values
        factual_max = float(max(np.max(entry_participation), np.max(exit_participation)))
        maximum_participation = max(maximum_participation, factual_max)
        if factual_max > float(portfolio["factual_entry_exit_value_participation_limit"]):
            unresolved += 1
            next_free = pd.Timestamp(row.exit_at)
            continue
        gross_profit = float(leg_notional * np.sum(signed_returns))
        traded_notional = float(leg_notional * leg_count + np.sum(exit_notionals))
        trading_cost = traded_notional * float(parameters["one_way_cost_rate"])
        holding_minutes = (
            pd.Timestamp(row.exit_at) - pd.Timestamp(row.entry_at)
        ).total_seconds() / 60.0
        borrow_cost = (
            leg_notional
            * leg_count
            * float(parameters["annual_borrow_rate"])
            * holding_minutes
            / (365.0 * 24.0 * 60.0)
            if int(row.direction) < 0
            else 0.0
        )
        net_profit = gross_profit - trading_cost - borrow_cost
        equity_before = equity
        equity += net_profit
        turnover += traded_notional
        total_cost += trading_cost + borrow_cost
        trades.append(
            {
                "variant": variant,
                "scenario": scenario,
                "candidate_id": int(row.candidate_id),
                "session_date": row.session_date,
                "entry_at": row.entry_at,
                "exit_at": row.exit_at,
                "direction": int(row.direction),
                "selected_tickers": row.selected_tickers,
                "exit_reason": row.exit_reason,
                "gross_used": leg_notional * leg_count / equity_before,
                "leg_notional_rub": leg_notional,
                "gross_basket_return": float(row.gross_basket_return),
                "gross_profit_rub": gross_profit,
                "trading_cost_rub": trading_cost,
                "borrow_cost_rub": borrow_cost,
                "net_profit_rub": net_profit,
                "equity_before_rub": equity_before,
                "equity_after_rub": equity,
                "maximum_participation": factual_max,
            }
        )
        next_free = pd.Timestamp(row.exit_at)
    trade_frame = pd.DataFrame(trades)
    pnl_by_day = (
        trade_frame.groupby("session_date")["net_profit_rub"].sum().to_dict()
        if not trade_frame.empty
        else {}
    )
    curve_rows = []
    running = peak = initial
    daily_returns = []
    for session in evaluation_sessions:
        before = running
        running += float(pnl_by_day.get(session, 0.0))
        daily_return = running / before - 1.0
        peak = max(peak, running)
        drawdown = running / peak - 1.0
        daily_returns.append(daily_return)
        curve_rows.append(
            {
                "variant": variant,
                "scenario": scenario,
                "session_date": session,
                "daily_net_profit_rub": float(pnl_by_day.get(session, 0.0)),
                "equity_rub": running,
                "daily_return": daily_return,
                "drawdown": drawdown,
            }
        )
    curve = pd.DataFrame(curve_rows)
    returns = np.asarray(daily_returns, dtype=float)
    years = tuple(int(value) for value in config["folds"]["expanding_oos_years"])
    total_return = running / initial - 1.0
    cagr = (running / initial) ** (1.0 / len(years)) - 1.0 if running > 0.0 else -1.0
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.sqrt(252.0) * np.mean(returns) / std) if std > 0.0 else 0.0
    yearly: dict[str, float] = {}
    curve_dates = pd.to_datetime(curve["session_date"])
    for year in years:
        values = curve.loc[curve_dates.dt.year.eq(year), "daily_return"].to_numpy()
        yearly[str(year)] = float(np.prod(1.0 + values) - 1.0) if len(values) else 0.0
    metrics = {
        "variant": variant,
        "scenario": scenario,
        "signal_count": len(signal_ids),
        "completed_trades": len(trade_frame),
        "unresolved_count": unresolved,
        "capacity_rejected_count": capacity_rejected,
        "overlapping_skipped_count": overlapping,
        "coverage": len(trade_frame) / max(1, len(trade_frame) + unresolved),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(-curve["drawdown"].min()) if not curve.empty else 0.0,
        "yearly_returns": yearly,
        "positive_years": sum(value > 0.0 for value in yearly.values()),
        "worst_year": min(yearly.values()) if yearly else 0.0,
        "turnover_rub": turnover,
        "costs_rub": total_cost,
        "maximum_participation": maximum_participation,
        "ending_equity_rub": running,
    }
    return trade_frame, curve, metrics
