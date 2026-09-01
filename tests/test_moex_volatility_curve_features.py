"""Tests for causal MOEX curve analytics and constant-maturity interpolation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab.futures import moex_volatility_curve_features as features


def test_forward_atm_formula_and_derivatives_at_zero_shift() -> None:
    frame = pd.DataFrame(
        {
            "s": [0.0, 0.0],
            "a": [20.0, 10.0],
            "b": [0.0, 2.0],
            "c": [1.0, 3.0],
            "d": [0.0, 4.0],
            "e": [0.0, 5.0],
            "years_to_expiry": [0.25, 0.25],
        }
    )

    result = features.evaluate_curve_at_forward_atm(frame)

    assert result["curve_analytic_valid"].all()
    assert result.loc[0, "atm_volatility_pct"] == 20.0
    assert result.loc[0, "atm_skew_per_x"] == 0.0
    assert result.loc[1, "atm_volatility_pct"] == 10.0
    assert result.loc[1, "atm_skew_per_x"] == 4.0
    assert result.loc[1, "atm_curvature_per_x2"] == 12.0


def test_nonpositive_maturity_is_missing_not_zero() -> None:
    frame = pd.DataFrame(
        {
            "s": [0.1, 0.1],
            "a": [20.0, 20.0],
            "b": [1.0, 1.0],
            "c": [1.0, 1.0],
            "d": [1.0, 1.0],
            "e": [1.0, 1.0],
            "years_to_expiry": [0.0, -0.001],
        }
    )

    result = features.evaluate_curve_at_forward_atm(frame)

    assert not result["curve_analytic_valid"].any()
    assert result[list(features.ANALYTIC_COLUMNS)].isna().all().all()


def test_interpolation_brackets_without_extrapolation() -> None:
    now = pd.Timestamp("2021-01-05 10:10", tz="Europe/Moscow")
    states = pd.DataFrame(
        {
            "fresh": [True, True],
            "effective_years_to_expiry": [20 / 365, 40 / 365],
            "full_name": ["RTS-20", "RTS-40"],
            "event_at": [now - pd.Timedelta(minutes=2)] * 2,
            "available_at": [now - pd.Timedelta(minutes=1)] * 2,
            "source_age_minutes": [1.0, 1.0],
            "decision_atm_volatility_pct": [10.0, 30.0],
            "decision_atm_skew_per_x": [-2.0, 2.0],
            "decision_atm_curvature_per_x2": [4.0, 8.0],
        }
    )

    middle = features._interpolate_metric(states, 30 / 365)
    outside = features._interpolate_metric(states, 90 / 365)

    assert middle["available"] is True
    assert middle["atm_volatility_pct"] == 20.0
    assert middle["atm_skew_per_x"] == 0.0
    assert middle["atm_curvature_per_x2"] == 6.0
    assert outside["available"] is False
    assert np.isnan(outside["atm_volatility_pct"])


def test_future_event_cannot_change_completed_asof_state() -> None:
    timezone = "Europe/Moscow"
    base = pd.DataFrame(
        {
            "full_name": ["RTS-3.21os"],
            "small_name": ["RTS-3.21os"],
            "asset": ["RI"],
            "source_root": ["RTS"],
            "event_at": [pd.Timestamp("2021-01-05 10:00", tz=timezone)],
            "available_at": [pd.Timestamp("2021-01-05 10:01", tz=timezone)],
            "years_to_expiry": [0.2],
            "s": [0.0],
            "a": [20.0],
            "b": [1.0],
            "c": [1.0],
            "d": [1.0],
            "e": [1.0],
            "curve_analytic_valid": [True],
        }
    )
    future = base.copy()
    future["event_at"] = pd.Timestamp("2021-01-05 10:20", tz=timezone)
    future["available_at"] = pd.Timestamp("2021-01-05 10:21", tz=timezone)
    future["a"] = 99.0
    grid = pd.DataFrame(
        {
            "decision_at": [pd.Timestamp("2021-01-05 10:10", tz=timezone)],
            "decision_date": [pd.Timestamp("2021-01-05")],
        }
    )

    expected = features._latest_series_states(base, grid)
    actual = features._latest_series_states(pd.concat([base, future]), grid)

    pd.testing.assert_frame_equal(expected, actual)


def test_panel_preserves_declared_asset_order_and_exposes_all_context() -> None:
    timezone = "Europe/Moscow"
    event_at = pd.Timestamp("2021-01-05 10:00", tz=timezone)
    rows: list[dict[str, object]] = []
    for asset in features.ASSETS:
        for days, level in ((20, 10.0), (100, 30.0)):
            rows.append(
                {
                    "full_name": f"{asset}-{days}",
                    "small_name": f"{asset}-{days}",
                    "asset": asset,
                    "source_root": asset,
                    "event_at": event_at,
                    "available_at": event_at + pd.Timedelta(minutes=1),
                    "years_to_expiry": days / 365.0,
                    "s": 0.0,
                    "a": level,
                    "b": 0.0,
                    "c": 1.0,
                    "d": 0.0,
                    "e": 0.0,
                    "curve_analytic_valid": True,
                }
            )
    event_features = pd.DataFrame(rows)

    panel, _ = features.build_constant_maturity_panel(event_features)
    first_decision = panel.loc[panel["decision_at"].eq(panel["decision_at"].min())]

    assert tuple(first_decision["asset"]) == features.ASSETS
    assert first_decision["complete_30d_90d"].all()
    for asset in features.ASSETS:
        column = f"context_{asset.lower()}_volatility_30d"
        assert first_decision[column].notna().all()
