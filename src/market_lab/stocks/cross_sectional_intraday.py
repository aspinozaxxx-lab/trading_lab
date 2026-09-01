"""Causal thirty-stock intraday residual features, neural timing, and ledger."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

PROTECTED_BOUNDARY: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
SOURCE_COLUMNS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "timestamp",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class StockPanel:
    timestamps: pd.DatetimeIndex
    tickers: tuple[str, ...]
    opens: np.ndarray
    closes: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        expected = (len(self.timestamps), len(self.tickers))
        for name in ("opens", "closes", "values"):
            if getattr(self, name).shape != expected:
                raise ValueError(f"{name} shape mismatch")
        if self.timestamps.tz is None:
            raise ValueError("panel timestamps must be timezone-aware")
        if len(self.timestamps) and self.timestamps.max() >= PROTECTED_BOUNDARY:
            raise ValueError("protected timestamp entered the stock panel")
        if not self.timestamps.is_monotonic_increasing or self.timestamps.has_duplicates:
            raise ValueError("panel timestamps must be unique and sorted")


@dataclass(frozen=True, slots=True)
class CandidateSet:
    frame: pd.DataFrame
    full_features: np.ndarray
    aggregate_features: np.ndarray
    full_feature_names: tuple[str, ...]
    aggregate_feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        rows = len(self.frame)
        if self.full_features.shape[0] != rows or self.aggregate_features.shape[0] != rows:
            raise ValueError("candidate feature row mismatch")
        if self.full_features.shape[1] != len(self.full_feature_names):
            raise ValueError("full feature-name mismatch")
        if self.aggregate_features.shape[1] != len(self.aggregate_feature_names):
            raise ValueError("aggregate feature-name mismatch")


def validate_source_manifest(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    source = config["source"]
    manifest_path = (project_root / source["manifest_path"]).resolve()
    if manifest_path.stat().st_size != int(source["manifest_bytes"]):
        raise ValueError("V35 source manifest byte count mismatch")
    if sha256_file(manifest_path) != source["manifest_sha256"]:
        raise ValueError("V35 source manifest SHA mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("protocol") != source["protocol"]:
        raise ValueError("V35 source protocol mismatch")
    if int(manifest.get("total_rows", -1)) != int(source["expected_rows"]):
        raise ValueError("V35 source row count mismatch")
    if manifest.get("contains_returns_labels_targets_or_pnl") is not False:
        raise ValueError("V35 source is not outcome-free")
    artifacts = manifest.get("artifacts", [])
    expected_tickers = tuple(config["universe"]["tickers"])
    if len(artifacts) != int(source["expected_tickers"]):
        raise ValueError("V35 source ticker count mismatch")
    if {item["ticker"] for item in artifacts} != set(expected_tickers):
        raise ValueError("V35 source universe mismatch")
    if max(pd.Timestamp(item["maximum_timestamp"]) for item in artifacts) >= PROTECTED_BOUNDARY:
        raise ValueError("V35 source manifest crosses protected boundary")
    return manifest


def preflight_source(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Verify only identities, schemas, row counts, and timestamps; never decode prices."""
    manifest = validate_source_manifest(config, project_root)
    source_directory = (project_root / config["source"]["directory"]).resolve()
    identities = True
    schemas = True
    rows = 0
    maximum = pd.Timestamp("1900-01-01", tz="UTC")
    minimum = pd.Timestamp("2100-01-01", tz="UTC")
    for item in manifest["artifacts"]:
        path = source_directory / item["path"]
        identities &= path.is_file()
        if not path.is_file():
            continue
        identities &= path.stat().st_size == int(item["bytes"])
        identities &= sha256_file(path) == item["sha256"]
        metadata = pq.ParquetFile(path)
        schemas &= tuple(metadata.schema_arrow.names) == SOURCE_COLUMNS
        rows += metadata.metadata.num_rows
        minimum = min(minimum, pd.Timestamp(item["minimum_timestamp"]))
        maximum = max(maximum, pd.Timestamp(item["maximum_timestamp"]))
    checks = {
        "manifest_identity_exact": True,
        "artifact_identities_exact": bool(identities),
        "schemas_exact": bool(schemas),
        "total_rows_exact": rows == int(config["source"]["expected_rows"]),
        "minimum_timestamp_exact": minimum
        == pd.Timestamp(config["source"]["minimum_timestamp_utc"]),
        "maximum_timestamp_exact": maximum
        == pd.Timestamp(config["source"]["maximum_timestamp_utc"]),
        "protected_boundary_exact": maximum < PROTECTED_BOUNDARY,
        "ticker_count_exact": len(manifest["artifacts"])
        == int(config["source"]["expected_tickers"]),
    }
    return {
        "checks": checks,
        "ticker_count": len(manifest["artifacts"]),
        "total_rows": rows,
        "minimum_timestamp": minimum.isoformat(),
        "maximum_timestamp": maximum.isoformat(),
    }


def load_panel(config: dict[str, Any], project_root: Path) -> StockPanel:
    """Load only the already isolated pre-2026 bundle and align exact common bars."""
    manifest = validate_source_manifest(config, project_root)
    source_directory = (project_root / config["source"]["directory"]).resolve()
    by_ticker = {item["ticker"]: item for item in manifest["artifacts"]}
    tickers = tuple(config["universe"]["tickers"])
    frames: dict[str, pd.DataFrame] = {}
    common: pd.DatetimeIndex | None = None
    for ticker in tickers:
        item = by_ticker[ticker]
        path = source_directory / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise ValueError(f"V35 data SHA mismatch for {ticker}")
        frame = pd.read_parquet(path, columns=["timestamp", "open", "close", "value"])
        timestamp = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
        if len(timestamp) and timestamp.max() >= PROTECTED_BOUNDARY:
            raise ValueError("protected timestamp decoded by V35")
        if timestamp.has_duplicates or not timestamp.is_monotonic_increasing:
            raise ValueError(f"invalid timestamp order for {ticker}")
        frame.index = timestamp
        frames[ticker] = frame
        common = timestamp if common is None else common.intersection(timestamp, sort=True)
    if common is None or common.empty:
        raise ValueError("V35 exact common panel is empty")
    common = common.sort_values()
    shape = (len(common), len(tickers))
    opens = np.empty(shape, dtype=np.float64)
    closes = np.empty(shape, dtype=np.float64)
    values = np.empty(shape, dtype=np.float64)
    for asset, ticker in enumerate(tickers):
        aligned = frames[ticker].reindex(common)
        opens[:, asset] = pd.to_numeric(aligned["open"], errors="coerce")
        closes[:, asset] = pd.to_numeric(aligned["close"], errors="coerce")
        values[:, asset] = pd.to_numeric(aligned["value"], errors="coerce")
    return StockPanel(common, tickers, opens, closes, values)


def _rolling_beta(
    returns: np.ndarray, market: np.ndarray, lookback: int, minimum: int
) -> np.ndarray:
    market_series = pd.Series(market)
    market_variance = market_series.rolling(lookback, min_periods=minimum).var(ddof=1)
    beta = np.full_like(returns, np.nan, dtype=np.float64)
    for asset in range(returns.shape[1]):
        covariance = pd.Series(returns[:, asset]).rolling(
            lookback, min_periods=minimum
        ).cov(market_series)
        beta[:, asset] = np.divide(
            covariance.to_numpy(),
            market_variance.to_numpy(),
            out=np.full(len(market), np.nan),
            where=market_variance.to_numpy() > 1e-12,
        )
    return beta


def _same_session_exact_window(
    timestamps: pd.DatetimeIndex, local_dates: np.ndarray, bars: int
) -> np.ndarray:
    valid = np.zeros(len(timestamps), dtype=bool)
    if bars <= 1:
        valid[:] = True
        return valid
    elapsed = timestamps[bars - 1 :] - timestamps[: -(bars - 1)]
    valid[bars - 1 :] = (
        (elapsed == pd.Timedelta(minutes=10 * (bars - 1)))
        & (local_dates[bars - 1 :] == local_dates[: -(bars - 1)])
    )
    return valid


AGGREGATE_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "bottom_mean_z",
    "bottom_min_z",
    "top_mean_z",
    "top_max_z",
    "tail_spread_z",
    "selected_mean_absolute_z",
    "cross_section_z_dispersion",
    "market_return_1",
    "market_return_3",
    "market_return_6",
    "market_volatility_78",
    "positive_return_breadth",
    "beta_mean",
    "beta_dispersion",
    "selected_liquidity_rank_min",
    "selected_liquidity_rank_mean",
    "one_bar_residual_dispersion",
    "selected_residual_mean_correlation_78",
    "time_sine",
    "time_cosine",
)


def build_candidates(panel: StockPanel, config: dict[str, Any]) -> CandidateSet:
    feature_config = config["features"]
    timing = config["timing"]
    candidate_config = config["candidate"]
    timestamps = panel.timestamps
    local = timestamps.tz_convert(timing["timezone"])
    local_dates = np.asarray(local.date)
    exact_previous = np.zeros(len(timestamps), dtype=bool)
    exact_previous[1:] = (
        (timestamps[1:] - timestamps[:-1] == pd.Timedelta(minutes=10))
        & (local_dates[1:] == local_dates[:-1])
    )
    valid_prices = (
        np.isfinite(panel.closes)
        & (panel.closes > 0)
        & np.isfinite(panel.opens)
        & (panel.opens > 0)
        & np.isfinite(panel.values)
        & (panel.values > 0)
    )
    returns = np.full_like(panel.closes, np.nan)
    valid_return = exact_previous[:, None] & valid_prices
    valid_return[1:] &= valid_prices[:-1]
    ratio = np.divide(
        panel.closes[1:],
        panel.closes[:-1],
        out=np.full_like(panel.closes[1:], np.nan),
        where=(panel.closes[1:] > 0) & (panel.closes[:-1] > 0),
    )
    returns[1:] = np.where(valid_return[1:], np.log(ratio), np.nan)
    market = np.mean(returns, axis=1)
    beta = _rolling_beta(
        returns,
        market,
        int(feature_config["beta_lookback_bars"]),
        int(feature_config["beta_minimum_bars"]),
    )
    residual = returns - beta * market[:, None]
    horizon = int(feature_config["residual_horizon_bars"])
    residual_frame = pd.DataFrame(residual)
    residual_horizon = residual_frame.rolling(horizon, min_periods=horizon).sum().to_numpy()
    exact_horizon = _same_session_exact_window(timestamps, local_dates, horizon)
    residual_horizon[~exact_horizon] = np.nan
    scale_lookback = int(feature_config["residual_scale_lookback_observations"])
    scale_minimum = int(feature_config["residual_scale_minimum_observations"])
    horizon_scale = (
        pd.DataFrame(residual_horizon)
        .shift(1)
        .rolling(scale_lookback, min_periods=scale_minimum)
        .std(ddof=1)
        .to_numpy()
    )
    one_scale = (
        residual_frame.shift(1)
        .rolling(scale_lookback, min_periods=scale_minimum)
        .std(ddof=1)
        .to_numpy()
    )
    z_horizon = np.divide(
        residual_horizon,
        horizon_scale,
        out=np.full_like(residual_horizon, np.nan),
        where=horizon_scale > 1e-12,
    )
    z_one = np.divide(
        residual,
        one_scale,
        out=np.full_like(residual, np.nan),
        where=one_scale > 1e-12,
    )
    value_frame = pd.DataFrame(np.log(np.maximum(panel.values, 1.0)))
    value_rank = value_frame.rank(axis=1, pct=True).to_numpy() * 2.0 - 1.0
    market_series = pd.Series(market)
    market_volatility = market_series.rolling(
        int(feature_config["beta_lookback_bars"]),
        min_periods=int(feature_config["beta_minimum_bars"]),
    ).std(ddof=1).to_numpy()
    market_3 = market_series.rolling(3, min_periods=3).sum().to_numpy()
    market_6 = market_series.rolling(6, min_periods=6).sum().to_numpy()
    clip = float(feature_config["clipping"])
    start_time = pd.Timestamp(timing["decision_local_time_start"]).time()
    end_time = pd.Timestamp(timing["decision_local_time_end"]).time()
    stride = int(timing["decision_stride_minutes"])
    decision_local = local + pd.Timedelta(minutes=10)
    decision_minutes = decision_local.hour * 60 + decision_local.minute
    start_minutes = start_time.hour * 60 + start_time.minute
    time_mask = (
        (decision_minutes >= start_minutes)
        & (decision_minutes <= end_time.hour * 60 + end_time.minute)
        & ((decision_minutes - start_minutes) % stride == 0)
    )
    successor_valid = np.zeros(len(timestamps), dtype=bool)
    successor = 1 + int(timing["holding_exact_bars"])
    if len(timestamps) > successor:
        elapsed = timestamps[successor:] - timestamps[:-successor]
        successor_valid[:-successor] = (
            (elapsed == pd.Timedelta(minutes=10 * successor))
            & (local_dates[successor:] == local_dates[:-successor])
        )
    eligible = (
        time_mask
        & successor_valid
        & np.isfinite(z_horizon).all(axis=1)
        & np.isfinite(z_one).all(axis=1)
        & np.isfinite(beta).all(axis=1)
        & valid_prices.all(axis=1)
    )
    long_count = int(feature_config["selected_long_count"])
    short_count = int(feature_config["selected_short_count"])
    rows: list[dict[str, Any]] = []
    full_features: list[np.ndarray] = []
    aggregate_features: list[np.ndarray] = []
    for index in np.flatnonzero(eligible):
        z = z_horizon[index]
        order = np.argsort(z, kind="stable")
        longs = order[:long_count]
        shorts = order[-short_count:]
        selected = np.concatenate([longs, shorts])
        bottom = z[longs]
        top = z[shorts]
        tail_spread = float(np.mean(top) - np.mean(bottom))
        selected_abs = float(np.mean(np.abs(z[selected])))
        if selected_abs < float(candidate_config["minimum_mean_absolute_selected_z"]):
            continue
        if tail_spread < float(candidate_config["minimum_top_minus_bottom_mean_z"]):
            continue
        entry_index = index + 1
        exit_index = index + successor
        entry_open = panel.opens[entry_index, selected]
        exit_open = panel.opens[exit_index, selected]
        signal_values = panel.values[index, selected]
        entry_values = panel.values[entry_index, selected]
        exit_values = panel.values[exit_index, selected]
        execution_finite = (
            np.isfinite(entry_open).all()
            and np.isfinite(exit_open).all()
            and np.isfinite(signal_values).all()
            and np.isfinite(entry_values).all()
            and np.isfinite(exit_values).all()
            and (entry_open > 0).all()
            and (exit_open > 0).all()
            and (signal_values > 0).all()
            and (entry_values > 0).all()
            and (exit_values > 0).all()
        )
        if execution_finite:
            raw_leg_returns = exit_open / entry_open - 1.0
            directions = np.concatenate([np.ones(long_count), -np.ones(short_count)])
            signed_leg_returns = directions * raw_leg_returns
            gross_return = float(np.mean(signed_leg_returns))
        else:
            raw_leg_returns = np.full(long_count + short_count, np.nan)
            signed_leg_returns = raw_leg_returns.copy()
            gross_return = math.nan
        window_start = max(0, index - int(feature_config["beta_lookback_bars"]) + 1)
        selected_history = residual[window_start : index + 1, selected]
        complete_history = selected_history[np.isfinite(selected_history).all(axis=1)]
        if len(complete_history) >= int(feature_config["beta_minimum_bars"]):
            correlation = np.corrcoef(complete_history, rowvar=False)
            upper = correlation[np.triu_indices(len(selected), k=1)]
            selected_correlation = float(np.nanmean(upper))
        else:
            selected_correlation = math.nan
        minutes = int(decision_minutes[index])
        angle = 2.0 * math.pi * (minutes - start_minutes) / (8.5 * 60.0)
        aggregate = np.array(
            [
                np.mean(bottom),
                np.min(bottom),
                np.mean(top),
                np.max(top),
                tail_spread,
                selected_abs,
                np.std(z, ddof=1),
                market[index],
                market_3[index],
                market_6[index],
                market_volatility[index],
                np.mean(returns[index] > 0),
                np.mean(beta[index]),
                np.std(beta[index], ddof=1),
                np.min(value_rank[index, selected]),
                np.mean(value_rank[index, selected]),
                np.std(residual[index], ddof=1),
                selected_correlation,
                math.sin(angle),
                math.cos(angle),
            ],
            dtype=np.float64,
        )
        if not np.isfinite(aggregate).all():
            continue
        full = np.concatenate(
            [
                np.clip(z, -clip, clip),
                np.clip(z_one[index], -clip, clip),
                np.clip(beta[index], -clip, clip),
                np.clip(value_rank[index], -clip, clip),
                np.clip(aggregate, -clip, clip),
            ]
        )
        if not np.isfinite(full).all():
            continue
        rows.append(
            {
                "candidate_id": len(rows),
                "source_bar_open_at": timestamps[index],
                "decision_at": timestamps[index] + pd.Timedelta(minutes=10),
                "entry_at": timestamps[entry_index],
                "exit_at": timestamps[exit_index],
                "session_date": str(local_dates[index]),
                "year": int(local[index].year),
                "long_tickers": [panel.tickers[position] for position in longs],
                "short_tickers": [panel.tickers[position] for position in shorts],
                "selected_indices": selected.tolist(),
                "signal_values": signal_values.tolist(),
                "entry_values": entry_values.tolist(),
                "exit_values": exit_values.tolist(),
                "raw_leg_returns": raw_leg_returns.tolist(),
                "signed_leg_returns": signed_leg_returns.tolist(),
                "gross_basket_return": gross_return,
                "execution_observed": bool(execution_finite),
                "tail_spread_z": tail_spread,
                "selected_mean_absolute_z": selected_abs,
            }
        )
        full_features.append(full.astype(np.float32))
        aggregate_features.append(np.clip(aggregate, -clip, clip).astype(np.float32))
    asset_names = tuple(panel.tickers)
    full_names = (
        tuple(f"residual_z6_{ticker}" for ticker in asset_names)
        + tuple(f"residual_z1_{ticker}" for ticker in asset_names)
        + tuple(f"beta_{ticker}" for ticker in asset_names)
        + tuple(f"value_rank_{ticker}" for ticker in asset_names)
        + AGGREGATE_FEATURE_NAMES
    )
    return CandidateSet(
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
    one_way = (
        float(portfolio["one_way_commission_bps"])
        + float(portfolio["one_way_slippage_bps"])
    ) / 10_000.0
    round_trip = 2.0 * one_way * float(portfolio["doubled_cost_multiplier"])
    holding_fraction = float(config["timing"]["holding_exact_bars"]) * 10.0 / (
        252.0 * 8.0 * 60.0
    )
    borrow = 0.5 * float(portfolio["annual_short_borrow_rate"]) * holding_fraction
    gross = pd.to_numeric(candidates["gross_basket_return"], errors="coerce").to_numpy()
    return (np.isfinite(gross) & (gross - round_trip - borrow > 0.0)).astype(np.int8)


def neural_probabilities(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    test_features: np.ndarray,
    *,
    hidden_layers: tuple[int, ...],
    model_config: dict[str, Any],
) -> np.ndarray | None:
    if len(train_features) < 100 or len(np.unique(train_labels)) < 2:
        return None
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_features)
    test_scaled = scaler.transform(test_features)
    probabilities = []
    for seed in model_config["seeds"]:
        classifier = MLPClassifier(
            hidden_layer_sizes=hidden_layers,
            activation=str(model_config["activation"]),
            solver=str(model_config["solver"]),
            alpha=float(model_config["alpha"]),
            batch_size=int(model_config["batch_size"]),
            learning_rate_init=float(model_config["learning_rate_init"]),
            max_iter=int(model_config["maximum_iterations"]),
            early_stopping=bool(model_config["early_stopping"]),
            validation_fraction=float(model_config["validation_fraction"]),
            n_iter_no_change=int(model_config["no_improvement_iterations"]),
            random_state=int(seed),
        )
        classifier.fit(train_scaled, train_labels)
        probabilities.append(classifier.predict_proba(test_scaled)[:, 1])
    return np.mean(probabilities, axis=0)


def _nonoverlap_returns(
    candidates: pd.DataFrame,
    probabilities: np.ndarray,
    threshold: float,
    round_trip_cost: float,
) -> tuple[np.ndarray, np.ndarray]:
    accepted_returns: list[float] = []
    dates: list[str] = []
    next_free = pd.Timestamp.min.tz_localize("UTC")
    order = np.argsort(pd.to_datetime(candidates["entry_at"], utc=True).to_numpy())
    for location in order:
        if not np.isfinite(probabilities[location]) or probabilities[location] < threshold:
            continue
        row = candidates.iloc[location]
        entry = pd.Timestamp(row["entry_at"])
        if entry < next_free or not bool(row["execution_observed"]):
            continue
        gross_return = float(row["gross_basket_return"])
        if not np.isfinite(gross_return):
            continue
        accepted_returns.append(gross_return - round_trip_cost)
        dates.append(str(row["session_date"]))
        next_free = pd.Timestamp(row["exit_at"])
    return np.asarray(accepted_returns), np.asarray(dates)


def select_probability_threshold(
    candidates: pd.DataFrame,
    probabilities: np.ndarray,
    config: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    model = config["model"]
    portfolio = config["portfolio"]
    one_way = (
        float(portfolio["one_way_commission_bps"])
        + float(portfolio["one_way_slippage_bps"])
    ) / 10_000.0
    stress_round_trip = 2.0 * one_way * float(portfolio["doubled_cost_multiplier"])
    minimum = int(model["calibration_minimum_completed_trades"])
    records = []
    for threshold in model["probability_thresholds"]:
        returns, dates = _nonoverlap_returns(
            candidates, probabilities, float(threshold), stress_round_trip
        )
        if len(returns):
            daily = pd.Series(returns, index=pd.to_datetime(dates)).groupby(level=0).sum()
            sharpe = (
                float(np.sqrt(252.0) * daily.mean() / daily.std(ddof=1))
                if len(daily) > 1 and daily.std(ddof=1) > 0
                else -math.inf
            )
            total = float(np.prod(1.0 + returns) - 1.0)
        else:
            sharpe = -math.inf
            total = -math.inf
        record = {
            "threshold": float(threshold),
            "trades": int(len(returns)),
            "stress_sharpe": sharpe if np.isfinite(sharpe) else None,
            "stress_total_return": total if np.isfinite(total) else None,
            "eligible": len(returns) >= minimum and np.isfinite(sharpe),
        }
        records.append(record)
    eligible = [record for record in records if record["eligible"]]
    if not eligible:
        return None, {"status": "sleep_insufficient_calibration", "thresholds": records}
    selected = max(
        eligible,
        key=lambda item: (
            float(item["stress_sharpe"]),
            float(item["stress_total_return"]),
            float(item["threshold"]),
        ),
    )
    return float(selected["threshold"]), {"status": "active", "thresholds": records}


def _last_session_mask(frame: pd.DataFrame, mask: np.ndarray) -> np.ndarray:
    result = mask.copy()
    sessions = frame.loc[mask, "session_date"]
    if not sessions.empty:
        result &= frame["session_date"].ne(sessions.max()).to_numpy()
    return result


def build_oos_predictions(
    candidates: CandidateSet, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = candidates.frame
    labels = doubled_cost_label(frame, config)
    model_config = config["model"]
    predictions: list[pd.DataFrame] = []
    folds: list[dict[str, Any]] = []
    variants = {
        "full_all_stock_neural": (
            candidates.full_features,
            tuple(int(value) for value in model_config["full_hidden_layers"]),
        ),
        "aggregate_only_neural": (
            candidates.aggregate_features,
            tuple(int(value) for value in model_config["aggregate_hidden_layers"]),
        ),
    }
    years = pd.to_numeric(frame["year"], errors="raise").to_numpy(dtype=int)
    for oos_year in config["folds"]["expanding_oos_years"]:
        calibration_year = int(oos_year) - 1
        calibration_mask = years == calibration_year
        test_mask = years == int(oos_year)
        selector_train_mask = _last_session_mask(frame, years < calibration_year)
        final_train_mask = _last_session_mask(frame, years < int(oos_year))
        for variant, (feature_matrix, hidden) in variants.items():
            selector_probability = neural_probabilities(
                feature_matrix[selector_train_mask],
                labels[selector_train_mask],
                feature_matrix[calibration_mask],
                hidden_layers=hidden,
                model_config=model_config,
            )
            if selector_probability is None or not calibration_mask.any():
                threshold = None
                threshold_record: dict[str, Any] = {
                    "status": "sleep_insufficient_selector_training"
                }
            else:
                threshold, threshold_record = select_probability_threshold(
                    frame.loc[calibration_mask].reset_index(drop=True),
                    selector_probability,
                    config,
                )
            test_probability = neural_probabilities(
                feature_matrix[final_train_mask],
                labels[final_train_mask],
                feature_matrix[test_mask],
                hidden_layers=hidden,
                model_config=model_config,
            )
            status = "active"
            if threshold is None:
                status = str(threshold_record["status"])
            if test_probability is None:
                status = "sleep_insufficient_final_training"
                test_probability = np.full(int(test_mask.sum()), np.nan)
            selected_frame = frame.loc[
                test_mask,
                ["candidate_id", "session_date", "year", "decision_at", "entry_at", "exit_at"],
            ].copy()
            selected_frame["variant"] = variant
            selected_frame["probability"] = test_probability
            selected_frame["threshold"] = threshold
            selected_frame["active_signal"] = (
                False
                if threshold is None
                else np.isfinite(test_probability) & (test_probability >= threshold)
            )
            selected_frame["fold_status"] = status
            predictions.append(selected_frame)
            folds.append(
                {
                    "oos_year": int(oos_year),
                    "variant": variant,
                    "status": status,
                    "selector_train_rows": int(selector_train_mask.sum()),
                    "calibration_rows": int(calibration_mask.sum()),
                    "final_train_rows": int(final_train_mask.sum()),
                    "test_rows": int(test_mask.sum()),
                    "selector_positive_labels": int(labels[selector_train_mask].sum()),
                    "final_positive_labels": int(labels[final_train_mask].sum()),
                    "selected_threshold": threshold,
                    "calibration_record": json.dumps(threshold_record, sort_keys=True),
                }
            )
    prediction_frame = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    return prediction_frame, pd.DataFrame(folds)


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
            "annual_borrow_rate": float(portfolio["stress_annual_short_borrow_rate"]),
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
    evaluation_sessions: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    portfolio = config["portfolio"]
    initial = float(portfolio["initial_capital_rub"])
    equity = initial
    next_free = pd.Timestamp.min.tz_localize("UTC")
    trades: list[dict[str, Any]] = []
    unresolved = 0
    capacity_rejected = 0
    overlapping_skipped = 0
    maximum_participation = 0.0
    turnover = 0.0
    total_cost = 0.0
    ordered = candidates.sort_values(["entry_at", "candidate_id"], kind="stable")
    for row in ordered.itertuples(index=False):
        if int(row.candidate_id) not in signal_ids:
            continue
        entry_at = pd.Timestamp(row.entry_at)
        if entry_at < next_free:
            overlapping_skipped += 1
            continue
        if not bool(row.execution_observed):
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
        if not np.isfinite(leg_notional) or leg_notional <= 0:
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
        gross_used = leg_notional * leg_count / equity
        gross_profit = float(leg_notional * np.sum(signed_returns))
        traded_notional = float(leg_notional * leg_count + np.sum(exit_notionals))
        trading_cost = traded_notional * float(parameters["one_way_cost_rate"])
        holding_minutes = float(config["timing"]["holding_exact_bars"]) * 10.0
        borrow_cost = (
            leg_notional
            * (leg_count / 2.0)
            * float(parameters["annual_borrow_rate"])
            * holding_minutes
            / (252.0 * 8.0 * 60.0)
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
                "long_tickers": row.long_tickers,
                "short_tickers": row.short_tickers,
                "gross_used": gross_used,
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
    oos_years = tuple(int(year) for year in config["folds"]["expanding_oos_years"])
    all_sessions = (
        sorted(set(evaluation_sessions))
        if evaluation_sessions is not None
        else sorted(
            {
                str(value)
                for value in candidates.loc[
                    candidates["year"].isin(oos_years), "session_date"
                ]
            }
        )
    )
    pnl_by_day = (
        trade_frame.groupby("session_date")["net_profit_rub"].sum().to_dict()
        if not trade_frame.empty
        else {}
    )
    curve_rows = []
    running = initial
    peak = initial
    daily_returns = []
    for session in all_sessions:
        before = running
        running += float(pnl_by_day.get(session, 0.0))
        daily_return = running / before - 1.0 if before else math.nan
        peak = max(peak, running)
        drawdown = running / peak - 1.0 if peak else math.nan
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
    returns_array = np.asarray(daily_returns, dtype=float)
    years_count = len(oos_years)
    total_return = running / initial - 1.0
    cagr = (running / initial) ** (1.0 / years_count) - 1.0 if running > 0 else -1.0
    daily_std = float(np.std(returns_array, ddof=1)) if len(returns_array) > 1 else 0.0
    sharpe = (
        float(np.sqrt(252.0) * np.mean(returns_array) / daily_std)
        if daily_std > 0
        else 0.0
    )
    maximum_drawdown = (
        float(-curve["drawdown"].min()) if not curve.empty else 0.0
    )
    yearly_returns: dict[str, float] = {}
    if not curve.empty:
        curve_dates = pd.to_datetime(curve["session_date"])
        for year in oos_years:
            values = curve.loc[curve_dates.dt.year == year, "daily_return"].to_numpy()
            yearly_returns[str(year)] = float(np.prod(1.0 + values) - 1.0) if len(values) else 0.0
    metrics = {
        "variant": variant,
        "scenario": scenario,
        "signal_count": len(signal_ids),
        "completed_trades": len(trade_frame),
        "unresolved_count": unresolved,
        "capacity_rejected_count": capacity_rejected,
        "overlapping_skipped_count": overlapping_skipped,
        "coverage": len(trade_frame) / max(1, len(trade_frame) + unresolved),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": maximum_drawdown,
        "yearly_returns": yearly_returns,
        "positive_years": sum(value > 0 for value in yearly_returns.values()),
        "turnover_rub": turnover,
        "costs_rub": total_cost,
        "maximum_participation": maximum_participation,
        "ending_equity_rub": running,
    }
    return trade_frame, curve, metrics
