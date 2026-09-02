"""Tests for the sealed V42R1 idle-fund cost stress."""

from __future__ import annotations

import pandas as pd
import pytest

import market_lab.futures_v42r1_v41_idle_fund_cost_stress as v42


def test_protocol_identity_costs_and_correction_are_exact() -> None:
    protocol = v42.load_protocol()

    assert protocol.config_sha256 == v42.CONFIG_SHA256
    assert protocol.payload["correction"]["only_changed_field"] == (
        "parents.v41.protocol_sha256"
    )
    assert tuple(protocol.payload["cost_scenarios"]) == v42.COST_SCENARIOS
    assert protocol.payload["evaluation"]["parameter_or_fund_selection_from_results"] == (
        "forbidden"
    )


def test_switching_cost_charges_initial_changes_and_terminal() -> None:
    eligible = pd.Series([1.0, 0.8, 0.8, 1.0])

    costs = v42._switching_costs(eligible, 0.001)

    assert costs.tolist() == pytest.approx([0.001, 0.0002, 0.0, 0.0012])
    assert abs(float(costs.sum()) - 0.0024) < 1e-12


def test_build_has_nine_fixed_stresses_and_no_selection() -> None:
    ledger, metrics = v42.build(v42.load_protocol())

    assert len(ledger) == 1827
    assert len(metrics["combinations"]) == 9
    assert metrics["fund_selection_allowed"] is False
    assert metrics["live_trading_allowed"] is False
    assert metrics["gates"]["all_nav_positive"]
