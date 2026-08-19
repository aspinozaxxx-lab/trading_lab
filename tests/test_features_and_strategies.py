"""Proverki past-only priznakov i bazovyh strategii."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab.config import AppConfig
from market_lab.features import MarketFeatureBuilder, make_direction_labels
from market_lab.models import LogisticStrategy
from market_lab.strategies import (
    buy_and_hold_targets,
    hysteresis_trend_targets,
    long_union_targets,
    regime_trend_targets,
    sma_crossover_targets,
)


def test_future_mutation_does_not_change_past_features(
    app_config: AppConfig, market_frame: pd.DataFrame
) -> None:
    """Proveryaet otsutstvie look-ahead izmeneniem budushchego hvosta."""
    builder = MarketFeatureBuilder(app_config.features)
    original = builder.build(market_frame)
    mutated = market_frame.copy()
    mutated.loc[mutated.index[200]:, "close"] *= 3.0
    changed = builder.build(mutated)
    pd.testing.assert_frame_equal(original.iloc[:180], changed.iloc[:180])


def test_direction_labels_use_future_open_interval(market_frame: pd.DataFrame) -> None:
    """Proveryaet formulu metki open t+1 k open t+2."""
    labels = make_direction_labels(market_frame)
    expected = market_frame["open"].iloc[2] > market_frame["open"].iloc[1]
    assert bool(labels.iloc[0]) is bool(expected)
    assert labels.iloc[-2:].isna().all()


def test_baseline_strategies_return_expected_positions(market_frame: pd.DataFrame) -> None:
    """Proveryaet buy-and-hold i napravlenie SMA na prostom roste."""
    index = market_frame.index[:30]
    assert (buy_and_hold_targets(index) == 1.0).all()
    close = pd.Series(np.arange(1.0, 31.0), index=index)
    targets = sma_crossover_targets(close, 3, 10, allow_short=False)
    assert targets.iloc[:9].eq(0.0).all()
    assert targets.iloc[9:].eq(1.0).all()


def test_regime_trend_uses_only_slow_trend_and_momentum() -> None:
    """Proveryaet vhod na roste i otsutstvie signala do gotovnosti okon."""
    index = pd.date_range("2020-01-01", periods=120, tz="UTC")
    close = pd.Series(np.arange(100.0, 220.0), index=index)
    targets = regime_trend_targets(close, sma_window=75, momentum_window=60)
    assert targets.iloc[:74].eq(0.0).all()
    assert targets.iloc[75:].eq(1.0).all()


def test_future_mutation_does_not_change_past_regime_targets(
    market_frame: pd.DataFrame,
) -> None:
    """Proveryaet otsutstvie look-ahead v rezhimnom pravile."""
    original = regime_trend_targets(market_frame["close"], 75, 60)
    mutated = market_frame["close"].copy()
    mutated.iloc[250:] *= 2.0
    changed = regime_trend_targets(mutated, 75, 60)
    pd.testing.assert_series_equal(original.iloc[:240], changed.iloc[:240])


def test_long_union_combines_model_and_trend_signals() -> None:
    """Proveryaet logicheskoe ILI dvuh long-cash komponentov."""
    index = pd.date_range("2020-01-01", periods=4, tz="UTC")
    model = pd.Series([0.0, 1.0, 0.0, 1.0], index=index)
    trend = pd.Series([0.0, 0.0, 1.0, 1.0], index=index)
    expected = pd.Series(
        [0.0, 1.0, 1.0, 1.0],
        index=index,
        name="target_position",
    )
    pd.testing.assert_series_equal(long_union_targets(model, trend), expected)


def test_hysteresis_trend_enters_and_uses_only_past() -> None:
    """Proveryaet sostoyanie hysteresis-pravila i otsutstvie look-ahead."""
    index = pd.date_range("2020-01-01", periods=240, tz="UTC")
    close = pd.Series(np.linspace(100.0, 220.0, len(index)), index=index)
    original = hysteresis_trend_targets(close, 150, 20, 0.01, 0.02)
    assert original.iloc[:149].eq(0.0).all()
    assert original.iloc[150:].eq(1.0).all()
    mutated = close.copy()
    mutated.iloc[220:] *= 0.5
    changed = hysteresis_trend_targets(mutated, 150, 20, 0.01, 0.02)
    pd.testing.assert_series_equal(original.iloc[:210], changed.iloc[:210])


def test_logistic_strategy_is_deterministic(
    app_config: AppConfig, market_frame: pd.DataFrame
) -> None:
    """Proveryaet identichnye prognozy pri odnom seed."""
    features = MarketFeatureBuilder(app_config.features).build(market_frame)
    labels = make_direction_labels(market_frame)
    train = slice(0, 220)
    test = slice(220, 260)
    first = LogisticStrategy(1.0, 0.5, False, 42).fit(features.iloc[train], labels.iloc[train])
    second = LogisticStrategy(1.0, 0.5, False, 42).fit(features.iloc[train], labels.iloc[train])
    pd.testing.assert_series_equal(
        first.predict_targets(features.iloc[test]),
        second.predict_targets(features.iloc[test]),
    )
