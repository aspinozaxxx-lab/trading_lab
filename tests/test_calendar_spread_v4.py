"""Tests for the post-V3 cost-aware calendar-spread candidate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import calendar_spread_v4 as subject
from tests.test_calendar_spread_v1 import _active_frame


def _cost_feature_frame() -> tuple[pd.DataFrame, dict[str, object]]:
    features = v1.build_feature_frame(_active_frame())
    for column in ("z10", "z20", "z40", "momentum5", "zero_convergence_score"):
        features[column] = np.nan
    features["cross_asset_residual"] = np.nan
    features["mlp_prediction"] = np.nan
    features["high_volatility"] = True
    for column in subject.COST_COLUMNS:
        features[column] = 10.0 if "point_value" in column else 1.0
    si = features.index[features["logical_asset"].eq("SI")]
    features.loc[si[25], ["z20", "std20", "quote_width"]] = [5.0, 100.0, 1000.0]
    features.loc[si[26], ["z20", "std20", "quote_width"]] = [0.0, 100.0, 1000.0]
    config = yaml.safe_load(v1.CONFIG_PATH.read_text(encoding="utf-8-sig"))
    return features, config


def test_cost_hurdle_uses_two_times_full_stress_round_trip() -> None:
    features, config = _cost_feature_frame()
    plans = subject.build_cost_aware_trade_plans(features, config)
    selected = plans.loc[
        plans["strategy_id"].eq("volatile_corridor_far_stop")
        & plans["asset"].eq("SI")
    ]
    assert len(selected) == 1
    row = selected.iloc[0]
    expected_cash = (5.0 - 0.35) * 100.0 * 10.0
    stress_round_trip = 2.0 * (4.0 * (1.0 * 10.0 + 1.0 * 10.0) + 2.0 * (1.0 + 1.0))
    assert row["expected_cash_opportunity_per_contract"] == pytest.approx(expected_cash)
    assert row["stress_round_trip_cost_per_contract"] == pytest.approx(stress_round_trip)
    assert row["opportunity_to_stress_cost_ratio"] == pytest.approx(
        expected_cash / stress_round_trip
    )
    assert row["opportunity_to_stress_cost_ratio"] >= 2.0


def test_selected_candidate_gets_unchanged_numeric_gate_but_adaptive_verdict() -> None:
    evaluation = {
        "cagr": 0.20,
        "sharpe": 2.0,
        "maximum_drawdown": 0.10,
        "positive_years": 2,
        "total_return": 0.30,
        "completed_trades": 30,
    }
    scenario = {
        "diagnostics": {"execution_complete": True},
        "periods": {"evaluation": evaluation},
    }
    metrics = {
        strategy: {
            "primary": scenario,
            "doubled": scenario,
            "stress": scenario,
        }
        for strategy in v1.STRATEGY_IDS
    }
    validation = {
        "minimum_evaluation_CAGR": 0.10,
        "minimum_evaluation_sharpe": 1.0,
        "maximum_evaluation_drawdown": 0.15,
        "minimum_positive_evaluation_years": 2,
        "minimum_completed_evaluation_trades": 20,
    }
    result = subject.selected_candidate_promotion(metrics, validation)
    assert result["passed"] is True
    assert result["selected_primary_strategy"] == "cross_sectional_extremes"
    assert result["post_selection_adaptive"] is True
    assert result["verdict"] == (
        "ADAPTIVE_LEAD_REQUIRES_NEW_UNSEEN_MULTILEG_VALIDATION"
    )


def test_context_adds_cost_columns_and_restores_every_parent_hook() -> None:
    originals = (
        v1._period_metrics,
        v1.build_feature_frame,
        v1.build_trade_plans,
        v1._promotion,
        v1._report_text,
        v1.ACTIVE_COLUMNS,
        v1.CONFIG_PATH,
    )
    with subject._correction_context():
        assert set(subject.COST_COLUMNS) <= set(v1.ACTIVE_COLUMNS)
        assert v1.build_trade_plans is subject.build_cost_aware_trade_plans
        assert v1._promotion is subject.selected_candidate_promotion
        assert v1.CONFIG_PATH == subject.CONFIG_PATH
    assert originals == (
        v1._period_metrics,
        v1.build_feature_frame,
        v1.build_trade_plans,
        v1._promotion,
        v1._report_text,
        v1.ACTIVE_COLUMNS,
        v1.CONFIG_PATH,
    )


def test_real_v4_protocol_is_post_selection_and_preserves_execution() -> None:
    protocol = subject.load_protocol()
    assert protocol.config_sha256 == (
        "b7ddc0ac977c61d7c4547ce978182d2a178422ee694ce1178d4d2d5c174677b9"
    )
    assert protocol.economic.payload["hypothesis"]["primary_strategy"] == (
        "cross_sectional_extremes"
    )
    assert protocol.economic.payload["execution"]["scenarios"] == v1.load_protocol().payload[
        "execution"
    ]["scenarios"]
    assert protocol.economic.output_directory == (
        subject.PROJECT_ROOT / "runs/calendar_spread_economic_2021_2025_v4"
    )
