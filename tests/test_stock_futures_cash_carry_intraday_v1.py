"""Tests for sealed synchronous covered cash-and-carry economics."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import stock_futures_cash_carry_intraday_v1 as experiment


def test_protocol_and_sources_are_exact() -> None:
    protocol = experiment.load_protocol()

    assert protocol.config_sha256 == experiment.CONFIG_SHA256
    assert set(protocol.spot_paths) == set(experiment.ASSETS)


def test_cashflow_sum_is_point_in_time_and_latest_per_event() -> None:
    frame = pd.DataFrame(
        {
            "logical_asset": ["SBRF", "SBRF", "SBRF"],
            "t": pd.to_datetime(["2024-07-01", "2024-07-01", "2025-07-01"]),
            "available_at_utc": pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-02-01T00:00:00Z",
                    "2024-01-01T00:00:00Z",
                ],
                utc=True,
            ),
            "cf": [10.0, 12.0, 20.0],
        }
    )

    value, events = experiment._cashflow_sum(
        frame,
        "SBRF",
        pd.Timestamp("2024-03-01T00:00:00Z"),
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-12-31"),
    )

    assert value == 12.0
    assert events == 1


def test_metrics_are_stable_for_flat_nav() -> None:
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    metrics = experiment._metrics(pd.Series(1.0, index=dates), dates)

    assert metrics["cagr"] == 0.0
    assert metrics["sharpe"] == 0.0
    assert metrics["maximum_drawdown"] == 0.0
