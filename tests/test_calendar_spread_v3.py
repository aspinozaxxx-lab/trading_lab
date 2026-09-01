"""Tests for calendar-spread V3 source-semantics correction."""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from market_lab.futures import calendar_spread_v1 as v1
from market_lab.futures import calendar_spread_v2 as v2
from market_lab.futures import calendar_spread_v3 as subject
from tests.test_calendar_spread_v1 import _active_frame


def test_feature_builder_uses_factual_last_not_closing_midpoint() -> None:
    active = _active_frame()
    active["last"] = active["quote_midpoint"] + np.sin(
        np.arange(len(active), dtype=float)
    )
    features = subject.build_last_trade_feature_frame(active)
    expected = active.sort_values(
        ["logical_asset", "trade_date"], kind="mergesort", ignore_index=True
    )
    assert features["quote_midpoint"].to_numpy() == pytest.approx(
        expected["last"].to_numpy()
    )
    assert not np.allclose(
        features["quote_midpoint"].to_numpy(),
        expected["bid"].add(expected["ask"]).div(2.0).to_numpy(),
    )


def test_trade_planner_does_not_use_eod_width_as_next_open_admission() -> None:
    features = v1.build_feature_frame(_active_frame())
    for column in ("z10", "z20", "z40", "momentum5", "zero_convergence_score"):
        features[column] = np.nan
    features["cross_asset_residual"] = np.nan
    features["mlp_prediction"] = np.nan
    features["high_volatility"] = True
    si = features.index[features["logical_asset"].eq("SI")]
    features.loc[si[25], ["z20", "std20", "quote_width"]] = [2.0, 1.0, 1000.0]
    features.loc[si[26], ["z20", "std20", "quote_width"]] = [0.0, 1.0, 1000.0]
    config = yaml.safe_load(v1.CONFIG_PATH.read_text(encoding="utf-8-sig"))
    with pytest.raises(ValueError, match="generated no plans"):
        v1.build_trade_plans(features, config)
    corrected = subject.build_width_independent_trade_plans(features, config)
    selected = corrected.loc[
        corrected["strategy_id"].eq("volatile_corridor_far_stop")
        & corrected["asset"].eq("SI")
    ]
    assert len(selected) == 1
    assert selected.iloc[0]["exit_reason"] == "corridor_take_profit"


def test_v3_context_changes_only_three_parent_hooks_and_restores() -> None:
    originals = (
        v1._period_metrics,
        v1.build_feature_frame,
        v1.build_trade_plans,
        v1.CONFIG_PATH,
    )
    with subject._correction_context():
        assert v1._period_metrics is v2.corrected_period_metrics
        assert v1.build_feature_frame is subject.build_last_trade_feature_frame
        assert v1.build_trade_plans is subject.build_width_independent_trade_plans
        assert v1.CONFIG_PATH == subject.CONFIG_PATH
    assert originals == (
        v1._period_metrics,
        v1.build_feature_frame,
        v1.build_trade_plans,
        v1.CONFIG_PATH,
    )


def test_real_v3_protocol_preserves_strategy_and_cost_definitions() -> None:
    protocol = subject.load_protocol()
    parent = v2.load_protocol()
    assert protocol.config_sha256 == (
        "c38a7356385baeb75be7f0f206f757d49ff192284239630aed1aee72a79f8f57"
    )
    assert protocol.economic.payload["strategies"] == parent.economic.payload[
        "strategies"
    ]
    assert protocol.economic.payload["execution"] == parent.economic.payload[
        "execution"
    ]
    assert protocol.economic.output_directory == (
        subject.PROJECT_ROOT / "runs/calendar_spread_economic_2021_2025_v3"
    )
