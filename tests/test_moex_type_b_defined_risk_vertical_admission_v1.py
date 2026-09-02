"""Tests for Type B defined-risk vertical structural admission."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_type_b_defined_risk_vertical_admission_v1 as subject


def test_protocol_and_grid_are_exact() -> None:
    config = subject.load_config()
    grid = subject.observation_grid(config)
    assert config["protocol_id"].endswith("_v1")
    assert len(grid) == 99
    assert grid[0] < grid[-1]


def test_pair_inventory_builds_bounded_call_and_put_debits() -> None:
    identity = pd.DataFrame(
        {
            "secid": ["C90", "C100", "P90", "P100"],
            "logical_asset": ["SI"] * 4,
            "strike": [90.0, 100.0, 90.0, 100.0],
            "option_type": ["call", "call", "put", "put"],
            "encoded_expiry_month": [10] * 4,
            "encoded_expiry_year_digit": [4] * 4,
            "encoded_week_code": [""] * 4,
        }
    )
    result = subject.pair_inventory(identity, set(identity["secid"]))
    call = result[result["option_type"].eq("call")].iloc[0]
    put = result[result["option_type"].eq("put")].iloc[0]
    assert (call["long_secid"], call["short_secid"]) == ("C90", "C100")
    assert (put["long_secid"], put["short_secid"]) == ("P100", "P90")
    assert call["strike_width"] == put["strike_width"] == 10.0


def test_vertical_admission_requires_fresh_four_sided_quotes_and_bounded_debit() -> None:
    pairs = pd.DataFrame(
        {
            "pair_id": ["x"],
            "logical_asset": ["SI"],
            "option_type": ["call"],
            "encoded_expiry_month": [10],
            "encoded_expiry_year_digit": [4],
            "encoded_week_code": [""],
            "lower_secid": ["C90"],
            "higher_secid": ["C100"],
            "lower_strike": [90.0],
            "higher_strike": [100.0],
            "strike_width": [10.0],
            "long_secid": ["C90"],
            "short_secid": ["C100"],
        }
    )
    at = pd.Timestamp("2024-10-01T10:00:00+03:00")
    legs = pd.DataFrame(
        {
            "grid_at_moscow": [at, at],
            "secid": ["C90", "C100"],
            "bid_price": [4.0, 1.0],
            "bid_volume": [2, 3],
            "bid_age_seconds": [2.0, 2.0],
            "offer_price": [5.0, 2.0],
            "offer_volume": [2, 3],
            "offer_age_seconds": [2.0, 2.0],
            "two_sided": [True, True],
            "locked_or_crossed": [False, False],
        }
    )
    result = subject.vertical_opportunities(pairs, legs, [1, 5])
    assert result["freshness_seconds"].tolist() == [5]
    assert result["entry_debit"].tolist() == [4.0]
