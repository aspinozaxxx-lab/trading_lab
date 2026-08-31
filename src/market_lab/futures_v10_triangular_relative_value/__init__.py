"""Sealed V10 triangular relative-value research experiment."""

from .core import (
    FX_ABLATION,
    PRIMARY_STRATEGY,
    SignalSettings,
    SimulationResult,
    StrategyDefinition,
    build_signal_frame,
    calculate_metrics,
    evaluate_promotion,
    settings_from_protocol,
    simulate_strategy,
)

__all__ = [
    "FX_ABLATION",
    "PRIMARY_STRATEGY",
    "SignalSettings",
    "SimulationResult",
    "StrategyDefinition",
    "build_signal_frame",
    "calculate_metrics",
    "evaluate_promotion",
    "settings_from_protocol",
    "simulate_strategy",
]
