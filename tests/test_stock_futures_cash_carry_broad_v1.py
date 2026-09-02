"""Tests for the sealed broad covered stock-futures cash-carry screen."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import stock_futures_cash_carry_broad_v1 as experiment


def test_protocol_and_exact_sources_load() -> None:
    protocol = experiment.load_protocol()

    assert protocol.config_sha256 == experiment.CONFIG_SHA256
    assert tuple(protocol.spot_paths) == experiment.STOCKS
    assert len(protocol.spot_paths) == 29


def test_cashflow_sum_is_point_in_time_latest_and_explicit_missing() -> None:
    frame = pd.DataFrame(
        {
            "assetcode": ["SBRF", "SBRF", "SBRF"],
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

    value, events, mapping_missing = experiment._cashflow_sum(
        frame,
        "SBRF",
        pd.Timestamp("2024-03-01T00:00:00Z"),
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-12-31"),
    )
    missing_value, missing_events, missing_mapping = experiment._cashflow_sum(
        frame,
        None,
        pd.Timestamp("2024-03-01T00:00:00Z"),
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-12-31"),
    )

    assert (value, events, mapping_missing) == (12.0, 1, False)
    assert (missing_value, missing_events, missing_mapping) == (0.0, 0, True)


def test_roundtrip_cost_uses_exact_contract_share_count() -> None:
    total, entry, exit_cost = experiment._roundtrip_cost_values(
        shares=1_000,
        spot_entry=20.0,
        futures_entry=20_500.0,
        spot_exit=21.0,
        futures_exit=21_400.0,
        model="ordinary",
    )

    assert entry == pytest.approx(30.25)
    assert exit_cost == pytest.approx(31.7)
    assert total == pytest.approx(61.95)


def test_metrics_are_stable_for_flat_nav() -> None:
    dates = pd.date_range("2023-01-01", periods=5, freq="D")
    metrics = experiment._metrics(pd.Series(1.0, index=dates), dates)

    assert metrics["cagr"] == 0.0
    assert metrics["sharpe"] == 0.0
    assert metrics["maximum_drawdown"] == 0.0
