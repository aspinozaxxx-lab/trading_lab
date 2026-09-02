"""Tests for Type B vertical displayed-depth and crossing-friction diagnostics."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import moex_type_b_vertical_execution_diagnostics_v1 as subject


def _opportunity() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "grid_at_moscow": [pd.Timestamp("2024-10-01T10:00:00+03:00")],
            "freshness_seconds": [5],
            "pair_id": ["SI:call:C90:C100"],
            "logical_asset": ["SI"],
            "option_type": ["call"],
            "strike_width": [10.0],
            "entry_debit": [4.0],
            "long_bid_price": [4.5],
            "long_bid_volume": [7],
            "long_offer_price": [5.0],
            "long_offer_volume": [6],
            "short_bid_price": [1.0],
            "short_bid_volume": [8],
            "short_offer_price": [1.5],
            "short_offer_volume": [9],
        }
    )


def test_protocol_is_exact_and_non_economic() -> None:
    config = subject.load_config()
    assert config["protocol_id"].endswith("_v1")
    assert config["live_trading_allowed"] is False
    assert config["predeclared_capacity_thresholds_contracts"] == [1, 5, 10, 25]


def test_enrich_computes_displayed_capacity_and_four_side_friction() -> None:
    result = subject.enrich(_opportunity())
    row = result.iloc[0]
    assert row["displayed_entry_capacity_contracts"] == 6
    assert row["displayed_exit_capacity_contracts"] == 7
    assert row["contemporaneous_exit_credit"] == 3.0
    assert row["four_side_crossing_cost"] == 1.0
    assert row["crossing_cost_fraction_of_strike_width"] == 0.1
    assert row["entry_debit_fraction_of_strike_width"] == 0.4


def test_summarize_uses_only_predeclared_thresholds() -> None:
    config = subject.load_config()
    metrics = subject.summarize(subject.enrich(_opportunity()), config)
    assert metrics["counts"]["entry_capacity_ge:5s:5"] == 1
    assert metrics["counts"]["entry_capacity_ge:5s:10"] == 0
    assert metrics["counts"]["crossing_fraction_le:5s:0.10"] == 1
    assert (
        metrics["contains_return_label_target_prediction_signal_trade_position_equity_or_pnl"]
        is False
    )


def test_crossed_leg_bbo_fails_closed() -> None:
    frame = _opportunity()
    frame.loc[0, "long_bid_price"] = 5.0
    with pytest.raises(ValueError, match="non-crossed leg BBO"):
        subject.enrich(frame)
