"""Synthetic tests for the dated CBR banking-liquidity forecast source."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import cbr_liquidity_forecast_source as source


def _page(
    publication: str,
    period_start: str,
    period_end: str,
    values: tuple[str, str, str, str, str],
    *,
    current: bool,
) -> bytes:
    if current:
        labels = (
            "Correspondent accounts",
            "Cash",
            "Government accounts",
            "CBR operations",
            f"One-week auction dated {publication}",
        )
    else:
        labels = (
            "Cash",
            "Government accounts",
            "Required reserves",
            "CBR operations",
            f"One-week auction dated {publication}",
        )
    rows = "".join(
        f"<tr><td>{label}</td><td>{value}</td></tr>"
        for label, value in zip(labels, values, strict=True)
    )
    return (
        "<html>"
        f'<div class="table-caption gray">Period {period_start} - {period_end}</div>'
        f'<table class="data spaced">{rows}</table>'
        "</html>"
    ).encode()


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {
            "Last-Modified": "Tue, 12 Jan 2021 12:00:00 GMT",
            "Content-Type": "text/html; charset=utf-8",
        }

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, pages: dict[date, bytes], fallback: bytes) -> None:
        self.pages = pages
        self.fallback = fallback
        self.requested: list[date] = []

    def get(self, url: str, *, headers: object, timeout: float) -> FakeResponse:
        del headers
        assert timeout == 60.0
        query = parse_qs(urlparse(url).query)
        requested = pd.to_datetime(query["UniDbQuery.DT"][0], dayfirst=True).date()
        self.requested.append(requested)
        return FakeResponse(self.pages.get(requested, self.fallback))


def test_parse_current_release_uses_end_of_publication_day() -> None:
    frame = source.parse_forecast_html(
        _page(
            "12.01.2021",
            "13.01.2021",
            "19.01.2021",
            ("302", "0", "-38", "820", "1 080"),
            current=True,
        ),
        requested_date=date(2021, 1, 12),
        endpoint_schema="current_2021_plus",
        source_url="https://www.cbr.ru/statistics/pffl/?x",
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert frame is not None
    assert frame["available_at"] == pd.Timestamp("2021-01-12T20:59:59Z")
    assert frame["forecast_period_start"] == pd.Timestamp("2021-01-13")
    assert frame["forecast_period_end"] == pd.Timestamp("2021-01-19")
    assert frame["correspondent_accounts_change_bln_rub"] == 302.0
    assert frame["government_accounts_change_bln_rub"] == -38.0
    assert frame["one_week_auction_limit_bln_rub"] == 1080.0
    assert frame["required_reserves_change_bln_rub"] is None


def test_parse_archive_schema_and_optional_auction_limit() -> None:
    frame = source.parse_forecast_html(
        _page(
            "10.01.2017",
            "11.01.2017",
            "17.01.2017",
            ("109", "254", "0", "521", "-"),
            current=False,
        ),
        requested_date=date(2017, 1, 10),
        endpoint_schema="archive_2012_2020",
        source_url="https://www.cbr.ru/archive/db/pffl/?x",
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert frame is not None
    assert frame["correspondent_accounts_change_bln_rub"] is None
    assert frame["cash_change_bln_rub"] == 109.0
    assert frame["government_accounts_change_bln_rub"] == 254.0
    assert frame["required_reserves_change_bln_rub"] == 0.0
    assert frame["one_week_auction_limit_bln_rub"] is None


def test_invalid_date_fallback_is_not_mislabeled() -> None:
    frame = source.parse_forecast_html(
        _page(
            "30.12.2025",
            "30.12.2025",
            "13.01.2026",
            ("-572", "211", "-820", "-3 520", "4 700"),
            current=True,
        ),
        requested_date=date(2021, 2, 23),
        endpoint_schema="current_2021_plus",
        source_url="https://www.cbr.ru/statistics/pffl/?x",
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert frame is None


def test_required_value_fails_closed() -> None:
    with pytest.raises(ValueError, match="required CBR forecast number"):
        source.parse_forecast_html(
            _page(
                "12.01.2021",
                "13.01.2021",
                "19.01.2021",
                ("302", "0", "-", "820", "1 080"),
                current=True,
            ),
            requested_date=date(2021, 1, 12),
            endpoint_schema="current_2021_plus",
            source_url="https://www.cbr.ru/statistics/pffl/?x",
            retrieved_at_utc="2026-09-01T00:00:00Z",
        )


def test_download_discovers_holiday_shift_and_writes_hashed_bundle(tmp_path: Path) -> None:
    first = _page(
        "12.01.2021",
        "13.01.2021",
        "19.01.2021",
        ("302", "0", "-38", "820", "1 080"),
        current=True,
    )
    shifted = _page(
        "20.01.2021",
        "21.01.2021",
        "26.01.2021",
        ("-10", "15", "200", "-500", "700"),
        current=True,
    )
    fallback = _page(
        "30.12.2025",
        "30.12.2025",
        "13.01.2026",
        ("-572", "211", "-820", "-3 520", "4 700"),
        current=True,
    )
    session = FakeSession(
        {
            date(2021, 1, 12): first,
            date(2021, 1, 20): shifted,
        },
        fallback,
    )
    output = tmp_path / "bundle"
    staging = tmp_path / "staging"

    result = source.download_cbr_liquidity_forecasts(
        output,
        staging_directory=staging,
        session=session,
        max_workers=1,
        fetched_at_utc="2026-09-01T00:00:00Z",
        week_starts=(date(2021, 1, 11), date(2021, 1, 18)),
    )

    assert result == output.resolve()
    data = pd.read_parquet(output / "cbr_liquidity_forecasts.parquet")
    coverage = pd.read_parquet(output / "coverage.parquet")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert data["publication_date"].dt.date.tolist() == [date(2021, 1, 12), date(2021, 1, 20)]
    assert coverage["attempt_count"].tolist() == [1, 2]
    assert session.requested == [date(2021, 1, 12), date(2021, 1, 19), date(2021, 1, 20)]
    assert manifest["request_count"] == 3
    assert manifest["release_count"] == 2
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"] is False
    assert manifest["rights"]["raw_redistribution_allowed"] is False
    assert (output / "manifest.json").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (staging / "plan.json").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(FileExistsError):
        source.download_cbr_liquidity_forecasts(
            output,
            staging_directory=staging,
            session=session,
            week_starts=(date(2021, 1, 11),),
        )


def test_protected_boundary_rejected() -> None:
    with pytest.raises(ValueError, match="source interval|protected"):
        source.conservative_available_at(date(2026, 1, 1))


def test_week_grid_never_precedes_source_start() -> None:
    weeks = source._week_starts(date(2017, 1, 1), date(2017, 1, 31))

    assert weeks[0] == date(2017, 1, 2)
    assert weeks[-1] == date(2017, 1, 30)
