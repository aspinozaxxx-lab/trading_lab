"""Tests for the sealed broad cash-carry idle-RUONIA overlay."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import stock_futures_cash_carry_broad_idle_ruonia_v1 as overlay


def test_protocol_and_parent_are_exact() -> None:
    protocol = overlay.load_protocol()

    assert protocol.config_sha256 == overlay.CONFIG_SHA256
    assert protocol.parent_root.exists()
    assert protocol.rates_root.exists()


def test_active_stocks_include_entry_and_exit_dates() -> None:
    trades = pd.DataFrame(
        {
            "stock_secid": ["GAZP", "SBER"],
            "entry_date": pd.to_datetime(["2025-01-02", "2025-01-04"]),
            "exit_date": pd.to_datetime(["2025-01-04", "2025-01-06"]),
        }
    )

    assert overlay._active_stocks(trades, pd.Timestamp("2025-01-01")) == 0
    assert overlay._active_stocks(trades, pd.Timestamp("2025-01-02")) == 1
    assert overlay._active_stocks(trades, pd.Timestamp("2025-01-04")) == 2
    assert overlay._active_stocks(trades, pd.Timestamp("2025-01-06")) == 1


def test_overlay_credits_interest_only_to_idle_fraction() -> None:
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    parent_nav = pd.Series([1.0, 1.0, 1.0], index=dates)
    idle_fraction = pd.Series([1.0, 0.0, 1.0], index=dates)
    rate_return = pd.Series([0.01, 0.01, 0.01], index=dates)

    nav, income = overlay._overlay_nav(parent_nav, idle_fraction, rate_return)

    assert nav.tolist() == [1.0, 1.01, 1.01]
    assert income == 0.01
