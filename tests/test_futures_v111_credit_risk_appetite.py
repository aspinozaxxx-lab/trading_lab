"""Synthetic monthly EBP, protected cells, missing masks, next-open and fee ledger."""

import csv
import io

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v111_credit_risk_appetite as screen


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["source"].update(
        raw_start="2019-10-01",
        raw_end="2020-03-31",
        expected_raw_reports=6,
        expected_eligible_reports=6,
    )
    return cfg


def table(cfg=None, values=None):
    cfg = config() if cfg is None else cfg
    dates = pd.date_range(cfg["source"]["raw_start"], cfg["source"]["raw_end"], freq="MS")
    values = ["-1"] * len(dates) if values is None else values
    return [
        {
            "date": f"{d.month}/1/{d.year}",
            "gz_spread": "DO_NOT_READ_GZ",
            "ebp": value,
            "est_prob": "DO_NOT_READ_PROB",
        }
        for d, value in zip(dates, values, strict=True)
    ]


def raw(rows=None):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=config()["source"]["headers"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(table() if rows is None else rows)
    return out.getvalue().encode()


def state(values=None):
    return screen.states(screen.records(raw(table(values=values)), config(), numeric=True))


def test_metadata_never_converts_values_or_reads_unrelated_columns(monkeypatch):
    def forbidden(*args):
        raise AssertionError("numeric conversion before seal")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    rows = screen.records(raw(), config())
    assert len(rows) == 6 and all("ebp" not in r for r in rows)
    assert rows[0]["original_date_token"] == "10/1/2019"


@pytest.mark.parametrize(
    "day,end,proxy,expected",
    [
        ("2017-11-01", "2017-11-30", "2017-12-31", "2018-01-01T04:59:59Z"),
        ("2019-10-01", "2019-10-31", "2019-11-30", "2019-12-01T04:59:59Z"),
        ("2020-01-01", "2020-01-31", "2020-02-29", "2020-03-01T04:59:59Z"),
        ("2020-02-01", "2020-02-29", "2020-03-31", "2020-04-01T03:59:59Z"),
        ("2025-10-01", "2025-10-31", "2025-11-30", "2025-12-01T04:59:59Z"),
        ("2025-11-01", "2025-11-30", "2025-12-31", "2026-01-01T04:59:59Z"),
    ],
)
def test_following_month_end_clock_and_dst(day, end, proxy, expected):
    assert screen.clock(pd.Timestamp(day)) == (
        pd.Timestamp(end),
        pd.Timestamp(proxy),
        pd.Timestamp(expected),
    )


@pytest.mark.parametrize(
    "value,direction", [("-1", 1), ("0", 1), ("-0", 1), ("1", 0), ("1e-6", 0), ("-1E-6", 1)]
)
def test_exact_structural_zero_inclusive_boundary(value, direction):
    s = state([value] * 6)
    assert s.ready.all() and s.primary_direction.eq(direction).all()
    assert s.control_direction.eq(1).all()


@pytest.mark.parametrize("missing", ["", ".", "NA"])
def test_latest_missing_month_masks_both_arms_no_older_good_fallback(missing):
    s = state(["-1", missing, "-1", "-1", "-1", "-1"])
    assert s.ready.tolist() == [True, False, True, True, True, True]
    signals = screen.targets(active(pd.bdate_range("2020-01-02", "2020-01-10")), s, config())
    assert all(
        p.feature_unavailable.all() and p.target_weight.eq(0).all() for p in signals.values()
    )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-inf", "--1", "1,000", "word"])
def test_non_numeric_nonfinite_tokens_rejected(value):
    with pytest.raises(ValueError, match="invalid EBP token"):
        state([value] * 6)


def test_protected_availability_cells_excluded_before_token_inspection():
    cfg = config()
    cfg["source"].update(
        raw_start="2025-10-01",
        raw_end="2025-12-31",
        expected_raw_reports=3,
        expected_eligible_reports=1,
    )
    rows = table(cfg, ["-1", "DO_NOT_READ_NOV", "DO_NOT_READ_DEC"])
    result = screen.records(raw(rows), cfg, numeric=True)
    assert len(result) == 1 and result[0]["ebp"] == "-1"


def test_raw_other_dates_and_2026_cells_not_inspected():
    rows = table()
    rows.insert(0, {**rows[0], "date": "1/1/1973", "ebp": "DO_NOT_READ_OLD"})
    rows.append({**rows[-1], "date": "1/1/2026", "ebp": "DO_NOT_READ_2026"})
    result = screen.records(raw(rows), config(), numeric=True)
    assert len(result) == 6


@pytest.mark.parametrize(
    "kind", ["duplicate", "missing", "unordered", "not_first_day", "bad_month", "ISO", "header"]
)
def test_calendar_and_schema_fail_closed(kind):
    rows = table()
    if kind == "duplicate":
        rows.insert(0, rows[0])
    elif kind == "missing":
        rows.pop(2)
    elif kind == "unordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif kind == "not_first_day":
        rows[0]["date"] = "10/2/2019"
    elif kind == "bad_month":
        rows[0]["date"] = "13/1/2019"
    elif kind == "ISO":
        rows[0]["date"] = "2019-10-01"
    content = raw(rows)
    if kind == "header":
        content = content.replace(b"date,gz_spread,ebp,est_prob", b"date,gz_spread,OTHER,est_prob")
    with pytest.raises(ValueError):
        screen.records(content, config(), numeric=True)


def test_future_value_change_preserves_prior_states():
    original = state()
    values = ["-1"] * 5 + ["10"]
    pd.testing.assert_frame_equal(state(values).iloc[:-1], original.iloc[:-1])


def test_next_open_missing_plan_stale_source_and_terminal_flat():
    cfg = config()
    p = screen.targets(active(pd.bdate_range("2019-11-28", "2019-12-05")), state(), cfg)["primary"]
    assert p.loc[p.effective_date.eq("2019-12-02"), "target_weight"].iloc[0] == 0
    assert p.loc[p.effective_date.eq("2019-12-03"), "target_weight"].iloc[0] == 0.9
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    missing = screen.targets(active().assign(plan_tradable=False), state(), cfg)
    assert all(s.target_weight.eq(0).all() for s in missing.values())
    stale = screen.targets(active(pd.bdate_range("2020-09-01", "2020-09-08")), state(), cfg)
    assert all(s.stale_at_fill.all() for s in stale.values())


def test_unchanged_flat_price_ledger_costs_and_cash_replay(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2019-11-28", "2019-12-05")), state(), cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": d,
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
            for d in signals["primary"].effective_date
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
        for m in costs.values():
            assert m["execution_complete"] and m["round_trips"] == 1
            assert m["gross_vm_pnl"] == pytest.approx(0)
            assert m["net_pnl"] == pytest.approx(-m["total_cost"])
        assert costs["double"]["net_pnl"] < costs["base"]["net_pnl"] < 0


def test_source_manifest_drift_before_numeric_read(tmp_path):
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="source manifest drift"):
        screen.source(cfg, tmp_path)
