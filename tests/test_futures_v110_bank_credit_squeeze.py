"""Synthetic quarterly source, conditional clock, masks and unchanged cost ledger."""

import io
import zipfile
from xml.etree import ElementTree as ET

import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active

from market_lab import futures_v110_bank_credit_squeeze as screen


def config():
    cfg = screen.prior.read_json(screen.CONFIG)
    cfg["source"].update(raw_start="2019-10-01", raw_end="2020-12-31", expected_reports=5)
    return cfg


def raws(values=None):
    dates = pd.date_range("2019-10-01", "2020-10-01", freq="QS").strftime("%Y-%m-%d")
    values = {"DRTSCILM": ["10"] * 5, "DRSDCILM": ["-10"] * 5} if values is None else values
    return {
        s: (
            "observation_date,"
            + s
            + "\n"
            + "\n".join(d + "," + v for d, v in zip(dates, values[s], strict=True))
        ).encode()
        for s in screen.SERIES
    }


def state(values=None):
    return screen.states(screen.records(raws(values), config(), numeric=True))


def test_metadata_does_not_convert_numbers(monkeypatch):
    def forbidden(*args):
        raise AssertionError("premature numeric read")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    rows = screen.records(raws(), config())
    assert len(rows) == 5 and all("values" not in r for r in rows)


@pytest.mark.parametrize(
    "day,proxy,available",
    [
        ("2017-10-01", "2017-11-30", "2017-12-01T04:59:59Z"),
        ("2020-01-01", "2020-02-29", "2020-03-01T04:59:59Z"),
        ("2020-04-01", "2020-05-31", "2020-06-01T03:59:59Z"),
        ("2020-07-01", "2020-08-31", "2020-09-01T03:59:59Z"),
        ("2025-10-01", "2025-11-30", "2025-12-01T04:59:59Z"),
    ],
)
def test_quarter_label_is_not_release_clock(day, proxy, available):
    p, a = screen.clock(pd.Timestamp(day))
    assert p == pd.Timestamp(proxy) and a == pd.Timestamp(available)


@pytest.mark.parametrize(
    "standards,demand,expected",
    [
        ("1", "-1", -1),
        ("0", "-1", 0),
        ("1", "0", 0),
        ("-1", "-1", 0),
        ("1", "1", 0),
        ("-1", "1", 0),
        ("0", "0", 0),
    ],
)
def test_both_strict_economic_signs_required(standards, demand, expected):
    s = state({"DRTSCILM": [standards] * 5, "DRSDCILM": [demand] * 5})
    assert s.ready.all() and s.primary_direction.eq(expected).all()
    assert s.control_direction.eq(-1).all()


@pytest.mark.parametrize("series", screen.SERIES)
def test_missing_latest_quarter_masks_no_older_good_fallback(series):
    values = {"DRTSCILM": ["1"] * 5, "DRSDCILM": ["-1"] * 5}
    values[series][1] = "."
    s = state(values)
    assert s.ready.tolist() == [True, False, True, True, True]
    cfg = config()
    p = screen.targets(active(pd.bdate_range("2020-03-02", "2020-03-09")), s, cfg)["primary"]
    assert p.feature_unavailable.all() and p.target_weight.eq(0).all()


@pytest.mark.parametrize("token", ["", "nan", "inf", "1,000", "--1", "None"])
def test_malformed_tokens_fail_closed(token):
    raw = raws()
    raw["DRTSCILM"] = raw["DRTSCILM"].replace(b"2019-10-01,10", ("2019-10-01," + token).encode())
    with pytest.raises(ValueError):
        screen.records(raw, config(), numeric=True)


@pytest.mark.parametrize("value", ["-100.01", "100.01"])
def test_percent_bounds(value):
    with pytest.raises(ValueError, match="percent outside bounds"):
        state({"DRTSCILM": [value] * 5, "DRSDCILM": ["-10"] * 5})


@pytest.mark.parametrize("kind", ["duplicate", "missing", "future", "header", "unordered"])
def test_calendar_identity_before_numeric_values(kind):
    raw = raws()
    lines = raw["DRTSCILM"].decode().splitlines()
    if kind == "duplicate":
        lines.append(lines[-1])
    elif kind == "missing":
        lines.pop(2)
    elif kind == "future":
        lines[-1] = "2026-01-01,DO_NOT_PARSE"
    elif kind == "header":
        lines[0] = "date,OTHER"
    else:
        lines[1], lines[2] = lines[2], lines[1]
    raw["DRTSCILM"] = "\n".join(lines).encode()
    with pytest.raises(ValueError):
        screen.records(raw, config(), numeric=True)


def test_future_change_cannot_change_earlier_state():
    values = {"DRTSCILM": ["10"] * 5, "DRSDCILM": ["-10"] * 5}
    values["DRTSCILM"][-1] = "-99"
    pd.testing.assert_frame_equal(state(values).iloc[:-1], state().iloc[:-1])


def test_next_open_proxy_ttl_missing_plan_and_terminal():
    cfg = config()
    p = screen.targets(active(pd.bdate_range("2019-11-28", "2019-12-05")), state(), cfg)["primary"]
    assert p.loc[p.effective_date.eq("2019-12-02"), "target_weight"].iloc[0] == 0
    assert p.loc[p.effective_date.eq("2019-12-03"), "target_weight"].iloc[0] == -0.9
    assert p.iloc[-1].terminal_flat and p.iloc[-1].target_weight == 0
    masked = screen.targets(active().assign(plan_tradable=False), state(), cfg)
    assert all(s.target_weight.eq(0).all() for s in masked.values())
    stale = screen.targets(active(pd.bdate_range("2021-05-03", "2021-05-10")), state(), cfg)
    assert all(s.stale_at_fill.all() for s in stale.values())


def test_unchanged_flat_price_ledger_double_costs_and_cash_replay(tmp_path):
    cfg = config()
    signals = screen.targets(active(pd.bdate_range("2019-11-28", "2019-12-05")), state(), cfg)
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


def test_manifest_drift_precedes_source_value_read(tmp_path):
    cfg = config()
    root = tmp_path / cfg["source"]["root"]
    root.mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="source manifest drift"):
        screen.source(cfg, tmp_path)


def xml_tree():
    root = ET.Element("{test}MessageGroup")
    dataset = ET.SubElement(root, "{test}DataSet", id="SLOOS")
    for series, name in screen.XML_SERIES.items():
        e = ET.SubElement(
            dataset,
            "{test}Series",
            {
                **screen.XML_ATTRIBUTES,
                "SERIES_NAME": name,
                "MEASURE": "STND" if series == "DRTSCILM" else "DEMAND",
            },
        )
        for day in pd.date_range("2019-12-31", "2020-12-31", freq="QE"):
            ET.SubElement(
                e,
                "{test}Obs",
                {
                    "TIME_PERIOD": str(day.date()),
                    "OBS_STATUS": "A",
                    "OBS_VALUE": "10" if series == "DRTSCILM" else "-10",
                },
            )
    return root


def xml_zip(root):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("SLOOS_data.xml", ET.tostring(root))
    return out.getvalue()


def test_xml_exact_series_quarter_end_mapping_and_no_premature_conversion(monkeypatch):
    def forbidden(*args):
        raise AssertionError("premature values")

    monkeypatch.setattr(screen, "Decimal", forbidden)
    rows = screen.xml_records(xml_zip(xml_tree()), config())
    assert len(rows) == 5 and all("values" not in r for r in rows)
    assert rows[0]["observation_date"] == pd.Timestamp("2019-10-01")
    assert rows[0]["xml_quarter_end_label"] == pd.Timestamp("2019-12-31")
    assert rows[0]["source_date"] == pd.Timestamp("2019-11-30")


def test_other_series_and_protected_cells_not_inspected():
    root = xml_tree()
    for e in list(root[0]):
        ET.SubElement(e, "{test}Obs", {"TIME_PERIOD": "2026-03-31", "UNKNOWN": "BAD_VALUE"})
    other = ET.SubElement(root[0], "{test}Series", SERIES_NAME="OTHER")
    ET.SubElement(other, "{test}Obs", {"TIME_PERIOD": "BAD_DATE", "OBS_VALUE": "DO_NOT_READ"})
    rows = screen.xml_records(xml_zip(root), config(), numeric=True)
    assert screen.states(rows).primary_direction.eq(-1).all()


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate_series",
        "bank_group",
        "status",
        "quarter",
        "duplicate_quarter",
        "missing_quarter",
        "token",
    ],
)
def test_xml_schema_and_calendar_fail_closed(kind):
    root = xml_tree()
    e = root[0][0]
    if kind == "duplicate_series":
        root[0].append(e)
    elif kind == "bank_group":
        e.set("BANKSIZE", "LG")
    elif kind == "status":
        e[0].set("OBS_STATUS", "UNKNOWN")
    elif kind == "quarter":
        e[0].set("TIME_PERIOD", "2019-12-30")
    elif kind == "duplicate_quarter":
        e.append(e[0])
    elif kind == "missing_quarter":
        e.remove(e[0])
    else:
        e[0].set("OBS_VALUE", "nan")
    with pytest.raises(ValueError):
        screen.xml_records(xml_zip(root), config(), numeric=True)
