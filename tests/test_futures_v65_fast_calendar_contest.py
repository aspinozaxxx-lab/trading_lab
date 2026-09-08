"""Small synthetic checks for the fast hypothesis contest."""

import json
from copy import deepcopy

import pandas as pd
import pytest

from market_lab import futures_v65_fast_calendar_contest as screen


def mapping(asset="SI", start="2021-01-04", periods=45):
    dates = pd.bdate_range(start, periods=periods + 1)
    return pd.DataFrame(
        {
            "decision_date": dates[:-1],
            "effective_date": dates[1:],
            "observed_through": dates[:-1],
            "asset_code": asset,
            "contract_id": "SYNTH",
            "plan_tradable": True,
            "roll": False,
        }
    )


@pytest.mark.parametrize(
    "name,asset",
    [
        ("ri_month_turn", "RI"),
        ("br_midweek_report", "BR"),
        ("br_after_roll", "BR"),
        ("si_weekend_hedge", "SI"),
    ],
)
def test_rules_are_price_free_and_strictly_next_open(name, asset):
    raw = mapping(asset)
    raw.loc[3, "roll"] = True
    hypothesis = {"id": name, "asset": asset}
    for arm in screen.ARMS:
        expected = screen.targets(raw, hypothesis, arm)
        poisoned = raw.assign(future_return=999.0, open=-999.0)
        pd.testing.assert_frame_equal(expected, screen.targets(poisoned, hypothesis, arm))
        assert (expected.decision_date < expected.effective_date).all()
        assert expected.iloc[-1].target_weight == 0
        assert expected.iloc[-1].terminal_flat


def test_roll_counter_is_prefix_causal_and_does_not_invent_first_roll():
    raw = mapping("BR")
    hypothesis = {"id": "br_after_roll", "asset": "BR"}
    assert not screen.targets(raw, hypothesis, "primary").target_weight.any()
    raw.loc[3, "roll"] = True
    expected = screen.targets(raw, hypothesis, "primary")
    assert expected.index[expected.target_weight.ne(0)].tolist() == [4, 5, 6, 7, 8]
    raw.loc[25, "roll"] = True
    pd.testing.assert_frame_equal(
        expected.iloc[:25], screen.targets(raw, hypothesis, "primary").iloc[:25]
    )


def test_weekend_uses_friday_open_and_cancels_delayed_entry():
    raw = mapping()
    hypothesis = {"id": "si_weekend_hedge", "asset": "SI"}
    result = screen.targets(raw, hypothesis, "primary")
    assert result.loc[result.target_weight.ne(0)].effective_date.dt.dayofweek.eq(4).all()
    raw.loc[3, "effective_date"] = pd.Timestamp("2021-01-09")
    result = screen.targets(raw, hypothesis, "primary")
    assert result.loc[3, "stale_at_fill"] and result.loc[3, "target_weight"] == 0


def test_protected_or_future_map_fails():
    raw = mapping(start="2025-12-29")
    hypothesis = {"id": "si_weekend_hedge", "asset": "SI"}
    with pytest.raises(ValueError, match="protected"):
        screen.targets(raw, hypothesis, "primary")
    raw = mapping()
    raw.loc[0, "observed_through"] = raw.loc[0, "effective_date"]
    with pytest.raises(ValueError, match="future map"):
        screen.targets(raw, hypothesis, "primary")


def test_stage1_lead_is_not_goal_success_and_bad_era_rejects():
    gates = json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))["screen_gates"]
    good = {
        "execution_complete": True,
        "terminal_carried": False,
        "round_trips": 20,
        "total_return": 0.5,
        "positive_years": 4,
        "year_segments": 5,
        "cagr": 0.10,
        "maximum_drawdown": 0.10,
        "sharpe": 0.9,
    }
    eras = {
        era: {
            "primary": {"primary": deepcopy(good), "doubled": deepcopy(good)},
            "control": {"primary": {**good, "cagr": 0.02}, "doubled": {**good, "cagr": 0.02}},
        }
        for era in ("early", "middle", "recent")
    }
    result = screen.assess(eras, gates)
    assert result["verdict"] == "STAGE2_CANDIDATE" and not result["goal_verified"]
    assert not result["historical_20_each_era"]
    eras["early"]["primary"]["doubled"]["total_return"] = -0.1
    assert screen.assess(eras, gates)["verdict"] == "REJECT_STAGE1"
