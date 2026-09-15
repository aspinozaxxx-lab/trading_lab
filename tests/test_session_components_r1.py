"""Unit normalization does not change requests, source gaps, prices or cost multipliers."""

import numpy as np
import pandas as pd
from test_session_components import changed, fixture, local_time

from market_lab.futures import session_components as base
from market_lab.futures.session_components_r1 import calculate, price_unit_specs


def test_daily_monetary_unit_scaling_is_invariant_and_not_cash_pnl():
    market, specs, cfg = fixture()
    original_requests = base.requests(market, specs, cfg)
    pairs, report = calculate(original_requests, market, specs, cfg)
    scaled = specs.copy()
    factor = np.array([1.0, 2.0, 0.5, 3.0])
    for field in ("sizing_point_value", "sizing_tick_cash_value", "conservative_fee_per_side"):
        scaled[field] *= factor
    pd.testing.assert_frame_equal(original_requests, base.requests(market, scaled, cfg))
    after, other = calculate(original_requests, market, scaled, cfg)
    pd.testing.assert_frame_equal(pairs, after)
    assert report == other
    assert all("cash" not in c for c in pairs)
    for result in report["results"].values():
        assert result["portfolio_pnl"] is None and result["cagr"] is None
        assert "costs_cash_observed_pairs" not in result


def test_point_one_matches_original_bp_and_unknown_exit_is_preserved():
    market, specs, cfg = fixture()
    req = base.requests(market, specs, cfg)
    pairs, _ = calculate(req, market, specs, cfg)
    old = base.evaluate(req, market, specs, cfg, "primary")
    pd.testing.assert_series_equal(
        pairs.loc[pairs.scenario.eq("primary"), "net_basis_points"].reset_index(drop=True),
        old.net_basis_points.reset_index(drop=True),
    )
    bars = market.bars.copy()
    bars.loc[bars.timestamp.eq(local_time(market.sessions[1], 620)), "volume"] = 0
    mutated = changed(market, bars)
    after, report = calculate(req, mutated, specs, cfg)
    assert report["verdict"] == "INCOMPLETE_SOURCE_NO_PROMOTION"
    first = after.loc[after.arm.eq("off_session")].iloc[0]
    assert first.entered_quantity == 1 and first.closed_quantity == 0
    assert np.isnan(first.net_basis_points)


def test_fee_uses_its_own_prior_point_conversion():
    _, specs, _ = fixture()
    specs.loc[1, "sizing_point_value"] = 2.0
    specs.loc[1, "sizing_tick_cash_value"] = 50.0
    specs.loc[1, "conservative_fee_per_side"] = 15.0
    normalized = price_unit_specs(specs)
    assert normalized.loc[1, "sizing_point_value"] == 1.0
    assert normalized.loc[1, "sizing_tick_cash_value"] == 25.0
    assert normalized.loc[1, "conservative_fee_per_side"] == 7.5
    assert specs.loc[1, "sizing_point_value"] == 2.0
