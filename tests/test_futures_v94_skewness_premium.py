"""Synthetic causal feature, roll, missingness, fixed-rule and ledger checks."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v94_skewness_premium as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def fixture():
    days = pd.bdate_range("2020-04-01", "2021-03-31")
    x = np.arange(len(days))
    returns = [np.where(x % 13 == 0, -0.04, 0.001), np.sin(x) * 0.005,
               np.where(x % 5 == 0, 0.01, -0.002), np.where(x % 13 == 0, 0.04, -0.001)]
    maps, observations = [], []
    for asset, ret in zip(screen.ASSETS, returns, strict=True):
        maps.append(pd.DataFrame({"effective_date": days,
            "decision_date": pd.Series(days).shift(1),
            "observed_through": pd.Series(days).shift(1), "asset_code": asset,
            "contract_id": np.where(x < 190, asset + "A", asset + "B"),
            "plan_tradable": True, "roll": x == 190}))
        for suffix, scale in (("A", 100), ("B", 10000)):
            close = scale * np.cumprod(1 + ret)
            observations.append(pd.DataFrame({"trade_date": days, "logical_asset": asset,
                "canonical_contract_id": asset + suffix, "close": close, "volume": 1e7}))
    return pd.concat(maps, ignore_index=True), pd.concat(observations, ignore_index=True)


def test_daily_return_is_same_contract_even_when_roll_prices_differ_hundredfold():
    active, obs = fixture()
    f = screen.features(active, obs, config())
    for asset in screen.ASSETS:
        part = f.loc[f.asset_code.eq(asset)].reset_index(drop=True)
        assert part.loc[190, "roll"]
        assert abs(part.loc[190, "same_contract_return"]) < 0.05
        expected = part.same_contract_return.iloc[65:191].skew()
        assert part.loc[190, "skewness"] == pytest.approx(expected)
        assert part.skewness.iloc[:126].isna().all()


def test_known_low_high_selection_next_open_mirror_gross_and_terminal_flat():
    active, obs = fixture()
    f = screen.features(active, obs, config())
    signals = screen.targets(active, f, config())
    p, c = signals["primary"], signals["control"]
    used = p.loc[p.target_weight.ne(0)]
    assert not used.empty
    assert set(used.asset_code) == {"BR", "SI"}
    assert used.loc[used.asset_code.eq("BR"), "target_weight"].eq(0.45).all()
    assert used.loc[used.asset_code.eq("SI"), "target_weight"].eq(-0.45).all()
    assert (used.selection_date <= used.decision_date).all()
    assert (used.decision_date < used.effective_date).all()
    assert (used.observed_through <= used.decision_date).all()
    assert p.groupby("effective_date").target_weight.apply(lambda s: s.abs().sum()).max() == 0.9
    assert p.groupby("effective_date").target_weight.sum().eq(0).all()
    assert p.loc[p.terminal_flat, "target_weight"].eq(0).all()
    np.testing.assert_array_equal(p.target_weight, -c.target_weight)
    assert p.selection_date.equals(c.selection_date)


def test_future_prices_cannot_change_past_features_or_decisions():
    active, obs = fixture()
    altered = obs.copy()
    cutoff = pd.Timestamp("2021-02-12")
    later = altered.trade_date.gt(cutoff)
    altered.loc[later, "close"] *= np.arange(later.sum()) + 1
    fa, fb = [screen.features(active, o, config()) for o in (obs, altered)]
    pd.testing.assert_frame_equal(fa.loc[fa.effective_date.le(cutoff)],
                                  fb.loc[fb.effective_date.le(cutoff)])
    a, b = [screen.targets(active, f, config())["primary"] for f in (fa, fb)]
    pd.testing.assert_frame_equal(a.loc[a.decision_date.le(cutoff)],
                                  b.loc[b.decision_date.le(cutoff)])


def test_missing_or_zero_volume_invalidates_full_window_not_compressed_or_zero_filled():
    active, obs = fixture()
    mask = obs.trade_date.eq("2020-08-03") & obs.logical_asset.eq("BR")
    for variant in (obs.loc[~mask], obs.assign(volume=obs.volume.mask(mask, 0.0))):
        f = screen.features(active, variant, config())
        b = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
        pos = b.index[b.effective_date.eq("2020-08-03")][0]
        assert b.same_contract_return.iloc[pos:pos + 2].isna().all()
        assert b.skewness.iloc[pos:pos + 127].isna().all()
        assert np.isfinite(b.skewness.iloc[pos + 127])


def test_incomplete_monthly_snapshot_does_not_reuse_old_rank_or_revive_midmonth():
    active, obs = fixture()
    f = screen.features(active, obs, config())
    f.loc[f.effective_date.eq("2021-02-01") & f.asset_code.eq("BR"), "skewness"] = np.nan
    p = screen.targets(active, f, config())["primary"]
    feb = p.loc[p.decision_date.between("2021-02-01", "2021-02-26")]
    assert feb.feature_unavailable.all() and feb.target_weight.eq(0).all()
    assert p.loc[p.decision_date.eq("2021-03-01"), "target_weight"].ne(0).any()


def test_tied_extremes_and_zero_variance_sleep_without_asset_tiebreak():
    active, obs = fixture()
    f = screen.features(active, obs.assign(close=100.0), config())
    assert f.skewness.isna().all()
    p = screen.targets(active, f, config())["primary"]
    assert p.target_weight.eq(0).all()
    f["skewness"] = f.asset_code.map({"BR": -2.0, "MIX": -2.0, "RI": 0.0, "SI": 2.0})
    assert screen.targets(active, f, config())["primary"].target_weight.eq(0).all()


def test_protected_duplicates_and_noncausal_input_fail_closed():
    active, obs = fixture()
    with pytest.raises(ValueError, match="duplicate map"):
        screen.features(pd.concat([active, active.iloc[:1]]), obs, config())
    with pytest.raises(ValueError, match="duplicate observation"):
        screen.features(active, pd.concat([obs, obs.iloc[:1]]), config())
    changed = active.copy()
    changed.loc[10, "observed_through"] = pd.Timestamp("2025-01-01")
    with pytest.raises(ValueError, match="noncausal"):
        screen.features(changed, obs, config())
    changed = obs.copy()
    changed.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.features(active, changed, config())
    with pytest.raises(ValueError, match="four-asset"):
        screen.features(active.iloc[1:], obs, config())


def test_synthetic_flat_market_pays_costs_without_created_gains():
    active, obs = fixture()
    f = screen.features(active, obs, config())
    p = screen.targets(active, f, config())["primary"]
    days = sorted(p.effective_date.unique())
    market = pd.DataFrame([{"session_date": d, "asset_code": a, "contract_id": a + suffix,
        "open": 100.0, "high": 100.0, "low": 100.0, "settle": 100.0, "volume": 1e7,
        "sizing_point_value": 100.0, "accounting_point_value": 100.0, "tick_size": 0.01,
        "fee_per_contract": 1.0, "initial_margin": 1000.0}
        for d in days for a in screen.ASSETS for suffix in ("A", "B")])
    values = []
    for ticks, fees in config()["execution"]["costs"].values():
        result = screen.base.run_futures_portfolio_ledger(market, p,
            screen.base.FuturesPortfolioLedgerConfig(expected_assets=screen.ASSETS,
                maximum_gross_notional_multiple=1.0, initial_margin_buffer_multiplier=2.0,
                maximum_participation=0.01, slippage_ticks=ticks, fee_multiplier=fees,
                execution_atomicity="asset", unexecutable_target_policy="cancel_and_clip"))
        m = screen.report.summarize(result)
        assert m["execution_complete"] and not m["terminal_carried"]
        assert m["gross_vm_pnl"] == pytest.approx(0.0)
        assert m["net_pnl"] == pytest.approx(-m["total_cost"])
        assert m["round_trips"] >= 2
        values.append(m)
    assert values[1]["net_pnl"] < values[0]["net_pnl"] < 0


def test_gate_cannot_promote_mirror_loss_bad_coverage_or_incomplete_execution():
    good = {"execution_complete": True, "critical_failure_count": 0,
        "unresolved_halt_count": 0, "terminal_carried": False, "round_trips": 60,
        "cagr": 0.1, "sharpe": 0.8, "maximum_drawdown": 0.1, "positive_years": 5,
        "worst_year": 0.01, "annual_returns": {str(y): 0.01 for y in range(2021, 2026)}}
    m = {arm: {cost: {**good, "cagr": 0.1 if arm == "primary" else 0.01}
        for cost in ("base", "double")} for arm in ("primary", "control")}
    q = {"ready_asset_date_fraction": 0.9}
    assert screen.report.assess(m, q, config())["verdict"] == "STAGE2_CANDIDATE"
    assert not screen.report.assess(m, q, config())["goal_verified"]
    assert screen.report.assess(m, {"ready_asset_date_fraction": 0.1}, config())[
        "verdict"] == "REJECT_STAGE1"
    bad = copy.deepcopy(m)
    bad["primary"]["double"]["cagr"] = -0.01
    assert screen.report.assess(bad, q, config())["verdict"] == "REJECT_STAGE1"
    bad["control"]["base"]["unresolved_halt_count"] = 1
    assert screen.report.assess(bad, q, config())["verdict"] == "INVALID_EXECUTION_NO_PROMOTION"
