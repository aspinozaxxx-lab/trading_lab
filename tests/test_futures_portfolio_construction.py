"""Testy causal portfolio construction bez future cen, labels i tuning."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from market_lab.futures.portfolio_construction import (
    ANNUAL_TARGET_VOLATILITY,
    COVARIANCE_SESSIONS,
    EWMA_VOLATILITY_SPAN,
    PORTFOLIO_ASSETS,
    PORTFOLIO_GROSS_CAP,
    TURNOVER_SLEEVES,
    build_causal_portfolio_targets,
)

# Chislo synthetic factual market sessions s zapasom dlya covariance.
SYNTHETIC_SESSIONS = 110


def _market_panel(sessions: int = SYNTHETIC_SESSIONS) -> pd.DataFrame:
    """Stroit polnyi adjusted-close panel s raznymi causal return-putyami."""
    dates = pd.bdate_range("2024-01-02", periods=sessions)
    step = np.arange(sessions, dtype=float)
    returns = {
        "SI": 0.0003 + 0.0080 * np.sin(step * 0.31) + 0.0020 * np.cos(step * 0.07),
        "RI": -0.0001 + 0.0100 * np.cos(step * 0.23) + 0.0015 * np.sin(step * 0.11),
        "BR": 0.0002 + 0.0120 * np.sin(step * 0.17 + 0.8),
        "MIX": 0.0001 + 0.0070 * np.cos(step * 0.29 + 0.4),
    }
    starts = {"SI": 90.0, "RI": 120_000.0, "BR": 75.0, "MIX": 3_000.0}
    rows = []
    for asset in PORTFOLIO_ASSETS:
        prices = starts[asset] * np.cumprod(1.0 + returns[asset])
        rows.extend(
            {
                "session_date": decision_date,
                "asset": asset,
                "adjusted_close": float(price),
            }
            for decision_date, price in zip(dates, prices, strict=True)
        )
    return pd.DataFrame(rows)


def _score_frame(
    dates: pd.DatetimeIndex,
    values: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Stroit polnye candidate-score snapshots na ukazannye decision dates."""
    scores = values or {"SI": 0.8, "RI": -0.6, "BR": 0.4, "MIX": -0.2}
    return pd.DataFrame(
        [
            {
                "decision_date": decision_date,
                "asset": asset,
                "candidate_score": scores[asset],
            }
            for decision_date in dates
            for asset in PORTFOLIO_ASSETS
        ]
    )


def _weights(frame: pd.DataFrame) -> pd.DataFrame:
    """Razvorachivaet polnyi output snapshot v decision-by-asset weights."""
    return frame.pivot(index="decision_date", columns="asset", values="target_weight").reindex(
        columns=PORTFOLIO_ASSETS
    )


def test_fixed_defaults_full_snapshot_and_risk_caps() -> None:
    """Fiksiruet 20/60/20%, 1x, 5 sleeves i proveriaet risk/gross caps."""
    assert EWMA_VOLATILITY_SPAN == 20
    assert COVARIANCE_SESSIONS == 60
    assert ANNUAL_TARGET_VOLATILITY == 0.20
    assert PORTFOLIO_GROSS_CAP == 1.0
    assert TURNOVER_SLEEVES == 5
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))[75:85]
    result = build_causal_portfolio_targets(market, _score_frame(dates))

    assert len(result) == len(dates) * len(PORTFOLIO_ASSETS)
    assert result.columns.tolist() == [
        "decision_date",
        "asset",
        "target_weight",
        "gross",
        "expected_annual_volatility",
        "provenance",
    ]
    asset_snapshots = result.groupby("decision_date")["asset"].agg(tuple)
    assert all(value == PORTFOLIO_ASSETS for value in asset_snapshots)
    assert result["gross"].between(0.0, PORTFOLIO_GROSS_CAP + 1e-12).all()
    assert result["expected_annual_volatility"].between(
        0.0, ANNUAL_TARGET_VOLATILITY + 1e-12
    ).all()
    assert _weights(result).iloc[-1].abs().sum() > 0.0
    for _, snapshot in result.groupby("decision_date"):
        assert snapshot["gross"].nunique() == 1
        assert snapshot["expected_annual_volatility"].nunique() == 1
    provenance = json.loads(result.iloc[-1]["provenance"])
    assert provenance["annual_target_volatility"] == 0.20
    assert provenance["intended_execution"] == "next_factual_trade_date_open"
    assert provenance["uses_future_prices_or_labels"] is False


def test_future_mutation_and_append_leave_historical_prefix_unchanged() -> None:
    """Dokazyvaet cutoff <=D i append-only stabilnost' gotovyh snapshots."""
    market = _market_panel()
    all_dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))
    decision_dates = all_dates[72:82]
    scores = _score_frame(decision_dates)
    base_last = decision_dates[4]
    base_market = market.loc[market["session_date"].le(base_last)].copy()
    base_scores = scores.loc[scores["decision_date"].le(base_last)].copy()
    base = build_causal_portfolio_targets(base_market, base_scores)
    extended = build_causal_portfolio_targets(market, scores)
    historical_extended = extended.loc[extended["decision_date"].le(base_last)].reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(base.reset_index(drop=True), historical_extended)

    mutated_market = market.copy()
    future_mask = mutated_market["session_date"].gt(base_last)
    mutated_market.loc[future_mask, "adjusted_close"] *= 9.0
    mutated_scores = scores.copy()
    mutated_scores.loc[mutated_scores["decision_date"].gt(base_last), "candidate_score"] *= -11.0
    mutated = build_causal_portfolio_targets(mutated_market, mutated_scores)
    historical_mutated = mutated.loc[mutated["decision_date"].le(base_last)].reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(base.reset_index(drop=True), historical_mutated)


def test_price_level_and_global_score_scale_invariance() -> None:
    """Dokazyvaet invariantnost' k edinicam cen i obshchemu masshtabu score."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))[75:83]
    scores = _score_frame(dates)
    baseline = build_causal_portfolio_targets(market, scores)

    scaled_market = market.copy()
    price_scales = {"SI": 1_000.0, "RI": 0.01, "BR": 7.0, "MIX": 0.2}
    scaled_market["adjusted_close"] *= scaled_market["asset"].map(price_scales)
    scaled_scores = scores.copy()
    scaled_scores["candidate_score"] *= 17.0
    scaled = build_causal_portfolio_targets(scaled_market, scaled_scores)

    np.testing.assert_allclose(
        baseline["target_weight"],
        scaled["target_weight"],
        rtol=1e-10,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        baseline["expected_annual_volatility"],
        scaled["expected_annual_volatility"],
        rtol=1e-10,
        atol=1e-12,
    )


def test_five_sleeve_impulse_is_equal_for_five_snapshots_then_expires() -> None:
    """Proveryaet ravnye 1/5 sleeves bez calendar-day sdviga."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))[75:81]
    rows = []
    for offset, decision_date in enumerate(dates):
        for asset in PORTFOLIO_ASSETS:
            rows.append(
                {
                    "decision_date": decision_date,
                    "asset": asset,
                    "candidate_score": 1.0 if offset == 0 and asset == "SI" else 0.0,
                }
            )
    result = build_causal_portfolio_targets(market, pd.DataFrame(rows))
    si_weights = _weights(result)["SI"]
    assert si_weights.iloc[0] != 0.0
    np.testing.assert_allclose(si_weights.iloc[:5], np.repeat(si_weights.iloc[0], 5))
    assert si_weights.iloc[5] == 0.0
    assert result["decision_date"].drop_duplicates().tolist() == list(dates)


def test_missing_or_insufficient_inputs_are_cash_with_full_snapshot() -> None:
    """Obnulyaet NaN/otsutstvuyushchii market/score i vsegda vozvrashchaet 4 assets."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))
    early_date = dates[30]
    mature_date = dates[75]
    market = market.loc[
        ~(
            market["session_date"].eq(mature_date)
            & market["asset"].eq("BR")
        )
    ].copy()
    scores = pd.DataFrame(
        [
            {"decision_date": early_date, "asset": asset, "candidate_score": 1.0}
            for asset in PORTFOLIO_ASSETS
        ]
        + [
            {"decision_date": mature_date, "asset": "SI", "candidate_score": 1.0},
            {"decision_date": mature_date, "asset": "RI", "candidate_score": np.nan},
            {"decision_date": mature_date, "asset": "BR", "candidate_score": 1.0},
        ]
    )
    result = build_causal_portfolio_targets(market, scores)
    weights = _weights(result)

    assert weights.loc[early_date].eq(0.0).all()
    assert weights.loc[mature_date, ["RI", "BR", "MIX"]].eq(0.0).all()
    assert weights.loc[mature_date, "SI"] != 0.0
    assert result.groupby("decision_date").size().eq(len(PORTFOLIO_ASSETS)).all()
    mature = result.loc[result["decision_date"].eq(mature_date)].set_index("asset")
    reasons = {
        asset: json.loads(mature.loc[asset, "provenance"])["cash_reason"]
        for asset in PORTFOLIO_ASSETS
    }
    assert reasons["RI"] == "missing_candidate_score"
    assert reasons["BR"] == "missing_current_adjusted_close"
    assert reasons["MIX"] == "missing_candidate_score"
    assert json.loads(mature.loc["SI", "provenance"])["market_cutoff"] == (
        mature_date.date().isoformat()
    )
