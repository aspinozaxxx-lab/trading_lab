"""Outcome-free tests for V36 online expert allocation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab import futures_v36_online_expert_ensemble as runner
from market_lab.futures import online_expert_ensemble as core


def _synthetic_panel() -> pd.DataFrame:
    dates = pd.bdate_range("2010-01-04", periods=620)
    rows = []
    for asset_index, asset in enumerate(core.ASSETS):
        returns = 0.0002 * (asset_index + 1) + 0.001 * np.sin(np.arange(len(dates)) / 17.0)
        closes = (100.0 + asset_index * 10.0) * np.exp(np.cumsum(returns))
        for date, close in zip(dates, closes, strict=True):
            rows.append(
                {
                    "trade_date": date,
                    "asset_code": asset,
                    "close": close,
                    "roll_yield": 0.01 if asset_index % 2 == 0 else -0.01,
                    "curve_valid": True,
                }
            )
    return pd.DataFrame(rows)


def test_config_seal_and_expert_order_are_fixed() -> None:
    config = runner.load_config()
    assert tuple(config["experts"]["ordered"]) == core.EXPERTS
    assert config["dates"]["forbidden_from"] == "2026-01-01"
    assert config["reporting"]["live_promotion_allowed"] is False


def test_expert_weights_are_causal_nonnegative_and_sum_to_one() -> None:
    config = runner.load_config()
    built = core.build_expert_scores(_synthetic_panel(), config)

    assert all(built.checks.values())
    sums = built.expert_weights.groupby("decision_date")["weight"].sum()
    assert np.allclose(sums, 1.0)
    assert built.expert_weights["weight"].ge(0.0).all()
    assert set(built.scores) == {
        "online_expert",
        "static_equal_active_experts",
        "frozen_three_sleeve",
    }


def test_first_week_is_uniform_and_has_no_future_update() -> None:
    config = runner.load_config()
    built = core.build_expert_scores(_synthetic_panel(), config)
    first_date = built.expert_weights["decision_date"].min()
    first = built.expert_weights.loc[built.expert_weights["decision_date"].eq(first_date)]

    assert np.allclose(first["weight"], 1.0 / len(core.EXPERTS))
    assert first["prior_week_proxy_return"].eq(0.0).all()


def test_risk_restoration_applies_online_cash_after_multiplier() -> None:
    config = runner.load_config()
    date = pd.Timestamp("2020-01-03")
    weekly = pd.DataFrame(
        {
            "decision_date": [date] * 4,
            "asset": list(core.ASSETS),
            "target_weight": [0.25, -0.25, 0.25, -0.25],
            "gross": [1.0] * 4,
            "expected_annual_volatility": [0.20] * 4,
            "provenance": ["synthetic"] * 4,
        }
    )
    scores = pd.DataFrame(
        {
            "decision_date": [date] * 4,
            "active_fraction": [0.5] * 4,
        }
    )

    restored, risk = core.restore_weekly_weights(weekly, scores, config)

    assert risk.iloc[0]["risk_multiplier"] == 1.25
    assert restored["target_weight"].abs().sum() == 0.625


def test_restoration_is_applied_only_after_base_mapping() -> None:
    date = pd.Timestamp("2020-01-03")
    mapped = pd.DataFrame(
        {
            "decision_date": [date] * 4,
            "effective_date": [date + pd.Timedelta(days=3)] * 4,
            "asset_code": list(core.ASSETS),
            "contract_id": ["A", "B", "C", "D"],
            "target_weight": [0.5, -0.5, 0.0, 0.0],
            "provenance": ["base"] * 4,
        }
    )
    risk = pd.DataFrame(
        {
            "decision_date": [date],
            "risk_multiplier": [2.0],
            "active_fraction": [0.5],
        }
    )

    restored = core.restore_mapped_targets(mapped, risk)

    assert restored["pre_restoration_target_weight"].abs().sum() == 1.0
    assert restored["target_weight"].abs().sum() == 1.0
    assert restored["provenance"].str.contains("V36_post_map_risk").all()


def test_preflight_verifies_all_declared_eras_without_price_decode() -> None:
    result = runner.preflight(runner.load_config())
    assert all(result["checks"].values())
    assert len(result["metadata"]) == 9


def test_source_projection_has_unique_execution_columns() -> None:
    panel, active, observations, specs = runner._read_inputs(runner.load_config())

    assert not panel.columns.duplicated().any()
    assert not active.columns.duplicated().any()
    assert not observations.columns.duplicated().any()
    assert not specs.columns.duplicated().any()
    assert "logical_asset" in observations
    assert "asset_code" not in observations
