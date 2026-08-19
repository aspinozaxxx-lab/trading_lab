"""Testy causal post-sleeve risk targeting futures-v7."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from market_lab.futures.portfolio_construction import (
    PORTFOLIO_ASSETS,
    build_causal_portfolio_targets,
)
from market_lab.futures.v7_portfolio import (
    V7_ANNUAL_TARGET_VOLATILITY,
    V7_GROSS_CAP,
    V7_PORTFOLIO_VERSION,
    build_causal_v7_portfolio_targets,
)

# Chislo synthetic sessions s zapasom dlya 60-session covariance.
SYNTHETIC_SESSIONS = 115


def _market_panel() -> pd.DataFrame:
    """Stroit polnyi four-asset factual close panel s nenulevoi covariance."""
    dates = pd.bdate_range("2023-01-03", periods=SYNTHETIC_SESSIONS)
    step = np.arange(SYNTHETIC_SESSIONS, dtype=float)
    paths = {
        "SI": 0.0002 + 0.010 * np.sin(step * 0.21),
        "RI": -0.0001 + 0.013 * np.cos(step * 0.17),
        "BR": 0.0003 + 0.016 * np.sin(step * 0.13 + 0.7),
        "MIX": 0.0001 + 0.009 * np.cos(step * 0.27 + 0.3),
    }
    starts = {"SI": 70.0, "RI": 100_000.0, "BR": 80.0, "MIX": 3_000.0}
    rows: list[dict[str, object]] = []
    for asset in PORTFOLIO_ASSETS:
        prices = starts[asset] * np.cumprod(1.0 + paths[asset])
        rows.extend(
            {
                "session_date": date,
                "asset": asset,
                "adjusted_close": float(price),
            }
            for date, price in zip(dates, prices, strict=True)
        )
    return pd.DataFrame(rows)


def _scores(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Stroit slabye polnye scores dlya proverki upward rescaling."""
    values = {"SI": 0.25, "RI": -0.18, "BR": 0.12, "MIX": -0.08}
    return pd.DataFrame(
        [
            {"decision_date": date, "asset": asset, "candidate_score": values[asset]}
            for date in dates
            for asset in PORTFOLIO_ASSETS
        ]
    )


def test_post_sleeve_target_uses_risk_without_exceeding_one_x() -> None:
    """Podnimaet razmytuyu sleeves ekspoziciyu do 20% ili do gross 1x."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))[75:86]
    scores = _scores(dates)
    base = build_causal_portfolio_targets(market, scores)
    result = build_causal_v7_portfolio_targets(market, scores)

    base_risk = base.groupby("decision_date")["expected_annual_volatility"].first()
    v7_risk = result.groupby("decision_date")["expected_annual_volatility"].first()
    assert (v7_risk >= base_risk - 1e-12).all()
    assert (result["gross"] <= V7_GROSS_CAP + 1e-12).all()
    for _, snapshot in result.groupby("decision_date"):
        gross = float(snapshot["gross"].iloc[0])
        risk = float(snapshot["expected_annual_volatility"].iloc[0])
        assert np.isclose(risk, V7_ANNUAL_TARGET_VOLATILITY, atol=1e-10) or np.isclose(
            gross,
            V7_GROSS_CAP,
            atol=1e-10,
        )
    provenance = json.loads(result.iloc[-1]["provenance"])
    assert provenance["v7_portfolio_version"] == V7_PORTFOLIO_VERSION
    assert provenance["post_sleeve_bidirectional_scaling"] is True
    assert provenance["uses_future_prices_or_labels"] is False


def test_future_mutation_and_append_leave_v7_prefix_unchanged() -> None:
    """Dokazyvaet chto post-sleeve scale na D ne chitaet market ili score posle D."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))[75:86]
    cutoff = dates[4]
    scores = _scores(dates)
    base = build_causal_v7_portfolio_targets(
        market.loc[market["session_date"].le(cutoff)].copy(),
        scores.loc[scores["decision_date"].le(cutoff)].copy(),
    )
    extended = build_causal_v7_portfolio_targets(market, scores)
    prefix = extended.loc[extended["decision_date"].le(cutoff)].reset_index(drop=True)
    pd.testing.assert_frame_equal(base.reset_index(drop=True), prefix)

    mutated_market = market.copy()
    mutated_market.loc[mutated_market["session_date"].gt(cutoff), "adjusted_close"] *= 8.0
    mutated_scores = scores.copy()
    mutated_scores.loc[mutated_scores["decision_date"].gt(cutoff), "candidate_score"] *= -9.0
    mutated = build_causal_v7_portfolio_targets(mutated_market, mutated_scores)
    mutated_prefix = mutated.loc[mutated["decision_date"].le(cutoff)].reset_index(drop=True)
    pd.testing.assert_frame_equal(base.reset_index(drop=True), mutated_prefix)


def test_all_cash_and_missing_asset_remain_fail_closed() -> None:
    """Ne sozdaet ekspoziciyu iz nulevogo ili nedostupnogo base target."""
    market = _market_panel()
    dates = pd.DatetimeIndex(sorted(market["session_date"].unique()))
    decision = dates[75]
    zero_scores = pd.DataFrame(
        [
            {"decision_date": decision, "asset": asset, "candidate_score": 0.0}
            for asset in PORTFOLIO_ASSETS
        ]
    )
    zero = build_causal_v7_portfolio_targets(market, zero_scores)
    assert zero["target_weight"].eq(0.0).all()
    assert zero["gross"].eq(0.0).all()
    assert zero["expected_annual_volatility"].eq(0.0).all()

    missing_market = market.loc[
        ~(market["session_date"].eq(decision) & market["asset"].eq("BR"))
    ].copy()
    active_scores = zero_scores.assign(candidate_score=1.0)
    guarded = build_causal_v7_portfolio_targets(missing_market, active_scores)
    snapshot = guarded.set_index("asset")
    assert snapshot.loc["BR", "target_weight"] == 0.0
    assert snapshot["gross"].iloc[0] <= V7_GROSS_CAP + 1e-12
