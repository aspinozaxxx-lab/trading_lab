"""Expanding-year competing-risk model with train-only Platt calibration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression

from market_lab.futures_v9_corridor.labels import CorridorEvent

RANDOM_STATE: Final[int] = 90_421
OOS_YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025)
SIGNED_FEATURES: Final[tuple[str, ...]] = (
    "momentum_1",
    "momentum_5",
    "momentum_20",
    "overnight_gap",
    "intraday_return",
    "first_hour_return",
    "last_hour_return",
    "carry_z",
    "cftc_z",
    "usd_rub_return_z",
)
UNSIGNED_FEATURES: Final[tuple[str, ...]] = (
    "atr_fraction",
    "daily_volatility_20",
    "range_position_20",
    "volatility_ratio_20",
    "volume_ratio_20",
    "close_location",
    "up_bar_fraction",
    "max_abs_bar_return",
    "intraday_return_skew",
    "regime_normal_probability",
    "regime_trend_probability",
    "regime_crash_probability",
    "key_rate_sleeping",
    "main_session_coverage",
)


@dataclass(frozen=True, slots=True)
class FoldAudit:
    """Temporal and calibration proof for one OOS calendar year."""

    corridor_id: str
    oos_year: int
    train_rows: int
    calibration_rows: int
    oos_rows: int
    train_label_latest_at: datetime
    calibration_label_latest_at: datetime
    threshold: float
    calibration_brier: float
    calibration_daily_max_count: int


@dataclass(frozen=True, slots=True)
class ModelResult:
    """All candidate probabilities and explicit train-only fold audits."""

    predictions: pd.DataFrame
    folds: tuple[FoldAudit, ...]
    feature_names: tuple[str, ...]


def _model_frame(features: pd.DataFrame, labels: pd.DataFrame, corridor_id: str) -> pd.DataFrame:
    selected = labels[
        (labels["corridor_id"] == corridor_id) & labels["label_resolved"].astype(bool)
    ].copy()
    frame = selected.merge(
        features,
        on=["decision_at", "decision_date", "asset"],
        how="inner",
        validate="many_to_one",
        suffixes=("", "_feature"),
    )
    frame = frame[frame["market_valid"].astype(bool)].copy()
    frame["direction_sign"] = frame["direction"].map({"long": 1.0, "short": -1.0})
    frame["atr_fraction"] = frame["atr_20"] / frame["adjusted_close"]
    frame["main_session_coverage"] = frame["main_session_bucket_count"] / 53.0
    for name in SIGNED_FEATURES:
        frame[f"signed_{name}"] = frame[name] * frame["direction_sign"]
    for asset in ("BR", "MIX", "RI", "SI"):
        frame[f"asset_{asset}"] = (frame["asset"] == asset).astype(float)
    frame["event_class"] = frame["event_type"].map(
        {
            CorridorEvent.TAKE_PROFIT.value: 0,
            CorridorEvent.STOP_LOSS.value: 1,
            CorridorEvent.TIME_EXIT.value: 2,
        }
    )
    if frame["event_class"].isna().any():
        raise ValueError("resolved model rows contain an unknown competing event")
    frame["event_class"] = frame["event_class"].astype(int)
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], utc=True)
    frame["event_at"] = pd.to_datetime(frame["event_at"], utc=True)
    return frame.sort_values(["decision_at", "asset", "direction"], kind="stable")


def _feature_columns() -> tuple[str, ...]:
    return (
        *UNSIGNED_FEATURES,
        *(f"signed_{name}" for name in SIGNED_FEATURES),
        "direction_sign",
        "asset_BR",
        "asset_MIX",
        "asset_RI",
        "asset_SI",
    )


def _probability_for_class(
    probabilities: np.ndarray,
    classes: np.ndarray,
    event_class: int,
) -> np.ndarray:
    matches = np.flatnonzero(classes == event_class)
    if len(matches) != 1:
        raise ValueError(f"fitted model lacks competing event class {event_class}")
    return probabilities[:, int(matches[0])]


def _platt_fit(raw_probability: np.ndarray, target: np.ndarray) -> LogisticRegression:
    clipped = np.clip(raw_probability, 1e-6, 1.0 - 1e-6)
    logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    if np.unique(target).size != 2:
        raise ValueError("calibration slice must contain TP and non-TP events")
    calibrator = LogisticRegression(
        C=1.0,
        solver="lbfgs",
        max_iter=1_000,
        random_state=RANDOM_STATE,
    )
    calibrator.fit(logit, target)
    return calibrator


def _platt_predict(calibrator: LogisticRegression, raw_probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(raw_probability, 1e-6, 1.0 - 1e-6)
    logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    return calibrator.predict_proba(logit)[:, 1]


def fit_expanding_corridor_models(
    features: pd.DataFrame,
    labels: pd.DataFrame,
) -> ModelResult:
    """Fit primary and diagnostic models with no OOS label/threshold access."""
    columns = _feature_columns()
    prediction_frames: list[pd.DataFrame] = []
    audits: list[FoldAudit] = []
    for corridor_id in ("primary", "safer_diagnostic"):
        frame = _model_frame(features, labels, corridor_id)
        for year in OOS_YEARS:
            calibration_year = year - 1
            calibration_start = pd.Timestamp(
                datetime(calibration_year, 1, 1, tzinfo=UTC)
            )
            oos_start = pd.Timestamp(datetime(year, 1, 1, tzinfo=UTC))
            oos_end = pd.Timestamp(datetime(year + 1, 1, 1, tzinfo=UTC))
            train = frame[
                (frame["decision_at"] < calibration_start)
                & (frame["event_at"] < calibration_start)
            ]
            calibration = frame[
                (frame["decision_at"] >= calibration_start)
                & (frame["decision_at"] < oos_start)
                & (frame["event_at"] < oos_start)
            ]
            oos = frame[(frame["decision_at"] >= oos_start) & (frame["decision_at"] < oos_end)]
            if min(len(train), len(calibration), len(oos)) == 0:
                raise ValueError(f"empty expanding split for {corridor_id}/{year}")
            imputer = SimpleImputer(
                strategy="median",
                add_indicator=True,
                keep_empty_features=True,
            )
            x_train = imputer.fit_transform(train.loc[:, columns])
            x_calibration = imputer.transform(calibration.loc[:, columns])
            x_oos = imputer.transform(oos.loc[:, columns])
            model = HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=160,
                max_leaf_nodes=15,
                min_samples_leaf=40,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )
            model.fit(x_train, train["event_class"].to_numpy())
            calibration_raw_all = model.predict_proba(x_calibration)
            calibration_raw_tp = _probability_for_class(
                calibration_raw_all, model.classes_, 0
            )
            calibrator = _platt_fit(
                calibration_raw_tp,
                (calibration["event_class"].to_numpy() == 0).astype(int),
            )
            calibration_probability = _platt_predict(calibrator, calibration_raw_tp)
            calibration_scores = calibration[["decision_at"]].copy()
            calibration_scores["score"] = calibration_probability
            daily_max = calibration_scores.groupby("decision_at", sort=True)["score"].max()
            threshold = float(daily_max.quantile(0.90, interpolation="linear"))
            oos_raw_all = model.predict_proba(x_oos)
            oos_probability = _platt_predict(
                calibrator, _probability_for_class(oos_raw_all, model.classes_, 0)
            )
            output = oos[
                [
                    "decision_at",
                    "decision_date",
                    "asset",
                    "direction",
                    "corridor_id",
                    "contract_id",
                    "event_type",
                    "event_at",
                    "entry_price",
                    "exit_price",
                    "gross_price_pnl",
                    "entry_volume",
                    "same_bar_collision",
                ]
            ].copy()
            output["fold_year"] = year
            output["calibrated_tp_probability"] = oos_probability
            output["raw_tp_probability"] = _probability_for_class(
                oos_raw_all, model.classes_, 0
            )
            output["raw_stop_probability"] = _probability_for_class(
                oos_raw_all, model.classes_, 1
            )
            output["raw_time_probability"] = _probability_for_class(
                oos_raw_all, model.classes_, 2
            )
            output["fold_threshold"] = threshold
            output["above_threshold"] = output["calibrated_tp_probability"] >= threshold
            output["daily_model_choice"] = False
            above = output[output["above_threshold"]]
            if not above.empty:
                chosen_indices = above.groupby("decision_at", sort=True)[
                    "calibrated_tp_probability"
                ].idxmax()
                output.loc[chosen_indices, "daily_model_choice"] = True
            prediction_frames.append(output)
            target = (calibration["event_class"].to_numpy() == 0).astype(float)
            audits.append(
                FoldAudit(
                    corridor_id=corridor_id,
                    oos_year=year,
                    train_rows=len(train),
                    calibration_rows=len(calibration),
                    oos_rows=len(oos),
                    train_label_latest_at=pd.Timestamp(train["event_at"].max()).to_pydatetime(),
                    calibration_label_latest_at=pd.Timestamp(
                        calibration["event_at"].max()
                    ).to_pydatetime(),
                    threshold=threshold,
                    calibration_brier=float(np.mean((calibration_probability - target) ** 2)),
                    calibration_daily_max_count=len(daily_max),
                )
            )
    predictions = pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["corridor_id", "decision_at", "asset", "direction"], kind="stable"
    )
    return ModelResult(predictions=predictions, folds=tuple(audits), feature_names=columns)


__all__ = [
    "FoldAudit",
    "ModelResult",
    "OOS_YEARS",
    "fit_expanding_corridor_models",
]
