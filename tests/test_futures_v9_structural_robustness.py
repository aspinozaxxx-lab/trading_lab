"""Focused tests for the frozen structural robustness calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v9_structural.robustness import (
    exact_terminal_contributions,
    return_metrics,
)


def test_terminal_contributions_exactly_add_to_compounded_return() -> None:
    contributions = pd.DataFrame(
        {"A": [0.01, -0.005, 0.002], "B": [0.0, 0.003, -0.001]},
        index=pd.bdate_range("2025-01-02", periods=3),
    )
    attributed = exact_terminal_contributions(contributions)
    expected = float((1.0 + contributions.sum(axis=1)).prod() - 1.0)
    assert float(attributed.sum()) == pytest.approx(expected)


def test_metrics_observation_clock_handles_a_removed_calendar_year() -> None:
    returns = pd.Series(np.full(504, 0.0001), index=pd.bdate_range("2021-01-04", periods=504))
    metrics = return_metrics(returns, observations_clock=True)
    assert metrics["observations"] == 504
    assert metrics["cagr"] == pytest.approx((1.0001**504) ** 0.5 - 1.0)
