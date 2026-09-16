"""Synthetic physical units, vintage/seasonal clocks, missingness and ledger tests."""

import numpy as np
import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v104_inventory_cover_premium as screen


def config():
    return screen.prior.read_json(screen.CONFIG)


def fixture():
    raw, coverage = [], []
    for week in pd.date_range("2015-01-02", "2021-08-27", freq="W-FRI"):
        day = week + pd.Timedelta(days=5)
        available = (
            (day + pd.Timedelta(hours=23, minutes=59, seconds=59))
            .tz_localize("America/New_York")
            .tz_convert("UTC")
        )
        meta = {
            "release_date": day,
            "data_week_ending": week,
            "available_at": available,
            "source_url": "synthetic:" + str(day.date()),
        }
        coverage.append({**meta, "sha256": "a" * 64, "admissible": True, "exclusion_reason": None})
        for (section, item), (field, unit) in screen.FIELDS.items():
            value = (200.0 if week.year == 2021 else 400.0) if field == "stocks" else 10000.0
            raw.append(
                {
                    **meta,
                    "section": section,
                    "item": item,
                    "unit": unit,
                    "current_value": value,
                    "raw_sha256": "a" * 64,
                    "release_specific_archive": True,
                }
            )
    return pd.DataFrame(raw), pd.DataFrame(coverage)


def state():
    return screen.states(*fixture(), config())


def test_units_seasonal_complete_history_and_equality_cash():
    d = state()
    july = d.loc[d.data_week_ending.between("2021-07-01", "2021-07-31")]
    assert july.ready.all() and july.cover_days.eq(20.0).all()
    assert july.seasonal_baseline_days.eq(40.0).all() and july.scarcity.all()
    assert july.baseline_complete_years.eq(5).all()
    assert july.baseline_week_count.ge(15).all()
    assert july.baseline_last_available_at_utc.lt(july.available_at_utc).all()
    assert not d.loc[d.data_week_ending.lt("2020-01-01"), "ready"].any()
    raw, c = fixture()
    raw.loc[raw.section.eq("Stocks"), "current_value"] = 400.0
    d = screen.states(raw, c, config())
    assert not d.scarcity.any() and d.control_direction.gt(0).any()


def test_same_month_other_years_not_current_year_or_other_seasons():
    raw, c = fixture()
    raw.loc[
        (raw.data_week_ending.dt.month.ne(7) | raw.data_week_ending.dt.year.eq(2021))
        & raw.section.eq("Stocks"),
        "current_value",
    ] = 17.0
    d = screen.states(raw, c, config())
    july = d.loc[d.data_week_ending.between("2021-07-01", "2021-07-31")]
    assert july.seasonal_baseline_days.eq(40.0).all()
    assert july.cover_days.eq(1.7).all()


def test_baseline_gives_each_year_equal_weight_despite_week_counts():
    raw, c = fixture()
    levels = {2016: 100.0, 2017: 200.0, 2018: 400.0, 2019: 800.0, 2020: 1600.0}
    mask = raw.section.eq("Stocks") & raw.data_week_ending.dt.year.isin(levels)
    raw.loc[mask, "current_value"] = raw.loc[mask, "data_week_ending"].dt.year.map(levels)
    d = screen.states(raw, c, config())
    july = d.loc[d.data_week_ending.between("2021-07-01", "2021-07-31")]
    assert july.seasonal_baseline_days.eq(62.0).all()


def test_missing_one_historical_year_month_has_no_shorter_history_fallback():
    raw, c = fixture()
    mask = raw.data_week_ending.dt.year.eq(2017) & raw.data_week_ending.dt.month.eq(7)
    raw.loc[mask & raw.section.eq("Stocks"), "current_value"] = np.nan
    d = screen.states(raw, c, config())
    july = d.loc[d.data_week_ending.between("2021-07-01", "2021-07-31")]
    assert july.observed.all() and not july.ready.any()
    assert july.seasonal_baseline_days.isna().all() and july.baseline_complete_years.eq(4).all()


@pytest.mark.parametrize("value", [0.0, -1.0, np.nan, np.inf])
def test_invalid_refinery_use_masks_not_zero_or_infinite_signal(value):
    raw, c = fixture()
    mask = raw.release_date.eq("2021-07-14") & raw.section.eq("Crude Oil Supply")
    raw.loc[mask, "current_value"] = value
    row = screen.states(raw, c, config()).set_index("release_date").loc["2021-07-14"]
    assert not row.ready and np.isnan(row.cover_days) and row.primary_direction == 0


def test_new_missing_release_masks_latest_state_never_uses_old_good_release():
    raw, c = fixture()
    raw = raw.loc[~(raw.release_date.eq("2021-07-14") & raw.section.eq("Stocks"))]
    d = screen.states(raw, c, config())
    p = screen.targets(active(pd.bdate_range("2021-07-12", "2021-07-20")), d, config())["primary"]
    assert p.loc[p.effective_date.eq("2021-07-15"), "target_weight"].iloc[0] == 0.9
    after = p.loc[p.effective_date.ge("2021-07-16")]
    assert after.feature_unavailable.all() and after.target_weight.eq(0).all()
    assert after.source_date.eq("2021-07-14").all()


def test_excluded_issue_preserved_as_unready_calendar_row():
    raw, c = fixture()
    c.loc[c.release_date.eq("2021-07-14"), "admissible"] = False
    d = screen.states(raw.loc[raw.release_date.ne("2021-07-14")], c, config())
    assert len(d) == len(c)
    row = d.set_index("release_date").loc["2021-07-14"]
    assert not row.ready and np.isnan(row.cover_days)


def test_later_revision_cannot_replace_first_vintage_in_baseline():
    raw, c = fixture()
    expected = screen.states(raw, c, config())
    extra_raw = raw.loc[raw.release_date.eq("2020-07-08")].copy()
    extra_c = c.loc[c.release_date.eq("2020-07-08")].copy()
    for frame in (extra_raw, extra_c):
        frame["release_date"] = pd.Timestamp("2020-07-16")
        frame["available_at"] = pd.Timestamp("2020-07-17T03:59:59Z")
        frame["source_url"] = "synthetic:2020-07-16"
    extra_raw.loc[extra_raw.section.eq("Stocks"), "current_value"] = 99999.0
    actual = screen.states(pd.concat([raw, extra_raw]), pd.concat([c, extra_c]), config())
    a, b = [
        d.loc[d.data_week_ending.ge("2021-01-01"), "seasonal_baseline_days"]
        for d in (expected, actual)
    ]
    np.testing.assert_array_equal(a.to_numpy(), b.to_numpy())


def test_future_values_and_forbidden_vintage_columns_cannot_change_past_state():
    raw, c = fixture()
    expected = screen.states(raw, c, config())
    changed = raw.assign(year_ago_value=-1e20, previous_value=1e20, reported_weekly_change=-1e20)
    changed.loc[changed.release_date.gt("2021-07-14"), "current_value"] *= 25.0
    actual = screen.states(changed, c, config())
    pd.testing.assert_frame_equal(
        expected.loc[expected.release_date.le("2021-07-14")],
        actual.loc[actual.release_date.le("2021-07-14")],
    )


def test_string_encoded_dates_keep_same_calendar_and_source_states():
    raw, c = fixture()
    expected = screen.states(raw, c, config())
    for frame in (raw, c):
        for column in ("release_date", "data_week_ending", "available_at"):
            frame[column] = frame[column].astype(str)
    pd.testing.assert_frame_equal(screen.states(raw, c, config()), expected)


def test_clock_units_duplicates_and_source_identity_fail_closed():
    raw, c = fixture()
    for column, value, message in [
        ("unit", "barrels", "unit"),
        ("raw_sha256", "bad", "identity"),
        ("release_specific_archive", False, "release-specific"),
        ("available_at", pd.Timestamp("2015-01-07T00:00:00Z"), "clock"),
        ("release_date", pd.Timestamp("2026-01-01"), "protected"),
    ]:
        changed = raw.copy()
        changed.loc[0, column] = value
        with pytest.raises(ValueError, match=message):
            screen.states(changed, c, config())
    with pytest.raises(ValueError, match="duplicate"):
        screen.states(pd.concat([raw, raw.iloc[:1]]), c, config())
    with pytest.raises(ValueError, match="duplicate"):
        screen.states(raw, pd.concat([c, c.iloc[:1]]), config())


def test_source_ttl_gap_missing_plan_and_terminal_flat():
    d = state()
    dates = pd.to_datetime(["2021-07-07", "2021-07-08", "2021-07-20", "2021-07-21", "2021-07-22"])
    p = screen.targets(active(dates), d, config())["primary"]
    gap = p.loc[p.effective_date.eq("2021-07-20")].iloc[0]
    assert gap.stale_at_fill and gap.requested_weight == 0.9 and gap.target_weight == 0
    assert p.loc[p.effective_date.eq("2021-07-21"), "target_weight"].iloc[0] == 0.9
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    late = screen.targets(active(pd.bdate_range("2021-10-01", "2021-10-08")), d, config())[
        "primary"
    ]
    assert late.stale_at_fill.all() and late.target_weight.eq(0).all()
    masked = screen.targets(active(dates).assign(plan_tradable=False), d, config())["primary"]
    assert masked.source_unavailable.all() and masked.target_weight.eq(0).all()


def test_flat_actual_ledger_has_only_costs_and_tamper_is_detected(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2021-07-01", "2021-07-20")), state(), cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": day,
                "asset_code": "BR",
                "contract_id": "BRTEST",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "settle": 100.0,
                "volume": 1e7,
                "sizing_point_value": 100.0,
                "accounting_point_value": 100.0,
                "tick_size": 0.01,
                "fee_per_contract": 1.0,
                "initial_margin": 1000.0,
            }
            for day in signals["primary"].effective_date
        ]
    )
    case = screen.engine.simulate_case(
        tmp_path / "case", signals, market, {"ready_asset_date_fraction": 1.0}, cfg, "synthetic"
    )
    assert (
        screen.prior.audit_case(tmp_path / "case", case, signals)[
            "cash_cost_metric_annual_count_replays"
        ]
        == 4
    )
    for costs in case["metrics"].values():
        for metric in costs.values():
            assert metric["execution_complete"] and metric["round_trips"] == 1
            assert metric["gross_vm_pnl"] == pytest.approx(0.0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0
    path = tmp_path / "case/ledger_primary_base.parquet"
    ledger = pd.read_parquet(path)
    ledger.loc[1, "starting_cash"] += 100.0
    ledger.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="cash continuity"):
        screen.prior.audit_case(tmp_path / "case", case, signals)
