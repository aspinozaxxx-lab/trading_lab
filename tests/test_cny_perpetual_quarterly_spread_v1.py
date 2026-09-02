"""Tests for sealed CNY perpetual-quarterly spread V1."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import cny_perpetual_quarterly_spread_v1 as spread


def _protocol() -> dict:
    protocol = copy.deepcopy(spread.load_protocol())
    protocol["periods"]["development"] = ["2023-01-02", "2023-03-20"]
    protocol["admission"]["minimum_annualized_excess_over_ruonia_percent"] = -100.0
    return protocol


def _perpetual(*, missing_realized: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2022-12-01", "2023-03-17")
    swap_rate = np.full(len(dates), 0.01)
    if missing_realized:
        swap_rate[dates.get_loc(pd.Timestamp("2023-02-01"))] = np.nan
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": 13_000.0,
            "close": 13_000.0,
            "swap_rate": swap_rate,
        }
    )


def _contract() -> dict:
    dates = pd.bdate_range("2023-01-02", "2023-03-17")
    return {
        "contract_id": "CNY-PERP:CRH3:2023-03-20",
        "secid": "CRH3",
        "expiration_date": pd.Timestamp("2023-03-20"),
        "frame": pd.DataFrame(
            {
                "trade_date": dates,
                "open": 13_000.0,
                "close": 13_000.0,
            }
        ),
    }


def _ruonia() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": ["ruonia"],
            "observation_date": [pd.Timestamp("2022-12-29")],
            "available_at": [pd.Timestamp("2022-12-30T21:00:00Z")],
            "value": [7.0],
        }
    )


def test_protocol_is_sealed_short_perpetual_and_forward_gated() -> None:
    protocol = spread.load_protocol()

    assert protocol["official_accounting"]["perpetual_side"] == "short"
    assert protocol["official_accounting"]["seller_funding_component"] == (
        "positive_SwapRate_times_Lot"
    )
    assert protocol["capital"]["cross_margin_credit"] == 0.0
    assert protocol["live_trading_allowed"] is False


def test_causal_swaprate_lookback_strictly_excludes_entry_date() -> None:
    perpetual = _perpetual()
    contract = _contract()
    entry = pd.Timestamp("2023-01-19")
    perpetual.loc[perpetual["trade_date"].eq(entry), "swap_rate"] = 99.0

    candidate = spread.build_candidate(
        perpetual, contract, _ruonia(), _protocol(), "primary"
    )

    assert candidate is not None
    assert candidate["entry_date"] == entry
    assert candidate["prior_mean_swaprate"] == pytest.approx(0.01)


def test_positive_swaprate_pays_short_and_is_profitable() -> None:
    trades, daily, metrics, checks = spread.simulate_period(
        _perpetual(), [_contract()], _ruonia(), _protocol(), "development", "primary"
    )

    admitted = trades.loc[trades["admitted"]].iloc[0]
    assert admitted["realized_funding_per_pair_rub"] > 0
    assert admitted["realized_per_pair_rub"] > 0
    assert metrics["admitted_trade_count"] == 1
    assert metrics["ending_equity_rub"] > 1_000_000.0
    assert daily["equity"].notna().all()
    assert all(checks.values())


def test_missing_realized_swaprate_rejects_candidate() -> None:
    trades, _, metrics, checks = spread.simulate_period(
        _perpetual(missing_realized=True),
        [_contract()],
        _ruonia(),
        _protocol(),
        "development",
        "primary",
    )

    assert not trades["admitted"].any()
    assert trades.iloc[0]["reason"] == "missing_realized_swaprate"
    assert metrics["admitted_trade_count"] == 0
    assert metrics["ending_equity_rub"] == 1_000_000.0
    assert all(checks.values())
