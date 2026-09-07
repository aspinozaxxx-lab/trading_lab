"""Synthetic target-free fixtures only."""

import copy
import json

import pytest

from market_lab.futures import algopack_fo_witnessed_core_v1 as core


def encode(value):
    return json.dumps(value).encode()


def discovery():
    rfud, series = [], []
    for asset, alias in core.ASSETS.items():
        for month, expiry in (("U", "2026-09-17"), ("Z", "2026-12-17"), ("H", "2027-03-18")):
            secid = core.PREFIXES[asset] + month + ("7" if month == "H" else "6")
            rfud.append([secid, "RFUD", alias, "futures", expiry, expiry])
            series.append([secid, "2026-01-01", expiry, alias, 1])
    return ({"securities": {"columns": core.RFUD_COLUMNS, "data": rfud}},
            {"series": {"columns": core.SERIES_COLUMNS, "data": series}})


def job(dataset="tradestats"):
    return {"dataset": dataset, "asset_code": "SI", "secid": "SiU6",
            "from": "2026-09-05", "till": "2026-09-21"}


def page(dataset="tradestats", index=0, total=1):
    values = ["2026-09-07", "10:00:00", "SiU6", "Si", "2026-09-07 10:01:00"]
    values += [1] * len(core.FIELDS[dataset])
    return {"data": {"columns": core.COMMON + core.FIELDS[dataset],
                     "data": [values] if total else []},
            "data.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"],
                            "data": [[index, total, 1]]}}


def test_discovery_sorted_without_prices():
    rfud, series = discovery()
    result = core.select_contracts(encode(rfud), encode(series), "2026-09-07")
    assert len(result) == 8
    assert [row["secid"] for row in result] == [
        "BRU6", "BRZ6", "MXU6", "MXZ6", "RIU6", "RIZ6", "SiU6", "SiZ6"]
    expiry = core.select_contracts(encode(rfud), encode(series), "2026-09-17")
    assert expiry[0]["secid"] == "BRZ6"


@pytest.mark.parametrize("defect", ["duplicate", "missing", "alias", "extra", "date", "flag",
                                   "expiry", "board", "null", "schema"])
def test_discovery_fail_closed(defect):
    rfud, series = discovery()
    if defect == "duplicate":
        rfud["securities"]["data"].append(rfud["securities"]["data"][0])
    elif defect == "missing":
        series["series"]["data"].pop(0)
    elif defect == "alias":
        rfud["securities"]["data"][0][2] = "WRONG"
    elif defect == "extra":
        rfud["marketdata"] = {}
    elif defect == "date":
        rfud["securities"]["data"][0][4] = "2026-9-17"
    elif defect == "flag":
        series["series"]["data"][0][-1] = True
    elif defect == "expiry":
        series["series"]["data"][0][2] = "2025-01-01"
    elif defect == "board":
        rfud["securities"]["data"][0][1] = "OTHER"
    elif defect == "null":
        rfud["securities"]["data"][0][-1] = None
    else:
        rfud["securities"]["columns"] = list(reversed(core.RFUD_COLUMNS))
    with pytest.raises(ValueError, match="invalid witnessed contract discovery"):
        core.select_contracts(encode(rfud), encode(series), "2026-09-07")


def test_perpetual_and_spread_excluded():
    rfud, series = discovery()
    for secid in ("SiF", "SiU6-SiZ6", "OTHER"):
        rfud["securities"]["data"].append([secid, "RFUD", "Si", None, None, None])
        series["series"]["data"].append([secid, None, None, None, None])
    assert len(core.select_contracts(encode(rfud), encode(series), "2026-09-07")) == 8


@pytest.mark.parametrize("dataset", core.FIELDS)
def test_parse_and_empty(dataset):
    rows, cursor = core.parse_page(encode(page(dataset)), job(dataset), 0)
    assert len(rows) == cursor["TOTAL"] == 1
    assert core.row_key(rows[0]) == (dataset, "SI", "SiU6", "2026-09-07", "10:00:00")
    assert core.parse_page(encode(page(dataset, total=0)), job(dataset), 0)[0] == []


def test_future_trading_date_not_publication_or_event_clock():
    value = page()
    value["data"]["data"][0][0] = "2026-09-14"
    rows, _ = core.parse_page(encode(value), job(), 0)
    assert rows[0]["SYSTIME"] == "2026-09-07 10:01:00"
    assert "available_at" not in rows[0]


@pytest.mark.parametrize("value", [None, "", "WRONG"])
def test_asset_masks(value):
    payload = page()
    payload["data"]["data"][0][3] = value
    rows, _ = core.parse_page(encode(payload), job(), 0)
    assert rows[0]["asset_code_missing"] == (value in (None, ""))
    assert rows[0]["asset_code_mismatch"] == (value == "WRONG")


@pytest.mark.parametrize("value", [None, 0, -1])
def test_spread_missing_zero_negative_preserved(value):
    payload = page("obstats")
    payload["data"]["data"][0][5] = value
    assert core.parse_page(encode(payload), job("obstats"), 0)[0][0]["spread_l1"] == value


@pytest.mark.parametrize("defect", ["extra", "schema", "cursor", "width", "contract", "date",
                                   "clock", "system", "negative", "fraction", "bool", "nan"])
def test_flow_fail_closed(defect):
    payload = copy.deepcopy(page())
    row = payload["data"]["data"][0]
    if defect == "extra":
        payload["marketdata"] = {}
    elif defect == "schema":
        payload["data"]["columns"].append("close")
    elif defect == "cursor":
        payload["data.cursor"]["data"][0][0] = 1
    elif defect == "width":
        row.pop()
    elif defect == "contract":
        row[2] = "SiZ6"
    elif defect == "date":
        row[0] = "2026-09-01"
    elif defect == "clock":
        row[1] = "1:00:00"
    elif defect == "system":
        row[4] = "2026-09-07T10:01:00+00:00"
    else:
        row[5] = {"negative": -1, "fraction": 1.5, "bool": True, "nan": float("nan")}[defect]
    with pytest.raises(ValueError, match="invalid witnessed source response"):
        core.parse_page(encode(payload), job(), 0)


@pytest.mark.parametrize("secid", ["../SiU6", "SiU6?token=x", "SiF", "RIU6", None])
def test_no_path_or_asset_escape(secid):
    value = job()
    value["secid"] = secid
    with pytest.raises(ValueError):
        core.flow_url(value, 0)


def test_duplicate_json_key():
    with pytest.raises(ValueError):
        core.parse_page(b'{"data":{},"data":{}}', job(), 0)
