"""Synthetic tests for the CBR inflation-expectations source collector."""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import cbr_inflation_expectations_source as source


def _minimal_xlsx(
    release_month: date,
    *,
    observed: float,
    expected: float,
    sentiment: float,
) -> bytes:
    def inline_cell(reference: str, value: str) -> str:
        return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'

    def number_cell(reference: str, value: float) -> str:
        return f'<c r="{reference}"><v>{value}</v></c>'

    month = release_month.isoformat()
    rows = [
        (
            '<row r="1">'
            f'{inline_cell("A1", "Прямые оценки годовой инфляции: медианные значения")}'
            "</row>"
        ),
        f'<row r="2">{inline_cell("B2", month)}</row>',
        (
            f'<row r="3">{inline_cell("A3", "наблюдаемая инфляция")}'
            f'{number_cell("B3", observed)}</row>'
        ),
        (
            f'<row r="4">{inline_cell("A4", "ожидаемая инфляция")}'
            f'{number_cell("B4", expected)}</row>'
        ),
        f'<row r="6">{inline_cell("A6", "Индекс потребительских настроений (ИПН)")}</row>',
        f'<row r="7">{inline_cell("B7", month)}</row>',
        f'<row r="8">{number_cell("B8", sentiment)}</row>',
    ]
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:B8"/><sheetData>{"".join(rows)}</sheetData></worksheet>'
    )
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Данные для графиков" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def _release_page(
    release_month: date,
    *,
    publication_text: str,
    updated_text: str,
    file_id: int,
    expected: float,
    observed: float,
) -> bytes:
    categories = [
        {
            "name": str(release_month.year),
            "categories": [
                date(release_month.year, month, 1).isoformat() for month in range(1, 13)
            ],
        }
    ]
    expected_data: list[float | None] = [None] * 12
    observed_data: list[float | None] = [None] * 12
    expected_data[release_month.month - 1] = expected
    observed_data[release_month.month - 1] = observed
    settings = {
        "xAxis": {"categories": categories},
        "series": [
            {
                "id": "s0",
                "name": "Ожидаемая населением инфляция",
                "data": expected_data,
            },
            {
                "id": "s1",
                "name": "Наблюдаемая населением инфляция",
                "data": observed_data,
            },
            {"id": "s2", "name": "Годовая инфляция", "data": [None] * 12},
        ],
    }
    key = f"{release_month.year % 100:02d}-{release_month.month:02d}"
    pdf = f"/Collection/Collection/File/{file_id}/Infl_exp_{key}.pdf"
    xlsx = f"/Collection/Collection/File/{file_id + 100}/stat_Infl_exp_{key}.xlsx"
    return (
        "<html><body>"
        f'<div class="news-info-line_date">{publication_text}</div>'
        f'<div id="GrafChart_ChartGroupModel_Charts_0__chart"></div>'
        f"<script>var settings = {json.dumps(settings, ensure_ascii=False)};</script>"
        f'<a href="{pdf}">PDF</a><a href="{xlsx}">XLSX</a>'
        f"<footer>Последнее обновление страницы: {updated_text}</footer>"
        "</body></html>"
    ).encode()


def _archive(releases: list[tuple[date, int]]) -> bytes:
    links: list[str] = []
    for release_month, file_id in releases:
        key = f"{release_month.year % 100:02d}-{release_month.month:02d}"
        links.append(
            f'<a href="/analytics/dkp/inflationary_expectations/Infl_exp_{key}/">page</a>'
        )
        links.append(
            f'<a href="/Collection/Collection/File/{file_id + 100}/'
            f'stat_Infl_exp_{key}.xlsx">xlsx</a>'
        )
    return "".join(links).encode()


def test_archive_discovers_complete_page_and_xlsx_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (date(2022, 1, 1), date(2022, 2, 1))
    monkeypatch.setattr(source, "EXPECTED_RELEASE_MONTHS", expected)

    releases = source.discover_release_links(_archive([(expected[0], 1), (expected[1], 2)]))

    assert [item.release_month for item in releases] == list(expected)
    assert releases[0].release_key == "22-01"
    with pytest.raises(ValueError, match="coverage drifted"):
        source.discover_release_links(_archive([(expected[0], 1)]))
    with pytest.raises(ValueError, match="official HTTPS host"):
        source.discover_release_links(
            b'<a href="https://example.com/analytics/dkp/inflationary_expectations/'
            b'Infl_exp_22-01/">bad</a>'
        )


def test_page_parser_uses_actual_release_day_and_exact_chart_endpoint() -> None:
    release = source.ReleaseLink(
        date(2025, 1, 1),
        "25-01",
        "https://www.cbr.ru/analytics/dkp/inflationary_expectations/Infl_exp_25-01/",
        "https://www.cbr.ru/Collection/Collection/File/101/stat_Infl_exp_25-01.xlsx",
    )

    row = source.parse_release_page(
        _release_page(
            release.release_month,
            publication_text="5 февраля 2025 года",
            updated_text="07.02.2025",
            file_id=1,
            expected=14.033,
            observed=16.4462,
        ),
        release=release,
        retrieved_at_utc="2026-09-01T03:00:00Z",
    )

    assert row["expected_inflation_value"] == 14.0
    assert row["expected_inflation_chart_exact"] == 14.033
    assert row["observed_inflation_value"] == 16.4
    assert row["publication_date"] == pd.Timestamp("2025-02-05")
    assert row["available_at"] == pd.Timestamp("2025-02-07T20:59:59Z")
    assert row["modified_after_publication"] is True


def test_statistics_workbook_parser_uses_semantic_labels_and_release_endpoint() -> None:
    values = source.parse_statistics_workbook(
        _minimal_xlsx(
            date(2025, 1, 1),
            observed=16.4462,
            expected=14.033,
            sentiment=103.53761833582462,
        ),
        release_month=date(2025, 1, 1),
    )

    assert values == {
        "expected_inflation_exact": 14.033,
        "observed_inflation_exact": 16.4462,
        "consumer_sentiment_index_exact": 103.53761833582462,
    }


class FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type, "ETag": '"synthetic"'}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.requested: list[str] = []
        self.releases = [(date(2022, 1, 1), 1), (date(2022, 2, 1), 2)]
        self.archive = _archive(self.releases)

    def get(self, url: str, *, headers: object, timeout: float) -> FakeResponse:
        del headers
        assert timeout == 60.0
        self.requested.append(url)
        if url == source.ARCHIVE_URL:
            return FakeResponse(self.archive, "text/html; charset=utf-8")
        for index, (release_month, file_id) in enumerate(self.releases):
            key = f"{release_month.year % 100:02d}-{release_month.month:02d}"
            page_url = (
                "https://www.cbr.ru/analytics/dkp/inflationary_expectations/"
                f"Infl_exp_{key}/"
            )
            xlsx_url = (
                f"https://www.cbr.ru/Collection/Collection/File/{file_id + 100}/"
                f"stat_Infl_exp_{key}.xlsx"
            )
            pdf_url = (
                f"https://www.cbr.ru/Collection/Collection/File/{file_id}/"
                f"Infl_exp_{key}.pdf"
            )
            expected = 10.0 + index
            observed = 12.0 + index
            if url == page_url:
                return FakeResponse(
                    _release_page(
                        release_month,
                        publication_text=(
                            "31 января 2022 года" if index == 0 else "28 февраля 2022 года"
                        ),
                        updated_text="31.01.2022" if index == 0 else "28.02.2022",
                        file_id=file_id,
                        expected=expected,
                        observed=observed,
                    ),
                    "text/html; charset=utf-8",
                )
            if url == xlsx_url:
                return FakeResponse(
                    _minimal_xlsx(
                        release_month,
                        observed=observed,
                        expected=expected,
                        sentiment=90.0 + 2.0 * index,
                    ),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            if url == pdf_url:
                return FakeResponse(b"%PDF-1.4\nsynthetic\n", "application/pdf")
        raise AssertionError(url)


def test_download_writes_hashed_immutable_target_free_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source,
        "EXPECTED_RELEASE_MONTHS",
        (date(2022, 1, 1), date(2022, 2, 1)),
    )
    output = tmp_path / "cbr-inflation-expectations-fixture-v1"
    session = FakeSession()

    result = source.download_cbr_inflation_expectations(
        output,
        session=session,
        max_workers=2,
        fetched_at_utc="2026-09-01T03:00:00Z",
        minimum_releases=1,
    )

    assert result == output.resolve()
    counts = Counter(session.requested)
    assert counts[source.ARCHIVE_URL] == 2
    assert len(session.requested) == 8
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["coverage"]["release_pages"] == 2
    assert manifest["coverage"]["aligned_confirmation_counts"] == {
        "risk_on": 0,
        "risk_off": 0,
        "mixed_or_zero": 1,
    }
    assert manifest["temporal_semantics"][
        "contains_prices_returns_targets_labels_or_pnl"
    ] is False
    assert manifest["source_quality"][
        "every_page_and_xlsx_inflation_display_endpoint_matches"
    ]
    assert source.sha256_file(result / manifest["artifacts"]["processed"]["path"]) == (
        manifest["artifacts"]["processed"]["sha256"]
    )
    assert manifest["artifacts"]["raw_responses"]["records"] == 8
    with pytest.raises(FileExistsError):
        source.download_cbr_inflation_expectations(
            output,
            session=session,
            max_workers=1,
            fetched_at_utc="2026-09-01T03:00:00Z",
            minimum_releases=1,
        )
