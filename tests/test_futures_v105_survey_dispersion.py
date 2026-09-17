"""Synthetic dispersion, exact-year pairing, source clocks and execution contracts."""

import numpy as np
import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v105_survey_dispersion as screen


def config():
    return screen.prior.read_json(screen.CONFIG)


def fixture():
    cfg, rows, dates = config(), [], []
    for i, month in enumerate(
        pd.to_datetime(["2021-07-01", "2021-09-01", "2021-12-01", "2022-02-01"])
    ):
        available = month + pd.offsets.MonthEnd(2) + pd.Timedelta(hours=23, minutes=59, seconds=59)
        available = available.tz_localize("Europe/Moscow").tz_convert("UTC")
        dates.append({"survey_month": month, "available_at": available})
        for year in (2022, 2023):
            for stat, value in (("p25", -2.0), ("p75", 6.0 - i)):
                rows.append(
                    {
                        **dates[-1],
                        "indicator": "gdp_yoy_pct",
                        "statistic": stat,
                        "forecast_year": year,
                        "forecast_period": pd.Timestamp(year, 12, 31),
                        "unit": "percent_yoy",
                        "value": value,
                        "current_vintage": True,
                        "source_url": cfg["source"]["source_url"],
                        "source_sheet": "synthetic",
                        "source_cell": "A1",
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(dates)


def state():
    return screen.states(*fixture(), config())


def test_exact_year_iqr_contraction_and_first_unready():
    d = state()
    assert d.ready.tolist() == [False, True, True, True]
    assert d.contraction.tolist() == [False, True, True, True]
    assert d.current_iqr.tolist() == [8.0, 7.0, 6.0, 5.0]
    assert d.forecast_year.tolist() == [2022, 2022, 2022, 2023]
    assert d.iloc[-1].previous_iqr == 6.0
    assert d.previous_available_at_utc[d.ready].lt(d.available_at_utc[d.ready]).all()
    assert d.source_date.iloc[0] == pd.Timestamp("2021-08-31")
    assert d.source_url.nunique() == 4


def test_year_roll_matches_previous_year_plus_two_not_previous_selected_horizon():
    raw, cal = fixture()
    raw.loc[
        raw.survey_month.eq("2021-12-01") & raw.forecast_year.eq(2022) & raw.statistic.eq("p75"),
        "value",
    ] = -1.0
    d = screen.states(raw, cal, config())
    assert d.iloc[-1].previous_iqr == 6.0 and d.iloc[-1].contraction


@pytest.mark.parametrize("upper", [-2.0, 5.0, 100.0])
def test_zero_equal_wider_iqr_is_valid_but_only_strict_contraction_buys(upper):
    raw, cal = fixture()
    raw.loc[raw.statistic.eq("p75"), "value"] = upper
    d = screen.states(raw, cal, config())
    assert d.ready.iloc[1:].all() and not d.contraction.any()
    assert d.control_direction.iloc[1:].eq(1.0).all()


@pytest.mark.parametrize("bad", [np.nan, np.inf, -3.0])
def test_invalid_quartile_masks_current_and_immediate_successor_without_fallback(bad):
    raw, cal = fixture()
    raw.loc[raw.survey_month.eq("2021-09-01") & raw.statistic.eq("p75"), "value"] = bad
    d = screen.states(raw, cal, config())
    assert not d.ready.iloc[1] and not d.ready.iloc[2] and d.ready.iloc[3]
    assert d.iqr_change.iloc[1:3].isna().all() and d.primary_direction.iloc[1:3].eq(0).all()


def test_missing_row_or_whole_release_retains_calendar_and_never_falls_back():
    raw, cal = fixture()
    for mask in (
        raw.survey_month.eq("2021-09-01") & raw.statistic.eq("p25"),
        raw.survey_month.eq("2021-09-01"),
    ):
        d = screen.states(raw.loc[~mask], cal, config())
        assert len(d) == 4 and not d.ready.iloc[1:3].any() and d.ready.iloc[3]


def test_overflowed_width_is_missing_not_a_direction():
    raw, cal = fixture()
    raw.loc[raw.statistic.eq("p25"), "value"] = -1e308
    raw.loc[raw.statistic.eq("p75"), "value"] = 1e308
    d = screen.states(raw, cal, config())
    assert not d.ready.any() and d.current_iqr.isna().all()
    assert d.primary_direction.eq(0).all()


def test_same_iqr_different_location_or_ignored_median_cannot_change_signal():
    raw, cal = fixture()
    expected = screen.states(raw, cal, config())
    shifted = raw.copy()
    shifted["value"] += shifted.survey_month.dt.month * 10.0
    medians = raw.loc[raw.statistic.eq("p25")].assign(statistic="median", value=1e30)
    d = screen.states(pd.concat([shifted, medians]), cal, config())
    for col in ["current_iqr", "previous_iqr", "iqr_change", "ready", "primary_direction"]:
        pd.testing.assert_series_equal(d[col], expected[col])


def test_future_values_cannot_change_prior_state():
    raw, cal = fixture()
    expected = screen.states(raw, cal, config())
    raw.loc[raw.survey_month.eq("2022-02-01"), "value"] *= 100
    pd.testing.assert_frame_equal(screen.states(raw, cal, config()).iloc[:3], expected.iloc[:3])


def test_bad_dates_units_keys_identity_and_availability_fail_closed():
    raw, cal = fixture()
    for col, value, match in [
        ("unit", "rubles", "unit"),
        ("current_vintage", False, "vintage"),
        ("source_url", "bad", "identity"),
        ("survey_month", pd.Timestamp("2026-01-01"), "protected"),
        ("available_at", pd.Timestamp("2021-08-30T20:59:59Z"), "clock"),
        ("forecast_period", pd.Timestamp("2021-12-31"), "period"),
    ]:
        changed = raw.copy()
        changed.loc[0, col] = value
        with pytest.raises(ValueError, match=match):
            screen.states(changed, cal, config())
    with pytest.raises(ValueError, match="duplicate"):
        screen.states(pd.concat([raw, raw.iloc[:1]]), cal, config())
    with pytest.raises(ValueError, match="duplicate"):
        screen.states(raw, pd.concat([cal, cal.iloc[:1]]), config())


def test_protected_availability_filtered_before_numeric_reader(tmp_path):
    raw, cal = fixture()
    extra = raw.iloc[:4].copy()
    extra["survey_month"] = pd.Timestamp("2025-12-01")
    extra["available_at"] = pd.Timestamp("2026-01-31T20:59:59Z")
    extra["value"] = 1e30
    with pytest.raises(ValueError, match="protected availability"):
        screen.states(extra, extra[["survey_month", "available_at"]].drop_duplicates(), config())
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    pd.concat([raw, extra]).to_parquet(root / cfg["source"]["processed"]["path"], index=False)
    admitted, calendar = screen.read_source(cfg, tmp_path)
    pd.testing.assert_frame_equal(
        admitted.reset_index(drop=True), raw.loc[:, cfg["source"]["allowed_columns"]]
    )
    pd.testing.assert_frame_equal(calendar, cal)


def test_after_availability_next_open_source_ttl_gap_plan_mask_terminal_flat():
    d, cfg = state(), config()
    dates = pd.to_datetime(
        ["2021-10-29", "2021-11-01", "2021-11-02", "2021-11-15", "2021-11-16", "2021-11-17"]
    )
    p = screen.targets(active(dates), d, cfg)["primary"]
    assert p.loc[p.effective_date.eq("2021-11-01"), "target_weight"].iloc[0] == 0.0
    assert p.loc[p.effective_date.eq("2021-11-02"), "target_weight"].iloc[0] == 0.9
    assert p.loc[p.effective_date.eq("2021-11-15"), "stale_at_fill"].iloc[0]
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0.0
    late = screen.targets(active(pd.bdate_range("2022-07-01", "2022-07-08")), d, cfg)["primary"]
    assert late.stale_at_fill.all() and late.target_weight.eq(0).all()
    masked = screen.targets(active(dates).assign(plan_tradable=False), d, cfg)["primary"]
    assert masked.source_unavailable.all() and masked.target_weight.eq(0).all()


def test_flat_price_actual_ledger_is_cost_only_and_tamper_detected(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2021-11-01", "2021-11-19")), state(), cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": day,
                "asset_code": "MIX",
                "contract_id": "MIXTEST",
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
