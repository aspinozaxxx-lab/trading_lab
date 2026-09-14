"""Synthetic workbook reconciliation and causal weekly-rig target tests."""

import json
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v74_baker_rig_supply as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def rigs():
    days = pd.date_range("2017-08-04", periods=30, freq="W-FRI")
    return pd.DataFrame({"source_date": days, "oil_rigs": np.arange(100, 130)})


def sheet_xml(rows):
    root = ET.Element(screen.NS + "worksheet")
    data = ET.SubElement(root, screen.NS + "sheetData")
    for number, values in rows.items():
        row = ET.SubElement(data, screen.NS + "row", r=str(number))
        for column, value in values.items():
            cell = ET.SubElement(row, screen.NS + "c", r=column + str(number))
            if isinstance(value, str):
                cell.set("t", "inlineStr")
                ET.SubElement(ET.SubElement(cell, screen.NS + "is"), screen.NS + "t").text = value
            elif value is not None:
                ET.SubElement(cell, screen.NS + "v").text = str(value)
    return ET.tostring(root)


def workbook(tmp_path, fault=None):
    path = tmp_path / "synthetic.xlsx"
    days = pd.date_range("2017-08-04", periods=16, freq="W-FRI")
    rows = {11: {chr(65 + j): value for j, value in enumerate(screen.HEADERS)}}
    number = 12
    for i, day in enumerate(days):
        serial = (day - pd.Timestamp("1899-12-30")).days
        for country, drill, count in [
            ("UNITED STATES", "Oil", 100 + i),
            ("UNITED STATES", "Gas", 20),
            ("CANADA", "Oil", 10),
        ]:
            values = [
                country,
                "County",
                "Basin",
                "No",
                drill,
                "Land",
                "State",
                "Horizontal",
                day.year,
                day.month,
                serial,
                count,
            ]
            rows[number] = {chr(65 + j): value for j, value in enumerate(values)}
            number += 1
    summary = {
        4: {"D": serial},
        11: {"B": "United States Total", "D": 135},
        22: {"B": "Oil", "D": 115},
    }
    if fault == "duplicate":
        rows[number] = rows[12].copy()
    elif fault == "missing":
        rows[12]["L"] = None
    elif fault == "negative":
        rows[12]["L"] = -1
    elif fault == "protected":
        rows[12]["K"] = (pd.Timestamp("2026-01-02") - pd.Timestamp("1899-12-30")).days
    elif fault == "period":
        rows[12]["J"] = 1
    elif fault == "summary":
        summary[22]["D"] += 1
    elif fault == "header":
        rows[11]["K"] = "ObservationDate"
    elif fault == "county":
        rows[14]["B"] = None
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="'
            + screen.NS[1:-1]
            + '" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="NAM Weekly" r:id="rId1"/>'
            '<sheet name="NAM Summary" r:id="rId2"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        archive.writestr("xl/sharedStrings.xml", '<sst xmlns="' + screen.NS[1:-1] + '"/>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(rows))
        archive.writestr("xl/worksheets/sheet2.xml", sheet_xml(summary))
    return path


def test_workbook_groups_dates_units_and_summary_reconcile(tmp_path):
    result, quality = screen.read_rigs(workbook(tmp_path))
    assert quality["all_true"] and quality["raw_subgroup_rows"] == 48
    assert len(result) == 16 and result.iloc[-1].oil_rigs == 115
    assert result.iloc[-1].total_us_rigs == 135 and result.oil_source_rows.eq(1).all()
    assert not quality["original_vintages_proved"]


@pytest.mark.parametrize(
    "fault", ["missing", "negative", "protected", "period", "summary", "header"]
)
def test_bad_source_fail_closed_before_market(tmp_path, fault):
    with pytest.raises(ValueError):
        screen.read_rigs(workbook(tmp_path, fault))


def test_thirteen_release_changes_use_no_price_or_future_count():
    original = rigs()
    first = screen.states(original, config())
    assert not first.ready.iloc[:13].any() and first.ready.iloc[13:].all()
    assert first.primary_direction.iloc[13:].eq(-1).all()
    assert first.oil_rig_change.iloc[13:].eq(13).all()
    original.loc[25:, "oil_rigs"] = 1
    changed = screen.states(original, config())
    pd.testing.assert_frame_equal(first.iloc[:25], changed.iloc[:25])


def test_duplicate_subgroup_masks_entire_week_without_dedup_or_shorter_history(tmp_path):
    result, quality = screen.read_rigs(workbook(tmp_path, "duplicate"))
    assert quality["raw_subgroup_rows"] == 49
    assert quality["duplicate_subgroup_records"] == quality["ambiguous_weekly_dates"] == 1
    assert result.iloc[0].ambiguous_week and pd.isna(result.iloc[0].oil_rigs)
    assert pd.isna(result.iloc[0].total_us_rigs)
    state = screen.states(result, config())
    assert not state.ready.iloc[:14].any() and state.ready.iloc[14:].all()


def test_ambiguous_intermediate_count_masks_full_lookback_without_zero_fill():
    original = rigs()
    original["ambiguous_week"] = False
    original.loc[14, ["oil_rigs", "ambiguous_week"]] = [np.nan, True]
    state = screen.states(original, config())
    assert state.ready.iloc[13]
    assert not state.ready.iloc[14:28].any() and state.ready.iloc[28:].all()


@pytest.mark.parametrize("count", [0, 100])
def test_zero_change_is_flat_not_unknown_and_control_stays_long(count):
    original = rigs()
    original["oil_rigs"] = count
    state = screen.states(original, config())
    assert state.primary_direction.eq(0).all()
    assert state.control_direction.iloc[13:].eq(1).all()


def test_missing_optional_county_keeps_typed_count_and_original_blank(tmp_path):
    result, quality = screen.read_rigs(workbook(tmp_path, "county"))
    assert quality["missing_county_rows"] == 1 and quality["raw_subgroup_rows"] == 48
    assert not result.ambiguous_week.any() and result.iloc[0].oil_rigs == 100


def test_missing_week_does_not_shorten_thirteen_release_history():
    state = screen.states(rigs().drop(index=14), config())
    assert state.ready.iloc[13] and not state.ready.iloc[14:27].any()
    assert state.ready.iloc[27:].all()


@pytest.mark.parametrize(
    "day,expected", [("2017-08-04", "2017-08-05T04:59:59Z"), ("2017-12-01", "2017-12-02T05:59:59Z")]
)
def test_chicago_end_of_release_day_includes_dst(day, expected):
    state = screen.states(
        pd.DataFrame({"source_date": [pd.Timestamp(day)], "oil_rigs": [100]}), config()
    )
    assert state.iloc[0].available_at_utc == pd.Timestamp(expected)


def test_holiday_publication_shift_is_not_imputed():
    original = rigs()
    original.loc[14, "source_date"] -= pd.Timedelta(days=2)
    state = screen.states(original, config())
    assert state.ready.iloc[13:].all()
    assert state.source_date.iloc[14] == original.source_date.iloc[14]


def test_target_waits_for_completed_release_and_closes_stale_state():
    cfg = config()
    state = screen.states(rigs(), cfg)
    state = state.iloc[:14]
    days = pd.bdate_range("2017-11-02", "2017-11-24")
    active = pd.DataFrame(
        {
            "decision_date": days[:-1],
            "effective_date": days[1:],
            "observed_through": days[:-1],
            "asset_code": "BR",
            "contract_id": "BR_TEST",
            "plan_tradable": True,
            "roll": False,
        }
    )
    cfg["period"] = {"start": "2017-11-02", "end": "2017-11-24"}
    result = screen.adapter.targets(active, state, "primary", cfg)
    # Nov3 Chicago release is not known at Friday Moscow EOD; first decision Monday.
    assert result.loc[result.decision_date.le("2017-11-03"), "target_weight"].eq(0).all()
    assert result.loc[result.decision_date.eq("2017-11-06"), "target_weight"].iloc[0] == -1
    assert result.loc[result.effective_date.gt("2017-11-17"), "target_weight"].eq(0).all()
    used = result.loc[result.target_weight.ne(0)]
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert result.iloc[-1].terminal_flat


@pytest.mark.parametrize("fault", ["duplicate", "protected", "missing"])
def test_invalid_rig_state_dates_or_counts_fail_closed(fault):
    original = rigs()
    if fault == "duplicate":
        original = pd.concat([original, original.iloc[:1]])
    elif fault == "protected":
        original.loc[0, "source_date"] = pd.Timestamp("2026-01-01")
    else:
        original.loc[0, "oil_rigs"] = np.nan
    with pytest.raises(ValueError):
        screen.states(original, config())
