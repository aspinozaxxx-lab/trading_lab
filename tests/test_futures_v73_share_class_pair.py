"""Synthetic same-contract history, future-independent selection and paired costs."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v73_share_class_pair as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def fixture():
    days = pd.bdate_range("2023-01-02", "2023-03-10")
    spec = pd.DataFrame(
        [
            {
                "stock_secid": stock,
                "contract_id": stock,
                "expiration": pd.Timestamp("2023-06-16"),
                "first_trade": pd.Timestamp("2022-01-01"),
            }
            for stock in ("SBER", "SBERP")
        ]
    )
    rows = []
    for i, day in enumerate(days):
        for stock in ("SBER", "SBERP"):
            for clock in ("15:40", "15:50"):
                stamp = pd.Timestamp(f"{day.date()} {clock}", tz="Europe/Moscow").tz_convert("UTC")
                close = 100.0 if stock == "SBERP" else (100.0 + (-1 if i % 2 else 1))
                if day == pd.Timestamp("2023-02-13") and stock == "SBER":
                    close = 120.0
                rows.append(
                    {
                        "timestamp": stamp,
                        "end_timestamp": stamp + pd.Timedelta(minutes=10) - pd.Timedelta(seconds=1),
                        "available_at": stamp + pd.Timedelta(minutes=10) - pd.Timedelta(seconds=1),
                        "contract_id": stock,
                        "stock_secid": stock,
                        "close": close,
                        "open": 100.0,
                        "volume": 1000.0,
                    }
                )
    return spec, pd.DataFrame(rows), days


def selected():
    spec, raw, days = fixture()
    decisions = screen.candidates(spec, raw.drop(columns="open"), days, config())
    return decisions, raw, days


def test_exact_past_twenty_and_fixed_weekly_pair_direction():
    decisions, _, _ = selected()
    chosen = decisions.loc[decisions.selected]
    assert len(chosen) == 1
    assert chosen.iloc[0].decision_date == pd.Timestamp("2023-02-13")
    assert chosen.iloc[0].common_direction == -1 and chosen.iloc[0].history_rows == 20
    assert (decisions.decision_date.dt.dayofweek == 0).all()
    assert decisions.iloc[0].reason == "insufficient_history"


def test_future_closes_and_all_future_opens_cannot_select_past_events():
    spec, raw, days = fixture()
    a = screen.candidates(spec, raw.drop(columns="open"), days, config())
    changed = raw.copy()
    changed["open"] = -99.0
    changed.loc[changed.timestamp.ge("2023-02-15T00:00:00Z"), "close"] *= 10
    b = screen.candidates(spec, changed.drop(columns="open"), days, config())
    pd.testing.assert_frame_equal(
        a.loc[a.decision_date.lt("2023-02-15")], b.loc[b.decision_date.lt("2023-02-15")]
    )


def test_future_endpoints_do_not_remove_selected_event_and_no_gap_bridge():
    decisions, raw, days = selected()
    selected_before = decisions.copy(deep=True)
    first = screen.outcomes(decisions, raw, days, config())
    assert first.complete.all()
    changed = raw.copy()
    mask = changed.timestamp.eq(
        pd.Timestamp("2023-02-16 15:50", tz="Europe/Moscow").tz_convert("UTC")
    ) & changed.stock_secid.eq("SBERP")
    changed.loc[mask, "open"] = np.nan
    after = screen.outcomes(decisions, changed, days, config())
    assert len(after) == len(first) and not after.complete.any()
    assert "intermediate" in after.iloc[0].reason
    pd.testing.assert_frame_equal(decisions, selected_before)
    result = screen.summarize(decisions, after, config())
    assert result["unresolved_events"] == 1 and result["verdict"] == "INCOMPLETE_NO_PROMOTION"


def test_entry_next_session_exact_fifth_successor_cost_on_all_four_notionals():
    decisions, raw, days = selected()
    changed = raw.copy()
    for day, price in [("2023-02-14", 120.0), ("2023-02-21", 110.0)]:
        stamp = pd.Timestamp(day + " 15:50", tz="Europe/Moscow").tz_convert("UTC")
        changed.loc[changed.timestamp.eq(stamp) & changed.stock_secid.eq("SBER"), "open"] = price
    row = screen.outcomes(decisions, changed, days, config()).iloc[0]
    assert row.entry_date == pd.Timestamp("2023-02-14") and row.exit_date == pd.Timestamp(
        "2023-02-21"
    )
    assert row.primary_gross == pytest.approx(10 / 220)
    assert row.base_cost_fraction == pytest.approx(0.0005 * 430 / 220)
    assert row.double_cost_fraction == pytest.approx(2 * row.base_cost_fraction)
    assert row.primary_double_net < row.primary_base_net < row.primary_gross
    assert row.one_contract_within_one_percent


def test_low_factual_capacity_is_reported_not_hidden_or_declared_execution():
    decisions, raw, days = selected()
    raw["volume"] = 10.0
    event = screen.outcomes(decisions, raw, days, config()).iloc[0]
    assert event.complete and not event.one_contract_within_one_percent
    assert event.one_contract_maximum_participation == 0.1


@pytest.mark.parametrize("fault", ["missing", "late", "zero_scale", "too_old"])
def test_unknown_current_history_and_zero_scale_sleep(fault):
    spec, raw, days = fixture()
    if fault == "missing":
        stamp = pd.Timestamp("2023-02-13 15:40", tz="Europe/Moscow").tz_convert("UTC")
        raw = raw.loc[~(raw.timestamp.eq(stamp) & raw.stock_secid.eq("SBERP"))]
    elif fault == "late":
        raw.loc[
            raw.timestamp.dt.tz_convert("Europe/Moscow").dt.date
            == pd.Timestamp("2023-02-13").date(),
            "available_at",
        ] += pd.Timedelta(minutes=10)
    elif fault == "zero_scale":
        raw["close"] = 100.0
    else:
        raw = raw.loc[
            raw.timestamp.lt("2023-01-05T00:00:00Z") | raw.timestamp.ge("2023-02-10T00:00:00Z")
        ]
    assert not screen.candidates(spec, raw.drop(columns="open"), days, config()).selected.any()


def test_no_fallback_to_longer_maturity_if_nearest_missing():
    spec, raw, days = fixture()
    far = spec.copy()
    far["expiration"] += pd.Timedelta(days=90)
    far["contract_id"] += "FAR"
    far_raw = raw.copy()
    far_raw["contract_id"] += "FAR"
    original = raw.loc[raw.timestamp.lt("2023-02-01T00:00:00Z")]
    decisions = screen.candidates(
        pd.concat([spec, far]), pd.concat([original, far_raw]).drop(columns="open"), days, config()
    )
    assert not decisions.selected.any()
    assert decisions.iloc[-1].reason == "missing_completed_pair"


@pytest.mark.parametrize("fault", ["protected", "duplicate", "early"])
def test_clock_or_identity_fail_closed(fault):
    _, raw, _ = fixture()
    if fault == "protected":
        raw.loc[0, "timestamp"] = pd.Timestamp("2026-01-01T00:00:00Z")
    elif fault == "duplicate":
        raw = pd.concat([raw, raw.iloc[:1]])
    else:
        raw["available_at"] = raw.timestamp
    with pytest.raises(ValueError):
        screen.normalize(raw)


def test_truncated_future_calendar_preserves_unresolved_denominator():
    decisions, raw, days = selected()
    events = screen.outcomes(decisions, raw, days[days <= "2023-02-17"], config())
    assert len(events) == 1 and not events.complete.any()


def test_event_gate_never_implies_portfolio_cagr_or_goal_and_requires_all_years():
    decisions, raw, days = selected()
    one = screen.outcomes(decisions, raw, days, config())
    records = []
    for year in (2023, 2024, 2025):
        for _ in range(10):
            row = one.iloc[0].to_dict()
            row["decision_date"] = pd.Timestamp(year=year, month=2, day=13)
            for cost in ("base", "double"):
                row["primary_" + cost + "_net"] = 0.01
                row["control_" + cost + "_net"] = -0.01
            records.append(row)
    events = pd.DataFrame(records)
    decisions = events[["decision_date"]].assign(selected=True, reason="selected")
    result = screen.summarize(decisions, events, config())
    assert result["verdict"] == "STAGE2_PORTFOLIO_CANDIDATE"
    assert not result["goal_verified"] and not result["portfolio_backtest"]
    assert result["metrics"]["primary"]["base"]["cagr"] is None
    bad = copy.deepcopy(events)
    bad.loc[0, "complete"] = False
    assert screen.summarize(decisions, bad, config())["verdict"] == "INCOMPLETE_NO_PROMOTION"
    events.loc[events.decision_date.dt.year.eq(2025), "primary_double_net"] = -0.01
    assert screen.summarize(decisions, events, config())["verdict"] == "REJECT_STAGE1"


def test_no_selected_events_are_a_recorded_result():
    decisions, raw, days = selected()
    decisions["selected"] = False
    events = screen.outcomes(decisions, raw, days, config())
    result = screen.summarize(decisions, events, config())
    assert result["selected_events"] == 0 and result["verdict"] == "REJECT_STAGE1"
    assert result["metrics"]["primary"]["double"]["mean_net"] is None
