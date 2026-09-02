"""Tests for corrected V42R2 switching-cost application."""

from __future__ import annotations

import pandas as pd
import pytest

import market_lab.futures_v42r2_v41_idle_fund_cost_stress as v42


def test_protocol_records_invalid_r1_and_preserves_economics() -> None:
    protocol = v42.load_protocol()

    assert protocol.config_sha256 == v42.CONFIG_SHA256
    assert protocol.payload["correction"]["economic_parameters_changed"] is False
    assert protocol.payload["correction"]["parent_inputs_changed"] is False
    assert protocol.payload["correction"]["invalidated_run"].startswith("runs/v42r1_")


def test_initial_purchase_is_charged_on_first_following_interval() -> None:
    eligible = pd.Series([1.0, 0.8, 0.8, 1.0])

    costs = v42._switching_costs(eligible, 0.001)

    assert costs.tolist() == pytest.approx([0.0, 0.0012, 0.0, 0.0012])
    assert abs(float(costs.sum()) - 0.0024) < 1e-12


def test_build_applies_initial_cost_and_keeps_nine_stresses() -> None:
    ledger, metrics = v42.build(v42.load_protocol())

    assert len(ledger) == 1827
    assert len(metrics["combinations"]) == 9
    assert ledger.loc[0, "primary__lqdt_contractual_max__switching_cost"] == 0.0
    assert ledger.loc[1, "primary__lqdt_contractual_max__switching_cost"] >= 0.0005
    assert metrics["fund_selection_allowed"] is False
