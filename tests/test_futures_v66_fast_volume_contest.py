"""Synthetic causality, volume ablation, target and multi-asset counting tests."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v66_fast_volume_contest as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def observations(periods=70):
    dates = pd.bdate_range("2021-01-04", periods=periods)
    parts = []
    for asset in config()["assets"]:
        close = 100 + np.sin(np.arange(periods))
        parts.append(
            pd.DataFrame(
                {
                    "trade_date": dates,
                    "logical_asset": asset,
                    "canonical_contract_id": asset + "TEST",
                    "open": 100.0,
                    "high": close + 2,
                    "low": close - 2,
                    "close": close,
                    "settle": close,
                    "volume": 10000.0,
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def mapping(raw):
    parts = []
    for asset, group in raw.groupby("logical_asset"):
        group = group.sort_values("trade_date")
        dates = group.trade_date.to_numpy()
        parts.append(
            pd.DataFrame(
                {
                    "decision_date": dates[:-1],
                    "effective_date": dates[1:],
                    "observed_through": dates[:-1],
                    "asset_code": asset,
                    "contract_id": group.canonical_contract_id.to_numpy()[:-1],
                    "plan_tradable": True,
                    "roll": False,
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


@pytest.mark.parametrize(
    "name,body,location,breakout,width,volume,expected",
    [
        ("volume_shock_reversal", -3, 0.1, 0, 1, 3, 1),
        ("volume_pressure_continuation", 2, 0.9, 0, 1, 3, 1),
        ("thin_breakout_fade", 1, 0.9, 1, 1, 0.5, -1),
        ("compressed_volume_expansion", 0.2, 0.9, 0, 0.3, 3, 1),
    ],
)
def test_rule_and_matched_volume_ablation(name, body, location, breakout, width, volume, expected):
    f = pd.DataFrame(
        {
            "body_z": [body],
            "close_location": [location],
            "breakout": [breakout],
            "range_ratio": [width],
            "volume_ratio": [volume],
            "ready": [True],
        }
    )
    assert screen.directions(f, name, "primary", config()).iloc[0] == expected
    f["volume_ratio"] = 1.5
    assert screen.directions(f, name, "primary", config()).iloc[0] == 0
    assert screen.directions(f, name, "control", config()).iloc[0] == expected
    f["ready"] = False
    assert screen.directions(f, name, "control", config()).iloc[0] == 0


def test_future_market_mutation_does_not_change_past_features_or_targets():
    raw = observations()
    actual = screen.features(raw, config())
    cutoff = pd.Timestamp("2021-03-01")
    mutated = raw.copy()
    future = mutated.trade_date.ge(cutoff)
    mutated.loc[future, ["open", "high", "low", "close", "settle", "volume"]] *= 3
    changed = screen.features(mutated, config())
    pd.testing.assert_frame_equal(
        actual.loc[actual.decision_date.lt(cutoff)], changed.loc[changed.decision_date.lt(cutoff)]
    )
    m = mapping(raw)
    for h in config()["hypotheses"]:
        a = screen.targets(m, actual, h["id"], "primary", config())
        b = screen.targets(m, changed, h["id"], "primary", config())
        pd.testing.assert_frame_equal(
            a.loc[a.decision_date.lt(cutoff)], b.loc[b.decision_date.lt(cutoff)]
        )


def test_same_contract_prior_only_warmup_missing_and_gap_reset():
    raw = observations()
    f = screen.features(raw, config())
    first = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
    assert not first.loc[:19, "ready"].any() and first.loc[20, "ready"]
    poisoned = raw.copy()
    bad_date = raw.trade_date.unique()[25]
    poisoned.loc[poisoned.trade_date.eq(bad_date), "volume"] = np.nan
    f = screen.features(poisoned, config())
    first = f.loc[f.asset_code.eq("BR")].reset_index(drop=True)
    assert not first.loc[25:45, "ready"].any() and first.loc[46, "ready"]
    changed = raw.copy()
    later = changed.trade_date.ge(raw.trade_date.unique()[35])
    changed.loc[later, "canonical_contract_id"] += "NEXT"
    f = screen.features(changed, config())
    assert not f.loc[f.contract_id.str.endswith("NEXT")].groupby("asset_code").head(20).ready.any()
    shifted = raw.copy()
    shifted.loc[later, "trade_date"] += pd.Timedelta(days=20)
    f = screen.features(shifted, config())
    assert (
        not f.loc[f.decision_date.ge(shifted.loc[later, "trade_date"].min())]
        .groupby("asset_code")
        .head(20)
        .ready.any()
    )


def test_five_tranches_fixed_denominator_roll_reset_terminal_and_gross():
    raw = observations()
    m = mapping(raw)
    f = screen.features(raw, config())
    f = f.assign(body_z=-3.0, volume_ratio=3.0, ready=True)
    a = screen.targets(m, f, "volume_shock_reversal", "primary", config())
    br = a.loc[a.asset_code.eq("BR")].reset_index(drop=True)
    np.testing.assert_allclose(br.loc[:4, "target_weight"], [0.06, 0.12, 0.18, 0.24, 0.30])
    assert a.groupby("effective_date").target_weight.sum().max() <= 0.9 + 1e-12
    assert a.groupby("asset_code").tail(1).target_weight.eq(0).all()
    m.loc[m.decision_date.ge(br.loc[30, "decision_date"]), "contract_id"] += "NEXT"
    rolled_features = f.copy()
    rolled_features.loc[
        rolled_features.decision_date.ge(br.loc[30, "decision_date"]), "contract_id"
    ] += "NEXT"
    b = screen.targets(m, rolled_features, "volume_shock_reversal", "primary", config())
    assert b.loc[b.decision_date.eq(br.loc[30, "decision_date"]), "target_weight"].eq(0.06).all()


def test_protected_data_duplicate_and_future_mapping_fail_closed():
    raw = observations()
    bad = raw.copy()
    bad.loc[0, "trade_date"] = "2026-01-01"
    with pytest.raises(ValueError, match="protected"):
        screen.features(bad, config())
    with pytest.raises(ValueError, match="duplicate"):
        screen.features(pd.concat([raw, raw.iloc[:1]]), config())
    m = mapping(raw)
    m.loc[0, "observed_through"] = m.loc[0, "effective_date"]
    with pytest.raises(ValueError, match="future map"):
        screen.targets(
            m, screen.features(raw, config()), "volume_shock_reversal", "primary", config()
        )


def test_position_episodes_count_separately_per_asset_and_sign():
    dates = pd.bdate_range("2021-01-04", periods=5)
    a = pd.DataFrame(
        {
            "session_date": dates,
            "asset_code": "BR",
            "contract_id": "A",
            "contracts": [0, 1, 2, -1, 0],
        }
    )
    b = pd.DataFrame(
        {
            "session_date": dates,
            "asset_code": "SI",
            "contract_id": "B",
            "contracts": [1, 1, 1, 0, 0],
        }
    )
    counts = screen.position_counts(pd.concat([a, b]).sort_values("session_date"))
    assert counts == {"position_entries": 3, "round_trips": 3, "exposed_asset_sessions": 6}


def test_untradable_and_stale_entries_are_masked_not_market_zeroes():
    raw = observations()
    m = mapping(raw)
    f = screen.features(raw, config()).assign(body_z=-3.0, volume_ratio=3.0, ready=True)
    dates = sorted(m.decision_date.unique())
    m.loc[m.decision_date.eq(dates[6]), "plan_tradable"] = False
    m.loc[m.decision_date.ge(dates[7]), "effective_date"] += pd.Timedelta(days=14)
    a = screen.targets(m, f, "volume_shock_reversal", "primary", config())
    unavailable = a.loc[a.decision_date.eq(dates[6])]
    stale = a.loc[a.decision_date.eq(dates[7])]
    assert unavailable.source_unavailable.all() and unavailable.target_weight.eq(0).all()
    assert stale.stale_at_fill.all() and stale.target_weight.eq(0).all()
    assert unavailable.requested_weight.ne(0).all() and stale.requested_weight.ne(0).all()
