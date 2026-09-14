"""Source clock, missingness and causal targets without real market outcomes."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v76_initial_claims_cycle as screen


def cfg():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def claims(n=120):
    return pd.DataFrame(
        {
            "source_date": pd.date_range("2016-01-02", periods=n, freq="W-SAT"),
            "claims": np.arange(n, dtype=float) + 100,
        }
    )


def one_asset(raw):
    return screen.states(raw, cfg()).loc[lambda x: x.asset_code.eq("BR")].reset_index(drop=True)


def test_full_56week_window_and_fixed_joint_directions():
    s = screen.states(claims(), cfg())
    br = s.loc[s.asset_code.eq("BR")]
    assert not br.ready.iloc[:55].any() and br.ready.iloc[55:].all()
    assert br.claims_change.iloc[55] == 52
    assert br.primary_direction.iloc[55:].eq(-1).all()
    assert s.loc[s.asset_code.eq("MIX")].primary_direction.iloc[55:].eq(-1).all()
    assert s.loc[s.asset_code.eq("SI")].primary_direction.iloc[55:].eq(1).all()


def test_future_claims_cannot_change_past_states():
    raw = claims()
    expected = one_asset(raw).iloc[:70]
    raw.loc[70:, "claims"] += 500
    pd.testing.assert_frame_equal(expected, one_asset(raw).iloc[:70])


@pytest.mark.parametrize("value", [0, 100])
def test_genuine_zero_or_flat_level_is_valid_not_missing(value):
    raw = claims()
    raw["claims"] = value
    state = one_asset(raw)
    assert state.ready.iloc[55:].all() and state.primary_direction.eq(0).all()
    assert state.control_direction.iloc[55:].eq(1).all()


def test_missing_count_masks_all_dependent_56weeks():
    raw = claims(140)
    raw.loc[70, "claims"] = np.nan
    s = one_asset(raw)
    assert s.ready.iloc[69] and not s.ready.iloc[70:126].any() and s.ready.iloc[126:].all()
    assert pd.isna(s.claims.iloc[70])


def test_missing_row_never_shortens_year_or_average():
    s = one_asset(claims(150).drop(index=70))
    assert s.ready.iloc[69] and not s.ready.iloc[70:125].any() and s.ready.iloc[125:].all()


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2017-08-05", "2017-08-13T03:59:59Z"),
        ("2017-12-02", "2017-12-10T04:59:59Z"),
        ("2017-03-11", "2017-03-19T03:59:59Z"),
    ],
)
def test_availability_uses_local_calendar_end_and_dst(day, expected):
    s = one_asset(pd.DataFrame({"source_date": [pd.Timestamp(day)], "claims": [100]}))
    assert s.available_at_utc.iloc[0] == pd.Timestamp(expected)


def test_late2025_retains_source_but_does_not_generate2026_states():
    raw = pd.DataFrame(
        {"source_date": pd.to_datetime(["2025-12-20", "2025-12-27"]), "claims": [10, 20]}
    )
    s = one_asset(raw)
    assert len(raw) == 2 and len(s) == 1 and s.source_date.iloc[0] == pd.Timestamp("2025-12-20")


@pytest.mark.parametrize("bad", ["-1", "nan", "inf", "1.5"])
def test_bad_csv_counts_fail_closed(tmp_path, bad):
    p = tmp_path / "claims.csv"
    p.write_text("observation_date,ICNSA\n2017-01-07," + bad + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError):
        screen.read_claims(p)


def test_csv_missing_is_not_numeric_zero(tmp_path):
    p = tmp_path / "claims.csv"
    p.write_text("observation_date,ICNSA\n2017-01-07,.\n2017-01-14,0\n", encoding="utf-8-sig")
    raw, q = screen.read_claims(p)
    assert q["missing_values"] == 1 and pd.isna(raw.claims.iloc[0]) and raw.claims.iloc[1] == 0


@pytest.mark.parametrize(
    "body",
    [
        "DATE,ICNSA\n2017-01-07,10\n",
        "observation_date,ICNSA\n2017-01-07,10\n2017-01-07,11\n",
        "observation_date,ICNSA\n2026-01-03,10\n",
        "observation_date,ICNSA\n2017-01-06,10\n",
        "<!DOCTYPE html>\n",
    ],
)
def test_csv_header_calendar_duplicates_and_protection(tmp_path, body):
    p = tmp_path / "claims.csv"
    p.write_text(body, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        screen.read_claims(p)


def test_targets_wait_for_availability_then_next_open_and_joint_flat():
    config = cfg()
    raw = claims(56)
    s = screen.states(raw, config)
    start = raw.source_date.iloc[-1]
    days = pd.bdate_range(start, start + pd.Timedelta(days=30))
    active = pd.concat(
        [
            pd.DataFrame(
                {
                    "decision_date": days[:-1],
                    "effective_date": days[1:],
                    "observed_through": days[:-1],
                    "asset_code": asset,
                    "contract_id": asset + "_TEST",
                    "plan_tradable": True,
                    "roll": False,
                }
            )
            for asset in config["assets"]
        ],
        ignore_index=True,
    )
    config["period"] = {"start": str(days[0].date()), "end": str(days[-1].date())}
    out = screen.adapter.targets(active, s, "primary", config)
    prior = out.decision_at_utc < s.loc[s.ready, "available_at_utc"].min()
    assert out.loc[prior, "target_weight"].eq(0).all()
    used = out.loc[out.target_weight.ne(0)]
    assert not used.empty and used.available_at_utc.le(used.decision_at_utc).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert (
        out.groupby("effective_date")
        .target_weight.apply(lambda x: x.abs().sum())
        .le(0.9 + 1e-12)
        .all()
    )
    assert (
        out.loc[out.effective_date.gt(start + pd.Timedelta(days=14)), "target_weight"].eq(0).all()
    )
    assert out.groupby("asset_code").tail(1).terminal_flat.all()
