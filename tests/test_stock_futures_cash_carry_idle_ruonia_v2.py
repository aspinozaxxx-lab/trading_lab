"""Tests for frozen cash-carry idle-RUONIA overlay."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import stock_futures_cash_carry_idle_ruonia_v2 as overlay


def test_protocol_and_parent_are_exact() -> None:
    protocol = overlay.load_protocol()

    assert protocol.config_sha256 == overlay.CONFIG_SHA256
    assert protocol.parent_root.exists()
    assert protocol.rates_root.exists()


def test_active_assets_include_entry_and_exit_dates() -> None:
    trades = pd.DataFrame(
        {
            "logical_asset": ["GAZR", "SBRF"],
            "entry_date": pd.to_datetime(["2025-01-02", "2025-01-04"]),
            "exit_date": pd.to_datetime(["2025-01-04", "2025-01-06"]),
        }
    )

    assert overlay._active_assets(trades, pd.Timestamp("2025-01-01")) == 0
    assert overlay._active_assets(trades, pd.Timestamp("2025-01-02")) == 1
    assert overlay._active_assets(trades, pd.Timestamp("2025-01-04")) == 2
    assert overlay._active_assets(trades, pd.Timestamp("2025-01-06")) == 1


def test_causal_rate_never_uses_future_availability() -> None:
    rates = pd.DataFrame(
        {
            "available_at": pd.to_datetime(
                ["2025-01-01T17:00:00Z", "2025-01-02T19:00:00Z"], utc=True
            ),
            "value": [10.0, 20.0],
        }
    )

    value = overlay._causal_rate(rates, pd.Timestamp("2025-01-02"))

    assert value is not None
    assert value[0] == 10.0
