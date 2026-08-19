"""Focused tests for the sealed V9 structural execution proxy."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures_v9_structural.execution import (
    _accounting_point_value,
    _execution_ready,
)


def _row(**overrides: object) -> pd.Series:
    values = {
        "open": 100.0,
        "settle": 101.0,
        "lag_gap": 1.0,
        "lag_point_value": 10.0,
        "lag_volume": 1000.0,
        "sizing_proxy_usable": True,
        "realized_point_value": 10.0,
        "point_value_lower": 9.0,
        "point_value_upper": 11.0,
    }
    values.update(overrides)
    return pd.Series(values)


def test_execution_requires_factual_open_and_consecutive_lagged_proxy() -> None:
    assert _execution_ready(_row()) == (True, "")
    ready, reason = _execution_ready(
        _row(open=float("nan"), lag_gap=2.0, sizing_proxy_usable=False)
    )
    assert not ready
    assert "missing_factual_open" in reason
    assert "nonconsecutive_lagged_contract_session" in reason


def test_point_value_sensitivity_is_directionally_adverse() -> None:
    row = _row()
    assert _accounting_point_value(row, 1.0, "adverse") == pytest.approx(9.0)
    assert _accounting_point_value(row, -1.0, "adverse") == pytest.approx(11.0)
    assert _accounting_point_value(row, 1.0, "favorable") == pytest.approx(11.0)
    assert _accounting_point_value(row, -1.0, "favorable") == pytest.approx(9.0)
