"""Synthetic tests for causal EIA WPSR release-vintage acquisition."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import eia_wpsr_source as source


def _table(release_week: str, previous_week: str, year_ago_week: str) -> bytes:
    return (
        f'"STUB_1","{release_week}","{previous_week}","Difference",'
        f'"Percent Change","{year_ago_week}","Difference","Percent Change"\r\n'
        '"Crude Oil","1,000.000","990.000","10.000","1.0",'
        '"950.000","50.000","5.3"\r\n'
        '"Commercial (Excluding SPR)","400.000","395.000","5.000","1.3",'
        '"390.000","10.000","2.6"\r\n'
        f'"STUB_1","STUB_2","{release_week}","{previous_week}","Difference",'
        f'"{year_ago_week}",'
        '"Difference","FOUR WEEK","YEAR AGO","Percent Change",'
        '"YTD","YEAR AGO","Percent Change"\r\n'
        '"Crude Oil Supply ","(1) Domestic Production","13,000","12,900",'
        '"100","12,000","1,000","12,950","12,100","7.0",'
        '"12,800","11,900","7.6"\r\n'
        '"Products Supplied ","(2) Total","--","20,000","–","19,000",'
        '"1,000","20,100","19,100","5.2","20,000","19,000","5.3"\r\n'
        "\x1a\r\n"
    ).encode("cp1252")


def _index(*slugs: str) -> bytes:
    links = "".join(
        f'<a href="/petroleum/supply/weekly/archive/{slug[:4]}/{slug}/wpsr_{slug}.php">x</a>'
        for slug in slugs
    )
    return f"<html><body>{links}</body></html>".encode()


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {
            "Last-Modified": "Wed, 06 Jan 2021 13:02:58 GMT",
            "Content-Type": "application/octet-stream",
        }

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: object,
        timeout: float,
    ) -> FakeResponse:
        del headers
        assert timeout == 60.0
        self.urls.append(url)
        return FakeResponse(self.payloads[url])


def test_discovery_is_official_unique_and_bounded() -> None:
    releases = source.discover_releases(
        _index("2012_01_05", "2025_12_29", "2025_12_31", "2026_01_07")
    )

    assert [release.release_date.isoformat() for release in releases] == [
        "2012-01-05",
        "2025-12-29",
    ]
    assert releases[0].table1_url.endswith("/2012_01_05/csv/table1.csv")


def test_normalization_preserves_missing_and_uses_end_of_release_day() -> None:
    release = source.Release(
        release_date=pd.Timestamp("2021-01-06").date(),
        issue_url=(
            "https://www.eia.gov/petroleum/supply/weekly/archive/2021/"
            "2021_01_06/wpsr_2021_01_06.php"
        ),
        table1_url=(
            "https://www.eia.gov/petroleum/supply/weekly/archive/2021/"
            "2021_01_06/csv/table1.csv"
        ),
    )

    frame = source.normalize_table1(
        _table("1/1/21", "12/25/20", "1/3/20"),
        release,
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert len(frame) == 4
    assert frame["available_at"].nunique() == 1
    assert frame["available_at"].iat[0] == pd.Timestamp("2021-01-07T04:59:59Z")
    assert frame["data_week_ending"].iat[0] == pd.Timestamp("2021-01-01")
    assert frame["previous_week_ending"].iat[0] == pd.Timestamp("2020-12-25")
    assert frame["year_ago_week_ending"].iat[0] == pd.Timestamp("2020-01-03")
    missing = frame.loc[frame["item"].eq("Total")].iloc[0]
    assert pd.isna(missing["current_value"])
    assert pd.isna(missing["reported_weekly_change"])
    assert missing["current_raw"] == "--"
    assert missing["unit"] == "thousand_barrels_per_day"


def test_unknown_numeric_token_fails_closed() -> None:
    release = source.Release(
        release_date=pd.Timestamp("2021-01-06").date(),
        issue_url="https://www.eia.gov/x",
        table1_url="https://www.eia.gov/y",
    )
    content = _table("1/1/21", "12/25/20", "1/3/20").replace(b'"13,000"', b'"X"')

    with pytest.raises(ValueError, match="unknown EIA numeric token"):
        source.normalize_table1(
            content,
            release,
            retrieved_at_utc="2026-09-01T00:00:00Z",
        )


def test_stale_duplicate_archive_release_is_preserved_but_not_admitted() -> None:
    coverage = pd.DataFrame(
        {
            "release_date": ["2019-06-26", "2019-07-03", "2019-07-10"],
            "data_week_ending": ["2019-06-21", "2019-06-21", "2019-07-05"],
            "sha256": ["a" * 64, "a" * 64, "b" * 64],
        }
    )

    classified = source.classify_release_admissibility(coverage)

    assert classified["admissible"].tolist() == [True, False, True]
    assert classified.loc[1, "exclusion_reason"] == "duplicate_stale_archive_file"


def test_download_writes_hashed_release_specific_bundle(tmp_path: Path) -> None:
    slugs = ("2020_01_03", "2021_01_06")
    index = _index(*slugs)
    payloads = {source.ARCHIVE_INDEX_URL: index}
    weeks = {
        "2020_01_03": ("12/27/19", "12/20/19", "12/28/18"),
        "2021_01_06": ("1/1/21", "12/25/20", "1/3/20"),
    }
    for slug in slugs:
        release = source.discover_releases(_index(slug))[0]
        payloads[release.table1_url] = _table(*weeks[slug])
    session = FakeSession(payloads)
    output = tmp_path / "eia"
    staging = tmp_path / "staging"

    result = source.download_eia_wpsr_source(
        output,
        staging_directory=staging,
        session=session,
        max_workers=1,
        fetched_at_utc="2026-09-01T00:00:00Z",
    )

    assert result == output.resolve()
    data = pd.read_parquet(output / "eia_wpsr_table1.parquet")
    coverage = pd.read_parquet(output / "coverage.parquet")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert len(data) == 8
    assert len(coverage) == 2
    assert data["release_date"].max() == pd.Timestamp("2021-01-06")
    assert data["available_at"].max() < source.PROTECTED_FROM
    assert manifest["release_count"] == 2
    assert manifest["processed_release_count"] == 2
    assert manifest["excluded_release_count"] == 0
    assert manifest["request_count"] == 3
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"] is False
    assert manifest["temporal_semantics"]["historical_development_backtest_admissible"] is True
    assert manifest["rights"]["raw_redistribution_allowed"] is True
    assert (staging / "plan.json").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (output / "manifest.json").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(FileExistsError):
        source.download_eia_wpsr_source(
            output,
            staging_directory=staging,
            session=session,
            max_workers=1,
        )


def test_conservative_availability_rejects_cross_boundary() -> None:
    with pytest.raises(ValueError, match="source interval|protected"):
        source.conservative_available_at(pd.Timestamp("2025-12-31").date())
