"""Synthetic tests for the official Bank of Russia business-climate source."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import cbr_business_climate_source as source


def _month_categories(year: int) -> list[str]:
    return [date(year, month, 1).isoformat() for month in range(1, 13)]


def _series(
    series_id: str,
    name: str,
    *,
    release_month: date,
    exact: float,
    label: str,
) -> dict[str, object]:
    data: list[object | None] = [None] * 12
    data[release_month.month - 1] = {"y": exact, "name": label}
    return {"id": series_id, "name": name, "data": data}


def _release_page(
    release_month: date,
    *,
    observation_month: date | None = None,
    publication_text: str,
    updated_text: str,
    file_id: int,
    bci_exact: float,
    bci_label: str,
) -> bytes:
    point_month = observation_month or release_month
    settings = {
        "xAxis": {
            "categories": [
                {
                    "name": str(release_month.year),
                    "categories": _month_categories(release_month.year),
                }
            ]
        },
        "series": [
            _series(
                "s0",
                "Сводный",
                release_month=point_month,
                exact=bci_exact,
                label=bci_label,
            ),
            _series(
                "s1",
                "Текущие оценки",
                release_month=point_month,
                exact=-0.03,
                label="0,0",
            ),
            _series(
                "s2",
                "Ожидания",
                release_month=point_month,
                exact=13.54,
                label="13,5",
            ),
        ],
    }
    pdf = f"/Collection/Collection/File/{file_id}/{release_month:%m%y}.pdf"
    return (
        "<html><body>"
        f'<div class="news-info-line_date">{publication_text}</div>'
        '<div id="GrafChart_ChartModel_chart"></div>'
        f"<script>var settings = {json.dumps(settings, ensure_ascii=False)};</script>"
        f'<a href="{pdf}">Скачать</a><a href="{pdf}">Комментарий</a>'
        f"<footer>Последнее обновление страницы: {updated_text}</footer>"
        "</body></html>"
    ).encode()


def test_archive_discovery_accepts_versioned_urls_and_rejects_missing_months(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (date(2022, 5, 1), date(2022, 6, 1))
    monkeypatch.setattr(source, "EXPECTED_RELEASE_MONTHS", expected)
    page = (
        b'<a href="/analytics/dkp/monitoring/06_22/">June</a>'
        b'<a href="/analytics/dkp/monitoring/05_22/">May</a>'
        b'<a href="/analytics/dkp/monitoring/0126/">Protected</a>'
    )

    releases = source.discover_release_links(page)

    assert [item.release_month for item in releases] == list(expected)
    assert releases[0].release_key == "05_22"
    with pytest.raises(ValueError, match="coverage drifted"):
        source.discover_release_links(
            b'<a href="/analytics/dkp/monitoring/05_22/">May</a>'
        )
    with pytest.raises(ValueError, match="official HTTPS host"):
        source.discover_release_links(
            b'<a href="https://example.com/analytics/dkp/monitoring/05_22/">bad</a>'
        )


def test_release_parser_uses_printed_chart_label_and_later_revision_day() -> None:
    release = source.ReleaseLink(
        date(2022, 10, 1),
        "10_22",
        "https://www.cbr.ru/analytics/dkp/monitoring/10_22/",
    )
    page = _release_page(
        release.release_month,
        publication_text="20 октября 2022 года",
        updated_text="24.11.2022",
        file_id=43418,
        bci_exact=-1.1987,
        bci_label="-1,2",
    )

    row = source.parse_release_page(
        page,
        release=release,
        retrieved_at_utc="2026-09-01T03:00:00Z",
    )

    assert row["bci_value"] == -1.2
    assert row["bci_chart_exact"] == -1.1987
    assert row["publication_date"] == pd.Timestamp("2022-10-20")
    assert row["last_updated_date"] == pd.Timestamp("2022-11-24")
    assert row["available_at"] == pd.Timestamp("2022-11-24T20:59:59Z")
    assert row["modified_after_publication"] is True
    assert row["pdf_url"] == (
        "https://www.cbr.ru/Collection/Collection/File/43418/1022.pdf"
    )


def test_release_parser_recovers_value_when_headline_has_no_number() -> None:
    release = source.ReleaseLink(
        date(2024, 1, 1),
        "0124",
        "https://www.cbr.ru/analytics/dkp/monitoring/0124/",
    )

    row = source.parse_release_page(
        _release_page(
            release.release_month,
            publication_text="24 января 2024 года",
            updated_text="24.01.2024",
            file_id=47793,
            bci_exact=6.7867,
            bci_label="6,8",
        ),
        release=release,
        retrieved_at_utc="2026-09-01T03:00:00Z",
    )

    assert row["bci_value"] == 6.8
    assert row["current_assessments_value"] == 0.0
    assert row["expectations_value"] == 13.5
    assert row["available_at"] == pd.Timestamp("2024-01-24T20:59:59Z")


def test_release_parser_retains_a_prior_month_chart_endpoint() -> None:
    release = source.ReleaseLink(
        date(2022, 5, 1),
        "05_22",
        "https://www.cbr.ru/analytics/dkp/monitoring/05_22/",
    )

    row = source.parse_release_page(
        _release_page(
            release.release_month,
            observation_month=date(2022, 4, 1),
            publication_text="31 мая 2022 года",
            updated_text="31.05.2022",
            file_id=41018,
            bci_exact=-4.9799,
            bci_label="-5,0",
        ),
        release=release,
        retrieved_at_utc="2026-09-01T03:00:00Z",
    )

    assert row["release_month"] == pd.Timestamp("2022-05-01")
    assert row["observation_month"] == pd.Timestamp("2022-04-01")
    assert row["bci_value"] == -5.0


class FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type, "ETag": '"synthetic"'}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.requested: list[str] = []
        self.archive = (
            b'<a href="/analytics/dkp/monitoring/05_22/">May</a>'
            b'<a href="/analytics/dkp/monitoring/06_22/">June</a>'
        )
        self.pages = {
            "https://www.cbr.ru/analytics/dkp/monitoring/05_22/": _release_page(
                date(2022, 5, 1),
                publication_text="31 мая 2022 года",
                updated_text="31.05.2022",
                file_id=1,
                bci_exact=-4.9799,
                bci_label="-5,0",
            ),
            "https://www.cbr.ru/analytics/dkp/monitoring/06_22/": _release_page(
                date(2022, 6, 1),
                publication_text="24 июня 2022 года",
                updated_text="24.06.2022",
                file_id=2,
                bci_exact=-1.9783,
                bci_label="-2,0",
            ),
        }

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
        if url == source.ARCHIVE_URL:
            return FakeResponse(self.archive, "text/html; charset=utf-8")
        if url in self.pages:
            return FakeResponse(self.pages[url], "text/html; charset=utf-8")
        if "/Collection/Collection/File/" in url:
            return FakeResponse(b"%PDF-1.4\nsynthetic\n", "application/pdf")
        raise AssertionError(url)


def test_download_writes_hashed_immutable_target_free_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source,
        "EXPECTED_RELEASE_MONTHS",
        (date(2022, 5, 1), date(2022, 6, 1)),
    )
    output = tmp_path / "cbr-business-climate-fixture-v1"
    session = FakeSession()

    result = source.download_cbr_business_climate(
        output,
        session=session,
        max_workers=2,
        fetched_at_utc="2026-09-01T03:00:00Z",
        minimum_releases=1,
    )

    assert result == output.resolve()
    counts = Counter(session.requested)
    assert counts[source.ARCHIVE_URL] == 2
    assert len(session.requested) == 6
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["coverage"]["release_pages"] == 2
    assert manifest["coverage"]["sequential_bci_delta_counts"] == {
        "positive": 1,
        "negative": 0,
        "zero": 0,
    }
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"] is False
    assert manifest["value_semantics"]["latest_current_vintage_history_not_used"] is True
    assert source.sha256_file(result / manifest["artifacts"]["processed"]["path"]) == (
        manifest["artifacts"]["processed"]["sha256"]
    )
    assert manifest["artifacts"]["raw_responses"]["records"] == 6
    with pytest.raises(FileExistsError):
        source.download_cbr_business_climate(
            output,
            session=session,
            max_workers=1,
            fetched_at_utc="2026-09-01T03:00:00Z",
            minimum_releases=1,
        )
