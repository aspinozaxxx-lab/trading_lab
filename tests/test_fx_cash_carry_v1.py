"""Tests for the sealed FX cash-and-carry V1 runner."""

from __future__ import annotations

import copy

import pandas as pd

from market_lab.futures import fx_cash_carry_v1 as carry


def _protocol() -> dict:
    protocol = copy.deepcopy(carry.load_protocol())
    protocol["periods"]["development"] = ["2023-01-01", "2023-12-31"]
    protocol["admission"]["minimum_excess_over_ruonia_percent"] = -100.0
    return protocol


def _spot() -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", "2023-03-17")
    return pd.DataFrame(
        {
            "trade_date": dates,
            "open": 70.0,
            "close": 70.0,
            "number_of_trades": 100,
        }
    )


def _contract() -> dict:
    dates = pd.bdate_range("2023-01-02", "2023-03-17")
    convergence = [
        72_000.0 - 2_000.0 * index / (len(dates) - 1) for index in range(len(dates))
    ]
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "open": convergence,
            "close": convergence,
        }
    )
    return {
        "contract_id": "Si:SiH3:2023-03-20",
        "secid": "SiH3",
        "expiration_date": pd.Timestamp("2023-03-20"),
        "frame": frame,
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


def test_protocol_is_sealed_and_forbids_reverse_carry() -> None:
    protocol = carry.load_protocol()

    assert protocol["hypothesis"]["reverse_carry_without_proven_usd_borrow"] == "forbidden"
    assert protocol["execution"]["usd_interest_percent"] == 0.0
    assert protocol["capital"]["spot_or_margin_cross_collateral_credit"] == 0.0
    assert protocol["live_trading_allowed"] is False


def test_causal_ruonia_never_reads_after_session_start() -> None:
    ruonia = pd.concat(
        [
            _ruonia(),
            pd.DataFrame(
                {
                    "series_id": ["ruonia"],
                    "observation_date": [pd.Timestamp("2023-01-03")],
                    "available_at": [pd.Timestamp("2023-01-04T21:01:00Z")],
                    "value": [99.0],
                }
            ),
        ],
        ignore_index=True,
    )

    rate, available = carry.causal_ruonia_percent(ruonia, pd.Timestamp("2023-01-04"))

    assert rate == 7.0
    assert available == "2022-12-30T21:00:00+00:00"


def test_profitable_convergence_is_marked_and_realized() -> None:
    trades, daily, metrics, checks = carry.simulate_period(
        _spot(), [_contract()], _ruonia(), _protocol(), "development", "primary"
    )

    admitted = trades.loc[trades["admitted"]].iloc[0]
    assert admitted["quantity"] > 0
    assert admitted["realized_pnl_rub"] > 0
    assert metrics["admitted_trade_count"] == 1
    assert metrics["ending_equity_rub"] > 1_000_000.0
    assert daily["equity"].notna().all()
    assert all(checks.values())


def test_fixed_hurdle_rejects_negative_basis() -> None:
    protocol = _protocol()
    protocol["admission"]["minimum_excess_over_ruonia_percent"] = 2.0
    contract = _contract()
    contract["frame"]["open"] = 69_000.0
    contract["frame"]["close"] = 69_000.0

    trades, _, metrics, _ = carry.simulate_period(
        _spot(), [contract], _ruonia(), protocol, "development", "primary"
    )

    assert not trades["admitted"].any()
    assert metrics["admitted_trade_count"] == 0
    assert metrics["ending_equity_rub"] == 1_000_000.0


def test_zero_activity_spot_rows_remain_calendar_but_never_execute() -> None:
    spot = _spot()
    spot[["open", "close", "number_of_trades"]] = 0.0

    trades, daily, metrics, checks = carry.simulate_period(
        spot, [_contract()], _ruonia(), _protocol(), "development", "primary"
    )

    assert not trades["admitted"].any()
    assert metrics["nonexecuting_spot_rows_rejected"] == len(spot)
    assert metrics["ending_equity_rub"] == 1_000_000.0
    assert len(daily) == len(spot)
    assert all(checks.values())
