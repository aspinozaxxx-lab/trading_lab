"""Focused structural tests for the sealed V49 exact 2x challenger."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v49_v39_double_risk_exact_execution as v49


def test_protocol_pins_one_exact_double_risk_mode() -> None:
    protocol = v49.load_protocol()

    assert protocol.config_sha256 == v49.CONFIG_SHA256
    assert protocol.payload["selection"]["candidate_count"] == 1
    assert protocol.payload["selection"]["mapped_target_multiplier"] == 2.0
    assert protocol.payload["risk_mode"]["maximum_gross_notional_multiple"] == 4.0
    assert protocol.payload["adaptive_same_history"] is True
    assert protocol.payload["live_trading_allowed"] is False


def test_scale_targets_preserves_zeros_directions_and_exact_double() -> None:
    targets = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(["2021-01-04", "2021-01-04", "2021-01-04"]),
            "asset_code": ["BR", "RI", "SI"],
            "target_weight": [0.4, -0.3, 0.0],
            "provenance": ["a", "b", "c"],
        }
    )

    scaled = v49.scale_targets(targets)

    assert scaled["target_weight"].tolist() == pytest.approx([0.8, -0.6, 0.0])
    assert scaled["v39_target_weight"].tolist() == [0.4, -0.3, 0.0]
    assert scaled["v49_mode"].eq(v49.MODE).all()
    with pytest.raises(ValueError, match="only the sealed"):
        v49.scale_targets(targets, 1.99)


def test_double_risk_ledger_config_rejects_parameter_drift() -> None:
    valid = {
        "initial_cash": v12.INITIAL_CASH,
        "expected_assets": v12.ASSETS,
        "maximum_gross_notional_multiple": 4.0,
        "initial_margin_buffer_multiplier": 2.0,
        "maximum_participation": v12.MAXIMUM_PARTICIPATION,
        "slippage_ticks": 1,
        "fee_multiplier": 1.0,
    }

    v49.DoubleRiskLedgerConfig(**valid)
    with pytest.raises(ValueError, match="settings drifted"):
        v49.DoubleRiskLedgerConfig(**{**valid, "maximum_gross_notional_multiple": 3.99})


def test_required_gate_pass_does_not_require_stretch_gate() -> None:
    futures = {
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
        "participation_clip_count": 0,
        "initial_margin_rejection_count": 0,
        "maximum_participation": 0.009,
    }
    combined = {
        "minimum_nav": 0.7,
        "cagr": 0.49,
        "sharpe": 1.0,
        "maximum_drawdown": 0.40,
        "worst_year": -0.10,
        "positive_years": 4,
    }
    scenarios = {
        name: {"futures": dict(futures), "combined": dict(combined)} for name in v49.SCENARIOS
    }
    config = {
        "gates": {
            "maximum_participation_lte": 0.01,
            "primary_cagr_gte": 0.45,
            "all_scenario_cagr_gte": 0.40,
            "all_scenario_sharpe_gte": 0.85,
            "all_scenario_mdd_lte": 0.50,
            "all_scenario_worst_year_gte": -0.20,
            "primary_positive_years_gte": 4,
            "stretch_primary_cagr_gte": 0.50,
        }
    }

    gates = v49.evaluate_gates(scenarios, config)

    assert all(gates[name] for name in v49.REQUIRED_GATES)
    assert gates["stretch_primary_cagr_50"] is False
