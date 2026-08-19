"""Prostye deterministichnye bazovye strategii."""

from __future__ import annotations

import pandas as pd


def buy_and_hold_targets(index: pd.Index) -> pd.Series:
    """Vozvrashchaet postoyannuyu dlinnuyu celevuyu poziciyu."""
    return pd.Series(1.0, index=index, name="target_position")


def sma_crossover_targets(
    close: pd.Series,
    fast_window: int,
    slow_window: int,
    allow_short: bool,
) -> pd.Series:
    """Formiruet poziciyu po peresecheniyu prostyh skolzyashchih srednih."""
    if fast_window >= slow_window:
        raise ValueError("fast_window dolzhen byt men'she slow_window")
    fast = close.rolling(fast_window, min_periods=fast_window).mean()
    slow = close.rolling(slow_window, min_periods=slow_window).mean()
    long_mask = fast > slow
    if allow_short:
        targets = pd.Series(-1.0, index=close.index)
        targets.loc[long_mask] = 1.0
    else:
        targets = long_mask.astype(float)
    return targets.where(fast.notna() & slow.notna(), 0.0).rename("target_position")


def regime_trend_targets(
    close: pd.Series,
    sma_window: int,
    momentum_window: int,
    entry_band: float = 0.0,
) -> pd.Series:
    """Razreshaet long tolko pri polozhitelnom medlennom trende i momentum."""
    if sma_window < 2 or momentum_window < 1:
        raise ValueError("Okna trend-strategii dolzhny byt polozhitelnymi")
    if entry_band < 0.0:
        raise ValueError("entry_band ne mozhet byt otricatelnym")
    moving_average = close.rolling(sma_window, min_periods=sma_window).mean()
    momentum = close / close.shift(momentum_window) - 1.0
    targets = ((close > moving_average * (1.0 + entry_band)) & (momentum > 0.0)).astype(float)
    ready = moving_average.notna() & momentum.notna()
    return targets.where(ready, 0.0).rename("target_position")


def hysteresis_trend_targets(
    close: pd.Series,
    sma_window: int,
    momentum_window: int,
    entry_band: float,
    exit_band: float,
) -> pd.Series:
    """Uderzhivaet long mezhdu razdelnymi porogami vhoda i vyhoda."""
    if sma_window < 2 or momentum_window < 1:
        raise ValueError("Okna hysteresis-strategii dolzhny byt polozhitelnymi")
    if entry_band < 0.0 or exit_band < 0.0:
        raise ValueError("Porogi hysteresis-strategii ne mogut byt otricatelnymi")
    moving_average = close.rolling(sma_window, min_periods=sma_window).mean()
    momentum = close / close.shift(momentum_window) - 1.0
    state = 0.0
    values: list[float] = []
    for price, average, momentum_value in zip(
        close,
        moving_average,
        momentum,
        strict=True,
    ):
        if pd.isna(average) or pd.isna(momentum_value):
            state = 0.0
        elif (
            state == 0.0
            and price > average * (1.0 + entry_band)
            and momentum_value > entry_band
        ):
            state = 1.0
        elif state == 1.0 and (
            price < average * (1.0 - exit_band)
            or momentum_value < -exit_band
        ):
            state = 0.0
        values.append(state)
    return pd.Series(values, index=close.index, name="target_position")


def long_union_targets(first: pd.Series, second: pd.Series) -> pd.Series:
    """Obedinyaet dva long-cash signala bez izmeneniya vremennyh metok."""
    if not first.index.equals(second.index):
        raise ValueError("Indeksy obedinyaemyh signalov dolzhny sovpadat")
    if ((first < 0.0) | (first > 1.0) | (second < 0.0) | (second > 1.0)).any():
        raise ValueError("Hybrid podderzhivaet tolko long-cash signaly")
    return first.astype(float).combine(second.astype(float), max).rename(
        "target_position"
    )
