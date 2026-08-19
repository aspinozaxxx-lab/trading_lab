"""Tochnye testy event-driven futures-ledger bez brokerskih dopushchenii."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.ledger import FuturesLedgerConfig, run_futures_ledger


def _market(
    *,
    third_old_open: float | None = 103.0,
    third_new_open: float | None = 112.0,
) -> pd.DataFrame:
    """Stroit tri sessii dvuh kontraktov s izvestnymi specs i volume."""
    dates = pd.date_range("2025-03-10", periods=3, freq="B")
    rows: list[dict[str, object]] = []
    old_opens = [100.0, 102.0, third_old_open]
    new_opens = [109.0, 110.0, third_new_open]
    old_settles = [101.0, 103.0, 104.0]
    new_settles = [109.5, 111.0, 113.0]
    for index, session_date in enumerate(dates):
        for contract, opens, settles in (
            ("SiH5", old_opens, old_settles),
            ("SiM5", new_opens, new_settles),
        ):
            rows.append(
                {
                    "session_date": session_date,
                    "contract_id": contract,
                    "open": opens[index],
                    "settle": settles[index],
                    "volume": 10_000.0,
                    "point_value": 10.0,
                    "tick_size": 0.5,
                    "fee_per_contract": 2.0,
                    "initial_margin": 100.0,
                }
            )
    return pd.DataFrame(rows)


def _targets(*rows: tuple[str, str, str | None, int]) -> pd.DataFrame:
    """Stroit causal'nye target-sobytiya iz korotkih kortezhei."""
    return pd.DataFrame(
        rows,
        columns=["effective_date", "decision_date", "contract_id", "target_contracts"],
    )


def test_exact_variation_margin_fee_and_one_tick_slippage() -> None:
    """Proveryaet entry, overnight gap, intraday VM i yavnyi denezhnyi cost."""
    result = run_futures_ledger(
        _market(),
        _targets(("2025-03-11", "2025-03-10", "SiH5", 2)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    second = result.ledger.iloc[1]
    third = result.ledger.iloc[2]
    assert second["overnight_gap_vm"] == pytest.approx(0.0)
    assert second["intraday_vm"] == pytest.approx(2 * (103.0 - 102.0) * 10.0)
    assert second["commission_cost"] == pytest.approx(4.0)
    assert second["slippage_cost"] == pytest.approx(10.0)
    assert second["ending_cash"] == pytest.approx(10_006.0)
    assert third["overnight_gap_vm"] == pytest.approx(0.0)
    assert third["intraday_vm"] == pytest.approx(20.0)
    assert result.metrics["ending_cash"] == pytest.approx(10_026.0)
    assert result.metrics["collateral_yield"] == pytest.approx(0.0)


def test_overnight_gap_and_intraday_settlement_are_both_booked() -> None:
    """Proveryaet razdelenie settle-to-open i open-to-settle posle entry."""
    market = _market()
    market.loc[
        (market["session_date"] == pd.Timestamp("2025-03-12"))
        & market["contract_id"].eq("SiH5"),
        ["open", "settle"],
    ] = [105.0, 104.0]
    result = run_futures_ledger(
        market,
        _targets(("2025-03-11", "2025-03-10", "SiH5", 2)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    final = result.ledger.iloc[-1]
    assert final["overnight_gap_vm"] == pytest.approx(2 * (105.0 - 103.0) * 10.0)
    assert final["intraday_vm"] == pytest.approx(2 * (104.0 - 105.0) * 10.0)
    assert final["variation_margin"] == pytest.approx(20.0)


def test_roll_is_atomic_and_charges_two_legs() -> None:
    """Proveryaet odnovremennyi exit/entry, dve komissii i dva slip-cost."""
    result = run_futures_ledger(
        _market(),
        _targets(
            ("2025-03-11", "2025-03-10", "SiH5", 2),
            ("2025-03-12", "2025-03-11", "SiM5", 2),
        ),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    roll = result.orders.loc[result.orders["leg"].str.startswith("roll_")]
    assert len(roll) == 2
    assert roll["filled"].all()
    assert roll["atomic_group"].nunique() == 1
    assert roll["commission_cost"].sum() == pytest.approx(8.0)
    assert roll["slippage_cost"].sum() == pytest.approx(20.0)
    assert result.ledger.iloc[-1]["contract_id"] == "SiM5"
    assert result.ledger.iloc[-1]["contracts"] == 2
    assert result.metrics["roll_count"] == 1


@pytest.mark.parametrize("missing_leg", ["old", "new"])
def test_missing_roll_open_carries_old_contract_without_partial_fill(missing_leg: str) -> None:
    """Proveryaet carry bez sinteticheskoi ceny pri propuske lyuboi nogi rola."""
    kwargs = {
        "third_old_open": None if missing_leg == "old" else 103.0,
        "third_new_open": None if missing_leg == "new" else 112.0,
    }
    result = run_futures_ledger(
        _market(**kwargs),
        _targets(
            ("2025-03-11", "2025-03-10", "SiH5", 2),
            ("2025-03-12", "2025-03-11", "SiM5", 2),
        ),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    roll = result.orders.loc[result.orders["leg"].str.startswith("roll_")]
    assert len(roll) == 2
    assert not roll["filled"].any()
    assert result.ledger.iloc[-1]["contract_id"] == "SiH5"
    assert result.ledger.iloc[-1]["contracts"] == 2
    assert result.metrics["roll_count"] == 0
    assert not result.execution_complete


def test_integer_contracts_and_causal_decision_are_mandatory() -> None:
    """Proveryaet zapret drobnogo target i resheniya na tekushchem open."""
    market = _market()
    with pytest.raises(ValueError, match="celym chislom"):
        run_futures_ledger(
            market,
            _targets(("2025-03-11", "2025-03-10", "SiH5", 1.5)),
        )
    with pytest.raises(ValueError, match="strogo ran'she"):
        run_futures_ledger(
            market,
            _targets(("2025-03-11", "2025-03-11", "SiH5", 1)),
        )


def test_gross_notional_and_double_margin_buffer_reject_excess() -> None:
    """Proveryaet otdel'nye otkazy po gross 1x i modeled IM buffer 2x."""
    gross_market = _market()
    gross_result = run_futures_ledger(
        gross_market,
        _targets(("2025-03-11", "2025-03-10", "SiH5", 11)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    assert gross_result.metrics["gross_limit_rejection_count"] >= 1
    assert gross_result.ledger.iloc[-1]["contracts"] == 0
    margin_market = _market()
    margin_market.loc[margin_market["contract_id"].eq("SiH5"), "initial_margin"] = 3_000.0
    margin_result = run_futures_ledger(
        margin_market,
        _targets(("2025-03-11", "2025-03-10", "SiH5", 2)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    assert margin_result.metrics["initial_margin_rejection_count"] >= 1
    assert margin_result.ledger.iloc[-1]["contracts"] == 0


def test_lagged_volume_limits_participation_and_current_volume_is_not_used() -> None:
    """Proveryaet 1% ot predydushchego volume i nezavisimost ot tekushchego volume."""
    market = _market()
    market.loc[
        (market["session_date"] == pd.Timestamp("2025-03-10"))
        & market["contract_id"].eq("SiH5"),
        "volume",
    ] = 100.0
    market.loc[
        (market["session_date"] == pd.Timestamp("2025-03-11"))
        & market["contract_id"].eq("SiH5"),
        "volume",
    ] = 1_000_000_000.0
    result = run_futures_ledger(
        market,
        _targets(("2025-03-11", "2025-03-10", "SiH5", 2)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    assert result.metrics["participation_rejection_count"] == 1
    assert result.metrics["maximum_participation"] == pytest.approx(0.02)
    assert result.orders.iloc[0]["participation"] == pytest.approx(0.02)
    assert not bool(result.orders.iloc[0]["filled"])


def test_unknown_liquidity_and_contract_specs_fail_closed() -> None:
    """Proveryaet yavnye flagi unknown volume, point value, fee i IM."""
    market = _market()
    entry = (market["session_date"] == pd.Timestamp("2025-03-11")) & market[
        "contract_id"
    ].eq("SiH5")
    previous = (market["session_date"] == pd.Timestamp("2025-03-10")) & market[
        "contract_id"
    ].eq("SiH5")
    market.loc[previous, "volume"] = np.nan
    market.loc[entry, ["point_value", "fee_per_contract", "initial_margin"]] = np.nan
    result = run_futures_ledger(
        market,
        _targets(("2025-03-11", "2025-03-10", "SiH5", 1)),
        FuturesLedgerConfig(initial_cash=10_000.0),
    )
    assert result.metrics["unknown_liquidity_count"] == 1
    assert result.metrics["unknown_point_value_count"] == 1
    assert result.metrics["unknown_fee_count"] == 1
    assert result.metrics["unknown_initial_margin_count"] == 1
    assert not result.execution_complete
    assert result.metrics["broker_exact"] is False
    assert result.metrics["research_only"] is True


def test_slippage_and_double_fee_stresses_are_exact() -> None:
    """Proveryaet 1/2/4 tick i dvoinoi fee bez izmeneniya gross VM."""
    targets = _targets(("2025-03-11", "2025-03-10", "SiH5", 2))
    one = run_futures_ledger(
        _market(),
        targets,
        FuturesLedgerConfig(initial_cash=10_000.0, slippage_ticks=1),
    )
    four = run_futures_ledger(
        _market(),
        targets,
        FuturesLedgerConfig(
            initial_cash=10_000.0,
            slippage_ticks=4,
            fee_multiplier=2.0,
        ),
    )
    assert one.metrics["slippage_cost"] == pytest.approx(10.0)
    assert four.metrics["slippage_cost"] == pytest.approx(40.0)
    assert one.metrics["commission_cost"] == pytest.approx(4.0)
    assert four.metrics["commission_cost"] == pytest.approx(8.0)
    assert one.metrics["variation_margin"] == pytest.approx(four.metrics["variation_margin"])


def test_terminal_carry_and_factual_liquidation_are_explicit() -> None:
    """Proveryaet otsutstvie synthetic close i factual final-open liquidation."""
    targets = _targets(("2025-03-11", "2025-03-10", "SiH5", 2))
    carried = run_futures_ledger(
        _market(), targets, FuturesLedgerConfig(initial_cash=10_000.0)
    )
    liquidated = run_futures_ledger(
        _market(),
        targets,
        FuturesLedgerConfig(initial_cash=10_000.0, terminal_policy="liquidate"),
    )
    assert carried.metrics["terminal_carried"] is True
    assert carried.metrics["terminal_contracts"] == 2
    assert liquidated.metrics["terminal_carried"] is False
    terminal_order = liquidated.orders.iloc[-1]
    assert terminal_order["leg"] == "exit"
    assert terminal_order["factual_open"] == pytest.approx(103.0)
    assert terminal_order["filled"]


def test_future_market_changes_cannot_change_past_ledger() -> None:
    """Proveryaet invariant proshlyh cash-events pri izmenenii budushchego."""
    market = _market()
    targets = _targets(("2025-03-11", "2025-03-10", "SiH5", 2))
    baseline = run_futures_ledger(
        market, targets, FuturesLedgerConfig(initial_cash=10_000.0)
    )
    changed = market.copy()
    future = changed["session_date"] == pd.Timestamp("2025-03-12")
    changed.loc[future, ["open", "settle", "volume"]] = [999.0, 1_111.0, 1.0]
    revised = run_futures_ledger(
        changed, targets, FuturesLedgerConfig(initial_cash=10_000.0)
    )
    columns = [
        "session_date",
        "variation_margin",
        "commission_cost",
        "slippage_cost",
        "ending_cash",
        "contracts",
    ]
    pd.testing.assert_frame_equal(
        baseline.ledger.loc[
            baseline.ledger["session_date"] <= pd.Timestamp("2025-03-11"), columns
        ].reset_index(drop=True),
        revised.ledger.loc[
            revised.ledger["session_date"] <= pd.Timestamp("2025-03-11"), columns
        ].reset_index(drop=True),
    )


def test_single_series_guard_rejects_cross_asset_as_fake_roll() -> None:
    """Proveryaet chto Si i RI ne mogut tikho prevratit'sya v odin roll."""
    market = _market()
    ri = market.loc[market["contract_id"].eq("SiM5")].copy()
    ri["contract_id"] = "RIH5"
    mixed = pd.concat(
        [market.loc[market["contract_id"].eq("SiH5")], ri], ignore_index=True
    )
    with pytest.raises(ValueError, match="multi-asset"):
        run_futures_ledger(
            mixed,
            _targets(("2025-03-11", "2025-03-10", "SiH5", 1)),
            FuturesLedgerConfig(initial_cash=10_000.0),
        )
