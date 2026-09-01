"""Synthetic tests for the official Bank of Russia macro-survey source."""

from __future__ import annotations

import json
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

from market_lab.futures import cbr_macro_survey_source as source

SURVEY_MONTHS = (
    date(2021, 5, 1),
    date(2022, 2, 1),
    date(2023, 2, 1),
    date(2024, 2, 1),
    date(2025, 12, 1),
)


def _serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


def _cell(reference: str, value: str | float | int) -> str:
    if isinstance(value, str):
        return f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    return f'<c r="{reference}"><v>{value}</v></c>'


def _sheet(spec: source.IndicatorSpec) -> bytes:
    first_column = 5 if spec.forecast_periods else 4
    cells = [_cell("B5", f"{spec.english_name}\nsynthetic unit")]
    for offset, month in enumerate(SURVEY_MONTHS):
        column = source._column_label(first_column + offset)
        cells.extend(
            [
                _cell(f"{column}6", _serial(month)),
                _cell(f"{column}7", month.strftime("%B %Y")),
            ]
        )
    if spec.forecast_periods:
        cells.extend([_cell("C8", "Median"), _cell("D8", _serial(date(2026, 12, 31)))])
        cells.extend([_cell("C9", "Average"), _cell("D9", _serial(date(2026, 12, 31)))])
        for offset, _month in enumerate(SURVEY_MONTHS):
            column = source._column_label(first_column + offset)
            cells.append(_cell(f"{column}8", float(int(spec.sheet) + offset)))
            cells.append(_cell(f"{column}9", float(int(spec.sheet) + offset) + 0.25))
    else:
        cells.extend([_cell("C8", "Median"), _cell("C9", "Average")])
        for offset, _month in enumerate(SURVEY_MONTHS):
            column = source._column_label(first_column + offset)
            cells.append(_cell(f"{column}8", float(int(spec.sheet) + offset)))
            cells.append(_cell(f"{column}9", float(int(spec.sheet) + offset) + 0.25))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData><row>{''.join(cells)}</row></sheetData></worksheet>"
    ).encode()


def _workbook(
    specs: tuple[source.IndicatorSpec, ...] = source.INDICATOR_SPECS,
) -> bytes:
    output = BytesIO()
    sheets = "".join(
        (
            f'<sheet name="{escape(spec.sheet)}" sheetId="{index}" '
            f'r:id="rId{index}"/>'
        )
        for index, spec in enumerate(specs, start=1)
    )
    relationships = "".join(
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
        for index, _spec in enumerate(specs, start=1)
    )
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
                f'relationships"><sheets>{sheets}</sheets></workbook>'
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                f'relationships">{relationships}</Relationships>'
            ),
        )
        for index, spec in enumerate(specs, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet(spec))
    return output.getvalue()


def test_page_parser_requires_the_expected_official_workbook() -> None:
    page = (
        b'<html><a href="/Content/Document/File/144490/full.xlsx">'
        b"Aggregated survey results</a></html>"
    )
    assert source.workbook_url_from_page(page) == source.WORKBOOK_URL

    with pytest.raises(ValueError, match="CBR"):
        source.workbook_url_from_page(
            b'<html><a href="https://example.com/full.xlsx">bad</a></html>'
        )


def test_conservative_availability_is_end_of_following_moscow_month() -> None:
    assert source.conservative_available_at(date(2021, 5, 1)) == pd.Timestamp(
        "2021-06-30T20:59:59Z"
    )
    assert source.conservative_available_at(date(2025, 12, 1)) == pd.Timestamp(
        "2026-01-31T20:59:59Z"
    )


def test_workbook_parser_builds_tidy_non_missing_current_vintage_records() -> None:
    frame = source.parse_macro_survey_workbook(
        _workbook(),
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert len(frame) == 170
    assert set(frame["indicator"]) == {spec.indicator for spec in source.INDICATOR_SPECS}
    assert set(frame["statistic"]) == {"median", "average"}
    assert frame["current_vintage"].all()
    fx = frame[
        frame["indicator"].eq("usd_rub_average")
        & frame["statistic"].eq("median")
        & frame["survey_month"].eq(pd.Timestamp("2021-05-01"))
    ].iloc[0]
    assert fx["forecast_period"] == pd.Timestamp("2026-12-31")
    assert fx["forecast_year"] == 2026
    assert fx["value"] == 11.0
    assert fx["source_cell"] == "E8"
    neutral = frame[
        frame["indicator"].eq("neutral_key_rate_pct")
        & frame["statistic"].eq("median")
        & frame["survey_month"].eq(pd.Timestamp("2025-12-01"))
    ].iloc[0]
    assert pd.isna(neutral["forecast_period"])
    assert pd.isna(neutral["forecast_year"])
    assert neutral["value"] == 20.0


def test_workbook_parser_fails_closed_on_missing_sheet_or_title_drift() -> None:
    with pytest.raises(ValueError, match="misses required sheets"):
        source.parse_macro_survey_workbook(
            _workbook(source.INDICATOR_SPECS[:-1]),
            retrieved_at_utc="2026-09-01T00:00:00Z",
        )

    wrong = source.IndicatorSpec("1", "wrong", "Unexpected title", "unit")
    with pytest.raises(ValueError, match="title mismatch"):
        source.parse_macro_survey_workbook(
            _workbook((source.INDICATOR_SPECS[0],)),
            retrieved_at_utc="2026-09-01T00:00:00Z",
            indicator_specs=(wrong,),
        )


class FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type, "ETag": '"synthetic"'}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, workbook: bytes) -> None:
        self.workbook = workbook
        self.requested: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: object,
        timeout: float,
    ) -> FakeResponse:
        del headers
        assert timeout == 60.0
        self.requested.append(url)
        if url == source.SOURCE_URL:
            return FakeResponse(
                (
                    b'<html><a href="/Content/Document/File/144490/full.xlsx">'
                    b"Aggregated survey results</a></html>"
                ),
                "text/html; charset=utf-8",
            )
        if url == source.WORKBOOK_URL:
            return FakeResponse(
                self.workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        raise AssertionError(url)


def test_download_writes_hashed_immutable_target_free_bundle(tmp_path: Path) -> None:
    output = tmp_path / "cbr-macro-survey-fixture-v1"
    session = FakeSession(_workbook())

    result = source.download_cbr_macro_survey(
        output,
        session=session,
        fetched_at_utc="2026-09-01T00:00:00Z",
        minimum_records=1,
    )

    assert result == output.resolve()
    assert session.requested == [source.SOURCE_URL, source.WORKBOOK_URL]
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["coverage"]["records"] == 170
    assert manifest["coverage"]["survey_months"] == 5
    assert manifest["coverage"]["survey_months_available_before_protected_boundary"] == 4
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"] is False
    assert manifest["temporal_semantics"]["missing_workbook_cells_are_not_zero"] is True
    assert source.sha256_file(result / manifest["artifacts"]["processed"]["path"]) == (
        manifest["artifacts"]["processed"]["sha256"]
    )
    assert (result / "official_cbr_macro_survey_current_vintage.xlsx").read_bytes().startswith(
        b"PK"
    )
    with pytest.raises(FileExistsError):
        source.download_cbr_macro_survey(
            output,
            session=session,
            fetched_at_utc="2026-09-01T00:00:00Z",
            minimum_records=1,
        )
