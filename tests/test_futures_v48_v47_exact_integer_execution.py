"""Focused tests for the sealed V48 exact scaled execution replay."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab import futures_v48_v47_exact_integer_execution as v48


def test_protocol_pins_exact_capacity_and_margin_modes() -> None:
    protocol = v48.load_protocol()

    assert protocol.config_sha256.startswith("3b7ae0e4")
    stability = protocol.payload["modes"]["stability"]
    frontier = protocol.payload["modes"]["frontier"]
    assert stability["mapped_target_multiplier"] == 1.10
    assert stability["initial_margin_buffer_multiplier"] == 2.50
    assert frontier["mapped_target_multiplier"] == 1.50
    assert frontier["maximum_gross_notional_multiple"] == 3.00


def test_scale_targets_preserves_zeros_directions_and_identity() -> None:
    targets = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(
                ["2021-01-04", "2021-01-04", "2021-01-04"]
            ),
            "asset_code": ["BR", "RI", "SI"],
            "target_weight": [0.4, -0.3, 0.0],
            "provenance": ["a", "b", "c"],
        }
    )

    scaled = v48.scale_targets(targets, 1.5, "frontier")

    assert scaled["target_weight"].tolist() == pytest.approx([0.6, -0.45, 0.0])
    assert scaled["v39_target_weight"].tolist() == [0.4, -0.3, 0.0]
    assert scaled["v48_mode"].eq("frontier").all()


def test_carry_combination_adds_only_excess_over_cash_baseline() -> None:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])
    exact = pd.Series([1_000_000.0, 1_100_000.0, 1_200_000.0], index=dates)
    carry = pd.Series([1.0, 1.10, 1.21], index=dates)
    baseline = pd.Series([1.0, 1.02, 1.0404], index=dates)

    combined = v48.combine_with_carry_excess(
        exact, carry, baseline, fraction=0.20
    )

    assert combined.iloc[0] == 1.0
    assert abs(combined.iloc[1] - 1.116) < 1e-12
    assert abs(combined.iloc[2] - 1.23392) < 1e-12
