"""Tests for unit-corrected CNY perpetual-quarterly spread V2."""

from __future__ import annotations

import copy

from market_lab.futures import cny_perpetual_quarterly_spread_v1 as v1
from market_lab.futures import cny_perpetual_quarterly_spread_v2 as v2
from tests.test_cny_perpetual_quarterly_spread_v1 import _contract, _perpetual, _ruonia


def _protocol() -> dict:
    protocol = copy.deepcopy(v2.load_protocol())
    protocol["periods"]["development"] = ["2023-01-02", "2023-03-20"]
    protocol["admission"]["minimum_annualized_excess_over_ruonia_percent"] = -100.0
    return protocol


def _quoted_perpetual():
    frame = _perpetual()
    frame[["open", "close"]] /= 1000.0
    return frame


def _quoted_contract():
    contract = _contract()
    contract["frame"][["open", "close"]] /= 1000.0
    return contract


def test_v2_seals_only_the_contract_unit_correction() -> None:
    old = v1.load_protocol()
    corrected = v2.load_protocol()

    assert old["official_accounting"]["point_value_rub_per_price_unit"] == 1.0
    assert corrected["official_accounting"]["point_value_rub_per_price_unit"] == 1000.0
    assert corrected["candidate_schedule"] == old["candidate_schedule"]
    assert corrected["admission"] == old["admission"]
    assert corrected["promotion_gates"] == old["promotion_gates"]


def test_candidate_uses_full_contract_notional() -> None:
    candidate = v2.build_candidate(
        _quoted_perpetual(), _quoted_contract(), _ruonia(), _protocol(), "primary"
    )

    assert candidate is not None
    assert candidate["point_value_rub_per_price_unit"] == 1000.0
    assert candidate["required_capital_per_pair"] > 9_000.0
    assert candidate["required_capital_per_pair"] < 10_000.0


def test_positive_funding_remains_profitable_but_sizing_is_bounded() -> None:
    trades, daily, metrics, checks = v2.simulate_period(
        _quoted_perpetual(),
        [_quoted_contract()],
        _ruonia(),
        _protocol(),
        "development",
        "primary",
    )

    admitted = trades.loc[trades["admitted"]].iloc[0]
    assert 0 < admitted["quantity"] < 100
    assert admitted["realized_funding_per_pair_rub"] > 0
    assert admitted["realized_per_pair_rub"] > 0
    assert metrics["ending_equity_rub"] > 1_000_000.0
    assert daily["equity"].notna().all()
    assert all(checks.values())
