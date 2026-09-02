"""Focused tests for the sealed V47 margin-feasible risk ladder."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v47_v39_margin_feasible_risk_ladder as v47


def _parent() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(
                ["2021-01-04", "2021-01-05", "2021-01-06"]
            ),
            "starting_cash": [1_000_000.0, 1_000_000.0, 1_100_000.0],
            "ending_cash": [1_000_000.0, 1_100_000.0, 1_200_000.0],
            "combined_ending_equity": [1_000_000.0, 1_100_000.0, 1_200_000.0],
            "modeled_initial_margin": [200_000.0, 200_000.0, 200_000.0],
        }
    )


def test_protocol_pins_both_risk_modes_without_selection() -> None:
    protocol = v47.load_protocol()

    assert protocol.config_sha256.startswith("0b3524f4")
    assert protocol.payload["modes"]["stability"]["v39_market_pnl_scale"] == 1.10
    assert protocol.payload["modes"]["frontier"]["v39_market_pnl_scale"] == 1.50
    assert protocol.payload["modes"]["select_mode_after_outcome"] is False


def test_simulation_separates_market_collateral_and_carry() -> None:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    carry = pd.Series([1.0, 1.02, 1.0404], index=dates)
    baseline = pd.Series([1.0, 1.01, 1.0201], index=dates)

    result = v47.simulate_mode(
        _parent(),
        carry,
        baseline,
        market_scale=1.0,
        carry_fraction=0.20,
        margin_multiplier=1.0,
        initial_nav=1_000_000.0,
    )

    assert result.loc[0, "total_return"] == 0.0
    assert abs(result.loc[1, "scaled_market_return"] - 0.10) < 1e-12
    assert abs(result.loc[1, "collateral_return"] - 0.006) < 1e-12
    assert abs(result.loc[1, "allocated_carry_return"] - 0.004) < 1e-12
    assert abs(result.loc[1, "nav"] - 1_110_000.0) < 1e-8


def test_margin_stress_reduces_free_cash_without_changing_market_pnl() -> None:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    carry = pd.Series([1.0, 1.0, 1.0], index=dates)
    baseline = pd.Series([1.0, 1.01, 1.0201], index=dates)

    ordinary = v47.simulate_mode(
        _parent(),
        carry,
        baseline,
        market_scale=1.5,
        carry_fraction=0.0,
        margin_multiplier=1.0,
        initial_nav=1_000_000.0,
    )
    stressed = v47.simulate_mode(
        _parent(),
        carry,
        baseline,
        market_scale=1.5,
        carry_fraction=0.0,
        margin_multiplier=1.25,
        initial_nav=1_000_000.0,
    )

    assert stressed.loc[1, "free_cash_fraction"] < ordinary.loc[1, "free_cash_fraction"]
    assert stressed.loc[1, "scaled_market_return"] == ordinary.loc[
        1, "scaled_market_return"
    ]
    assert stressed.loc[1, "collateral_return"] < ordinary.loc[
        1, "collateral_return"
    ]
