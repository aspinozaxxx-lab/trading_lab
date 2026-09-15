"""Synthetic metadata-only source checks."""

import io
import json

import pandas as pd
import pytest

from market_lab.futures import gpr_vintages_source_v1 as m


def data(months):
    target = io.BytesIO()
    pd.DataFrame({"month": pd.to_datetime(months), "GPRC_RUS": [123.0] * len(months)}).to_stata(
        target, write_index=False, convert_dates={"month": "tm"}, version=118,
        variable_labels={"GPRC_RUS": "Geopolitical Risk Russia"})
    return target.getvalue()


def test_plan_and_request_bounds():
    assert len(m.plan()) == len(set(m.plan())) == 46
    assert m.plan()[:3] == ["202203", "202401", "202512"]
    for month in ("202202", "202601", "bad"):
        with pytest.raises(ValueError):
            m.history_url(month)
    with pytest.raises(ValueError):
        m.raw_url("202203", "main")
    assert "/" + "a" * 40 + "/" in m.raw_url("202203", "a" * 40)


def test_metadata_projects_only_calendar_labels():
    months = pd.date_range("2021-02-01", "2022-03-01", freq="MS")
    result = m.metadata(data(months), "202203")
    assert result["complete_prior13_month_calendar"]
    assert result["russia_variable_candidates"] == ["GPRC_RUS"]
    assert result["numeric_gpr_values_read_for_design"] is False
    assert "123" not in json.dumps(result)


@pytest.mark.parametrize("months", [["2026-01-01"], ["2022-04-01"],
                                   ["2021-01-01", "2021-01-01"],
                                   ["2021-02-01", "2021-01-01"]])
def test_bad_dates(months):
    with pytest.raises(ValueError):
        m.metadata(data(months), "202203")


def test_calendar_missing_month_not_zero_fill():
    result = m.metadata(data(["2021-01-01", "2022-02-01"]), "202203")
    assert not result["complete_prior13_month_calendar"]


def test_oldest_commit_max_clock_and_history_count():
    rows = [{"sha": "a" * 40, "commit": {
        "author": {"date": "2024-01-01T00:00:00Z"},
        "committer": {"date": "2024-01-02T00:00:00Z"}}},
        {"sha": "b" * 40, "commit": {
            "author": {"date": "2022-03-02T00:00:00Z"},
            "committer": {"date": "2022-03-01T00:00:00Z"}}}]
    result = m.first_commit(json.dumps(rows).encode())
    assert result["commit"] == "b" * 40
    assert result["commit_timestamp_proxy"].startswith("2022-03-02")
    assert not result["actual_public_push_time_verified"]
    for bad in ([], rows * 50, {}):
        with pytest.raises(ValueError):
            m.first_commit(json.dumps(bad).encode())
