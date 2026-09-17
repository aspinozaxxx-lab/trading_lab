"""Synthetic funding sums, calendar, publication clocks, masks and unchanged ledger."""

import copy
import json

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v109_private_deleveraging as screen


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["source"].update(
        raw_start="2022-01-05",
        raw_end="2022-02-23",
        expected_raw_reports=8,
        expected_eligible_reports=8,
    )
    return cfg


def table(cfg=None):
    cfg = config() if cfg is None else cfg
    spec = cfg["source"]
    rows = []
    for i, day in enumerate(pd.date_range(spec["raw_start"], spec["raw_end"], freq="W-WED")):
        cells = [{"keyId": key, "value": str(100 - i)} for key in spec["borrowing_keys"]]
        cells += [{"keyId": key, "value": str(200 - i)} for key in spec["lending_keys"]]
        rows.append({"_id": {"date": day.strftime("%Y-%m-%d")}, "values": cells})
    return {"data": rows[::-1]}


def raw(doc=None, cfg=None):
    return json.dumps(table(cfg) if doc is None else doc).encode()


def records(doc=None, cfg=None):
    cfg = config() if cfg is None else cfg
    return screen.records(raw(doc, cfg), cfg, numeric=True)


def state(doc=None, cfg=None):
    cfg = config() if cfg is None else cfg
    return screen.states(records(doc, cfg), cfg)


def test_metadata_does_not_convert_magnitudes(monkeypatch):
    def forbidden(*args):
        raise AssertionError("numeric conversion before seal")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    result = screen.records(raw(), config())
    assert len(result) == 8 and all(r["cells_complete"] for r in result)
    assert all("values" not in r for r in result)


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2022-02-02", "2022-02-13T04:59:59Z"),
        ("2022-03-02", "2022-03-13T04:59:59Z"),
        ("2022-03-09", "2022-03-20T03:59:59Z"),
        ("2025-12-17", "2025-12-28T04:59:59Z"),
        ("2025-12-24", "2026-01-04T04:59:59Z"),
    ],
)
def test_conditional_clock_dst_and_boundary(day, expected):
    assert screen.availability(pd.Timestamp(day), 10) == pd.Timestamp(expected)


def test_sum_six_buckets_each_side_and_exact_four_report_warmup():
    result = state()
    assert result.ready.tolist() == [False] * 4 + [True] * 4
    assert result.primary_direction.tolist() == [0.0] * 4 + [1.0] * 4
    assert result.iloc[4].borrowing_total == "576"
    assert result.iloc[4].lending_total == "1176"
    assert result.iloc[4].comparison_source_date == pd.Timestamp("2022-01-05")


@pytest.mark.parametrize("side", ["borrowing", "lending"])
@pytest.mark.parametrize("change", [0, 1])
def test_both_sides_must_strictly_contract(side, change):
    cfg = config()
    doc = table()
    keys = cfg["source"][side + "_keys"]
    initial = 100 if side == "borrowing" else 200
    for i, row in enumerate(reversed(doc["data"])):
        for cell in row["values"]:
            if cell["keyId"] in keys:
                cell["value"] = str(initial + i * change)
    result = state(doc)
    assert result.ready.iloc[4:].all() and result.primary_direction.eq(0).all()


@pytest.mark.parametrize("missing", ["null", "absent"])
def test_missing_cell_masks_full_five_report_window_no_good_fallback(missing):
    doc = table()
    rows = list(reversed(doc["data"]))
    if missing == "null":
        rows[3]["values"][0]["value"] = None
    else:
        rows[3]["values"].pop(0)
    result = state(doc)
    assert not result.ready.any() and result.primary_direction.eq(0).all()


def test_real_zero_allowed_but_zero_total_not_ready():
    doc = table()
    doc["data"][3]["values"][0]["value"] = "0"
    assert state(doc).iloc[4].ready
    for cell in doc["data"][3]["values"][:6]:
        cell["value"] = "0"
    assert not state(doc).iloc[4].ready


def test_schema_break_restarts_window_without_ever_using_other_era():
    cfg = config()
    cfg["source"]["schema_break"] = "2022-01-26"
    result = state(cfg=cfg)
    assert result.ready.tolist() == [False] * 7 + [True]


@pytest.mark.parametrize("bad", ["", "NaN", "Infinity", "1,000", "--1"])
def test_bad_token_rejected_before_economics(bad):
    doc = table()
    doc["data"][0]["values"][0]["value"] = bad
    with pytest.raises(ValueError, match="invalid financing token"):
        records(doc)


@pytest.mark.parametrize("bad", ["-1", "-0.01"])
def test_negative_amount_is_not_a_contraction_signal(bad):
    doc = table()
    doc["data"][0]["values"][0]["value"] = bad
    with pytest.raises(ValueError, match="nonfinite/negative"):
        state(doc)


def test_protected_available_cells_never_inspected():
    cfg = config()
    cfg["source"].update(
        raw_start="2025-12-17",
        raw_end="2025-12-31",
        expected_raw_reports=3,
        expected_eligible_reports=1,
    )
    doc = table(cfg)
    doc["data"][0]["values"] = "DO_NOT_INSPECT"
    doc["data"][1]["values"] = [{"unexpected": "NOT_A_NUMBER"}]
    result = records(doc, cfg)
    assert len(result) == 1 and result[0]["source_date"] == pd.Timestamp("2025-12-17")


def test_future_report_changes_cannot_change_prior_states():
    original = state()
    doc = table()
    for cell in doc["data"][0]["values"]:
        cell["value"] = "9000"
    pd.testing.assert_frame_equal(state(doc).iloc[:-1], original.iloc[:-1])


def test_duplicate_unknown_keys_and_missing_week_fail_closed():
    a = table()
    a["data"][0]["values"].append(copy.deepcopy(a["data"][0]["values"][0]))
    b = table()
    b["data"][0]["values"][0]["keyId"] = "OTHER_MARKET"
    for doc in (a, b):
        with pytest.raises(ValueError, match="duplicate/unknown key"):
            records(doc)
    a = table()
    a["data"].pop(3)
    with pytest.raises(ValueError, match="weekly calendar"):
        records(a)
    a = table()
    a["data"][0]["_id"]["date"] = "2026-01-07"
    with pytest.raises(ValueError, match="protected dates"):
        records(a)


def test_eod_next_open_missing_plan_stale_and_terminal():
    cfg = config()
    plan = active(pd.bdate_range("2022-02-10", "2022-02-18"))
    p = screen.targets(plan, state(), cfg)["primary"]
    assert p.loc[p.effective_date.eq("2022-02-14"), "target_weight"].iloc[0] == 0
    assert p.loc[p.effective_date.eq("2022-02-15"), "target_weight"].iloc[0] == 0.9
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    masked = screen.targets(plan.assign(plan_tradable=False), state(), cfg)
    assert all(frame.target_weight.eq(0).all() for frame in masked.values())
    stale = screen.targets(active(pd.bdate_range("2022-06-01", "2022-06-08")), state(), cfg)
    assert all(frame.stale_at_fill.all() for frame in stale.values())


def test_existing_ledger_flat_market_and_double_costs(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2022-02-10", "2022-02-18")), state(), cfg)
    market = pd.DataFrame(
        [
            {
                "session_date": day,
                "asset_code": "SI",
                "contract_id": "SITEST",
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


def test_source_manifest_drift_is_rejected_before_value_read(tmp_path):
    cfg = config()
    root = tmp_path / cfg["source"]["root"] / "capture"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="source manifest drift"):
        screen.source(cfg, tmp_path)
