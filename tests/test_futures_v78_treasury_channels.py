"""Synthetic quote clocks, missingness, signs and future isolation only."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v78_treasury_channels as screen


def cfg():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def quotes(n=100):
    return pd.DataFrame(
        {
            "source_date": pd.bdate_range("2024-01-02", periods=n),
            "DGS10_valid": True,
            "DFII10_valid": True,
            "DGS10_bps": 200 + np.arange(n) * 2.0,
            "DFII10_bps": -10 + np.arange(n, dtype=float),
        }
    )


def one(raw, variant="real_discount"):
    return (
        screen.states(raw, cfg(), variant)
        .loc[lambda x: x.asset_code.eq("BR")]
        .reset_index(drop=True)
    )


def test_distinct_signs_and_full_21_observations():
    real = one(quotes())
    inflation = one(quotes(), "inflation_compensation")
    assert not real.ready.iloc[:20].any() and real.ready.iloc[20:].all()
    assert real.primary_direction.iloc[20:].eq(-1).all()
    assert inflation.primary_direction.iloc[20:].eq(1).all()
    state = screen.states(quotes(), cfg(), "real_discount")
    assert state.loc[state.asset_code.eq("SI") & state.ready].primary_direction.eq(1).all()


def test_future_quote_changes_cannot_change_past_states():
    raw = quotes()
    expected = one(raw).iloc[:60]
    raw.loc[60:, "DFII10_bps"] += 200
    pd.testing.assert_frame_equal(expected, one(raw).iloc[:60])


def test_partial_missing_masks_dependent_history_without_imputation():
    raw = quotes()
    raw.loc[40, ["DFII10_valid", "DFII10_bps"]] = [False, np.nan]
    state = one(raw)
    assert state.ready.iloc[39] and not state.ready.iloc[40:61].any()
    assert state.ready.iloc[61:].all() and pd.isna(state.DFII10_bps.iloc[40])


def test_both_missing_is_not_a_new_observation():
    raw = quotes()
    raw.loc[40, ["DGS10_valid", "DFII10_valid"]] = False
    raw.loc[40, ["DGS10_bps", "DFII10_bps"]] = np.nan
    state = one(raw)
    assert len(state) == len(raw) - 1
    assert not state.source_date.eq(raw.source_date.iloc[40]).any()


def test_long_gap_masks_complete_dependent_windows():
    raw = quotes()
    raw.loc[40:, "source_date"] += pd.Timedelta(days=14)
    state = one(raw)
    assert state.ready.iloc[39] and not state.ready.iloc[40:60].any()
    assert state.ready.iloc[60:].all()


@pytest.mark.parametrize("level", [0, -125, 125])
def test_flat_or_negative_yield_is_valid(level):
    raw = quotes()
    raw["DFII10_bps"] = level
    state = one(raw)
    assert state.ready.iloc[20:].all() and state.primary_direction.eq(0).all()


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2024-03-07", "2024-03-12T03:59:59Z"),
        ("2024-11-01", "2024-11-06T04:59:59Z"),
        ("2019-01-11", "2019-01-17T04:59:59Z"),
        ("2020-08-18", "2020-08-27T03:59:59Z"),
        ("2017-04-14", "2017-05-19T03:59:59Z"),
    ],
)
def test_local_calendar_dst_and_known_corrections(day, expected):
    raw = quotes(1)
    raw["source_date"] = pd.Timestamp(day)
    assert screen.clock_states(raw, cfg()).available_at_utc.iloc[0] == pd.Timestamp(expected)


def test_late_component_delays_every_dependent_window():
    raw = quotes(50)
    custom = cfg()
    custom["signal"]["availability_date_floors"] = {
        str(raw.source_date.iloc[25].date()): "2024-04-01"
    }
    state = screen.clock_states(raw, custom).sort_values("source_date")
    assert state.available_at_utc.iloc[25:46].ge(pd.Timestamp("2024-04-02T03:59:59Z")).all()
    assert state.dominated_late_window.iloc[25:46].all()


def test_metadata_mode_never_needs_quote_levels():
    raw = quotes().drop(columns=["DGS10_bps", "DFII10_bps"])
    state = one(raw, "metadata")
    assert "real_change_bps" not in state and state.ready.iloc[20:].all()


def test_late2025_availability_does_not_create2026_state():
    raw = quotes(1)
    raw["source_date"] = pd.Timestamp("2025-12-31")
    assert screen.states(raw, cfg(), "metadata").empty


@pytest.mark.parametrize("value", ["nan", "inf", "1.234", "1,2", "text"])
def test_invalid_quote_csv(tmp_path, value):
    path = tmp_path / "bad.csv"
    path.write_text("observation_date,DFII10\n2024-01-02," + value + "\n", encoding="utf-8-sig")
    with pytest.raises(ValueError):
        screen.read_quote_csv(path, "DFII10")


def test_quote_bps_are_exact_and_missing_is_not_zero(tmp_path):
    path = tmp_path / "q.csv"
    path.write_text(
        "observation_date,DFII10\n2024-01-02,-0.01\n2024-01-03,0\n2024-01-04,.\n",
        encoding="utf-8-sig",
    )
    full, q = screen.read_quote_csv(path, "DFII10")
    meta, same = screen.read_quote_csv(path, "DFII10", metadata_only=True)
    assert full.DFII10_bps.iloc[0] == -1 and full.DFII10_bps.iloc[1] == 0
    assert pd.isna(full.DFII10_bps.iloc[2]) and q["missing_values"] == 1
    assert same == q and "DFII10_bps" not in meta


@pytest.mark.parametrize(
    "body",
    [
        "DATE,DFII10\n2024-01-02,1\n",
        "observation_date,DFII10\n2026-01-02,1\n",
        "observation_date,DFII10\n2024/01/02,1\n",
        "observation_date,DFII10\n2024-01-02,1\n2024-01-02,2\n",
        "<html>\n",
    ],
)
def test_schema_duplicate_date_and_holdout_guards(tmp_path, body):
    path = tmp_path / "q.csv"
    path.write_text(body, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        screen.read_quote_csv(path, "DFII10")
