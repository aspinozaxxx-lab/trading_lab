"""Synthetic tests for the CBR daily banking-liquidity factors source."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import cbr_liquidity_factors_source as source


def _page(rows: list[tuple[str, ...]]) -> bytes:
    body = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return (
        "<html><table class=\"data spaced\">"
        "<tr><th>Date</th><th>Cash</th></tr>"
        "<tr><th>Components</th></tr>"
        f"{body}</table></html>"
    ).encode()


def _rows() -> list[tuple[str, ...]]:
    return [
        ("29.12.2025", "-55,7", "166,1", "0", "1 232", "288", "-14,5", "0", "-377,5"),
        ("30.12.2025", "-35,7", "109,8", "0", "60", "0", "-14,6", "0", "604,5"),
        ("31.12.2025", "53,7", "107,5", "0", "0", "0", "0", "0", "-35,1"),
    ]


def test_parse_maps_minfin_column_and_next_working_day_availability() -> None:
    parsed = source.parse_liquidity_factors_html(
        _page(list(reversed(_rows()))),
        source_url="https://www.cbr.ru/statistics/flikvid/?x",
        retrieved_at_utc="2026-09-01T00:00:00Z",
        source_start=date(2025, 12, 1),
        source_end=date(2025, 12, 31),
    )

    assert parsed.raw_row_count == 3
    assert parsed.excluded_without_pre_boundary_publication == 1
    assert parsed.frame["observation_date"].dt.date.tolist() == [
        date(2025, 12, 29),
        date(2025, 12, 30),
    ]
    assert parsed.frame["publication_date"].dt.date.tolist() == [
        date(2025, 12, 30),
        date(2025, 12, 31),
    ]
    assert parsed.frame["available_at"].tolist() == [
        pd.Timestamp("2025-12-30T07:31:00Z"),
        pd.Timestamp("2025-12-31T07:31:00Z"),
    ]
    assert parsed.frame["minfin_fx_operations_bln_rub"].tolist() == [-14.5, -14.6]
    assert parsed.frame["government_accounts_change_bln_rub"].tolist() == [166.1, 109.8]
    assert parsed.frame["historical_values_may_be_revised"].all()


def test_parser_rejects_malformed_dated_row() -> None:
    rows = _rows()
    rows[0] = rows[0][:-1]
    with pytest.raises(ValueError, match="nine cells"):
        source.parse_liquidity_factors_html(
            _page(rows),
            source_url="https://www.cbr.ru/statistics/flikvid/?x",
            retrieved_at_utc="2026-09-01T00:00:00Z",
            source_start=date(2025, 12, 1),
            source_end=date(2025, 12, 31),
        )


def test_parser_rejects_non_numeric_factor() -> None:
    rows = _rows()
    rows[0] = (*rows[0][:6], "missing", *rows[0][7:])
    with pytest.raises(ValueError, match="invalid CBR liquidity number"):
        source.parse_liquidity_factors_html(
            _page(rows),
            source_url="https://www.cbr.ru/statistics/flikvid/?x",
            retrieved_at_utc="2026-09-01T00:00:00Z",
            source_start=date(2025, 12, 1),
            source_end=date(2025, 12, 31),
        )


def test_official_query_is_deterministic_and_bounded() -> None:
    url = source.build_liquidity_factors_url()
    query = parse_qs(urlparse(url).query)

    assert urlparse(url).netloc == "www.cbr.ru"
    assert query["UniDbQuery.From"] == ["01.01.2021"]
    assert query["UniDbQuery.To"] == ["31.12.2025"]
    assert query["UniDbQuery.Posted"] == ["True"]
    with pytest.raises(ValueError, match="source interval"):
        source.build_liquidity_factors_url(date(2020, 12, 31), date(2025, 12, 31))


def test_protected_publication_boundary_rejected() -> None:
    with pytest.raises(ValueError, match="protected"):
        source.conservative_available_at(date(2026, 1, 1))
