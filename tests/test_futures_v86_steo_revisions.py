"""Synthetic forecast revisions, duplicate protection and conservative clocks."""

from decimal import Decimal
from xml.etree import ElementTree as ET

import pandas as pd
import pytest

from market_lab import futures_v86_steo_revisions as screen


def meta():
    return {"headers": {"C3": "2024", "C4": "Jan", "D4": "Feb", "E4": "Mar",
                         "F4": "Apr", "G4": "May", "H4": "Jun"},
            "series_rows": {"papr_world": [6, 10], "patc_world": [19]},
            "document_clocks_not_original_availability_proof": {
                "modified": "2024-01-05T12:00:00Z"}}


def cells(demand="101", supply="100"):
    out = {}
    for col in "CDEFGH":
        for row in (6, 10, 19):
            address = f"{col}{row}"
            value = demand if row == 19 else supply
            out[address] = ET.fromstring(f'<c xmlns="{screen.source.NS["s"]}" '
                                        f'r="{address}"><v>{value}</v></c>')
    return out


@pytest.mark.parametrize("edition,expected", [
    ("202401", ["2024-04", "2024-05", "2024-06"]),
    ("202403", ["2024-04", "2024-05", "2024-06"]),
    ("202404", ["2024-07", "2024-08", "2024-09"]),
    ("202510", ["2026-01", "2026-02", "2026-03"]),
])
def test_same_next_calendar_quarter_including_prepublished_future_forecast(edition, expected):
    assert screen.next_quarter(edition) == expected


def test_month_mapping_and_supply_demand_units():
    assert screen.monthly_columns(meta())["2024-06"] == "H"
    assert screen.deficit(meta(), cells(), screen.next_quarter("202401")) == (Decimal(1), "ready")


def test_same_horizon_revisions_do_not_use_current_quarter_values():
    c = cells()
    for row in (6, 10, 19):
        c[f"C{row}"].find("s:v", screen.source.NS).text = "never-read"
    assert screen.deficit(meta(), c, screen.next_quarter("202401"))[0] == 1


def test_duplicate_disagreement_is_not_selected_or_averaged():
    c = cells()
    c["F10"].find("s:v", screen.source.NS).text = "99"
    assert screen.deficit(meta(), c, screen.next_quarter("202401")) == (
        None, "duplicated_world_series_disagree")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "", "missing"])
def test_missing_invalid_values_do_not_become_zero(value):
    assert screen.deficit(meta(), cells(demand=value), screen.next_quarter("202401"))[0] is None


def test_absent_quarter_does_not_shift_horizon():
    assert screen.deficit(meta(), cells(), screen.next_quarter("202404")) == (
        None, "quarter_not_covered")


def item():
    return {"release_date": "2024-01-09", "notice_url": None, "metadata": meta()}


def test_availability_is_release_eod_new_york_not_issue_month():
    clock, reason = screen.availability(item(), None)
    assert reason == "ready" and clock == pd.Timestamp("2024-01-10T04:59:59.999999999Z")


def test_notice_and_last_modification_delay_values():
    i = item()
    i["notice_url"] = "https://example.invalid/notice"
    i["metadata"]["document_clocks_not_original_availability_proof"]["modified"] = (
        "2024-01-20T12:00:00Z")
    assert screen.availability(i, b"<p>Released: January 18, 2024</p>")[0] == pd.Timestamp(
        "2024-01-21T04:59:59.999999999Z")


def test_current_2026_header_not_used_as_notice_release():
    i = item()
    i["notice_url"] = "https://example.invalid/notice"
    raw = b"Release Date: September 9, 2026<p>Released: January 18, 2024</p>"
    assert screen.availability(i, raw)[0] == pd.Timestamp("2024-01-19T04:59:59.999999999Z")


@pytest.mark.parametrize("change", ["missing", "naive", "2026"])
def test_unprovable_clock_does_not_get_earlier_lag(change):
    i = item()
    clocks = i["metadata"]["document_clocks_not_original_availability_proof"]
    choices = {"missing": None, "naive": "2024-01-05", "2026": "2026-01-01T00:00Z"}
    clocks["modified"] = choices[change]
    assert screen.availability(i, None)[0] is None


def test_unknown_notice_is_masked():
    i = item()
    i["notice_url"] = "https://example.invalid/notice"
    assert screen.availability(i, b"No explicit release timestamp")[0] is None
