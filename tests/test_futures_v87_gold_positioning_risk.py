"""Synthetic causality, exact signs, source masks and reused next-open mapping."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v87_gold_positioning_risk as screen


def cfg():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def raw(start="2024-01-02", n=20):
    return pd.DataFrame({
        "report_date": pd.date_range(start, periods=n, freq="7D"),
        "logical_market": "GOLD", "cftc_contract_market_code": "088691",
        "open_interest": 1000, "managed_money_long": np.arange(n) + 100,
        "managed_money_short": 80,
    })


@pytest.mark.parametrize("day,expected", [
    ("2024-01-02", "2024-01-10T04:59:59Z"),
    ("2024-07-02", "2024-07-10T03:59:59Z"),
    ("2018-12-24", "2019-02-02T04:59:59Z"),
    ("2018-12-31", "2019-02-06T04:59:59Z"),
    ("2023-01-31", "2023-02-25T04:59:59Z"),
    ("2023-02-07", "2023-03-04T04:59:59Z"),
    ("2025-09-30", "2025-11-20T04:59:59Z"),
    ("2025-11-10", "2025-12-11T04:59:59Z"),
    ("2025-12-16", "2025-12-24T04:59:59Z"),
    ("2019-03-26", "2019-04-04T03:59:59Z"),
])
def test_normal_holiday_shutdown_cyber_and_gold_correction_clocks(day, expected):
    assert screen.report_clock(pd.Timestamp(day), cfg()) == pd.Timestamp(expected)


def test_quarter_impulse_and_fixed_risk_off_basket():
    reports, state = screen.states(raw(), cfg())
    assert not reports.ready.iloc[:13].any()
    assert reports.ready.iloc[13:].all()
    assert np.allclose(reports.change_over13reports.iloc[13:], 0.013)
    assert state.loc[state.ready & state.asset_code.eq("SI"), "primary_direction"].eq(1).all()
    assert state.loc[state.ready & state.asset_code.eq("MIX"), "primary_direction"].eq(-1).all()


@pytest.mark.parametrize("mode,direction", [("rising", 1), ("falling", -1), ("flat", 0)])
def test_sign_is_exact_normalized_net_not_long_count(mode, direction):
    d = raw(n=14)
    d["managed_money_long"] = 100
    d["managed_money_short"] = 50
    d.loc[13, "open_interest"] = {"rising": 500, "falling": 2000, "flat": 1000}[mode]
    reports, _ = screen.states(d, cfg())
    assert reports.risk_off_direction.iloc[-1] == direction


def test_equal_rational_shares_are_exact_zero():
    d = raw(n=14)
    d["open_interest"] = 3000
    d["managed_money_long"] = 1000
    d["managed_money_short"] = 0
    d.loc[13, ["open_interest", "managed_money_long"]] = [6000, 2000]
    assert screen.states(d, cfg())[0].risk_off_direction.iloc[-1] == 0


@pytest.mark.parametrize("field,value", [
    ("open_interest", 0), ("open_interest", np.nan), ("open_interest", np.inf),
    ("managed_money_long", -1), ("managed_money_short", 1.5),
    ("managed_money_short", 1001), ("managed_money_long", np.nan),
])
def test_invalid_interior_report_masks_whole_window_no_skip(field, value):
    d = raw(n=30).astype({field: float})
    d.loc[8, field] = value
    reports, _ = screen.states(d, cfg())
    assert not reports.ready.iloc[13:22].any()
    assert reports.ready.iloc[22:].all()
    assert reports.change_over13reports.iloc[13:22].isna().all()


def test_missing_week_not_replaced_by_longer_lookback():
    d = raw(n=17).drop(index=10)
    reports, _ = screen.states(d, cfg())
    assert not reports.ready.any()


def test_future_positions_never_change_existing_states():
    d = raw(n=30)
    reports, state = screen.states(d.iloc[:20], cfg())
    d.loc[20:, "managed_money_long"] = 999
    extended, longer_state = screen.states(d, cfg())
    pd.testing.assert_frame_equal(reports, extended.iloc[:20].reset_index(drop=True))
    pd.testing.assert_frame_equal(state, longer_state.loc[
        longer_state.report_date.le(d.report_date.iloc[19])].reset_index(drop=True))


def test_all_window_availability_is_maximum_not_just_current(monkeypatch):
    original = screen.report_clock
    delayed_date = pd.Timestamp("2024-03-26")

    def delayed(day, config):
        if day == delayed_date:
            return pd.Timestamp("2024-05-20T03:59:59Z")
        return original(day, config)

    monkeypatch.setattr(screen, "report_clock", delayed)
    reports, _ = screen.states(raw(n=21), cfg())
    window = reports.loc[reports.source_date.between("2024-04-02", "2024-05-07")]
    assert window.available_at_utc.ge("2024-05-20T03:59:59Z").all()


@pytest.mark.parametrize("change", ["duplicate", "protected", "wrong_market", "wrong_code"])
def test_scope_is_fail_closed(change):
    d = raw()
    if change == "duplicate":
        d.loc[1, "report_date"] = d.loc[0, "report_date"]
    elif change == "protected":
        d.loc[19, "report_date"] = pd.Timestamp("2026-01-06")
    elif change == "wrong_market":
        d.loc[0, "logical_market"] = "WTI"
    else:
        d.loc[0, "cftc_contract_market_code"] = "067651"
    with pytest.raises(ValueError):
        screen.states(d, cfg())


def test_2025_report_published_2026_never_enters_state():
    reports, state = screen.states(raw(start="2025-09-30", n=14), cfg())
    assert reports.source_date.max() == pd.Timestamp("2025-12-30")
    assert state.available_at_utc.lt("2026-01-01T00:00:00Z").all()
    assert state.source_date.max() == pd.Timestamp("2025-12-23")


def test_next_factual_open_same_masks_and_no_trading_before_release():
    config = cfg()
    _, state = screen.states(raw(n=14), config)
    active = pd.DataFrame([
        {"asset_code": asset, "decision_date": decision, "effective_date": effective,
         "observed_through": decision, "contract_id": asset + "TEST", "plan_tradable": True,
         "roll": False}
        for asset in config["assets"]
        for decision, effective in [("2024-04-09", "2024-04-10"),
                                    ("2024-04-10", "2024-04-11"),
                                    ("2024-04-11", "2024-04-12"),
                                    ("2024-04-23", "2024-04-24"),
                                    ("2024-04-24", "2024-04-25")]
    ])
    primary = screen.adapter.targets(active, state, "primary", config)
    control = screen.adapter.targets(active, state, "control", config)
    assert primary.loc[primary.decision_date.eq("2024-04-09"), "target_weight"].eq(0).all()
    ready = primary.loc[primary.decision_date.eq("2024-04-10")]
    assert ready.set_index("asset_code").target_weight.to_dict() == {"MIX": -0.45, "SI": 0.45}
    assert primary.loc[primary.decision_date.eq("2024-04-23"), "stale_at_fill"].all()
    assert primary.loc[primary.terminal_flat, "target_weight"].eq(0).all()
    pd.testing.assert_series_equal(primary.feature_unavailable, control.feature_unavailable)
    pd.testing.assert_series_equal(primary.stale_at_fill, control.stale_at_fill)
    used = primary.loc[primary.target_weight.ne(0)]
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.decision_date.lt(used.effective_date).all()
