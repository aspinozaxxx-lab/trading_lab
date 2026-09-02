"""Tests for the sealed V50R1 calendar-basis correction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab import futures_v50r1_v49_robustness as subject


def test_real_protocol_preserves_v50_sampling_and_gates() -> None:
    protocol = subject.load_protocol()

    assert protocol["protocol_id"] == "v50r1_v49_robustness_audit_v1"
    assert protocol["analysis"]["block_sessions"] == [5, 21, 63, 126]
    assert protocol["analysis"]["bootstrap_total_paths"] == 300_000
    assert protocol["diagnostic_gates"]["minimum_20"]["minimum_stress_q05_cagr"] == 0.20
    assert protocol["metric_correction"]["correction_scope"] == (
        "canonical_V49_metric_replay_only"
    )
    assert protocol["metric_correction"]["bootstrap_calendar_year_days_unchanged"] == (
        365.2425
    )
    assert protocol["live_trading_allowed"] is False


def test_v49_metric_replay_uses_exact_365_25_calendar() -> None:
    dates = pd.Series(pd.to_datetime(["2020-12-30", "2025-12-30"]))
    levels = pd.Series([1.0, 6.122431721618415])

    metrics = subject._v49_performance_metrics(levels, dates, initial_cash=1.0)

    elapsed_days = (dates.iloc[-1] - dates.iloc[0]).days
    expected = (levels.iloc[-1] ** (365.25 / elapsed_days)) - 1.0
    assert np.isclose(metrics["cagr"], expected, rtol=0.0, atol=1e-15)

