"""Synthetic vintage arithmetic, timing and eligibility; no market outcomes."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v80_gpr_risk as screen


def cfg():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def months(edition="202403", latest=3.0):
    start = pd.Timestamp(edition + "01")
    frame = pd.DataFrame({"month": pd.date_range(start - pd.DateOffset(months=13),
                                               start, freq="MS"), "GPRC_RUS": 2.0})
    frame.loc[len(frame) - 2, "GPRC_RUS"] = latest
    frame.loc[len(frame) - 1, "GPRC_RUS"] = 99.0  # Incomplete current month ignored.
    return frame


def feature(frame=None, edition="202403", clock="2024-03-01T12:00:00Z"):
    result = screen.vintage_feature(months(edition) if frame is None else frame,
                                    edition, clock, cfg())
    result.update(source_url="https://example.invalid/" + edition, raw_sha256="a" * 64)
    return result


def test_exact_prior12_mean_excludes_latest_and_partial_current():
    r = feature()
    assert r["ready"] and r["prior12_mean_percent"] == 2.0
    assert r["latest_complete_month_percent"] == 3.0 and r["risk_change_percent"] == 1.0
    assert r["source_date"] == pd.Timestamp("2024-02-29")


@pytest.mark.parametrize("value", [np.nan, -1, np.inf, 9000])
def test_partial_edition_scalar_does_not_enter_signal(value):
    frame = months()
    frame.loc[len(frame) - 1, "GPRC_RUS"] = value
    assert feature(frame) == feature()


@pytest.mark.parametrize("value", [np.nan, -1, np.inf, 100.01])
def test_invalid_window_masks_not_imputed(value):
    frame = months()
    frame.loc[4, "GPRC_RUS"] = value
    r = feature(frame)
    assert not r["ready"] and np.isnan(r["risk_change_percent"])
    state = screen.states(pd.DataFrame([r]), cfg())
    assert state.primary_direction.eq(0).all() and state.control_direction.eq(0).all()


def test_missing_calendar_month_not_replaced_by_older_month():
    frame = months().drop(index=4)
    r = feature(frame)
    assert not r["ready"] and np.isnan(r["risk_change_percent"])


def test_undated_values_retained_in_source_but_not_in_window():
    frame = pd.concat([months(), pd.DataFrame({"month": [pd.NaT], "GPRC_RUS": [99.0]})],
                      ignore_index=True)
    assert feature(frame) == feature()


@pytest.mark.parametrize("latest,direction", [(0, -1), (2, 0), (3, 1), (100, 1)])
def test_fixed_stress_signs_and_independent_constant_control(latest, direction):
    state = screen.states(pd.DataFrame([feature(months(latest=latest))]), cfg())
    assert state.ready.all()
    assert dict(zip(state.asset_code, state.primary_direction, strict=True)) == {
        "BR": direction, "MIX": -direction, "SI": direction,
    }
    assert dict(zip(state.asset_code, state.control_direction, strict=True)) == {
        "BR": 1, "MIX": -1, "SI": 1,
    }


@pytest.mark.parametrize("clock,expected", [
    ("2024-03-01T12:00:00Z", "2024-03-03T12:00:00Z"),
    ("2024-02-28T12:00:00Z", "2024-03-03T00:00:00Z"),
    ("2024-03-10T12:00:00Z", "2024-03-12T12:00:00Z"),
])
def test_commit_proxy_floor_and_two_calendar_day_delay(clock, expected):
    assert feature(clock=clock)["available_at_utc"] == pd.Timestamp(expected)


def test_naive_clock_rejected():
    with pytest.raises(ValueError, match="untimed"):
        feature(clock="2024-03-01")


def test_old_late_edition_cannot_replace_newer_known_one():
    old = feature(clock="2024-05-10T00:00:00Z")
    new = feature(edition="202404", clock="2024-04-01T00:00:00Z")
    state = screen.states(pd.DataFrame([old, new]), cfg())
    assert set(state.edition) == {"202404"}


def test_future_edition_values_do_not_change_past_states():
    raw = pd.DataFrame([feature(), feature(edition="202404", clock="2024-04-01T00:00:00Z")])
    state = screen.states(raw, cfg()).loc[lambda d: d.edition.eq("202403")].reset_index(drop=True)
    raw.loc[1, "risk_change_percent"] = -99
    changed = screen.states(raw, cfg()).loc[lambda d: d.edition.eq("202403")]
    pd.testing.assert_frame_equal(state, changed.reset_index(drop=True))


@pytest.mark.parametrize("change", ["protected", "future_month", "duplicate", "unordered"])
def test_invalid_dates_fail_before_features(change):
    frame = months()
    if change == "protected":
        frame.loc[len(frame) - 1, "month"] = pd.Timestamp("2026-01-01")
    elif change == "future_month":
        frame.loc[len(frame) - 1, "month"] = pd.Timestamp("2024-04-01")
    elif change == "duplicate":
        frame.loc[1, "month"] = frame.month.iloc[0]
    else:
        frame = frame.iloc[::-1]
    with pytest.raises(ValueError, match="GPR months"):
        feature(frame)


def active_map():
    rows = []
    for asset in cfg()["assets"]:
        for day in pd.bdate_range("2024-03-01", "2024-05-10"):
            row = {"asset_code": asset, "decision_date": day, "observed_through": day,
                   "effective_date": day + pd.offsets.BDay(), "plan_tradable": True,
                   "contract_id": asset + "M4", "roll": False}
            rows.append(row)
    return pd.DataFrame(rows)


def test_targets_wait_for_release_and_next_open_then_expire():
    state = screen.states(pd.DataFrame([feature()]), cfg())
    signal = screen.adapter.targets(active_map(), state, "primary", cfg())
    used = signal.loc[signal.target_weight.ne(0)]
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert used.effective_date.min() == pd.Timestamp("2024-03-05")
    assert signal.loc[signal.effective_date.gt("2024-05-01"), "target_weight"].eq(0).all()
    assert signal.groupby("asset_code").tail(1).terminal_flat.all()


def test_untradable_plan_masks_both_arms_without_using_future_labels():
    active = active_map()
    active["plan_tradable"] = False
    state = screen.states(pd.DataFrame([feature()]), cfg())
    signals, quality = screen.feasibility(state, cfg(), active)
    assert quality["source_unavailable"] == len(active)
    assert all(s.target_weight.eq(0).all() for s in signals.values())


def test2026_availability_creates_no_state():
    state = screen.states(pd.DataFrame([feature(clock="2025-12-31T00:00:00Z")]), cfg())
    assert state.empty
