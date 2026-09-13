"""Synthetic timing, missing-reporting, cost-ledger and rejection checks for V68."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v68_reported_option_flow as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def source():
    rows = []
    for day in pd.date_range("2021-01-08", periods=5, freq="W-FRI"):
        for asset in config()["assets"]:
            for side, volume, oi in [("call", 80.0, 30.0), ("put", 20.0, 70.0)]:
                rows.append(
                    {
                        "tradedate": day,
                        "logical_asset": asset,
                        "option_type": side,
                        "secid": asset + side,
                        "boardid": "TEST",
                        "volume": volume,
                        "openposition": oi,
                        "available_at_utc": (
                            day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
                        ).tz_convert("UTC"),
                    }
                )
    return pd.DataFrame(rows)


def mapping():
    dates = pd.bdate_range("2021-01-04", "2021-02-19")
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "decision_date": dates[:-1],
                    "effective_date": dates[1:],
                    "observed_through": dates[:-1],
                    "asset_code": asset,
                    "contract_id": "SYNTH-" + asset,
                    "plan_tradable": True,
                    "roll": False,
                }
            )
            for asset in config()["assets"]
        ],
        ignore_index=True,
    )


def test_reported_subsets_keep_unknown_cells_missing_and_direction_ablation():
    raw = source()
    unknown = raw.copy().assign(secid=raw.secid + "UNKNOWN", volume=np.nan, openposition=np.nan)
    state = screen.states(pd.concat([raw, unknown], ignore_index=True))
    assert state.ready.all()
    assert state.primary_direction.eq(1).all() and state.control_direction.eq(-1).all()
    assert state.call_volume_missing_rows.eq(1).all()
    assert state.call_volume_observed_rows.eq(1).all()
    assert state.call_volume.eq(80).all()
    changed = raw.copy()
    changed.loc[changed.option_type.eq("call"), "volume"] = 1.0
    other = screen.states(changed)
    assert other.primary_direction.eq(-1).all()
    pd.testing.assert_series_equal(state.control_direction, other.control_direction)


def test_missing_side_and_zero_total_are_not_imputed_or_traded():
    raw = source()
    raw.loc[raw.option_type.eq("put"), "volume"] = np.nan
    state = screen.states(raw)
    assert state.put_volume.isna().all() and not state.ready.any()
    assert state.primary_direction.isna().all()
    zero = source().assign(volume=0.0)
    assert not screen.states(zero).ready.any()
    for arm in screen.ARMS:
        targets = screen.targets(mapping(), state, arm, config())
        assert targets.target_weight.eq(0).all()


def test_strict_prior_source_next_open_staleness_and_terminal_flat():
    state = screen.states(source())
    result = screen.targets(mapping(), state, "primary", config())
    first = result.loc[result.target_weight.ne(0)].iloc[0]
    assert first.source_date == pd.Timestamp("2021-01-08")
    assert first.decision_date == pd.Timestamp("2021-01-11")
    assert first.effective_date == pd.Timestamp("2021-01-12")
    used = result.loc[result.target_weight.ne(0)]
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.source_date.lt(used.decision_date).all()
    assert result.groupby("effective_date").target_weight.sum().max() == 1.0
    assert result.groupby("asset_code").tail(1).target_weight.eq(0).all()
    stale = result.loc[result.effective_date.ge("2021-02-16")]
    assert stale.stale_at_fill.all() and stale.target_weight.eq(0).all()


def test_future_source_mutation_cannot_change_past_targets():
    raw = source()
    changed = raw.copy()
    cutoff = pd.Timestamp("2021-01-22")
    changed.loc[changed.tradedate.ge(cutoff) & changed.option_type.eq("call"), "volume"] = 1.0
    for arm in screen.ARMS:
        a = screen.targets(mapping(), screen.states(raw), arm, config())
        b = screen.targets(mapping(), screen.states(changed), arm, config())
        pd.testing.assert_frame_equal(
            a.loc[a.decision_date.le(cutoff)], b.loc[b.decision_date.le(cutoff)]
        )


def test_late_availability_is_not_backdated():
    raw = source()
    late = raw.tradedate.eq("2021-01-15")
    raw.loc[late, "available_at_utc"] += pd.Timedelta(days=5)
    raw.loc[late & raw.option_type.eq("call"), "volume"] = 1.0
    out = screen.targets(mapping(), screen.states(raw), "primary", config())
    before = out.loc[out.decision_date.eq("2021-01-18")]
    after = out.loc[out.decision_date.eq("2021-01-21")]
    assert before.source_date.eq(pd.Timestamp("2021-01-08")).all()
    assert after.source_date.eq(pd.Timestamp("2021-01-15")).all()
    assert after.target_weight.eq(-0.25).all()


def test_new_bad_release_masks_old_good_signal_without_fallback():
    raw = source()
    raw.loc[raw.tradedate.eq("2021-01-15"), "volume"] = np.nan
    out = screen.targets(mapping(), screen.states(raw), "primary", config())
    before = out.loc[out.decision_date.eq("2021-01-14")]
    after = out.loc[out.decision_date.eq("2021-01-18")]
    assert before.target_weight.eq(0.25).all()
    assert after.source_date.eq(pd.Timestamp("2021-01-15")).all()
    assert after.feature_unavailable.all() and after.target_weight.eq(0).all()


def test_invalid_source_duplicate_protected_negative_and_early_clock_fail_closed():
    raw = source()
    with pytest.raises(ValueError, match="duplicate"):
        screen.states(pd.concat([raw, raw.iloc[:1]]))
    protected = raw.copy()
    protected.loc[0, "tradedate"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.states(protected)
    negative = raw.copy()
    negative.loc[0, "volume"] = -1
    with pytest.raises(ValueError, match="invalid observed"):
        screen.states(negative)
    early = raw.copy()
    early["available_at_utc"] -= pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="premature"):
        screen.states(early)


def test_future_map_missing_contract_and_stale_fill():
    state = screen.states(source())
    bad = mapping()
    bad.loc[0, "observed_through"] = bad.loc[0, "effective_date"]
    with pytest.raises(ValueError, match="future map"):
        screen.targets(bad, state, "primary", config())
    unavailable = mapping()
    unavailable.loc[unavailable.decision_date.eq("2021-01-14"), "contract_id"] = None
    out = screen.targets(unavailable, state, "primary", config())
    row = out.loc[out.decision_date.eq("2021-01-14")]
    assert row.source_unavailable.all() and row.target_weight.eq(0).all()
    shifted = mapping()
    shifted["effective_date"] += pd.Timedelta(days=10)
    out = screen.targets(shifted, state, "primary", config())
    assert out.stale_at_fill.all() and out.target_weight.eq(0).all()


def test_nullable_position_ids_count_per_asset_sign_and_contract():
    p = pd.DataFrame(
        {
            "session_date": pd.bdate_range("2021-01-04", periods=5),
            "asset_code": "BR",
            "contract_id": pd.array([None, "A", "A", "B", None], dtype="string"),
            "contracts": [0, 1, -1, -1, 0],
        }
    )
    assert screen.position_counts(p) == {
        "position_entries": 3,
        "round_trips": 3,
        "exposed_asset_sessions": 3,
    }


def test_assessment_cannot_promote_failed_primary_or_incomplete_execution():
    good = {
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
        "terminal_carried": False,
        "round_trips": 60,
        "cagr": 0.1,
        "sharpe": 0.8,
        "maximum_drawdown": 0.1,
        "positive_years": 5,
        "worst_year": 0.01,
        "annual_returns": {str(y): 0.01 for y in range(2021, 2026)},
    }
    m = {
        arm: {
            cost: {**good, "cagr": 0.1 if arm == "primary" else 0.04} for cost in ["base", "double"]
        }
        for arm in screen.ARMS
    }
    q = {"ready_asset_date_fraction": 0.9}
    assert screen.assess(m, q, config())["verdict"] == "STAGE2_CANDIDATE"
    assert not screen.assess(m, q, config())["goal_verified"]
    bad = copy.deepcopy(m)
    bad["primary"]["double"]["cagr"] = -0.01
    assert screen.assess(bad, q, config())["verdict"] == "REJECT_STAGE1"
    bad["control"]["base"]["execution_complete"] = False
    assert screen.assess(bad, q, config())["verdict"] == "INVALID_EXECUTION_NO_PROMOTION"


def test_synthetic_shared_ledger_costs_and_factual_next_open():
    dates = pd.bdate_range("2021-01-04", "2021-02-19")
    market = pd.concat(
        [
            pd.DataFrame(
                {
                    "session_date": dates,
                    "asset_code": asset,
                    "contract_id": "SYNTH-" + asset,
                    "open": 100 + np.arange(len(dates)) * 0.1,
                    "high": 102 + np.arange(len(dates)) * 0.1,
                    "low": 98 + np.arange(len(dates)) * 0.1,
                    "settle": 100.1 + np.arange(len(dates)) * 0.1,
                    "volume": 1e7,
                    "sizing_point_value": 100.0,
                    "accounting_point_value": 100.0,
                    "tick_size": 0.01,
                    "fee_per_contract": 1.0,
                    "initial_margin": 1000.0,
                }
            )
            for asset in config()["assets"]
        ],
        ignore_index=True,
    )
    signal = screen.targets(mapping(), screen.states(source()), "primary", config())
    values = []
    for ticks, fee in [(1, 1.0), (2, 2.0)]:
        result = screen.base.run_futures_portfolio_ledger(
            market,
            signal,
            screen.base.FuturesPortfolioLedgerConfig(
                initial_cash=screen.base.CAPITAL,
                expected_assets=tuple(config()["assets"]),
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=0.01,
                slippage_ticks=ticks,
                fee_multiplier=fee,
                execution_atomicity="asset",
                unexecutable_target_policy="cancel_and_clip",
            ),
        )
        metrics = screen.summarize(result)
        assert metrics["execution_complete"] and not metrics["terminal_carried"]
        assert metrics["round_trips"] == 4
        assert metrics["total_cost"] > 0
        values.append(metrics)
    assert values[1]["total_cost"] > values[0]["total_cost"]
    assert values[1]["net_pnl"] < values[0]["net_pnl"]
