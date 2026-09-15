"""Fixed beta estimator, algebraic risk balance, causal timing and cost smoke tests."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v95_beta_premium as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


def fixture():
    dates = pd.bdate_range("2019-06-03", "2021-03-31")
    x = np.arange(len(dates))
    factor = 0.004 * np.sin(x)
    active, obs = [], []
    for asset, beta in zip(screen.ASSETS, (0.4, 0.8, 1.2, 1.6), strict=True):
        active.append(pd.DataFrame({"decision_date": pd.Series(dates).shift(1),
            "observed_through": pd.Series(dates).shift(1), "effective_date": dates,
            "asset_code": asset, "contract_id": np.where(x < 330, asset + "A", asset + "B"),
            "plan_tradable": True, "roll": x == 330}))
        for suffix, scale in (("A", 100), ("B", 10000)):
            obs.append(pd.DataFrame({"trade_date": dates, "logical_asset": asset,
                "canonical_contract_id": asset + suffix,
                "close": scale * np.cumprod(1.0 + beta * factor), "volume": 1e7}))
    return pd.concat(active, ignore_index=True), pd.concat(obs, ignore_index=True)


def test_exact_return_roll_does_not_create_beta_shock_and_known_loading_recovered():
    active, obs = fixture()
    returns, beta = screen.features(active, obs, config())
    assert beta.loc[:251, list(screen.ASSETS)].isna().all().all()
    for asset, expected in zip(screen.ASSETS, (0.4, 0.8, 1.2, 1.6), strict=True):
        np.testing.assert_allclose(beta.loc[252:, asset], expected, rtol=1e-9)
        assert returns.loc[returns.roll & returns.asset_code.eq(asset),
                           "same_contract_return"].abs().max() < 0.01
    assert beta.loc[252:, "complete_return_count"].eq(252).all()


def test_primary_estimated_beta_neutral_control_equal_notional_and_next_open():
    active, obs = fixture()
    _, beta = screen.features(active, obs, config())
    p, c = (screen.targets(active, beta, config())[a] for a in ("primary", "control"))
    used = p.loc[~p.terminal_flat]
    assert used.loc[used.asset_code.eq("BR"), "target_weight"].to_numpy() == pytest.approx(0.72)
    assert used.loc[used.asset_code.eq("SI"), "target_weight"].to_numpy() == pytest.approx(-0.18)
    exposure = (used.target_weight * used.selected_beta).groupby(used.effective_date).sum()
    np.testing.assert_allclose(exposure, 0, atol=1e-12)
    gross = used.groupby("effective_date").target_weight.apply(lambda w: w.abs().sum())
    np.testing.assert_allclose(gross, 0.9)
    assert c.loc[~c.terminal_flat & c.asset_code.eq("BR"), "target_weight"].eq(0.45).all()
    assert c.loc[~c.terminal_flat & c.asset_code.eq("SI"), "target_weight"].eq(-0.45).all()
    assert (p.selection_date <= p.decision_date).all()
    assert (p.decision_date < p.effective_date).all()
    assert p.loc[p.terminal_flat, "target_weight"].eq(0).all()


def test_future_mutation_cannot_change_past_beta_or_targets():
    active, obs = fixture()
    changed = obs.copy()
    cutoff = pd.Timestamp("2021-02-12")
    mask = changed.trade_date.gt(cutoff)
    changed.loc[mask, "close"] *= np.arange(mask.sum()) + 1
    a, b = [screen.features(active, frame, config())[1] for frame in (obs, changed)]
    pd.testing.assert_frame_equal(a.loc[a.effective_date.le(cutoff)],
                                  b.loc[b.effective_date.le(cutoff)])
    ta, tb = [screen.targets(active, f, config())["primary"] for f in (a, b)]
    pd.testing.assert_frame_equal(ta.loc[ta.decision_date.le(cutoff)],
                                  tb.loc[tb.decision_date.le(cutoff)])


def test_one_missing_asset_contaminates_whole_factor_window_without_compression():
    active, obs = fixture()
    mask = obs.trade_date.eq("2020-01-02") & obs.logical_asset.eq("BR")
    for variant in (obs.loc[~mask], obs.assign(volume=obs.volume.mask(mask, 0.0))):
        returns, beta = screen.features(active, variant, config())
        pos = beta.index[beta.effective_date.eq("2020-01-02")][0]
        assert beta.loc[pos:pos + 252, list(screen.ASSETS)].isna().all().all()
        assert np.isfinite(beta.loc[pos + 253, list(screen.ASSETS)].astype(float)).all()
        assert returns.loc[returns.effective_date.eq("2020-01-02")
                           & returns.asset_code.eq("BR"), "same_contract_return"].isna().all()


def test_bad_month_does_not_keep_old_weights_or_revive_before_next_month():
    active, obs = fixture()
    _, beta = screen.features(active, obs, config())
    beta.loc[beta.effective_date.eq("2021-02-01"), "RI"] = np.nan
    p = screen.targets(active, beta, config())["primary"]
    feb = p.loc[p.decision_date.between("2021-02-01", "2021-02-26")]
    assert feb.feature_unavailable.all() and feb.target_weight.eq(0).all()
    assert p.loc[p.decision_date.eq("2021-03-01"), "target_weight"].ne(0).any()


def test_positive_beta_eligibility_ties_and_near_zero_without_exploding_gross():
    cfg = config()
    for values, reason in (([-1, 0, -2, 4], "fewer_than_two_positive_betas"),
                           ([1, 1, 1, 1], "tied_extreme_betas"),
                           ([1, np.nan, 2, 3], "incomplete_beta_window")):
        p, c, actual = screen.allocation(pd.Series(values, index=screen.ASSETS), cfg)
        assert actual == reason and not any(p.values()) and not any(c.values())
    p, _, reason = screen.allocation(pd.Series([-1, 1e-100, 1, 4], index=screen.ASSETS), cfg)
    assert reason == "ready" and p["BR"] == 0
    assert np.isfinite(list(p.values())).all()
    assert sum(abs(x) for x in p.values()) == pytest.approx(0.9)
    active, obs = fixture()
    _, beta = screen.features(active, obs.assign(close=100.0), cfg)
    assert beta.loc[:, list(screen.ASSETS)].isna().all().all()


def test_protected_duplicates_noncausal_and_missing_map_fail_closed():
    active, obs = fixture()
    protected = obs.copy()
    protected.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.features(active, protected, config())
    with pytest.raises(ValueError, match="duplicate prices"):
        screen.features(active, pd.concat([obs, obs.iloc[:1]]), config())
    changed = active.copy()
    changed.loc[10, "observed_through"] = pd.Timestamp("2025-01-01")
    with pytest.raises(ValueError, match="noncausal"):
        screen.features(changed, obs, config())
    with pytest.raises(ValueError, match="four-asset"):
        screen.features(active.iloc[1:], obs, config())


def test_existing_case_runner_and_flat_market_create_only_cost_losses(tmp_path):
    cfg = config()
    active, obs = fixture()
    _, beta = screen.features(active, obs, cfg)
    signals = screen.targets(active, beta, cfg)
    dates = sorted(signals["primary"].effective_date.unique())
    market = pd.DataFrame([{"session_date": d, "asset_code": a, "contract_id": a + suffix,
        "open": 100.0, "high": 100.0, "low": 100.0, "settle": 100.0, "volume": 1e7,
        "sizing_point_value": 100.0, "accounting_point_value": 100.0, "tick_size": 0.01,
        "fee_per_contract": 1.0, "initial_margin": 1000.0}
        for d in dates for a in screen.ASSETS for suffix in ("A", "B")])
    case = screen.engine.simulate_case(tmp_path / "case", signals, market,
                                       {"ready_asset_date_fraction": 1.0}, cfg, "synthetic")
    for arm in ("primary", "control"):
        for result in case["metrics"][arm].values():
            assert result["execution_complete"] and not result["terminal_carried"]
            assert result["gross_vm_pnl"] == pytest.approx(0.0)
            assert result["net_pnl"] == pytest.approx(-result["total_cost"])
        assert case["metrics"][arm]["double"]["net_pnl"] < case["metrics"][arm]["base"]["net_pnl"]
    assert case["assessment"]["verdict"] == "REJECT_STAGE1"
    assert not case["assessment"]["goal_verified"]
    with pytest.raises(FileExistsError):
        screen.engine.simulate_case(tmp_path / "case", signals, market,
                                     {"ready_asset_date_fraction": 1.0}, cfg, "synthetic")


def test_positive_metrics_do_not_erase_execution_or_coverage_failure():
    good = {"execution_complete": True, "critical_failure_count": 0,
        "unresolved_halt_count": 0, "terminal_carried": False, "round_trips": 60,
        "cagr": 0.1, "sharpe": 0.8, "maximum_drawdown": 0.1, "positive_years": 5,
        "worst_year": 0.01, "annual_returns": {str(y): 0.01 for y in range(2021, 2026)}}
    metrics = {arm: {cost: {**good, "cagr": 0.1 if arm == "primary" else 0.01}
        for cost in ("base", "double")} for arm in ("primary", "control")}
    assess = screen.engine.adapter.assess
    assert assess(metrics, {"ready_asset_date_fraction": 0.9}, config())[
        "verdict"] == "STAGE2_CANDIDATE"
    assert assess(metrics, {"ready_asset_date_fraction": 0.7}, config())[
        "verdict"] == "REJECT_STAGE1"
    bad = copy.deepcopy(metrics)
    bad["control"]["double"]["unresolved_halt_count"] = 1
    assert assess(bad, {"ready_asset_date_fraction": 0.9}, config())[
        "verdict"] == "INVALID_EXECUTION_NO_PROMOTION"
