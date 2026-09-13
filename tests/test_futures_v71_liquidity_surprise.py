"""Synthetic source alignment, causal-clock and promotion tests for V71."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v71_liquidity_surprise as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def sources():
    f = pd.DataFrame(
        {
            "publication_date": pd.to_datetime(["2021-01-12", "2021-01-19"]),
            "forecast_period_start": pd.to_datetime(["2021-01-13", "2021-01-20"]),
            "forecast_period_end": pd.to_datetime(["2021-01-19", "2021-01-26"]),
            screen.VALUE: [5.0, 5.0],
            "raw_sha256": ["f1", "f2"],
        }
    )
    f["available_at"] = f.publication_date.map(screen.moscow_eod)
    dates = pd.bdate_range("2021-01-11", "2021-02-02")
    a = pd.DataFrame(
        {
            "observation_date": dates,
            "publication_date": dates + pd.offsets.BDay(1),
            screen.VALUE: 2.0,
            "raw_sha256": "actual",
        }
    )
    a["available_at"] = (
        a.publication_date.dt.tz_localize("Europe/Moscow") + pd.Timedelta(hours=10, minutes=31)
    ).dt.tz_convert("UTC")
    return f, a


def mapping():
    days = pd.bdate_range("2021-01-11", "2021-02-05")
    return pd.DataFrame(
        {
            "decision_date": days[:-1],
            "effective_date": days[1:],
            "observed_through": days[:-1],
            "asset_code": "SI",
            "contract_id": "SI_SYNTH",
            "plan_tradable": True,
            "roll": False,
        }
    )


def targets(f, a, arm="primary"):
    return screen.shared.targets(mapping(), screen.states(f, a, config()), arm, config())


def test_matching_is_mean_cumulative_workdays_not_sum_or_weekend_mean():
    f, a = sources()
    a.loc[a.observation_date.eq("2021-01-12"), screen.VALUE] = 9999
    state = screen.states(f, a, config())
    assert state.ready.all()
    assert state.actual_rows.eq(5).all()
    assert state.actual_matching_value.eq(6.0).all()
    assert state.forecast_error.eq(1.0).all()
    assert state.primary_direction.eq(1).all()
    assert state.control_direction.eq(1).all()
    assert state.available_at_utc.iloc[0] == pd.Timestamp("2021-01-20T20:59:59Z")


def test_actual_positive_but_below_forecast_is_short_not_control():
    f, a = sources()
    f[screen.VALUE] = 7.0
    state = screen.states(f, a, config())
    assert state.primary_direction.eq(-1).all()
    assert state.control_direction.eq(1).all()
    f[screen.VALUE] = 6.0
    assert screen.states(f, a, config()).primary_direction.eq(0).all()


@pytest.mark.parametrize(
    "fault",
    ["missing_day", "missing_value", "extra_weekend", "irregular_period", "missing_forecast"],
)
def test_incomplete_period_is_masked_not_imputed(fault):
    f, a = sources()
    if fault == "missing_day":
        a = a.loc[~a.observation_date.eq("2021-01-15")]
    elif fault == "missing_value":
        a.loc[a.observation_date.eq("2021-01-15"), screen.VALUE] = np.nan
    elif fault == "extra_weekend":
        extra = a.iloc[[0]].copy()
        extra["observation_date"] = pd.Timestamp("2021-01-16")
        extra["publication_date"] = pd.Timestamp("2021-01-18")
        extra["available_at"] = pd.Timestamp("2021-01-18T07:31:00Z")
        a = pd.concat([a, extra], ignore_index=True)
    elif fault == "irregular_period":
        f.loc[0, "forecast_period_start"] += pd.Timedelta(days=1)
    else:
        f.loc[0, screen.VALUE] = np.nan
    state = screen.states(f, a, config())
    assert not state.ready.iloc[0] and state.ready.iloc[1]
    assert pd.isna(state.actual_matching_value.iloc[0])
    assert pd.isna(state.primary_direction.iloc[0])


def test_no_trade_before_whole_period_published_then_next_open():
    out = targets(*sources())
    assert out.loc[out.decision_date.lt("2021-01-20"), "target_weight"].eq(0).all()
    first = out.loc[out.target_weight.ne(0)].iloc[0]
    assert first.decision_date == pd.Timestamp("2021-01-20")
    assert first.effective_date == pd.Timestamp("2021-01-21")
    assert first.actual_last_available_at_utc <= first.decision_at_utc
    assert first.source_date < first.decision_date < first.effective_date
    assert out.iloc[-1].target_weight == 0 and out.iloc[-1].terminal_flat


def test_future_actual_mutation_cannot_change_past_signal():
    f, a = sources()
    changed = a.copy()
    changed.loc[changed.observation_date.ge("2021-01-20"), screen.VALUE] = -100.0
    left, right = targets(f, a), targets(f, changed)
    pd.testing.assert_frame_equal(
        left.loc[left.decision_date.lt("2021-01-27")],
        right.loc[right.decision_date.lt("2021-01-27")],
    )


def test_invalid_new_period_supersedes_old_without_fallback():
    f, a = sources()
    a.loc[a.observation_date.eq("2021-01-22"), screen.VALUE] = np.nan
    out = targets(f, a)
    masked = out.loc[out.decision_date.ge("2021-01-27")]
    assert masked.source_date.eq(pd.Timestamp("2021-01-26")).all()
    assert masked.feature_unavailable.all() and masked.target_weight.eq(0).all()


def test_unpublished_final_actual_delays_entry():
    f, a = sources()
    a.loc[a.observation_date.eq("2021-01-19"), "available_at"] = pd.Timestamp(
        "2021-01-22T10:00:00Z"
    )
    out = targets(f, a)
    assert out.loc[out.decision_date.lt("2021-01-22"), "target_weight"].eq(0).all()
    assert out.loc[out.target_weight.ne(0)].iloc[0].effective_date == pd.Timestamp("2021-01-25")


def test_missing_next_release_expires_at_fixed_ttl():
    f, a = sources()
    out = targets(f.iloc[:1], a)
    assert out.loc[out.effective_date.gt("2021-01-29"), "target_weight"].eq(0).all()
    assert out.loc[out.effective_date.eq("2021-01-29"), "target_weight"].eq(1).all()


def test_future_forecast_period_is_not_a_2026_actual_request():
    f, a = sources()
    f = f.iloc[:1].copy()
    f["publication_date"] = pd.Timestamp("2025-12-30")
    f["available_at"] = screen.moscow_eod("2025-12-30")
    f["forecast_period_start"] = pd.Timestamp("2025-12-31")
    f["forecast_period_end"] = pd.Timestamp("2026-01-06")
    out = screen.states(f, a, config())
    assert not out.ready.any() and not out.in_window.any()
    assert out.actual_rows.eq(0).all()
    assert out.reason.eq("period_outside_window").all()


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_actual",
        "duplicate_forecast",
        "protected_actual",
        "premature_actual",
        "premature_forecast",
        "infinite_actual",
    ],
)
def test_invalid_source_fails_closed(fault):
    f, a = sources()
    if fault == "duplicate_actual":
        a = pd.concat([a, a.iloc[:1]])
    elif fault == "duplicate_forecast":
        f = pd.concat([f, f.iloc[:1]])
    elif fault == "protected_actual":
        a.loc[0, "observation_date"] = pd.Timestamp("2026-01-01")
    elif fault == "premature_actual":
        a.loc[0, "available_at"] = pd.Timestamp("2021-01-12T07:00:00Z")
    elif fault == "premature_forecast":
        f.loc[0, "available_at"] = pd.Timestamp("2021-01-12T08:00:00Z")
    else:
        a.loc[0, screen.VALUE] = np.inf
    with pytest.raises(ValueError):
        screen.states(f, a, config())


def test_assessment_requires_meaningful_excess_and_never_confirms_goal():
    cfg = config()
    value = {
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
        "terminal_carried": False,
        "round_trips": 100,
        "cagr": 0.1,
        "sharpe": 1.0,
        "maximum_drawdown": 0.1,
        "positive_years": 5,
        "annual_returns": {str(year): 0.1 for year in range(2021, 2026)},
        "worst_year": 0.1,
    }
    metrics = {
        arm: {cost: copy.deepcopy(value) for cost in cfg["execution"]["costs"]}
        for arm in screen.ARMS
    }
    for control in metrics["control"].values():
        control["cagr"] = 0.09
    quality = {"ready_asset_date_fraction": 0.9}
    assert screen.assess(metrics, quality, cfg)["verdict"] == "REJECT_STAGE1"
    for control in metrics["control"].values():
        control["cagr"] = 0.07
    result = screen.assess(metrics, quality, cfg)
    assert result["verdict"] == "STAGE2_CANDIDATE" and not result["goal_verified"]
    metrics["primary"]["double"]["execution_complete"] = False
    assert screen.assess(metrics, quality, cfg)["verdict"] == "INVALID_EXECUTION_NO_PROMOTION"
