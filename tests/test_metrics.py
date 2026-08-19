"""Proverki finansovyh metrik na malyh izvestnyh ryadah."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.backtest.metrics import calculate_max_drawdown, calculate_metrics


def test_max_drawdown_is_twenty_five_percent() -> None:
    """Proveryaet padenie ot 120 do 90."""
    equity = pd.Series([100.0, 120.0, 90.0, 108.0])
    assert calculate_max_drawdown(equity) == pytest.approx(0.25)


def test_zero_volatility_has_finite_sharpe_and_calmar() -> None:
    """Proveryaet zashchitu metrik ot deleniya na nol."""
    equity = pd.Series([100.0, 100.0, 100.0])
    returns = pd.Series([0.0, 0.0, 0.0])
    metrics = calculate_metrics(equity, returns, 100.0, 252, 0.0, 0, 0.0, 0.0)
    assert metrics["sharpe"] == 0.0
    assert metrics["calmar"] == 0.0

