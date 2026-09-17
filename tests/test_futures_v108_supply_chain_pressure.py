"""Synthetic vintage selection, missingness, protected columns, clocks and integer ledger."""

import copy
import csv
import io

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v108_supply_chain_pressure as screen


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["source"].update(first_vintage="2022-05", last_vintage="2022-06", expected_vintages=2)
    return cfg


def table():
    return [
        ["Date", "May-22", "Jun-22", "Dec-25", "Jan-26"],
        ["31-Mar-2022", "1", "0.5", "NOT_READ", "NOT_READ"],
        ["30-Apr-2022", "2", "3", "NOT_READ", "NOT_READ"],
        ["31-May-2022", "#N/A", "4", "NOT_READ", "NOT_READ"],
        ["30-Nov-2025", "#N/A", "#N/A", "NOT_READ", "NOT_READ"],
        ["31-Dec-2025", "#N/A", "#N/A", "NOT_READ", "NOT_READ"],
        ["31-Jan-2026", "NOT_READ", "NOT_READ", "NOT_READ", "NOT_READ"],
        ["", "", "", "", ""],
    ]


def raw(rows=None):
    stream = io.StringIO()
    csv.writer(stream).writerows(table() if rows is None else rows)
    return stream.getvalue().encode()


def state(rows=None):
    return screen.states(screen.records(raw(rows), config(), numeric=True))


def test_metadata_never_converts_numbers(monkeypatch):
    def forbidden(*args):
        raise AssertionError("numeric conversion during metadata review")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    records = screen.records(raw(), config())
    assert [r["vintage"] for r in records] == ["2022-05", "2022-06"]
    assert "current_index" not in records[0]
    assert [r["numeric_observation_count"] for r in records] == [2, 3]


@pytest.mark.parametrize(
    "month,expected",
    [
        ("2022-05", "2022-06-01T03:59:59Z"),
        ("2025-11", "2025-12-01T04:59:59Z"),
        ("2025-12", "2026-01-01T04:59:59Z"),
    ],
)
def test_conservative_month_end_clock_dst_and_protected_last_vintage(month, expected):
    assert screen.availability(pd.Period(month, "M")) == pd.Timestamp(expected)


def test_same_vintage_not_previous_published_value():
    rows = table()
    rows[2][1] = "5"
    actual = state(rows)
    assert actual.primary_direction.tolist() == [1.0, 1.0]
    assert actual.current_index.tolist() == ["5", "4"]
    assert actual.previous_index.tolist() == ["1", "3"]


@pytest.mark.parametrize(
    "current,previous,long",
    [
        ("0", "-1", 0.0),
        ("-1", "-2", 0.0),
        ("1", "1", 0.0),
        ("1", "2", 0.0),
        ("1", "0", 1.0),
        ("0.3", "0.30", 0.0),
    ],
)
def test_strict_positive_and_rising_rule_retains_zero(current, previous, long):
    rows = table()
    rows[1][1], rows[2][1] = previous, current
    actual = state(rows)
    assert actual.ready.iloc[0] and actual.primary_direction.iloc[0] == long
    assert actual.control_direction.iloc[0] == 1.0


@pytest.mark.parametrize("row_index", [1, 2])
def test_missing_is_mask_not_numeric_zero(row_index):
    rows = table()
    rows[row_index][1] = "#N/A"
    actual = state(rows)
    assert not actual.ready.iloc[0]
    assert actual.primary_direction.iloc[0] == actual.control_direction.iloc[0] == 0
    field = "previous_index" if row_index == 1 else "current_index"
    assert actual[field].iloc[0] is None


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "nan", "", "1,3"])
def test_invalid_historical_values_fail_closed(bad):
    rows = table()
    rows[2][1] = bad
    with pytest.raises(ValueError, match="invalid numeric"):
        screen.records(raw(rows), config(), numeric=True)


def test_future_rows_and_columns_cannot_alter_earlier_signals():
    rows = table()
    original = state(rows)
    for row in rows[1:-1]:
        row[3:] = ["UNPARSEABLE", "UNPARSEABLE"]
    rows[-2][1:] = ["UNPARSEABLE"] * 4
    pd.testing.assert_frame_equal(original, state(rows))
    rows[2][2] = "999"
    assert state(rows).iloc[0].to_dict() == original.iloc[0].to_dict()


def test_duplicate_unsorted_wrong_date_header_and_lookahead_fail_closed():
    modifications = []
    a = table()
    a[0][2] = "May-22"
    modifications.append((a, "duplicate"))
    a = table()
    a[1][0] = "30-Mar-2022"
    modifications.append((a, "month-end"))
    a = table()
    a[2][0] = a[1][0]
    modifications.append((a, "duplicates"))
    a = table()
    a[0][1] = "XXX-22"
    modifications.append((a, "vintage label"))
    a = table()
    a[3][1] = "1"
    modifications.append((a, "future value"))
    a = table()
    a[-1][1] = "1"
    modifications.append((a, "undated"))
    for rows, message in modifications:
        with pytest.raises(ValueError, match=message):
            screen.records(raw(rows), config(), numeric=True)


def test_protected_vintage_never_accepted():
    cfg = config()
    cfg["source"].update(first_vintage="2025-12", last_vintage="2025-12", expected_vintages=1)
    with pytest.raises(ValueError, match="incomplete selected"):
        screen.records(raw(), cfg, numeric=True)


def test_clock_plan_staleness_and_terminal():
    cfg = config()
    plan = active(pd.bdate_range("2022-05-30", "2022-06-10"))
    actual = screen.targets(plan, state(), cfg)["primary"]
    assert actual.loc[actual.effective_date.eq("2022-06-01"), "target_weight"].iloc[0] == 0
    assert actual.loc[actual.effective_date.eq("2022-06-02"), "target_weight"].iloc[0] == 0.9
    assert actual.iloc[-1].terminal_flat and actual.iloc[-1].target_weight == 0
    missing = screen.targets(plan.assign(plan_tradable=False), state(), cfg)["primary"]
    assert missing.source_unavailable.all() and missing.target_weight.eq(0).all()
    late = screen.targets(active(pd.bdate_range("2022-10-03", "2022-10-10")), state(), cfg)
    assert late["primary"].stale_at_fill.all() and late["primary"].target_weight.eq(0).all()


def test_no_signal_before_complete_vintage_and_missing_state_abstains():
    cfg = config()
    records = screen.records(raw(), cfg, numeric=True)
    records[0].update(previous_index=None, ready=False)
    plan = active(pd.bdate_range("2022-05-30", "2022-06-10"))
    signals = screen.targets(plan, screen.states(records), cfg)
    assert all(s.target_weight.eq(0).all() for s in signals.values())
    poison = copy.deepcopy(records)
    poison[0]["current_index"] = "Infinity"
    with pytest.raises(ValueError, match="nonfinite"):
        screen.states(poison)


def test_existing_integer_ledger_flat_price_and_costs(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2022-05-30", "2022-06-10")), state(), cfg)
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
            assert metric["gross_vm_pnl"] == pytest.approx(0)
            assert metric["net_pnl"] == pytest.approx(-metric["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0


def test_source_hash_drift_rejected_before_csv_read(tmp_path):
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="manifest drift"):
        screen.source(cfg, tmp_path)
