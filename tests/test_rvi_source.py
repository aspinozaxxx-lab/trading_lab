"""Tests for immutable, protected-boundary MOEX RVI source acquisition."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import rvi_source


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self, rows: list[list[object]], page_size: int = 2) -> None:
        self.rows = rows
        self.page_size = page_size
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: object,
        timeout: float,
    ) -> FakeResponse:
        del headers, timeout
        self.urls.append(url)
        offset = int(parse_qs(urlparse(url).query)["start"][0])
        page = self.rows[offset : offset + self.page_size]
        return FakeResponse(
            {
                "history": {"columns": list(rvi_source.ISS_COLUMNS), "data": page},
                "history.cursor": {
                    "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                    "data": [[offset, len(self.rows), self.page_size]],
                },
            }
        )


def _rows() -> list[list[object]]:
    return [
        ["2018-01-03", "RVI", 16.66, 18.02, 15.83, 17.95],
        ["2018-01-04", "RVI", 17.95, 19.10, 17.20, 18.50],
        ["2025-12-30", "RVI", 24.00, 25.50, 23.80, 25.10],
    ]


def test_download_writes_bounded_provenance_and_conservative_lag(tmp_path: Path) -> None:
    session = FakeSession(_rows())
    output = tmp_path / "rvi-source"

    result = rvi_source.download_rvi_source(
        output,
        session=session,
        fetched_at_utc="2026-08-31T00:00:00Z",
    )

    assert result == output.resolve()
    data = pd.read_parquet(output / "rvi_daily.parquet")
    assert len(data) == 3
    assert data["source_date"].max() == pd.Timestamp("2025-12-30")
    assert (
        data["conservative_available_from_date"]
        == data["source_date"] + pd.Timedelta(days=1)
    ).all()
    assert data["current_vintage_snapshot"].all()
    assert len(session.urls) == 2
    for url in session.urls:
        query = parse_qs(urlparse(url).query)
        assert query["from"] == ["2018-01-01"]
        assert query["till"] == ["2025-12-31"]
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["request_bounds"]["protected_from"] == "2026-01-01"
    assert manifest["artifacts"]["processed"]["rows"] == 3
    assert manifest["temporal_semantics"]["historical_revision_archive_proved"] is False


def test_normalization_rejects_protected_row() -> None:
    frame = pd.DataFrame(
        [["2026-01-02", "RVI", 20.0, 21.0, 19.0, 20.5]],
        columns=[column.lower() for column in rvi_source.ISS_COLUMNS],
    )

    with pytest.raises(ValueError, match="escaped|protected"):
        rvi_source.normalize_rvi_history(frame)


def test_normalization_rejects_invalid_ohlc() -> None:
    frame = pd.DataFrame(
        [["2025-12-30", "RVI", 20.0, 19.0, 18.0, 20.5]],
        columns=[column.lower() for column in rvi_source.ISS_COLUMNS],
    )

    with pytest.raises(ValueError, match="OHLC"):
        rvi_source.normalize_rvi_history(frame)


def test_downloader_never_overwrites_existing_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "rvi-source"
    output.mkdir()

    with pytest.raises(FileExistsError):
        rvi_source.download_rvi_source(output, session=FakeSession(_rows()))
