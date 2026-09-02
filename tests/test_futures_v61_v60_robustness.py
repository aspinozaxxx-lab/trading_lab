"""Structural tests for the sealed V61 V60 robustness audit."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v61_v60_robustness as subject


def test_protocol_pins_v60_and_fixed_300k_diagnostic() -> None:
    protocol = subject.load_protocol()

    assert protocol["parent_v60"]["immutable_verdict"] == "GO_TO_NEW_FORWARD_CONFIRMATION"
    assert protocol["analysis"]["bootstrap_total_paths"] == 300_000
    assert protocol["analysis"]["block_sessions"] == [5, 21, 63, 126]
    assert protocol["analysis"]["bootstrap_threshold_maximum_drawdown"] == 0.25
    assert protocol["analysis"]["strategy_parameter_search"] is False
    assert protocol["live_trading_allowed"] is False


def test_bootstrap_summary_uses_twenty_return_and_twenty_five_drawdown() -> None:
    samples = pd.DataFrame(
        {
            "cagr": [0.10, 0.20, 0.30, 0.60],
            "maximum_drawdown": [0.10, 0.20, 0.30, 0.20],
            "sharpe": [0.5, 1.0, 1.2, 2.0],
        }
    )

    summary = subject.summarize_bootstrap_25(samples, (0.05, 0.50, 0.95))

    assert summary["probability_mdd_le_0_25"] == 0.75
    assert summary["probability_cagr_ge_0_20_and_mdd_le_0_25"] == 0.50
    assert summary["probability_cagr_ge_0_50_and_mdd_le_0_25"] == 0.25


def test_assessment_requires_every_predeclared_minimum_gate() -> None:
    protocol = {
        "diagnostic_gates": {
            "minimum_20": {
                "minimum_stress_joint_20_25_frequency": 0.75,
                "minimum_stress_q05_cagr": 0.20,
                "stress_252d_fraction_cagr_ge_20": 0.65,
                "stress_504d_fraction_cagr_ge_20": 0.75,
                "every_stress_leave_year_out_cagr_ge": 0.20,
            },
            "aspirational_50": {
                "minimum_stress_joint_50_25_frequency": 0.50,
                "minimum_stress_median_cagr": 0.50,
            },
        }
    }
    bootstrap = pd.DataFrame(
        {
            "scenario": ["stress"],
            "probability_cagr_ge_0_20_and_mdd_le_0_25": [0.80],
            "probability_cagr_ge_0_50_and_mdd_le_0_25": [0.60],
            "cagr_q05": [0.21],
            "cagr_q50": [0.51],
        }
    )
    rolling = {
        "stress": {
            "252": {"fraction_cagr_ge_0_20": 0.70},
            "504": {"fraction_cagr_ge_0_20": 0.80},
        }
    }
    leave = pd.DataFrame({"scenario": ["stress"], "cagr": [0.22]})

    passed = subject.assess_targets(protocol, bootstrap, rolling, leave)
    leave.loc[0, "cagr"] = 0.19
    failed = subject.assess_targets(protocol, bootstrap, rolling, leave)

    assert passed["minimum_20_supported_internally"] is True
    assert passed["aspirational_50_supported_internally"] is True
    assert failed["minimum_20_supported_internally"] is False
