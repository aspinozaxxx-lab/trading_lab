"""Tests for the empty-trade metrics correction in calendar-spread V2."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import calendar_spread_v2 as subject


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2024-01-03", "2024-01-04"]),
            "starting_cash": [1_000_000.0, 1_000_000.0],
            "ending_cash": [1_000_000.0, 1_000_000.0],
        }
    )


def test_empty_trade_schema_returns_zero_trade_metrics() -> None:
    result = subject.corrected_period_metrics(
        _daily(),
        pd.DataFrame([{"status": "skipped_zero_capacity_or_size"}]),
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-12-31"),
    )
    assert result["completed_trades"] == 0
    assert result["total_return"] == pytest.approx(0.0)
    assert result["win_rate"] is None


def test_nonempty_trade_metrics_remain_parent_identical() -> None:
    trades = pd.DataFrame(
        [
            {
                "status": "completed",
                "entry_execution_date": pd.Timestamp("2024-01-03"),
                "net_pnl": 10.0,
            }
        ]
    )
    expected = subject._PARENT_PERIOD_METRICS(
        _daily(), trades, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")
    )
    actual = subject.corrected_period_metrics(
        _daily(), trades, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")
    )
    assert actual == expected


def test_correction_context_restores_parent_globals_on_error() -> None:
    original_metrics = v1._period_metrics
    original_config = v1.CONFIG_PATH
    with (
        pytest.raises(RuntimeError, match="synthetic"),
        subject._correction_context(),
    ):
        assert v1._period_metrics is subject.corrected_period_metrics
        assert v1.CONFIG_PATH == subject.CONFIG_PATH
        raise RuntimeError("synthetic")
    assert v1._period_metrics is original_metrics
    assert original_config == v1.CONFIG_PATH


def test_real_v2_protocol_inherits_exact_v1_and_uses_new_output() -> None:
    protocol = subject.load_protocol()
    assert protocol.config_sha256 == (
        "e986530265ab6c87c39fbb6315dcb39d1eb80b971ff58d8614bff5966bb4a1eb"
    )
    assert protocol.economic.payload["strategies"] == v1.load_protocol().payload[
        "strategies"
    ]
    assert protocol.economic.output_directory == (
        subject.PROJECT_ROOT / "runs/calendar_spread_economic_2021_2025_v2"
    )
