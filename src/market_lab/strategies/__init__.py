"""Bazovye pravila formirovaniya celevyh pozicii."""

from market_lab.strategies.rules import (
    buy_and_hold_targets,
    hysteresis_trend_targets,
    long_union_targets,
    regime_trend_targets,
    sma_crossover_targets,
)

__all__ = [
    "buy_and_hold_targets",
    "hysteresis_trend_targets",
    "long_union_targets",
    "regime_trend_targets",
    "sma_crossover_targets",
]
