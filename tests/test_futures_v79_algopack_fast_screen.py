import json
import math

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v79_algopack_fast_screen as mod


def config():
    return json.loads((mod.REPO / mod.CONFIG).read_bytes())


def frames():
    index = pd.date_range("2024-10-15 08:00", periods=12, freq="10min", tz="UTC")
    calendar, features = pd.DataFrame(index=index), pd.DataFrame(index=index)
    calendar["local_date"] = "2024-10-15"
    for asset in mod.ASSETS:
        calendar[f"{asset}_plan_eligible"] = True
        calendar[f"{asset}_contract_id"] = "SYNTH"
        for field, value in zip(mod.FIELDS, (.001, .4, .5, .3, .3, math.asinh(2)), strict=True):
            features[f"{asset}_{field}"] = value
        features[f"{asset}_price_status"] = "READY"
        features[f"{asset}_flow_status"] = "READY"
    return calendar, features


def test_pressure_and_common_eligibility():
    calendar, features = frames()
    signals = mod.make_signals(calendar, features, config())
    selected = signals.query("arm == 'pressure' and asset == 'BR'")
    assert selected["direction"].tolist() == [0] + [1] * 11
    assert signals.query("arm == 'absorption'")["direction"].eq(0).all()
    events = mod.choose_events(signals)
    chosen = events.query("arm == 'pressure' and asset == 'BR'")
    assert len(chosen) == 2
    assert chosen.iloc[1].entry_at >= chosen.iloc[0].exit_at


def test_absorption_and_depth_change():
    calendar, features = frames()
    features["BR_return_1"] = -.001
    features["BR_depth_l10"] = -.3
    features.loc[features.index[3]:, ["SI_depth_l1", "SI_depth_l10"]] = .7
    signals = mod.make_signals(calendar, features, config())
    assert signals.query("arm == 'absorption' and asset == 'BR'")["direction"].tolist() == (
        [0] + [-1] * 11)
    assert signals.query("arm == 'depth_change' and asset == 'SI'")["direction"].sum() == 1


@pytest.mark.parametrize("kind", ["gap", "roll", "day", "missing", "plan"])
def test_past_invalid_masks_next_row(kind):
    calendar, features = frames()
    stamp = calendar.index[3]
    if kind == "gap":
        calendar = calendar.drop(calendar.index[2])
        features = features.loc[calendar.index]
    elif kind == "roll":
        calendar.loc[stamp:, "BR_contract_id"] = "NEW"
    elif kind == "day":
        calendar.loc[stamp:, "local_date"] = "2024-10-16"
    elif kind == "missing":
        features.loc[calendar.index[2], "BR_volume_imbalance"] = np.nan
    else:
        calendar.loc[calendar.index[2], "BR_plan_eligible"] = False
    signals = mod.make_signals(calendar, features, config())
    row = signals.loc[(signals.arm == "pressure") & (signals.asset == "BR")
                      & (signals.information_end == stamp)].iloc[0]
    assert not row.eligible and row.direction == 0


def test_future_feature_mutation_does_not_change_prior_signals():
    calendar, features = frames()
    before = mod.make_signals(calendar, features, config())
    features.loc[features.index[6]:, "BR_volume_imbalance"] = -0.8
    after = mod.make_signals(calendar, features, config())
    pd.testing.assert_frame_equal(before.loc[before.information_end < calendar.index[6]],
                                  after.loc[after.information_end < calendar.index[6]])
    features["BR_target"] = 1
    with pytest.raises(ValueError):
        mod.make_signals(calendar, features, config())


def test_short_return_costs_missing_and_no_portfolio_claim():
    calendar, features = frames()
    features["BR_volume_imbalance"] = -.5
    features["BR_trade_imbalance"] = -.5
    features["BR_depth_l10"] = -.5
    signals = mod.make_signals(calendar, features, config())
    intents = mod.choose_events(signals)
    labels = pd.DataFrame(index=calendar.index)
    for asset in mod.ASSETS:
        labels[f"{asset}_target"] = math.log(1.01)
        labels[f"{asset}_label_status"] = "READY"
    first = intents.iloc[0].information_end
    labels.loc[first, "MIX_target"] = np.nan
    events = mod.attach_outcomes(intents, labels)
    shorts = events.query("arm == 'pressure' and asset == 'BR'")
    assert shorts.iloc[0].gross_bps == pytest.approx(-100)
    assert shorts.iloc[0].net_1x_bps == pytest.approx(-110)
    assert shorts.iloc[0].net_2x_bps == pytest.approx(-120)
    assert len(events) == len(intents)
    summary = mod.summarize(events, signals, config())
    assert summary["pressure"]["unresolved_events"] == 1
    assert summary["pressure"]["CAGR"] is None
    assert summary["price_momentum"]["verdict"] == "CONTROL_ONLY"


@pytest.mark.parametrize("times", [
    ["2026-01-01T00:00:00Z"], ["2025-12-31T23:00:00Z"],
    ["2019-12-31T12:00:00Z"],
    ["2024-01-01T12:00:00Z", "2024-01-01T12:00:00Z"],
    ["2024-01-01T12:00:00Z", "2024-01-01T11:00:00Z"],
])
def test_input_dates_blocked_before_values(tmp_path, times):
    path = tmp_path / "synthetic.parquet"
    pd.DataFrame({"information_end": pd.to_datetime(times), "unused_price": 999.0}).to_parquet(path)
    with pytest.raises(ValueError):
        mod.checked_index(path)


def test_empty_arms_are_not_success():
    calendar, features = frames()
    features.loc[:, features.columns.str.endswith("volume_imbalance")] = 0
    features.loc[:, features.columns.str.endswith("return_1")] = 0
    signals = mod.make_signals(calendar, features, config())
    intents = mod.choose_events(signals)
    assert intents.empty
    labels = pd.DataFrame(index=calendar.index)
    for asset in mod.ASSETS:
        labels[f"{asset}_target"] = np.nan
        labels[f"{asset}_label_status"] = "MISSING_LABEL"
    summary = mod.summarize(mod.attach_outcomes(intents, labels), signals, config())
    assert all(summary[name]["completed_events"] == 0 for name in mod.ARMS)
    assert summary["pressure"]["verdict"] == "REJECT_STAGE1"
