"""Tests for the bounded FRED STLFSI4 source collector."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import stlfsi_source as source


def _csv(values: list[tuple[str, str]]) -> bytes:
    lines = ["observation_date,STLFSI4"]
    lines.extend(f"{day},{value}" for day, value in values)
    return ("\n".join(lines) + "\n").encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {"Content-Type": "application/csv", "ETag": "test"}

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        assert headers["Accept"] == "text/csv,*/*;q=0.8"
        assert headers["Connection"] == "close"
        assert timeout == 20.0
        self.urls.append(url)
        return _Response(self.content)


def _payload() -> bytes:
    return _csv(
        [
            ("2018-01-05", "-0.1"),
            ("2018-01-12", "0.0"),
            ("2018-01-19", "0.2"),
            ("2018-01-26", "."),
        ]
    )


def test_series_url_is_official_and_server_bounded() -> None:
    parsed = urlparse(source.series_url())

    assert parsed.scheme == "https"
    assert parsed.hostname == "fred.stlouisfed.org"
    assert parsed.path == "/graph/fredgraph.csv"
    assert parse_qs(parsed.query) == {
        "id": ["STLFSI4"],
        "cosd": ["2018-01-01"],
        "coed": ["2025-12-31"],
    }


def test_parser_preserves_missing_and_rejects_non_friday_or_protected_rows() -> None:
    parsed = source.parse_fred_csv(_payload())

    assert len(parsed) == 4
    assert parsed["stress_index"].isna().sum() == 1
    assert parsed.loc[0, "stress_index"] == -0.1
    with pytest.raises(ValueError, match="non-Friday"):
        source.parse_fred_csv(_csv([("2018-01-06", "0.1")]))
    with pytest.raises(ValueError, match="protected STLFSI4 bounds"):
        source.parse_fred_csv(_csv([("2026-01-02", "0.1")]))


def test_availability_is_following_thursday_end_in_chicago() -> None:
    winter = source.conservative_available_at(pd.Timestamp("2025-01-03").date())
    summer = source.conservative_available_at(pd.Timestamp("2025-07-04").date())

    assert winter == pd.Timestamp("2025-01-10T05:59:59Z")
    assert summer == pd.Timestamp("2025-07-11T04:59:59Z")


def test_build_uses_official_zero_boundary_and_preserves_missing() -> None:
    built = source.build_stress_index(
        source.parse_fred_csv(_payload()),
        retrieved_at_utc="2026-09-01T05:00:00Z",
        minimum_rows=4,
    )

    assert built["complete"].tolist() == [True, True, True, False]
    assert built["stress_state"].tolist() == [
        "normal_or_below",
        "normal_or_below",
        "above_average",
        "missing",
    ]
    assert str(built["retrieved_at_utc"].dtype) == "datetime64[ms, UTC]"


def test_download_writes_immutable_replayable_bundle(tmp_path: Path) -> None:
    session = _Session(_payload())
    output = tmp_path / "fred-stlfsi4-test-v1"

    result = source.download_stlfsi(
        output,
        session=session,
        fetched_at_utc="2026-09-01T05:00:00Z",
        minimum_rows=4,
    )

    assert result == output.resolve()
    assert session.urls == [source.series_url()]
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    frame = pd.read_parquet(result / "stlfsi4.parquet")
    coverage = pd.read_parquet(result / "coverage.parquet")
    assert manifest["coverage"]["rows"] == 4
    assert manifest["coverage"]["stress_state_counts"] == {
        "above_average": 1,
        "normal_or_below": 2,
    }
    assert manifest["value_semantics"]["structural_boundary"] == 0.0
    assert len(frame) == 4
    assert len(coverage) == 1
    with gzip.open(result / "official_fred_stlfsi4_response.jsonl.gz", "rt") as stream:
        records = [json.loads(line) for line in stream]
    assert len(records) == 1
    content = base64.b64decode(records[0]["content"], validate=True)
    assert source.sha256_bytes(content) == records[0]["sha256"]
    assert b"2026-" not in content
    stated = (result / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
    assert stated == source.sha256_file(result / "manifest.json")

    with pytest.raises(FileExistsError):
        source.download_stlfsi(output, session=session, minimum_rows=4)
