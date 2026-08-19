"""Priznaki i targety bez zaglyadyvaniya za tekushchii close."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from market_lab.data.moex import validate_market_frame

RETURN_LAGS = (1, 3, 6, 12, 24, 48, 96)  # Lagi log-dohodnosti v 10m-barah.
VOLATILITY_WINDOWS = (6, 24, 96)  # Okna realizovannoi volatil'nosti.
NORMALIZATION_WINDOWS = (24, 96)  # Okna lokal'noi normalizacii obema i oborota.
INTRADAY_BARS_PER_HOUR = 6  # Chislo desyatiminutnyh barov v chase.
BAR_MINUTES = 10  # Dlitel'nost' odnogo bazovogo bara.
SESSION_START_MINUTE = 9 * 60 + 50  # Nachalo obshei setki MOEX po moskovskomu vremeni.
FEATURE_COLUMNS = (  # Polnyi i zafiksirovannyi vhod causal-TCN.
    *(f"return_{lag}" for lag in RETURN_LAGS),
    "open_gap",
    "candle_range",
    "candle_body",
    "close_location",
    *(f"volatility_{window}" for window in VOLATILITY_WINDOWS),
    *(f"volume_z_{window}" for window in NORMALIZATION_WINDOWS),
    *(f"value_z_{window}" for window in NORMALIZATION_WINDOWS),
    "time_sin",
    "time_cos",
    "weekday_sin",
    "weekday_cos",
    "bar_available",
    "staleness_bars",
    "cross_rank_return_1",
    "cross_rank_return_6",
    "cross_rank_volume",
    "market_return_1",
    "market_return_6",
    "market_volatility_24",
)


@dataclass(frozen=True)
class FeatureScaler:
    """Hranit train-only median i robustnyi masshtab kazhdogo priznaka."""

    median: np.ndarray
    scale: np.ndarray
    columns: tuple[str, ...] = FEATURE_COLUMNS

    def transform(self, values: np.ndarray) -> np.ndarray:
        """Normalizuet i ogranichivaet vybrosy bez izmeneniya ishodnika."""
        transformed = (values.astype(np.float32, copy=False) - self.median) / self.scale
        return np.clip(transformed, -10.0, 10.0).astype(np.float32, copy=False)

    def as_dict(self) -> dict[str, object]:
        """Vozvrashchaet serializuemoe predstavlenie scaler-a."""
        return {
            "columns": list(self.columns),
            "median": self.median.tolist(),
            "scale": self.scale.tolist(),
            "method": "train-only median/IQR, clipped to [-10, 10]",
        }


def _rolling_robust_z(series: pd.Series, window: int) -> pd.Series:
    """Schitaet istoricheskii z-score log-velichiny po median i IQR."""
    logged = np.log1p(series.clip(lower=0.0))
    rolling = logged.rolling(window, min_periods=window)
    median = rolling.median()
    q75 = rolling.quantile(0.75)
    q25 = rolling.quantile(0.25)
    scale = (q75 - q25).clip(lower=1e-6)
    return (logged - median) / scale


def build_asset_features(
    frame: pd.DataFrame,
    ticker: str,
    horizon_bars: int,
    calendar_index: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Stroit causal-priznaki i target na obshei wall-clock setke."""
    checked = validate_market_frame(frame)
    if calendar_index is None:
        calendar = checked.index
    else:
        calendar = pd.DatetimeIndex(calendar_index).sort_values().unique()
        if calendar.tz is None:
            raise ValueError("Obshchii sequence-kalendar dolzhen byt timezone-aware")
    result = checked.reindex(calendar)
    execution_open = result["open"].copy()
    available = execution_open.notna()
    last_close = result["close"].ffill()
    for column in ("open", "high", "low", "close"):
        result[column] = result[column].where(available, last_close)
    result["volume"] = result["volume"].fillna(0.0)
    result["value"] = result["value"].fillna(0.0)
    result["bar_available"] = available.astype(float)
    result["staleness_bars"] = (
        (~available).astype(int).groupby(available.astype(int).cumsum()).cumsum().astype(float)
    )
    local_index = result.index.tz_convert("Europe/Moscow")
    local_dates = pd.Series(local_index.date, index=result.index)
    log_close = np.log(result["close"])
    one_return = log_close.diff().clip(-0.20, 0.20)
    for lag in RETURN_LAGS:
        result[f"return_{lag}"] = (log_close - log_close.shift(lag)).clip(-0.50, 0.50)
    result["open_gap"] = np.log(result["open"] / result["close"].shift(1)).clip(-0.20, 0.20)
    result["candle_range"] = np.log(result["high"] / result["low"]).clip(0.0, 0.20)
    result["candle_body"] = np.log(result["close"] / result["open"]).clip(-0.20, 0.20)
    spread = (result["high"] - result["low"]).replace(0.0, np.nan)
    result["close_location"] = (
        (result["close"] - result["low"]) / spread - 0.5
    ).fillna(0.0)
    for window in VOLATILITY_WINDOWS:
        result[f"volatility_{window}"] = one_return.rolling(
            window, min_periods=window
        ).std()
    for window in NORMALIZATION_WINDOWS:
        result[f"volume_z_{window}"] = _rolling_robust_z(result["volume"], window)
        result[f"value_z_{window}"] = _rolling_robust_z(result["value"], window)
    minute = local_index.hour * 60 + local_index.minute
    time_angle = 2.0 * np.pi * minute / (24.0 * 60.0)
    result["time_sin"] = np.sin(time_angle)
    result["time_cos"] = np.cos(time_angle)
    weekday_angle = 2.0 * np.pi * local_index.dayofweek / 5.0
    result["weekday_sin"] = np.sin(weekday_angle)
    result["weekday_cos"] = np.cos(weekday_angle)
    entry_times = result.index + pd.Timedelta(minutes=BAR_MINUTES)
    exit_times = entry_times + pd.Timedelta(minutes=BAR_MINUTES * horizon_bars)
    result["entry_open"] = execution_open.reindex(entry_times).to_numpy()
    result["exit_open"] = execution_open.reindex(exit_times).to_numpy()
    result["entry_time"] = entry_times
    result["exit_time"] = exit_times
    exit_local_date = pd.Series(
        exit_times.tz_convert("Europe/Moscow").date,
        index=result.index,
    )
    result["target_return"] = result["exit_open"] / result["entry_open"] - 1.0
    result.loc[exit_local_date != local_dates, "target_return"] = np.nan
    result["ticker"] = ticker
    result["local_date"] = pd.to_datetime(local_dates.to_numpy())
    result["slot"] = ((minute - SESSION_START_MINUTE) // BAR_MINUTES).astype(int)
    result.index.name = "timestamp"
    return result.reset_index()


def add_cross_section_features(
    panel: pd.DataFrame,
    target_mode: Literal["absolute", "cross_section_residual"] = "absolute",
) -> pd.DataFrame:
    """Dobavlyaet causal-agregaty i otdel'nyi model-target zadannogo rezhima."""
    result = panel.copy()
    grouped = result.groupby("timestamp", sort=False)
    result["cross_rank_return_1"] = grouped["return_1"].rank(pct=True) - 0.5
    result["cross_rank_return_6"] = grouped["return_6"].rank(pct=True) - 0.5
    result["cross_rank_volume"] = grouped["volume_z_24"].rank(pct=True) - 0.5
    result["market_return_1"] = grouped["return_1"].transform("median")
    result["market_return_6"] = grouped["return_6"].transform("median")
    result["market_volatility_24"] = grouped["volatility_24"].transform("median")
    if target_mode == "absolute":
        result["model_target"] = result["target_return"]
    elif target_mode == "cross_section_residual":
        target_median = grouped["target_return"].transform("median")
        result["model_target"] = result["target_return"] - target_median
    else:
        raise ValueError(f"Neizvestnyi target_mode: {target_mode}")
    return result.sort_values(["ticker", "timestamp"], kind="mergesort").reset_index(drop=True)


def fit_feature_scaler(panel: pd.DataFrame, train_end: date) -> FeatureScaler:
    """Ocenivaet robustnye parametry iskluchitel'no na train-periode."""
    train = panel.loc[panel["local_date"] <= pd.Timestamp(train_end), FEATURE_COLUMNS]
    values = train.to_numpy(dtype=np.float64)
    median = np.nanmedian(values, axis=0)
    q75 = np.nanpercentile(values, 75.0, axis=0)
    q25 = np.nanpercentile(values, 25.0, axis=0)
    scale = q75 - q25
    scale[~np.isfinite(scale) | (scale < 1e-6)] = 1.0
    if not np.isfinite(median).all():
        raise ValueError("Train-period ne pozvolil ocenit' vse mediany priznakov")
    return FeatureScaler(median=median.astype(np.float32), scale=scale.astype(np.float32))


def complete_feature_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Udalyaet stroki bez polnogo istoricheskogo vhoda ili targeta."""
    required = [
        *FEATURE_COLUMNS,
        "target_return",
        "model_target",
        "entry_open",
        "exit_open",
    ]
    return panel.dropna(subset=required).copy()
