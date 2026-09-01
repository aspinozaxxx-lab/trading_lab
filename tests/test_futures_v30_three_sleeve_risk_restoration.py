"""Tests for V30 equal signal sleeves and causal final-risk restoration."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab import futures_v30_three_sleeve_risk_restoration as source


def _trend_and_curve() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = [pd.Timestamp("2012-01-03"), pd.Timestamp("2012-01-04")]
    assets = list(source.ASSETS)
    first = [1.0, 0.5, -0.5, -1.0]
    second = [0.5, np.nan, np.nan, np.nan]
    trend = pd.DataFrame(
        [
            {
                "decision_date": date,
                "asset": asset,
                "candidate_score": values[index],
            }
            for date, values in zip(dates, (first, second), strict=True)
            for index, asset in enumerate(assets)
        ]
    )
    carry = [1.0, -1.0, np.nan, 1.0]
    curve = pd.DataFrame(
        [
            {
                "trade_date": date,
                "asset": asset,
                "roll_yield": carry[index],
                "carry_available": index != 2,
            }
            for date in dates
            for index, asset in enumerate(assets)
        ]
    )
    return trend, curve


def _scenario(
    *, cagr: float = 0.22, sharpe: float = 1.1, mdd: float = 0.25
) -> dict[str, object]:
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": mdd,
        "positive_years": 4,
        "worst_year": -0.10,
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
    }


def _robustness() -> dict[str, object]:
    bootstrap = {
        str(block): {"probability_cagr_ge_0_20_and_mdd_le_0_30": 0.45}
        for block in source.BOOTSTRAP_BLOCKS
    }
    leave = {
        str(year): {"cagr": 0.10, "sharpe": 0.8, "maximum_drawdown": 0.25}
        for year in range(2013, 2018)
    }
    summary = {
        "bootstrap": bootstrap,
        "leave_one_year_out": leave,
        "rolling_252": {
            "positive_fraction": 0.80,
            "maximum_window_drawdown": 0.25,
        },
    }
    return {"primary": summary, "stress": summary}


def test_default_protocol_is_development_only_and_pre2012_unread() -> None:
    protocol = source.load_protocol()

    assert protocol.payload["development_selection"]["independent_validation"] is False
    assert protocol.payload["development_selection"]["2008_2011_returns_or_pnl_observed"] is False
    assert protocol.payload["risk_restoration"]["maximum_multiplier"] == 2.0


def test_components_are_equal_bounded_and_missing_carry_sleeps_only() -> None:
    trend, curve = _trend_and_curve()

    built = source.compose_signal_components(trend, curve)
    first = built.components.loc[
        built.components["decision_date"].eq(pd.Timestamp("2012-01-03"))
    ].set_index("asset")

    assert first.loc["SI", "composite_score"] == 1.0
    assert first.loc["RI", "composite_score"] == 0.0
    assert np.isclose(first.loc["BR", "composite_score"], -1.0 / 3.0)
    assert first.loc["BR", "curve_carry"] == 0.0
    assert not bool(first.loc["BR", "carry_available"])
    assert built.components["composite_score"].dropna().abs().le(1.0).all()
    assert all(built.checks.values())


def test_single_available_asset_has_zero_relative_component() -> None:
    trend, curve = _trend_and_curve()

    built = source.compose_signal_components(trend, curve)
    second = built.components.loc[
        built.components["decision_date"].eq(pd.Timestamp("2012-01-04"))
    ].set_index("asset")

    assert second.loc["SI", "relative_trend"] == 0.0
    assert np.isfinite(second.loc["SI", "composite_score"])
    assert second.loc[["RI", "BR", "MIX"], "composite_score"].isna().all()


def test_risk_restoration_is_cash_at_zero_and_capped_at_two() -> None:
    expected = pd.Series([0.0, np.nan, 0.05, 0.10, 0.20, 0.40])

    multiplier = source.risk_restoration_multiplier(expected)

    assert multiplier.tolist() == [0.0, 0.0, 2.0, 2.0, 1.0, 0.5]
    restored = expected.fillna(0.0) * multiplier
    assert restored.le(source.FINAL_TARGET_VOLATILITY + 1e-12).all()


def test_assessment_passes_only_with_all_stability_gates() -> None:
    scenarios = {
        "primary": _scenario(),
        "doubled": _scenario(cagr=0.21),
        "stress": _scenario(cagr=0.205, sharpe=1.02, mdd=0.29),
    }

    passed = source.assess_candidate(scenarios, _robustness(), {"proof": True})
    scenarios["stress"] = _scenario(cagr=0.199, sharpe=1.02, mdd=0.29)
    failed = source.assess_candidate(scenarios, _robustness(), {"proof": True})

    assert passed["passed"] is True
    assert passed["supports_50_percent_on_open_development"] is False
    assert failed["passed"] is False
    assert failed["conditions"]["all_main_CAGR_at_least_20pct"] is False
