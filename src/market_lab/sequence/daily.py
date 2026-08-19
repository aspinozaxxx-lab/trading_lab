"""Causal daily-panel dlya medlennogo pyatidnevnogo sequence-protokola."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from market_lab.data.moex import validate_market_frame
from market_lab.sequence.dataset import (
    AssetSequenceArray,
    SequenceSamples,
    SequenceStore,
    select_sequence_samples,
)
from market_lab.sequence.features import FeatureScaler

MOSCOW_TIMEZONE = "Europe/Moscow"  # Chasovoi poyas torgovyh sessii MOEX.
MAIN_SESSION_START_MINUTE = 9 * 60 + 50  # Pervyi 10m-bar osnovnoi sessii.
MAIN_SESSION_LAST_BAR_MINUTE = 18 * 60 + 40  # Poslednii dopustimyi begin bara.
MAIN_SESSION_SIGNAL_MINUTE = 18 * 60 + 50  # Moment posle zakrytiya bara 18:40.
REGULAR_SESSION_OPEN_MINUTE = 9 * 60 + 50  # Planovoe vremya sleduyushchego open.
DEFAULT_HORIZON_SESSIONS = 5  # Bazovyi pyatidnevnyi open-to-open target.
STAGGERED_PHASE_COUNT = 5  # Chislo ezhednevnyh pyatidnevnyh subportfelei.
DAILY_RETURN_LAGS = (1, 2, 5, 10, 20, 60, 120)  # Lagi close-dohodnostei.
DAILY_VOLATILITY_WINDOWS = (5, 20, 60)  # Okna realizovannoi volatil'nosti.
DAILY_SMA_WINDOWS = (5, 20, 60, 120)  # Okna otnosheniya close k SMA.
DAILY_NORMALIZATION_WINDOWS = (20, 60)  # Okna robustnoi normirovki activity.
INTRADAY_SUMMARY_COLUMNS = (  # Causal-svodki formy tekushchei osnovnoi sessii.
    "intraday_realized_volatility",
    "morning_return",
    "afternoon_return",
    "last_hour_return",
    "vwap_deviation",
    "first_hour_volume_share",
    "last_hour_volume_share",
    "range_efficiency",
    "bar_return_volume_correlation",
    "high_time_fraction",
    "low_time_fraction",
)
DAILY_FEATURE_COLUMNS = (  # Fiksirovannyi causal-vhod bez external context.
    *(f"return_{lag}" for lag in DAILY_RETURN_LAGS),
    "open_gap",
    "candle_range",
    "candle_body",
    "close_location",
    *(f"volatility_{window}" for window in DAILY_VOLATILITY_WINDOWS),
    *(f"sma_ratio_{window}" for window in DAILY_SMA_WINDOWS),
    *(f"volume_z_{window}" for window in DAILY_NORMALIZATION_WINDOWS),
    *(f"value_z_{window}" for window in DAILY_NORMALIZATION_WINDOWS),
    "daily_available",
    "staleness_sessions",
    *INTRADAY_SUMMARY_COLUMNS,
    "cross_rank_return_1",
    "cross_rank_return_5",
    "cross_rank_return_20",
    "cross_rank_volume",
    "breadth_positive_1",
    "dispersion_return_1",
    "dispersion_return_5",
    "market_return_1",
    "market_return_5",
    "market_return_20",
    "market_volatility_20",
)


@dataclass(frozen=True)
class DailySamples:
    """Hranit ssylki na koncy causal sequence i audit-metadannye."""

    indices: np.ndarray
    positions: np.ndarray
    metadata: pd.DataFrame
    feature_columns: tuple[str, ...]
    sequence_length: int

    def __len__(self) -> int:
        """Vozvrashchaet chislo vybrannyh sequence-primerov."""
        return len(self.indices)


def _rolling_robust_z(series: pd.Series, window: int) -> pd.Series:
    """Schitaet istoricheskii robust-z log-velichiny po median i IQR."""
    logged = np.log1p(series.clip(lower=0.0))
    rolling = logged.rolling(window, min_periods=window)
    median = rolling.median()
    scale = (rolling.quantile(0.75) - rolling.quantile(0.25)).clip(lower=1e-6)
    return (logged - median) / scale


def _session_timestamp(
    sessions: Sequence[object],
    minute_of_day: int,
) -> pd.DatetimeIndex:
    """Preobrazuet session-date v planovyi timezone-aware UTC timestamp."""
    values: list[pd.Timestamp | pd.NaTType] = []
    for session in sessions:
        if pd.isna(session):
            values.append(pd.NaT)
            continue
        local = pd.Timestamp(session).normalize().tz_localize(MOSCOW_TIMEZONE)
        values.append(local + pd.Timedelta(minutes=minute_of_day))
    return pd.DatetimeIndex(pd.to_datetime(values, utc=True))


def _aggregate_main_session(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Agregiruet tol'ko polnost'yu dostupnye bary osnovnoi sessii."""
    checked = validate_market_frame(frame)
    local_index = checked.index.tz_convert(MOSCOW_TIMEZONE)
    minute = local_index.hour * 60 + local_index.minute
    mask = (minute >= MAIN_SESSION_START_MINUTE) & (
        minute <= MAIN_SESSION_LAST_BAR_MINUTE
    )
    main = checked.loc[mask].copy()
    if main.empty:
        raise ValueError(f"Net barov osnovnoi sessii dlya {ticker}")
    local_main = main.index.tz_convert(MOSCOW_TIMEZONE)
    main["session_date"] = local_main.tz_localize(None).normalize()
    main["bar_begin"] = main.index
    grouped = main.groupby("session_date", sort=True)
    daily = grouped.agg(
        raw_open=("open", "first"),
        raw_high=("high", "max"),
        raw_low=("low", "min"),
        raw_close=("close", "last"),
        raw_volume=("volume", "sum"),
        raw_value=("value", "sum"),
        bar_count=("open", "size"),
        first_bar_begin=("bar_begin", "first"),
        last_bar_begin=("bar_begin", "last"),
    )
    daily = daily.join(_intraday_session_statistics(main), how="left")
    daily.index = pd.DatetimeIndex(daily.index, name="session_date")
    return daily


def _intraday_session_statistics(main: pd.DataFrame) -> pd.DataFrame:
    """Szhimaet izvestnuyu k 18:50 formu sessii bez budushchih barov."""
    working = main.copy()
    local = working.index.tz_convert(MOSCOW_TIMEZONE)
    working["minute"] = local.hour * 60 + local.minute
    working["bar_log_return"] = np.log(working["close"] / working["open"])

    def summarize(group: pd.DataFrame) -> pd.Series:
        """Vozvrashchaet odinnadcat' stabil'nyh svodok odnoi sessii."""
        first_open = float(group["open"].iloc[0])
        last_close = float(group["close"].iloc[-1])
        morning = group.loc[group["minute"] <= 10 * 60 + 50]
        afternoon = group.loc[group["minute"] >= 14 * 60]
        last_hour = group.loc[group["minute"] >= 17 * 60 + 40]
        morning = morning if not morning.empty else group.iloc[:1]
        afternoon = afternoon if not afternoon.empty else group.iloc[-1:]
        last_hour = last_hour if not last_hour.empty else group.iloc[-1:]
        total_volume = float(group["volume"].sum())
        total_value = float(group["value"].sum())
        vwap = total_value / total_volume if total_volume > 0.0 else np.nan
        path = float(group["bar_log_return"].abs().sum())
        bar_returns = group["bar_log_return"].to_numpy(dtype=float)
        log_volume = np.log1p(group["volume"].to_numpy(dtype=float))
        correlation = (
            float(np.corrcoef(bar_returns, log_volume)[0, 1])
            if np.std(bar_returns) > 0.0 and np.std(log_volume) > 0.0
            else 0.0
        )
        divisor = max(len(group) - 1, 1)
        return pd.Series(
            {
                "intraday_realized_volatility": float(
                    np.sqrt(np.square(group["bar_log_return"]).sum())
                ),
                "morning_return": float(morning["close"].iloc[-1] / first_open - 1.0),
                "afternoon_return": float(
                    last_close / afternoon["open"].iloc[0] - 1.0
                ),
                "last_hour_return": float(
                    last_close / last_hour["open"].iloc[0] - 1.0
                ),
                "vwap_deviation": float(last_close / vwap - 1.0)
                if np.isfinite(vwap) and vwap > 0.0
                else 0.0,
                "first_hour_volume_share": float(morning["volume"].sum() / total_volume)
                if total_volume > 0.0
                else 0.0,
                "last_hour_volume_share": float(last_hour["volume"].sum() / total_volume)
                if total_volume > 0.0
                else 0.0,
                "range_efficiency": float(abs(np.log(last_close / first_open)) / path)
                if path > 0.0
                else 0.0,
                "bar_return_volume_correlation": float(correlation)
                if np.isfinite(correlation)
                else 0.0,
                "high_time_fraction": float(np.argmax(group["high"].to_numpy()) / divisor),
                "low_time_fraction": float(np.argmin(group["low"].to_numpy()) / divisor),
            }
        )

    return working.groupby("session_date", sort=True).apply(
        summarize, include_groups=False
    )


def _asset_daily_features(
    daily: pd.DataFrame,
    ticker: str,
    calendar: pd.DatetimeIndex,
    horizon_sessions: int,
) -> pd.DataFrame:
    """Stroit asset-priznaki na obshchem session-calendar bez budushchego."""
    result = daily.reindex(calendar).copy()
    available = result["raw_close"].notna()
    observed_session_open = result["raw_open"].copy()
    first_bar_local = pd.to_datetime(result["first_bar_begin"], utc=True).dt.tz_convert(
        MOSCOW_TIMEZONE
    )
    scheduled_open_available = available & (
        first_bar_local.dt.hour * 60 + first_bar_local.dt.minute
    ).eq(REGULAR_SESSION_OPEN_MINUTE)
    last_close = result["raw_close"].ffill()
    for raw_column, column in (
        ("raw_open", "open"),
        ("raw_high", "high"),
        ("raw_low", "low"),
        ("raw_close", "close"),
    ):
        result[column] = result[raw_column].where(available, last_close)
    result["volume"] = result["raw_volume"].fillna(0.0)
    result["value"] = result["raw_value"].fillna(0.0)
    result["bar_count"] = result["bar_count"].fillna(0).astype(int)
    result["daily_available"] = available.astype(float)
    result["staleness_sessions"] = (
        (~available).astype(int).groupby(available.astype(int).cumsum()).cumsum().astype(float)
    )
    for column in INTRADAY_SUMMARY_COLUMNS:
        result[column] = result[column].where(available, 0.0).fillna(0.0)
    log_close = np.log(result["close"])
    one_return = log_close.diff().clip(-0.5, 0.5)
    for lag in DAILY_RETURN_LAGS:
        result[f"return_{lag}"] = (log_close - log_close.shift(lag)).clip(-1.5, 1.5)
    result["open_gap"] = np.log(result["open"] / result["close"].shift(1)).clip(
        -0.5, 0.5
    )
    result["candle_range"] = np.log(result["high"] / result["low"]).clip(0.0, 0.5)
    result["candle_body"] = np.log(result["close"] / result["open"]).clip(-0.5, 0.5)
    spread = (result["high"] - result["low"]).replace(0.0, np.nan)
    result["close_location"] = (
        (result["close"] - result["low"]) / spread - 0.5
    ).fillna(0.0)
    for window in DAILY_VOLATILITY_WINDOWS:
        result[f"volatility_{window}"] = one_return.rolling(
            window, min_periods=window
        ).std()
    for window in DAILY_SMA_WINDOWS:
        average = result["close"].rolling(window, min_periods=window).mean()
        result[f"sma_ratio_{window}"] = result["close"] / average - 1.0
    for window in DAILY_NORMALIZATION_WINDOWS:
        result[f"volume_z_{window}"] = _rolling_robust_z(result["volume"], window)
        result[f"value_z_{window}"] = _rolling_robust_z(result["value"], window)

    session_values = pd.Series(calendar, index=calendar)
    result["signal_time"] = _session_timestamp(calendar, MAIN_SESSION_SIGNAL_MINUTE)
    result["raw_open"] = observed_session_open.where(scheduled_open_available)
    result["open_return_1"] = np.log(result["raw_open"]).diff().clip(-0.5, 0.5)
    result["entry_session"] = session_values.shift(-1)
    result["scheduled_exit_session"] = session_values.shift(-(horizon_sessions + 1))
    result["entry_time"] = _session_timestamp(
        result["entry_session"].tolist(), REGULAR_SESSION_OPEN_MINUTE
    )
    result["entry_open"] = result["raw_open"].shift(-1)
    result["scheduled_exit_open"] = result["raw_open"].shift(
        -(horizon_sessions + 1)
    )
    factual_exit_sessions = session_values.where(result["raw_open"].notna()).shift(
        -(horizon_sessions + 1)
    )
    result["exit_session"] = factual_exit_sessions.bfill()
    result["exit_time"] = _session_timestamp(
        result["exit_session"].tolist(), REGULAR_SESSION_OPEN_MINUTE
    )
    result["exit_open"] = result["scheduled_exit_open"].bfill()
    result["entry_available"] = result["entry_open"].notna()
    result["raw_target_return"] = result["exit_open"] / result["entry_open"] - 1.0
    result["horizon_sessions"] = horizon_sessions
    result["session_number"] = np.arange(len(result), dtype=np.int32)
    result["session_phase"] = result["session_number"] % STAGGERED_PHASE_COUNT
    result["ticker"] = ticker
    return result.reset_index()


def _add_cross_section_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Dobavlyaet tekushchie rangi, breadth i dispersion bez targetov."""
    result = panel.copy()
    group_key = result["session_date"]
    available = result["daily_available"].eq(1.0)
    for source, target in (
        ("return_1", "cross_rank_return_1"),
        ("return_5", "cross_rank_return_5"),
        ("return_20", "cross_rank_return_20"),
        ("volume_z_20", "cross_rank_volume"),
    ):
        current = result[source].where(available)
        result[target] = current.groupby(group_key).rank(pct=True).sub(0.5).fillna(0.0)
    masked_return_1 = result["return_1"].where(available)
    masked_return_5 = result["return_5"].where(available)
    masked_return_20 = result["return_20"].where(available)
    masked_volatility = result["volatility_20"].where(available)
    result["breadth_positive_1"] = (
        masked_return_1.gt(0.0)
        .where(masked_return_1.notna())
        .groupby(group_key)
        .transform("mean")
    )
    result["dispersion_return_1"] = masked_return_1.groupby(group_key).transform(
        lambda values: values.std(ddof=0)
    )
    result["dispersion_return_5"] = masked_return_5.groupby(group_key).transform(
        lambda values: values.std(ddof=0)
    )
    result["market_return_1"] = masked_return_1.groupby(group_key).transform("median")
    result["market_return_5"] = masked_return_5.groupby(group_key).transform("median")
    result["market_return_20"] = masked_return_20.groupby(group_key).transform("median")
    result["market_volatility_20"] = masked_volatility.groupby(group_key).transform(
        "median"
    )
    return result


def _normalize_market_series(series: pd.Series) -> pd.Series:
    """Privodit market-series k unikal'nym moskovskim session-date."""
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("market_series dolzhen imet DatetimeIndex")
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    if series.index.tz is None:
        dates = series.index.normalize()
    else:
        dates = series.index.tz_convert(MOSCOW_TIMEZONE).tz_localize(None).normalize()
    normalized = pd.Series(numeric.to_numpy(), index=dates, name="market_value")
    return normalized.groupby(level=0).last().sort_index()


def residualize_daily_targets(
    panel: pd.DataFrame,
    method: Literal["cross_section", "beta"] = "cross_section",
    market_series: pd.Series | None = None,
    beta_window: int = 60,
    beta_min_periods: int = 20,
) -> pd.DataFrame:
    """Stroit cross-section ili causal beta-residual dlya model'nogo targeta."""
    if beta_window < 2 or not 2 <= beta_min_periods <= beta_window:
        raise ValueError("beta_window i beta_min_periods zadany nekorrektno")
    result = panel.copy()
    if method == "cross_section":
        center = result.groupby("session_date", sort=False)["raw_target_return"].transform(
            "median"
        )
        result["target_return"] = result["raw_target_return"] - center
        result["rolling_beta"] = np.nan
        result["external_market_target_return"] = np.nan
        return result
    if method != "beta":
        raise ValueError(f"Neizvestnyi residual method: {method}")
    if market_series is None:
        raise ValueError("beta-residual trebuet market_series")
    market = _normalize_market_series(market_series)
    calendar = pd.DatetimeIndex(sorted(result["session_date"].unique()))
    market = market.reindex(calendar)
    market_log_return = np.log(market).diff()
    horizon_values = result["horizon_sessions"].dropna().unique()
    if len(horizon_values) != 1:
        raise ValueError("Panel dolzhen imet odin horizon_sessions")
    market_entry = result["entry_session"].map(market)
    market_exit = result["exit_session"].map(market)
    result["external_market_target_return"] = market_exit / market_entry - 1.0
    beta_parts: list[pd.DataFrame] = []
    for ticker, part in result.groupby("ticker", sort=False):
        ordered = part.sort_values("session_date", kind="mergesort")
        stock_return = ordered.set_index("session_date")["open_return_1"].reindex(calendar)
        covariance = stock_return.rolling(
            beta_window, min_periods=beta_min_periods
        ).cov(market_log_return)
        variance = market_log_return.rolling(
            beta_window, min_periods=beta_min_periods
        ).var()
        beta_parts.append(
            pd.DataFrame(
                {
                    "ticker": ticker,
                    "session_date": calendar,
                    "rolling_beta": covariance / variance.replace(0.0, np.nan),
                }
            )
        )
    beta_frame = pd.concat(beta_parts, ignore_index=True)
    result = result.drop(columns="rolling_beta", errors="ignore").merge(
        beta_frame,
        on=["ticker", "session_date"],
        how="left",
        validate="one_to_one",
    )
    result["target_return"] = result["raw_target_return"] - (
        result["rolling_beta"] * result["external_market_target_return"]
    )
    return result


def join_external_context_asof(
    panel: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    """Prisoedinyaet tol'ko context, opublikovannyi ne pozzhe signal-time."""
    if "available_at" in context.columns:
        available_at = pd.DatetimeIndex(pd.to_datetime(context["available_at"], utc=True))
        values = context.drop(columns="available_at").copy()
    else:
        if not isinstance(context.index, pd.DatetimeIndex):
            raise TypeError("External context trebuet DatetimeIndex ili available_at")
        if context.index.tz is None:
            raise ValueError("External context timestamp dolzhen byt timezone-aware")
        available_at = context.index.tz_convert("UTC")
        values = context.copy()
    numeric_columns = [
        column
        for column in values.columns
        if pd.api.types.is_numeric_dtype(values[column])
        or pd.api.types.is_bool_dtype(values[column])
    ]
    if not numeric_columns:
        raise ValueError("External context ne soderzhit chislovyh kolonok")
    values = values.loc[:, numeric_columns].copy()
    values.index = available_at
    values = values.groupby(level=0).last().sort_index().ffill()
    rename = {
        column: column if column.startswith("context_") else f"context_{column}"
        for column in values.columns
    }
    values = values.rename(columns=rename)
    values["context_available_at"] = values.index
    signals = pd.DataFrame(
        {"signal_time": pd.to_datetime(panel["signal_time"], utc=True).drop_duplicates()}
    ).sort_values("signal_time")
    merged = pd.merge_asof(
        signals,
        values.reset_index(names="available_at").sort_values("available_at"),
        left_on="signal_time",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="available_at")
    result = panel.merge(merged, on="signal_time", how="left", validate="many_to_one")
    return result.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )


def build_daily_panel(
    frames: Mapping[str, pd.DataFrame],
    horizon_sessions: int = DEFAULT_HORIZON_SESSIONS,
    residual_method: Literal["cross_section", "beta"] = "cross_section",
    market_series: pd.Series | None = None,
    external_context: pd.DataFrame | None = None,
    beta_window: int = 60,
    beta_min_periods: int = 20,
) -> pd.DataFrame:
    """Stroit obshchii causal daily-panel i pyatidnevnyi residual target."""
    if not frames:
        raise ValueError("Dlya daily-panel nuzhen hotya by odin ticker")
    if horizon_sessions != DEFAULT_HORIZON_SESSIONS:
        raise ValueError("V3 daily-protokol zafiksirovan na pyati sessiyah")
    aggregated = {
        ticker.upper(): _aggregate_main_session(frame, ticker.upper())
        for ticker, frame in frames.items()
    }
    calendar = pd.DatetimeIndex(
        sorted(set().union(*(part.index for part in aggregated.values()))),
        name="session_date",
    )
    parts = [
        _asset_daily_features(part, ticker, calendar, horizon_sessions)
        for ticker, part in aggregated.items()
    ]
    panel = _add_cross_section_features(pd.concat(parts, ignore_index=True))
    panel = residualize_daily_targets(
        panel,
        method=residual_method,
        market_series=market_series,
        beta_window=beta_window,
        beta_min_periods=beta_min_periods,
    )
    if external_context is not None:
        panel = join_external_context_asof(panel, external_context)
    return panel.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )


def daily_feature_columns(panel: pd.DataFrame) -> tuple[str, ...]:
    """Dobavlyaet k bazovomu spisku vse chislovye as-of context-priznaki."""
    context_columns = sorted(
        column
        for column in panel.columns
        if column.startswith("context_")
        and column != "context_available_at"
        and pd.api.types.is_numeric_dtype(panel[column])
    )
    return (*DAILY_FEATURE_COLUMNS, *context_columns)


def fit_daily_feature_scaler(
    panel: pd.DataFrame,
    train_end: date,
    feature_columns: Sequence[str] | None = None,
) -> FeatureScaler:
    """Ocenivaet median i IQR daily-priznakov tol'ko do train_end."""
    columns = tuple(feature_columns or daily_feature_columns(panel))
    train = panel.loc[
        pd.to_datetime(panel["session_date"]).le(pd.Timestamp(train_end)),
        columns,
    ]
    values = train.to_numpy(dtype=np.float64)
    median = np.nanmedian(values, axis=0)
    q75 = np.nanpercentile(values, 75.0, axis=0)
    q25 = np.nanpercentile(values, 25.0, axis=0)
    scale = q75 - q25
    scale[~np.isfinite(scale) | (scale < 1e-6)] = 1.0
    if not np.isfinite(median).all():
        raise ValueError("Train-period ne pozvolil ocenit' daily-scaler")
    return FeatureScaler(
        median=median.astype(np.float32),
        scale=scale.astype(np.float32),
        columns=columns,
    )


def build_daily_sequence_store(
    panel: pd.DataFrame,
    scaler: FeatureScaler,
    sequence_length: int,
) -> SequenceStore:
    """Upakovyvaet daily-panel v sovmestimoe s TCN plotnoe hranilishche."""
    if sequence_length < 1:
        raise ValueError("sequence_length dolzhen byt polozhitel'nym")
    assets: list[AssetSequenceArray] = []
    for ticker, part in panel.groupby("ticker", sort=True):
        ordered = part.sort_values("session_date", kind="mergesort").reset_index(drop=True)
        raw_features = ordered.loc[:, scaler.columns].to_numpy(dtype=np.float32)
        finite_rows = np.isfinite(raw_features).all(axis=1)
        valid_sequences = (
            pd.Series(finite_rows.astype(np.int16))
            .rolling(sequence_length, min_periods=sequence_length)
            .sum()
            .eq(sequence_length)
            .to_numpy()
        )
        assets.append(
            AssetSequenceArray(
                ticker=str(ticker),
                features=scaler.transform(raw_features),
                timestamps=pd.to_datetime(ordered["signal_time"], utc=True).to_numpy(),
                local_dates=pd.to_datetime(ordered["session_date"]).to_numpy(
                    dtype="datetime64[D]"
                ),
                slots=ordered["session_phase"].to_numpy(dtype=np.int16),
                entry_times=pd.to_datetime(ordered["entry_time"], utc=True).to_numpy(),
                exit_times=pd.to_datetime(ordered["exit_time"], utc=True).to_numpy(),
                entry_opens=ordered["entry_open"].to_numpy(dtype=np.float64),
                exit_opens=ordered["exit_open"].to_numpy(dtype=np.float64),
                targets=ordered["target_return"].to_numpy(dtype=np.float32),
                raw_targets=ordered["raw_target_return"].to_numpy(dtype=np.float32),
                market_regime=ordered["market_return_20"].to_numpy(dtype=np.float32),
                momentum_score=ordered["return_20"].to_numpy(dtype=np.float32),
                signal_available=ordered["daily_available"].eq(1.0).to_numpy(),
                valid_sequences=valid_sequences,
            )
        )
    if not assets:
        raise ValueError("Daily-panel ne soderzhit aktivov")
    return SequenceStore(assets=tuple(assets), sequence_length=sequence_length)


def select_daily_sequence_samples(
    store: SequenceStore,
    start_date: date,
    end_date: date,
    *,
    embargo_sessions: int = 0,
    phases: Collection[int] | None = None,
    require_target: bool = True,
    purge_exit_before: date | pd.Timestamp | None = None,
) -> SequenceSamples:
    """Vyberaet TCN-ready daily-samples i purgit targety po exit-time."""
    allowed_phases = list(range(STAGGERED_PHASE_COUNT)) if phases is None else sorted(phases)
    samples = select_sequence_samples(
        store,
        start_date,
        end_date,
        stride_bars=1,
        embargo_bars=embargo_sessions,
        allowed_slots=allowed_phases,
        require_target=require_target,
    )
    if purge_exit_before is None:
        return samples
    boundary = _utc_boundary(purge_exit_before)
    keep = pd.to_datetime(samples.metadata["exit_time"], utc=True).lt(boundary).to_numpy()
    if not keep.any():
        raise ValueError("Purge udalil vse daily TCN-samples")
    return SequenceSamples(
        asset_ids=samples.asset_ids[keep],
        positions=samples.positions[keep],
        metadata=samples.metadata.loc[keep].reset_index(drop=True),
    )


def _utc_boundary(value: date | pd.Timestamp) -> pd.Timestamp:
    """Normalizuet granicu purge k momentu otkrytiya moskovskoi sessii."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.normalize().tz_localize(MOSCOW_TIMEZONE) + pd.Timedelta(
            minutes=REGULAR_SESSION_OPEN_MINUTE
        )
    return timestamp.tz_convert("UTC")


def select_daily_samples(
    panel: pd.DataFrame,
    start_date: date,
    end_date: date,
    sequence_length: int,
    *,
    mode: Literal["train", "eval"] = "train",
    feature_columns: Sequence[str] | None = None,
    embargo_sessions: int = 0,
    purge_exit_before: date | pd.Timestamp | None = None,
    phases: Collection[int] | None = None,
) -> DailySamples:
    """Vyberaet causal sequence s phase, embargo i purge po exit-time."""
    if sequence_length < 1 or embargo_sessions < 0:
        raise ValueError("sequence_length i embargo_sessions zadany nekorrektno")
    if mode not in {"train", "eval"}:
        raise ValueError(f"Neizvestnyi sample mode: {mode}")
    selected_features = tuple(feature_columns or daily_feature_columns(panel))
    missing = set(selected_features) - set(panel.columns)
    if missing:
        raise ValueError(f"Net daily-priznakov: {sorted(missing)}")
    allowed_phases = set(range(STAGGERED_PHASE_COUNT)) if phases is None else set(phases)
    if not allowed_phases or not allowed_phases <= set(range(STAGGERED_PHASE_COUNT)):
        raise ValueError("phases dolzhny byt nepustym podmnozhestvom 0..4")
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date ne mozhet byt posle end_date")
    ordered = panel.sort_values(["ticker", "session_date"], kind="mergesort").reset_index(
        drop=True
    )
    period_sessions = pd.DatetimeIndex(
        sorted(
            session
            for session in ordered["session_date"].unique()
            if start <= pd.Timestamp(session) <= end
        )
    )
    if len(period_sessions) <= embargo_sessions:
        raise ValueError("Embargo udalil vse daily-sessii perioda")
    first_allowed = period_sessions[embargo_sessions]
    boundary = _utc_boundary(purge_exit_before) if purge_exit_before is not None else None
    sample_indices: list[np.ndarray] = []
    sample_positions: list[np.ndarray] = []
    metadata_parts: list[pd.DataFrame] = []
    metadata_columns = [
        "ticker",
        "session_date",
        "signal_time",
        "entry_session",
        "entry_time",
        "entry_open",
        "entry_available",
        "exit_session",
        "exit_time",
        "exit_open",
        "raw_target_return",
        "target_return",
        "session_phase",
    ]
    for _, part in ordered.groupby("ticker", sort=True):
        values = part.loc[:, selected_features].to_numpy(dtype=np.float64)
        finite_rows = np.isfinite(values).all(axis=1)
        valid_sequence = (
            pd.Series(finite_rows.astype(np.int16))
            .rolling(sequence_length, min_periods=sequence_length)
            .sum()
            .eq(sequence_length)
            .to_numpy()
        )
        session_dates = pd.to_datetime(part["session_date"])
        mask = (
            valid_sequence
            & session_dates.between(first_allowed, end).to_numpy()
            & part["session_phase"].isin(allowed_phases).to_numpy()
        )
        if mode == "train":
            mask &= np.isfinite(part["target_return"].to_numpy(dtype=np.float64))
        if boundary is not None:
            exits = pd.to_datetime(part["exit_time"], utc=True)
            mask &= exits.lt(boundary).fillna(False).to_numpy()
        positions = np.flatnonzero(mask)
        if not len(positions):
            continue
        indices = part.index.to_numpy(dtype=np.int64)[positions]
        sample_indices.append(indices)
        sample_positions.append(positions.astype(np.int32))
        metadata = part.iloc[positions].loc[:, metadata_columns].copy()
        metadata["panel_index"] = indices
        metadata["asset_position"] = positions
        metadata_parts.append(metadata)
    if not metadata_parts:
        raise ValueError(f"Net daily-primerov za {start_date}..{end_date}")
    metadata = pd.concat(metadata_parts, ignore_index=True).sort_values(
        ["signal_time", "ticker"], kind="mergesort"
    )
    ordering = metadata.index.to_numpy()
    metadata = metadata.reset_index(drop=True)
    all_indices = np.concatenate(sample_indices)[ordering]
    all_positions = np.concatenate(sample_positions)[ordering]
    return DailySamples(
        indices=all_indices,
        positions=all_positions,
        metadata=metadata,
        feature_columns=selected_features,
        sequence_length=sequence_length,
    )
