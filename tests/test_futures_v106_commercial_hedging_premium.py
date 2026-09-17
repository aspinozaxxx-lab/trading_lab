"""Synthetic annual hedging-pressure baseline, causal clocks and ledger contracts."""

import numpy as np
import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v106_commercial_hedging_premium as screen


def config():
    return screen.prior.read_json(screen.CONFIG)


def raw(n=80):
    dates = pd.date_range("2020-01-07", periods=n, freq="7D")
    return pd.DataFrame(
        {
            "report_date": dates,
            "logical_market": "WTI",
            "cftc_contract_market_code": "067651",
            "contract_units": config()["source"]["contract_units"],
            "source_archive_year": dates.year,
            "open_interest": 1000.0,
            "producer_long": 100.0,
            "producer_short": np.where(np.arange(n) < 52, 200.0, 300.0),
        }
    )


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2024-01-02", "2024-01-10T04:59:59Z"),
        ("2024-07-02", "2024-07-10T03:59:59Z"),
        ("2018-12-24", "2019-02-02T04:59:59Z"),
        ("2023-01-31", "2023-02-25T04:59:59Z"),
        ("2025-09-30", "2025-11-20T04:59:59Z"),
        ("2025-11-10", "2025-12-11T04:59:59Z"),
        ("2019-03-26", "2019-04-03T03:59:59Z"),
    ],
)
def test_pinned_delays_dst_and_no_gold_correction(day, expected):
    assert screen.report_clock(pd.Timestamp(day)) == pd.Timestamp(expected)


def test_previous52_not_current_in_baseline_and_even_median():
    d, _ = screen.states(raw(), config())
    assert not d.ready.iloc[:52].any() and d.ready.iloc[52:].all()
    assert d.prior52_median_share.iloc[52] == 0.1
    assert d.prior52_median_share.iloc[78] == 0.15
    assert d.prior52_median_share.iloc[79] == 0.2
    assert d.primary_direction.iloc[52:79].eq(1).all() and d.primary_direction.iloc[79] == 0
    assert d.baseline_latest_report_date[d.ready].lt(d.source_date[d.ready]).all()


def test_nonpositive_or_equal_pressure_never_buys_and_scale_invariant():
    source = raw()
    expected, _ = screen.states(source, config())
    scaled = source.copy()
    scaled[screen.NUMBERS] *= 3
    actual, _ = screen.states(scaled, config())
    for col in ("commercial_net_short_share", "prior52_median_share", "primary_direction", "ready"):
        pd.testing.assert_series_equal(expected[col], actual[col])
    for value in (100.0, 50.0, 200.0):
        flat, _ = screen.states(source.assign(producer_short=value), config())
        assert not flat.primary_direction.any() and flat.ready.iloc[52:].all()


@pytest.mark.parametrize(
    "field,value",
    [
        ("open_interest", 0.0),
        ("open_interest", np.nan),
        ("open_interest", np.inf),
        ("producer_long", -1.0),
        ("producer_short", 1.5),
        ("producer_short", 1001.0),
        ("producer_long", np.nan),
        ("open_interest", float(2**53)),
    ],
)
def test_bad_interior_row_masks_all53_dependencies_without_skipping(field, value):
    d = raw(120)
    d.loc[54, field] = value
    state, _ = screen.states(d, config())
    assert state.ready.iloc[52:54].all()
    assert not state.ready.iloc[54:107].any() and state.ready.iloc[107:].all()
    assert state.prior52_median_share.iloc[54:107].isna().all()


def test_missing_week_fails_window_no_longer_fallback():
    d = raw(120).drop(index=54)
    reports, _ = screen.states(d, config())
    assert not reports.ready.iloc[54:106].any()
    assert reports.ready.iloc[106:].all()


def test_future_positions_and_other_categories_do_not_change_past():
    d = raw(100)
    before, _ = screen.states(d.iloc[:80], config())
    d.loc[80:, "producer_short"] = 999.0
    d["managed_money_long"] = 1e30
    d["total_traders"] = -1e30
    after, _ = screen.states(d, config())
    pd.testing.assert_frame_equal(before, after.iloc[:80].reset_index(drop=True))


def test_dependency_clock_max_and_late_older_state_cannot_overwrite_new(monkeypatch):
    original = screen.report_clock
    first = pd.Timestamp("2020-01-07")
    delayed = pd.Timestamp("2021-06-01T03:59:59Z")
    monkeypatch.setattr(
        screen, "report_clock", lambda day: delayed if day == first else original(day)
    )
    reports, state = screen.states(raw(120), config())
    dependent = reports.loc[reports.source_date.le(first + pd.Timedelta(weeks=52))]
    assert dependent.available_at_utc.ge(delayed).all()
    assert reports.dominated_late_report.any()
    assert state.source_date.is_monotonic_increasing


@pytest.mark.parametrize(
    "change", ["duplicate", "market", "code", "unit", "protected", "late_availability"]
)
def test_scope_fail_closed(change):
    d = raw()
    if change == "duplicate":
        d.loc[1, "report_date"] = d.loc[0, "report_date"]
    elif change == "protected":
        d.loc[0, "report_date"] = pd.Timestamp("2026-01-01")
    elif change == "late_availability":
        d.loc[0, "report_date"] = pd.Timestamp("2025-12-30")
    else:
        d.loc[
            0,
            {
                "market": "logical_market",
                "code": "cftc_contract_market_code",
                "unit": "contract_units",
            }[change],
        ] = "bad"
    with pytest.raises(ValueError):
        screen.states(d, config())


def test_reader_filters_future_available_values_and_other_market_before_load(tmp_path):
    d = raw()
    future = d.iloc[:1].copy()
    future["report_date"] = pd.Timestamp("2025-12-30")
    future["source_archive_year"] = 2025
    future["producer_short"] = 1e30
    other = d.assign(logical_market="GOLD", cftc_contract_market_code="088691", producer_short=1e30)
    all_rows = pd.concat([d, future, other], ignore_index=True)
    cfg = config()
    cfg["source"].update(wti_rows=81, minimum_report_date="2020-01-07")
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    all_rows.to_parquet(root / cfg["source"]["processed"]["file"], index=False)
    expected = d.loc[:, cfg["source"]["allowed_columns"]]
    pd.testing.assert_frame_equal(screen.read_source(cfg, tmp_path), expected)


def test_next_open_clock_ttl_gap_plan_masks_and_terminal_flat():
    _, state = screen.states(raw(60), config())
    dates = pd.to_datetime(
        ["2021-01-12", "2021-01-13", "2021-01-14", "2021-01-27", "2021-01-28", "2021-01-29"]
    )
    p = screen.targets(active(dates), state, config())["primary"]
    assert p.loc[p.effective_date.eq("2021-01-13"), "target_weight"].iloc[0] == 0
    assert p.loc[p.effective_date.eq("2021-01-14"), "target_weight"].iloc[0] == 0.9
    assert p.loc[p.effective_date.eq("2021-01-27"), "stale_at_fill"].iloc[0]
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    late = screen.targets(active(pd.bdate_range("2021-06-01", "2021-06-08")), state, config())[
        "primary"
    ]
    assert late.stale_at_fill.all() and late.target_weight.eq(0).all()
    masked = screen.targets(active(dates).assign(plan_tradable=False), state, config())["primary"]
    assert masked.source_unavailable.all() and masked.target_weight.eq(0).all()


def test_flat_market_actual_ledger_costs_and_cash_tamper_detection(tmp_path):
    cfg = config()
    _, state = screen.states(raw(), cfg)
    signals = screen.targets(active(pd.bdate_range("2021-01-13", "2021-02-01")), state, cfg)
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
