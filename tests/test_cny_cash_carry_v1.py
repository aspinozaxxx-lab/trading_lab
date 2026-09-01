"""Tests for sealed CNY cash-and-carry V1."""

from __future__ import annotations

from market_lab.futures import cny_cash_carry_v1 as carry


def test_protocol_is_sealed_conservative_and_forward_gated() -> None:
    protocol = carry.load_protocol()

    assert protocol["execution"]["cny_interest_percent"] == 0.0
    assert protocol["capital"]["cross_collateral_credit"] == 0.0
    assert protocol["hypothesis"]["reverse_carry_without_proven_cny_borrow"] == "forbidden"
    assert (
        protocol["promotion_gates"]
        ["live_promotion_requires_future_multiyear_confirmation_even_if_all_numeric_gates_pass"]
        is True
    )
    assert protocol["live_trading_allowed"] is False


def test_ledger_adapter_preserves_cny_lot_and_costs() -> None:
    protocol = carry.load_protocol()
    adapted = carry.ledger_protocol(protocol)

    assert adapted["inputs"]["si"]["contract_usd_notional"] == 1000.0
    assert (
        adapted["execution"]["primary_half_spread_bps_each_leg_each_side"]
        == protocol["execution"]["primary_half_spread_bps_each_leg_each_side"]
    )
    assert adapted["admission"] == protocol["admission"]
    assert adapted["capital"] == protocol["capital"]
