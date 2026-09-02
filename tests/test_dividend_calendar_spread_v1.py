"""Tests for the sealed dividend-revision spread experiment."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import dividend_calendar_spread_v1 as experiment


def test_protocol_and_source_bundle_are_exact() -> None:
    protocol = experiment.load_protocol()

    assert protocol.config_sha256 == experiment.CONFIG_SHA256
    assert protocol.paths["archive_daily"].is_file()


def test_cashflow_between_legs_uses_open_closed_boundary_and_risk() -> None:
    snapshot = {
        "rows": pd.DataFrame(
            {
                "t": pd.to_datetime(["2025-03-20", "2025-06-20", "2025-09-20"]),
                "cf": [10.0, 20.0, 30.0],
                "cfrisk": [1.0, 0.5, 1.0],
            }
        )
    }

    value = experiment._between_cashflow(
        snapshot, pd.Timestamp("2025-03-20"), pd.Timestamp("2025-06-20")
    )

    assert value == 10.0


def test_execution_uses_next_quote_and_bid_for_long_exit() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "E",
                "asset": "GAZR",
                "spread_id": "S",
                "signal_date": pd.Timestamp("2025-01-01"),
                "near_expiration": pd.Timestamp("2025-03-20"),
                "direction": 1,
                "fair_target": 10.0,
            }
        ]
    )
    quotes = pd.DataFrame(
        {
            "spread_id": ["S", "S"],
            "trade_date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "bid": [8.0, 10.0],
            "ask": [9.0, 11.0],
        }
    )

    trades, unresolved = experiment.execute_events(events, quotes)

    assert unresolved == 0
    assert trades.loc[0, "entry_fill"] == 9.0
    assert trades.loc[0, "exit_fill"] == 10.0
    assert trades.loc[0, "gross_points"] == 1.0
    assert trades.loc[0, "primary_net_points"] == -1.0
