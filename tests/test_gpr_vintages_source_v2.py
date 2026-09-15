"""Synthetic undated-row masking with all dated scope checks intact."""

import pandas as pd
import pytest
from test_gpr_vintages_source_v1 import data

from market_lab.futures import gpr_vintages_source_v2 as m


def test_undated_raw_preserved_only_calendar_masked():
    months = list(pd.date_range("2021-02-01", "2022-03-01", freq="MS")) + [pd.NaT] * 3
    raw = data(months)
    result = m.metadata(raw, "202203")
    assert result["rows"] == 17 and result["dated_rows"] == 14
    assert result["undated_rows_preserved_not_used"] == 3
    assert result["complete_prior13_month_calendar"]
    assert not result["numeric_gpr_values_read_for_design"]


@pytest.mark.parametrize("months", [[pd.NaT], ["2026-01-01", pd.NaT],
                                   ["2022-04-01", pd.NaT],
                                   ["2021-01-01", "2021-01-01", pd.NaT],
                                   ["2021-02-01", "2021-01-01", pd.NaT]])
def test_missing_does_not_hide_bad_dated_rows(months):
    with pytest.raises(ValueError):
        m.metadata(data(months), "202203")


def test_dated_missing_months_stay_incomplete():
    result = m.metadata(data(["2021-01-01", pd.NaT, "2022-02-01"]), "202203")
    assert not result["complete_prior13_month_calendar"]
