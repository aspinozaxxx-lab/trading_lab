"""Synthetic same-contract, notional units, lag, missingness and real-ledger tests."""

import numpy as np
import pandas as pd
import pytest
from test_futures_v94_skewness_premium import fixture as price_fixture

from market_lab import futures_v103_illiquidity_premium as screen


def config():
    return screen.prior.read_json(screen.CONFIG)


def fixture():
    active, obs = price_fixture()
    specs = obs.rename(
        columns={
            "trade_date": "session_date",
            "logical_asset": "asset_symbol",
            "canonical_contract_id": "contract_id",
        }
    ).copy()
    specs["sizing_point_value"] = 100.0
    specs["sizing_observed_session_date"] = specs.groupby(
        ["asset_symbol", "contract_id"]
    ).session_date.shift(1)
    specs["sizing_lag_sessions"] = 1
    specs["sizing_usable"] = specs.sizing_observed_session_date.notna()
    return active, obs, specs


def calculated():
    active, obs, specs = fixture()
    return active, screen.features(active, obs, specs, config())


def ranked():
    active, feature = calculated()
    feature["illiquidity"] = feature.asset_code.map({"BR": 4.0, "MIX": 3.0, "RI": 2.0, "SI": 1.0})
    return active, feature


def test_ratio_units_complete_window_and_same_contract_roll():
    _, f = calculated()
    p = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
    assert abs(p.loc[190, "same_contract_return"]) < 0.05 and p.loc[190, "roll"]
    assert p.illiquidity.iloc[:63].isna().all()
    expected = (
        1e6
        * p.loc[1:63, "same_contract_return"].abs()
        / (p.loc[1:63, "current_close"] * p.loc[1:63, "current_volume"] * 100.0)
    )
    assert p.loc[63, "illiquidity"] == pytest.approx(expected.mean())
    assert p.loc[63, "illiquidity_window_count"] == 63


def test_quote_unit_conversion_does_not_change_notional_ranking():
    active, obs, specs = fixture()
    a = screen.features(active, obs, specs, config())
    changed = obs.copy()
    s = specs.copy()
    changed.loc[changed.logical_asset.eq("BR"), "close"] *= 100.0
    s.loc[s.asset_symbol.eq("BR"), "sizing_point_value"] /= 100.0
    b = screen.features(active, changed, s, config())
    np.testing.assert_allclose(a.illiquidity, b.illiquidity, rtol=1e-10, equal_nan=True)


def test_zero_returns_are_real_zero_but_missing_volume_poison_full_windows():
    active, obs, specs = fixture()
    zero = screen.features(active, obs.assign(close=100.0), specs, config())
    assert zero.illiquidity.dropna().eq(0).all()
    assert screen.targets(active, zero, config())["primary"].target_weight.eq(0).all()
    mask = obs.trade_date.eq("2020-08-03") & obs.logical_asset.eq("BR")
    for changed in (obs.loc[~mask], obs.assign(volume=obs.volume.mask(mask, 0.0))):
        f = screen.features(active, changed, specs, config())
        p = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
        index = p.index[p.effective_date.eq("2020-08-03")][0]
        assert p.illiquidity.iloc[index : index + 64].isna().all()
        assert np.isfinite(p.illiquidity.iloc[index + 64])


@pytest.mark.parametrize(
    "column,value",
    [
        ("sizing_point_value", 0.0),
        ("sizing_usable", False),
        ("sizing_lag_sessions", 0),
        ("sizing_observed_session_date", pd.Timestamp("2020-08-03")),
    ],
)
def test_unknown_or_noncausal_size_mask_not_replaced_by_accounting_value(column, value):
    active, obs, specs = fixture()
    mask = specs.session_date.eq("2020-08-03") & specs.asset_symbol.eq("BR")
    specs.loc[mask, column] = value
    specs["realized_accounting_point_value"] = 1e20
    f = screen.features(active, obs, specs, config())
    p = f.loc[f.asset_code.eq("BR") & f.effective_date.eq("2020-08-03")].iloc[0]
    assert not p.illiquidity_observed and np.isnan(p.daily_illiquidity)


def test_monthly_high_minus_low_strictly_prior_session_and_mirror():
    active, feature = ranked()
    p, c = screen.targets(active, feature, config()).values()
    used = p.loc[p.target_weight.ne(0)]
    assert used.loc[used.asset_code.eq("BR"), "target_weight"].eq(0.45).all()
    assert used.loc[used.asset_code.eq("SI"), "target_weight"].eq(-0.45).all()
    assert set(used.asset_code) == {"BR", "SI"}
    assert used.source_date.lt(used.selection_date).all()
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert p.decision_date.lt(p.effective_date).all()
    np.testing.assert_array_equal(p.target_weight, -c.target_weight)
    assert p.groupby("effective_date").target_weight.sum().eq(0).all()
    assert p.groupby("effective_date").target_weight.apply(lambda s: s.abs().sum()).max() == 0.9
    assert p.loc[p.terminal_flat, "target_weight"].eq(0).all()


def test_current_decision_day_and_future_market_values_cannot_change_its_target():
    active, obs, specs = fixture()
    before = screen.features(active, obs, specs, config())
    changed = obs.copy()
    cutoff = pd.Timestamp("2021-02-01")
    future = changed.trade_date.ge(cutoff)
    changed.loc[future, "close"] *= np.arange(future.sum()) + 1
    changed.loc[future, "volume"] /= 1000.0
    after = screen.features(active, changed, specs, config())
    a, b = [screen.targets(active, f, config())["primary"] for f in (before, after)]
    pd.testing.assert_frame_equal(
        a.loc[a.decision_date.le(cutoff)], b.loc[b.decision_date.le(cutoff)]
    )


def test_missing_or_tied_monthly_snapshot_sleeps_no_midmonth_revival():
    active, f = ranked()
    f.loc[f.effective_date.eq("2021-01-29") & f.asset_code.eq("BR"), "illiquidity"] = np.nan
    p = screen.targets(active, f, config())["primary"]
    feb = p.loc[p.decision_date.between("2021-02-01", "2021-02-26")]
    assert feb.feature_unavailable.all() and feb.target_weight.eq(0).all()
    assert p.loc[p.decision_date.eq("2021-03-01"), "target_weight"].ne(0).any()
    f["illiquidity"] = f.asset_code.map({"BR": 4.0, "MIX": 4.0, "RI": 2.0, "SI": 1.0})
    assert screen.targets(active, f, config())["primary"].target_weight.eq(0).all()


def test_bad_spec_identity_protected_boundary_and_missing_plan():
    active, obs, specs = fixture()
    with pytest.raises(ValueError, match="duplicate feature specs"):
        screen.features(active, obs, pd.concat([specs, specs.iloc[:1]]), config())
    specs.loc[0, "session_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.features(active, obs, specs, config())
    active, f = ranked()
    active.loc[active.asset_code.eq("BR"), "plan_tradable"] = False
    p = screen.targets(active, f, config())["primary"]
    br = p.loc[p.asset_code.eq("BR")]
    assert br.requested_weight.gt(0).any() and br.target_weight.eq(0).all()


def test_long_calendar_gap_masks_complete_window_and_cancels_stale_fill():
    active, obs, specs = fixture()
    cutoff = pd.Timestamp("2020-08-03")
    for frame, columns in (
        (active, ["decision_date", "effective_date", "observed_through"]),
        (obs, ["trade_date"]),
        (specs, ["session_date", "sizing_observed_session_date"]),
    ):
        for column in columns:
            frame.loc[frame[column].ge(cutoff), column] += pd.Timedelta(days=10)
    f = screen.features(active, obs, specs, config())
    p = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
    index = p.index[p.effective_date.eq("2020-08-13")][0]
    assert not p.loc[index, "illiquidity_observed"]
    assert p.illiquidity.iloc[index : index + 63].isna().all()
    assert np.isfinite(p.illiquidity.iloc[index + 63])
    f["illiquidity"] = f.asset_code.map({"BR": 4.0, "MIX": 3.0, "RI": 2.0, "SI": 1.0})
    cfg = config()
    cfg["period"]["start"] = "2020-07-01"
    signals = screen.targets(active, f, cfg)["primary"]
    gap = signals.loc[signals.effective_date.eq("2020-08-13")]
    assert gap.stale_at_fill.all() and gap.target_weight.eq(0).all()
    assert gap.requested_weight.ne(0).any() and not gap.source_unavailable.any()
    august = signals.loc[signals.decision_date.between("2020-08-13", "2020-08-31")]
    assert august.feature_unavailable.all() and august.target_weight.eq(0).all()


def test_flat_real_ledger_no_gains_and_tamper_detected(tmp_path):
    active, f = ranked()
    cfg = config()
    signals = screen.targets(active, f, cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": d,
                "asset_code": a,
                "contract_id": a + s,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "settle": 100.0,
                "volume": 1e7,
                "sizing_point_value": 100.0,
                "accounting_point_value": 100.0,
                "tick_size": 0.01,
                "fee_per_contract": 1.0,
                "initial_margin": 1000.0,
            }
            for d in signals["primary"].effective_date.unique()
            for a in screen.ASSETS
            for s in ("A", "B")
        ]
    )
    folder = tmp_path / "case"
    case = screen.engine.simulate_case(
        folder, signals, market, {"ready_asset_date_fraction": 1.0}, cfg, "synthetic"
    )
    screen.prior.audit_case(folder, case, signals)
    for arm in case["metrics"].values():
        for metric in arm.values():
            assert metric["execution_complete"] and not metric["terminal_carried"]
            assert metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert arm["double"]["net_pnl"] < arm["base"]["net_pnl"] < 0
    ledger = pd.read_parquet(folder / "ledger_primary_base.parquet")
    ledger.loc[1, "starting_cash"] += 100
    ledger.to_parquet(folder / "ledger_primary_base.parquet", index=False)
    with pytest.raises(ValueError, match="cash continuity"):
        screen.prior.audit_case(folder, case, signals)
