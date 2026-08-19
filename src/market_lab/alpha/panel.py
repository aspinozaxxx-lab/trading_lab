"""Postroenie dnevnogo decision-panel iz chasovyh svechei."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab.alpha.config import AlphaConfig
from market_lab.data.moex import validate_market_frame

DAILY_LAGS = (1, 2, 5, 10, 20, 60, 120)  # Lagi dohodnosti v torgovyh dnyah.
ROLLING_WINDOWS = (5, 10, 20, 60)  # Okna riskov i otnoshenii v torgovyh dnyah.
CROSS_SECTION_SOURCES = (  # Priznaki dlya otnositel'nogo ranzhirovaniya.
    "ret_5d",
    "ret_20d",
    "ret_60d",
    "ret_120d",
    "vol_20d",
    "volume_20d",
)
BASE_FEATURE_COLUMNS = (  # Bazovye priznaki odnogo instrumenta.
    *(f"ret_{lag}d" for lag in DAILY_LAGS),
    *(f"vol_{window}d" for window in ROLLING_WINDOWS),
    *(f"sma_{window}d" for window in ROLLING_WINDOWS),
    *(f"volume_{window}d" for window in ROLLING_WINDOWS),
    "range_1d",
    "body_1d",
    "close_location_1d",
    "weekday",
    "month_sin",
    "month_cos",
)
MODEL_FEATURE_COLUMNS = (  # Polnyi spisok priznakov tablichnoi modeli.
    *BASE_FEATURE_COLUMNS,
    *(f"cs_{source}" for source in CROSS_SECTION_SOURCES),
    "market_ret_20d",
)


def alpha_cache_path(config: AlphaConfig, ticker: str) -> Path:
    """Vozvrashchaet ozhidaemyi put chasovogo Parquet-kesha."""
    protocol = config.protocol
    universe = config.universe
    stem = (
        f"{ticker}_{universe.board}_{universe.timeframe}_"
        f"{protocol.data_start.isoformat()}_{protocol.test_end.isoformat()}.parquet"
    )
    return config.paths.processed_data_dir / stem


def sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 binarnogo faila bez zagruzki ego celikom v pamyat'."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _daily_aggregate(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Szhimaet chasy v polnye moskovskie dni i vozvrashchaet last-pozicii."""
    local_dates = pd.Index(frame.index.tz_convert("Europe/Moscow").date, name="decision_date")
    positions = pd.Series(np.arange(len(frame)), index=local_dates)
    first_positions = positions.groupby(level=0, sort=True).first().to_numpy()
    last_positions = positions.groupby(level=0, sort=True).last().to_numpy()
    grouped = frame.groupby(local_dates, sort=True)
    daily = pd.DataFrame(
        {
            "open": frame["open"].iloc[first_positions].to_numpy(),
            "high": grouped["high"].max().to_numpy(),
            "low": grouped["low"].min().to_numpy(),
            "close": frame["close"].iloc[last_positions].to_numpy(),
            "volume": grouped["volume"].sum().to_numpy(),
            "value": grouped["value"].sum().to_numpy(),
            "decision_time": frame.index[last_positions],
        },
        index=pd.DatetimeIndex(pd.to_datetime(local_dates[last_positions]), name="decision_date"),
    )
    return daily, last_positions


def build_asset_decisions(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Stroit priznaki na close i target mezhdu dvumya budushchimi open."""
    checked = validate_market_frame(frame)
    daily, last_positions = _daily_aggregate(checked)
    next_hour_open = checked["open"].shift(-1).iloc[last_positions].to_numpy()
    next_hour_time = pd.Series(checked.index, index=checked.index).shift(-1).iloc[last_positions]
    daily["entry_open"] = next_hour_open
    daily["entry_time"] = next_hour_time.to_numpy()
    daily["target_return"] = daily["entry_open"].shift(-1) / daily["entry_open"] - 1.0
    daily["exit_open"] = daily["entry_open"].shift(-1)
    daily["exit_time"] = daily["entry_time"].shift(-1)
    daily["ticker"] = ticker
    close_return = daily["close"].pct_change()
    for lag in DAILY_LAGS:
        daily[f"ret_{lag}d"] = daily["close"].pct_change(lag)
    for window in ROLLING_WINDOWS:
        daily[f"vol_{window}d"] = close_return.rolling(window).std()
        daily[f"sma_{window}d"] = daily["close"] / daily["close"].rolling(window).mean() - 1.0
        daily[f"volume_{window}d"] = (
            daily["volume"] / daily["volume"].rolling(window).mean() - 1.0
        )
    spread = (daily["high"] - daily["low"]).replace(0.0, np.nan)
    daily["range_1d"] = spread / daily["close"]
    daily["body_1d"] = (daily["close"] - daily["open"]) / daily["open"]
    daily["close_location_1d"] = (daily["close"] - daily["low"]) / spread - 0.5
    daily["weekday"] = daily.index.dayofweek.astype(float)
    angle = 2.0 * np.pi * (daily.index.month.astype(float) - 1.0) / 12.0
    daily["month_sin"] = np.sin(angle)
    daily["month_cos"] = np.cos(angle)
    return daily.reset_index()


def add_cross_section_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Dobavlyaet tol'ko odnovremennye rangi i rynochnoe sostoyanie."""
    result = panel.copy()
    for source in CROSS_SECTION_SOURCES:
        result[f"cs_{source}"] = (
            result.groupby("decision_date")[source].rank(pct=True) - 0.5
        )
    result["market_ret_20d"] = result.groupby("decision_date")["ret_20d"].transform(
        "mean"
    )
    return result


def load_panel(
    config: AlphaConfig,
    tickers: list[str],
    end_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chitaet ukazannyi universum do granicy i vozvrashchaet panel s manifestom."""
    parts: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []
    for ticker in tickers:
        path = alpha_cache_path(config, ticker)
        if not path.exists():
            raise FileNotFoundError(f"Net alpha-kesha dlya {ticker}: {path}")
        frame = pd.read_parquet(path)
        frame = frame.loc[frame.index <= end_date]
        decisions = build_asset_decisions(frame, ticker)
        parts.append(decisions)
        manifest_rows.append(
            {
                "ticker": ticker,
                "path": str(path),
                "sha256": sha256_file(path),
                "source_rows_used": len(frame),
                "first_timestamp_used": frame.index.min(),
                "last_timestamp_used": frame.index.max(),
                "decision_rows": len(decisions),
            }
        )
    panel = add_cross_section_features(pd.concat(parts, ignore_index=True))
    panel = panel.sort_values(["decision_date", "ticker"], kind="mergesort").reset_index(
        drop=True
    )
    return panel, pd.DataFrame(manifest_rows)


def complete_model_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """Udalyaet tol'ko stroki bez priznakov ili budushchego targeta."""
    required = [*MODEL_FEATURE_COLUMNS, "target_return", "entry_open", "exit_open"]
    return panel.dropna(subset=required).copy()
