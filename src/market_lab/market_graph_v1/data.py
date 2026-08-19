"""Sealed, development-only data assembly for market-graph-v1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = PROJECT_ROOT / "configs/market_graph_v1.yaml"
PROTOCOL_SHA256 = "4ced820c7ec5f589a5fe7f6cc4a797b65ed3013d6b4aaa3a169d0ca225819344"


def sha256_file(path: Path) -> str:
    """Return the exact SHA-256 of a local artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class MarketGraphArrays:
    """Dense common-calendar panel; targets are kept outside inference views."""

    dates: np.ndarray
    tickers: tuple[str, ...]
    feature_names: tuple[str, ...]
    asset_feature_count: int
    features: np.ndarray
    feature_mask: np.ndarray
    asset_mask: np.ndarray
    correlation_returns: np.ndarray
    targets: np.ndarray
    target_mask: np.ndarray
    entry_open: np.ndarray
    raw_open: np.ndarray
    raw_value: np.ndarray
    exit_index: np.ndarray

    def __post_init__(self) -> None:
        days, assets, features = self.features.shape
        expected = (days, assets)
        if self.feature_mask.shape != self.features.shape:
            raise ValueError("feature_mask shape does not match features")
        for name in (
            "asset_mask",
            "correlation_returns",
            "targets",
            "target_mask",
            "entry_open",
            "raw_open",
            "raw_value",
            "exit_index",
        ):
            if getattr(self, name).shape != expected:
                raise ValueError(f"{name} shape does not match common panel")
        if len(self.dates) != days or len(self.tickers) != assets:
            raise ValueError("date/ticker axes do not match feature tensor")
        if len(self.feature_names) != features:
            raise ValueError("feature_names do not match feature tensor")


@dataclass(frozen=True, slots=True)
class FoldDefinition:
    """One fixed expanding outer fold and its train-only scalers."""

    year: int
    train_indices: np.ndarray
    test_indices: np.ndarray
    feature_median: np.ndarray
    feature_iqr: np.ndarray
    factor_iqr: float
    residual_iqr: float


@dataclass(frozen=True, slots=True)
class InferenceArrays:
    """Target-free input accepted by prediction code."""

    normalized_features: np.ndarray
    feature_mask: np.ndarray
    asset_mask: np.ndarray
    correlations: np.ndarray


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    """Load the byte-sealed protocol and fail closed on any identity drift."""
    path = path.resolve()
    if path != PROTOCOL_PATH.resolve():
        raise ValueError("market_graph_v1 only accepts its canonical sealed config")
    actual = sha256_file(path)
    if actual != PROTOCOL_SHA256:
        raise ValueError(f"market_graph_v1 config SHA mismatch: {actual}")
    declared = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if declared != actual:
        raise ValueError("market_graph_v1 sidecar SHA mismatch")
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def _checked_source(config: dict[str, Any]) -> Path:
    source = config["source"]
    panel_path = (PROJECT_ROOT / source["panel_path"]).resolve()
    manifest_path = (PROJECT_ROOT / source["manifest_path"]).resolve()
    if "sequence_10m" in str(panel_path).lower():
        raise ValueError("protected sequence_10m inputs are forbidden")
    if sha256_file(panel_path) != source["panel_sha256"]:
        raise ValueError("market_graph_v1 panel SHA mismatch")
    if panel_path.stat().st_size != int(source["panel_bytes"]):
        raise ValueError("market_graph_v1 panel byte count mismatch")
    if sha256_file(manifest_path) != source["manifest_sha256"]:
        raise ValueError("market_graph_v1 manifest SHA mismatch")
    return panel_path


def load_market_graph_arrays(
    config: dict[str, Any] | None = None,
) -> MarketGraphArrays:
    """Read only the sealed development panel and construct all-asset tensors."""
    config = load_protocol() if config is None else config
    panel_path = _checked_source(config)
    tickers = tuple(config["universe"]["tickers"])
    asset_columns = tuple(config["features"]["asset_columns"])
    context_columns = tuple(config["features"]["market_context_columns"])
    feature_names = asset_columns + context_columns
    columns = list(
        dict.fromkeys(
            [
                "session_date",
                "ticker",
                "daily_available",
                "entry_available",
                "raw_target_return",
                "return_1",
                "entry_open",
                "raw_open",
                "raw_value",
                "exit_session",
                *feature_names,
            ]
        )
    )
    frame = pd.read_parquet(panel_path, columns=columns)
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if len(frame) != int(config["source"]["panel_rows"]):
        raise ValueError("market_graph_v1 panel row count mismatch")
    if frame.duplicated(["session_date", "ticker"]).any():
        raise ValueError("market_graph_v1 panel has duplicate date/ticker rows")
    if set(frame["ticker"].unique()) != set(tickers):
        raise ValueError("market_graph_v1 ticker universe mismatch")
    dates = np.array(sorted(frame["session_date"].unique()), dtype="datetime64[ns]")
    if len(dates) * len(tickers) != len(frame):
        raise ValueError("market_graph_v1 must be a complete common-calendar grid")
    minimum = np.datetime64(config["source"]["minimum_date"])
    maximum = np.datetime64(config["source"]["maximum_date"])
    if dates[0] != minimum or dates[-1] != maximum or dates[-1] >= np.datetime64("2026-01-01"):
        raise ValueError("market_graph_v1 development boundary mismatch")

    date_order = {value: index for index, value in enumerate(dates)}
    ticker_order = {ticker: index for index, ticker in enumerate(tickers)}
    frame["_date_index"] = frame["session_date"].map(
        lambda value: date_order[np.datetime64(value, "ns")]
    )
    frame["_ticker_index"] = frame["ticker"].map(ticker_order)
    frame = frame.sort_values(["_date_index", "_ticker_index"], kind="mergesort")
    if not np.array_equal(
        frame["_date_index"].to_numpy(), np.repeat(np.arange(len(dates)), len(tickers))
    ):
        raise ValueError("market_graph_v1 date axis is incomplete")
    if not np.array_equal(
        frame["_ticker_index"].to_numpy(), np.tile(np.arange(len(tickers)), len(dates))
    ):
        raise ValueError("market_graph_v1 ticker axis is incomplete")

    shape = (len(dates), len(tickers))
    raw_features = frame.loc[:, feature_names].apply(pd.to_numeric, errors="coerce").to_numpy()
    raw_features = raw_features.reshape(*shape, len(feature_names)).astype(np.float32)
    finite_features = np.isfinite(raw_features)
    asset_mask = frame["daily_available"].eq(1.0).to_numpy().reshape(shape)
    feature_mask = finite_features & asset_mask[:, :, None]
    features = np.where(feature_mask, raw_features, 0.0).astype(np.float32)
    targets = pd.to_numeric(frame["raw_target_return"], errors="coerce").to_numpy().reshape(shape)
    entry_available = frame["entry_available"].fillna(False).astype(bool).to_numpy().reshape(shape)
    target_mask = asset_mask & entry_available & np.isfinite(targets)
    targets = np.where(target_mask, targets, 0.0).astype(np.float32)

    def matrix(column: str, *, fill: float = np.nan) -> np.ndarray:
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy().reshape(shape)
        return np.where(np.isfinite(values), values, fill).astype(np.float32)

    exits = pd.to_datetime(frame["exit_session"], errors="coerce").to_numpy().reshape(shape)
    exit_index = np.full(shape, -1, dtype=np.int32)
    for date_index in range(len(dates)):
        for asset_index in range(len(tickers)):
            value = exits[date_index, asset_index]
            if not np.isnat(value):
                exit_index[date_index, asset_index] = date_order.get(np.datetime64(value, "ns"), -1)

    return MarketGraphArrays(
        dates=dates,
        tickers=tickers,
        feature_names=feature_names,
        asset_feature_count=len(asset_columns),
        features=features,
        feature_mask=feature_mask,
        asset_mask=asset_mask,
        correlation_returns=matrix("return_1"),
        targets=targets,
        target_mask=target_mask,
        entry_open=matrix("entry_open"),
        raw_open=matrix("raw_open"),
        raw_value=matrix("raw_value", fill=0.0),
        exit_index=exit_index,
    )


def causal_correlations(
    returns: np.ndarray,
    asset_mask: np.ndarray,
    *,
    lookback: int = 60,
    minimum_observations: int = 40,
    clipping: tuple[float, float] = (-0.8, 0.8),
) -> np.ndarray:
    """Compute pairwise rolling correlations using dates no later than each decision."""
    if returns.shape != asset_mask.shape:
        raise ValueError("returns and asset_mask shapes must match")
    days, assets = returns.shape
    result = np.zeros((days, assets, assets), dtype=np.float32)
    observed = np.isfinite(returns) & asset_mask
    values = np.where(observed, returns, 0.0).astype(np.float64)
    for date_index in range(days):
        start = max(0, date_index - lookback + 1)
        x = values[start : date_index + 1]
        m = observed[start : date_index + 1].astype(np.float64)
        count = m.T @ m
        sx = x.T @ m
        sy = sx.T
        sxx = np.square(x).T @ m
        syy = sxx.T
        sxy = x.T @ x
        safe_count = np.maximum(count, 1.0)
        covariance = sxy - sx * sy / safe_count
        variance_x = np.maximum(sxx - np.square(sx) / safe_count, 0.0)
        variance_y = np.maximum(syy - np.square(sy) / safe_count, 0.0)
        denominator = np.sqrt(variance_x * variance_y)
        correlation = np.divide(
            covariance,
            denominator,
            out=np.zeros_like(covariance),
            where=(count >= minimum_observations) & (denominator > 1e-12),
        )
        correlation = np.clip(correlation, clipping[0], clipping[1])
        np.fill_diagonal(
            correlation,
            np.where(np.diag(count) >= minimum_observations, clipping[1], 0.0),
        )
        result[date_index] = correlation.astype(np.float32)
    return result


def _robust_feature_scaler(
    arrays: MarketGraphArrays,
    last_train_index: int,
) -> tuple[np.ndarray, np.ndarray]:
    values = arrays.features[: last_train_index + 1]
    masks = arrays.feature_mask[: last_train_index + 1]
    median = np.zeros(values.shape[-1], dtype=np.float32)
    iqr = np.ones(values.shape[-1], dtype=np.float32)
    for feature_index in range(values.shape[-1]):
        sample = values[:, :, feature_index][masks[:, :, feature_index]]
        if len(sample) < 40:
            continue
        q25, q50, q75 = np.quantile(sample.astype(np.float64), [0.25, 0.5, 0.75])
        median[feature_index] = float(q50)
        iqr[feature_index] = max(float(q75 - q25), 1e-6)
    return median, iqr


def _target_scales(
    arrays: MarketGraphArrays,
    train_indices: np.ndarray,
) -> tuple[float, float]:
    factors: list[float] = []
    residuals: list[np.ndarray] = []
    for index in train_indices:
        mask = arrays.target_mask[index]
        if not mask.any():
            continue
        factor = float(arrays.targets[index, mask].mean())
        factors.append(factor)
        residuals.append(arrays.targets[index, mask] - factor)
    if not factors or not residuals:
        raise ValueError("no train targets for target scaling")
    factor_q = np.quantile(np.asarray(factors), [0.25, 0.75])
    residual_q = np.quantile(np.concatenate(residuals), [0.25, 0.75])
    return (
        max(float(factor_q[1] - factor_q[0]), 1e-4),
        max(float(residual_q[1] - residual_q[0]), 1e-4),
    )


def build_folds(
    arrays: MarketGraphArrays,
    config: dict[str, Any],
) -> tuple[FoldDefinition, ...]:
    """Build the fixed expanding 2021-2025 folds with a conservative train gap."""
    history = int(config["features"]["history_sessions"])
    purge = int(config["folds"]["purge_sessions"])
    embargo = int(config["folds"]["embargo_sessions"])
    years = np.array([pd.Timestamp(value).year for value in arrays.dates])
    folds: list[FoldDefinition] = []
    for year in config["folds"]["expanding_outer_years"]:
        test = np.flatnonzero(years == int(year))
        test = test[test >= history - 1]
        if len(test) == 0:
            raise ValueError(f"empty OOS fold {year}")
        last_train = int(test[0]) - purge - embargo - 1
        train = np.arange(history - 1, last_train + 1, dtype=np.int64)
        train = train[arrays.target_mask[train].any(axis=1)]
        if len(train) == 0:
            raise ValueError(f"empty train fold {year}")
        median, iqr = _robust_feature_scaler(arrays, int(train[-1]))
        factor_iqr, residual_iqr = _target_scales(arrays, train)
        folds.append(
            FoldDefinition(
                year=int(year),
                train_indices=train,
                test_indices=test.astype(np.int64),
                feature_median=median,
                feature_iqr=iqr,
                factor_iqr=factor_iqr,
                residual_iqr=residual_iqr,
            )
        )
    return tuple(folds)


def inference_arrays(
    arrays: MarketGraphArrays,
    fold: FoldDefinition,
    correlations: np.ndarray,
) -> InferenceArrays:
    """Normalize features with train-only statistics and expose no targets."""
    scaled = (arrays.features - fold.feature_median[None, None, :]) / fold.feature_iqr[
        None, None, :
    ]
    scaled = np.clip(scaled, -10.0, 10.0)
    normalized = np.where(arrays.feature_mask, scaled, 0.0).astype(np.float32)
    return InferenceArrays(
        normalized_features=normalized,
        feature_mask=arrays.feature_mask,
        asset_mask=arrays.asset_mask,
        correlations=correlations,
    )


def causal_feature_window(
    inference: InferenceArrays,
    decision_index: int,
    history: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return one all-asset window ending exactly at the decision cutoff."""
    if decision_index < history - 1:
        raise ValueError("insufficient causal history")
    start = decision_index - history + 1
    features = inference.normalized_features[start : decision_index + 1]
    masks = inference.asset_mask[start : decision_index + 1]
    return features.transpose(1, 0, 2).copy(), masks.transpose(1, 0).copy()


def relative_momentum_scores(arrays: MarketGraphArrays) -> np.ndarray:
    """Fixed equal blend of within-date ranks for 20/60/120-session momentum."""
    indices = [arrays.feature_names.index(f"return_{horizon}") for horizon in (20, 60, 120)]
    scores = np.zeros(arrays.asset_mask.shape, dtype=np.float32)
    for date_index in range(len(arrays.dates)):
        parts: list[np.ndarray] = []
        for feature_index in indices:
            valid = (
                arrays.asset_mask[date_index] & arrays.feature_mask[date_index, :, feature_index]
            )
            values = arrays.features[date_index, :, feature_index]
            rank = np.zeros(len(arrays.tickers), dtype=np.float64)
            if valid.sum() >= 2:
                rank[valid] = (
                    pd.Series(values[valid]).rank(pct=True, method="average").to_numpy() - 0.5
                )
            parts.append(rank)
        scores[date_index] = np.mean(parts, axis=0).astype(np.float32)
        scores[date_index, ~arrays.asset_mask[date_index]] = 0.0
    return scores
