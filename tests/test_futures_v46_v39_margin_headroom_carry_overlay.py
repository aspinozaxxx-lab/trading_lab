"""Focused tests for the sealed V46 self-financing carry overlay."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v46_v39_margin_headroom_carry_overlay as v46


def _parent(margin: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.to_datetime(
                ["2021-01-04", "2021-01-05", "2021-01-06"]
            ),
            "combined_ending_equity": [1_000_000.0, 1_100_000.0, 1_200_000.0],
            "modeled_initial_margin": margin,
        }
    )


def test_protocol_pins_full_v39_and_fixed_cash_fraction() -> None:
    protocol = v46.load_protocol()

    assert protocol.config_sha256.startswith("b18ed5bc")
    assert protocol.payload["overlay"]["v39_directional_nav_weight"] == 1.0
    assert protocol.payload["overlay"]["fixed_initial_carry_cash_fraction"] == 0.20
    assert protocol.payload["live_trading_allowed"] is False


def test_overlay_adds_only_excess_over_displaced_cash() -> None:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    carry = pd.Series([1.0, 1.10, 1.21], index=dates)
    baseline = pd.Series([1.0, 1.02, 1.0404], index=dates)

    result = v46.simulate_overlay(
        _parent([500_000.0, 500_000.0, 500_000.0]),
        carry,
        baseline,
        fraction=0.20,
        headroom_threshold=0.70,
    )

    assert result["headroom_eligible"].tolist() == [False, True, True]
    assert result.loc[0, "combined_nav"] == 1.0
    assert abs(result.loc[1, "combined_nav"] - 1.116) < 1e-12
    assert abs(result.loc[2, "combined_nav"] - 1.23392) < 1e-12


def test_overlay_sleeps_when_prior_margin_has_no_headroom() -> None:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    carry = pd.Series([1.0, 1.10, 1.21], index=dates)
    baseline = pd.Series([1.0, 1.02, 1.0404], index=dates)

    result = v46.simulate_overlay(
        _parent([800_000.0, 880_000.0, 960_000.0]),
        carry,
        baseline,
        fraction=0.20,
        headroom_threshold=0.70,
    )

    assert not result["headroom_eligible"].any()
    assert result["carry_excess_value"].abs().max() < 1e-12
    assert result["combined_nav"].tolist() == [1.0, 1.1, 1.2]
