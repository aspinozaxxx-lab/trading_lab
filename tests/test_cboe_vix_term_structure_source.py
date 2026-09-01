"""Tests for the bounded FRED-distributed Cboe volatility source."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import cboe_vix_term_structure_source as source


def _csv(series_id: str, values: list[tuple[str, str]]) -> bytes:
    lines = [f"observation_date,{series_id}"]
    lines.extend(f"{day},{value}" for day, value in values)
    return ("\n".join(lines) + "\n").encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {"Content-Type": "application/csv", "ETag": "test"}

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
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
        series_id = parse_qs(urlparse(url).query)["id"][0]
        return _Response(self.payloads[series_id])


def _payloads() -> dict[str, bytes]:
    return {
        "VIXCLS": _csv(
            "VIXCLS",
            [
                ("2018-01-02", "20.0"),
                ("2018-01-03", "."),
                ("2018-01-04", "10.0"),
            ],
        ),
        "VXVCLS": _csv(
            "VXVCLS",
            [
                ("2018-01-02", "18.0"),
                ("2018-01-03", "17.0"),
                ("2018-01-04", "12.0"),
            ],
        ),
    }


def test_series_url_is_official_and_server_bounded() -> None:
    url = source.series_url("VIXCLS")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.hostname == "fred.stlouisfed.org"
    assert parsed.path == "/graph/fredgraph.csv"
    assert query == {
        "id": ["VIXCLS"],
        "cosd": ["2018-01-01"],
        "coed": ["2025-12-31"],
    }
    with pytest.raises(ValueError, match="unsupported"):
        source.series_url("VIX_FUTURE")


def test_parser_preserves_missing_and_rejects_protected_observations() -> None:
    parsed = source.parse_fred_csv(_payloads()["VIXCLS"], series_id="VIXCLS")

    assert len(parsed) == 3
    assert parsed["vix_close"].isna().sum() == 1
    assert parsed.loc[0, "vix_close"] == 20.0
    assert parsed["observation_date"].max() == pd.Timestamp("2018-01-04")

    protected = _csv("VIXCLS", [("2026-01-02", "15.0")])
    with pytest.raises(ValueError, match="protected date bounds"):
        source.parse_fred_csv(protected, series_id="VIXCLS")


def test_availability_uses_conservative_chicago_day_end() -> None:
    winter = source.conservative_available_at(pd.Timestamp("2025-01-02").date())
    summer = source.conservative_available_at(pd.Timestamp("2025-07-02").date())

    assert winter == pd.Timestamp("2025-01-03T05:59:59Z")
    assert summer == pd.Timestamp("2025-07-03T04:59:59Z")


def test_build_preserves_pair_missingness_and_structural_boundary() -> None:
    payloads = _payloads()
    frames = {
        series_id: source.parse_fred_csv(content, series_id=series_id)
        for series_id, content in payloads.items()
    }

    built = source.build_term_structure(
        frames,
        retrieved_at_utc="2026-09-01T04:00:00Z",
        minimum_rows=3,
        minimum_complete_pairs=2,
    )

    assert built["complete_pair"].tolist() == [True, False, True]
    assert built["term_structure"].tolist() == [
        "backwardation",
        "missing",
        "contango",
    ]
    assert built.loc[0, "vix_vix3m_ratio"] == pytest.approx(20.0 / 18.0)
    assert pd.isna(built.loc[1, "vix_vix3m_ratio"])
    assert str(built["retrieved_at_utc"].dtype) == "datetime64[ms, UTC]"


def test_download_writes_immutable_replayable_bundle(tmp_path: Path) -> None:
    payloads = _payloads()
    session = _Session(payloads)
    output = tmp_path / "fred-cboe-vix-test-v1"

    result = source.download_cboe_vix_term_structure(
        output,
        session=session,
        fetched_at_utc="2026-09-01T04:00:00Z",
        minimum_rows=3,
        minimum_complete_pairs=2,
    )

    assert result == output.resolve()
    assert len(session.urls) == 2
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    frame = pd.read_parquet(result / "cboe_vix_term_structure.parquet")
    coverage = pd.read_parquet(result / "coverage.parquet")
    assert manifest["coverage"]["grid_rows"] == 3
    assert manifest["coverage"]["complete_pairs"] == 2
    assert manifest["coverage"]["term_structure_counts"] == {
        "backwardation": 1,
        "contango": 1,
        "flat": 0,
    }
    assert manifest["rights"]["cboe_values_copyrighted"] is True
    assert len(frame) == 3
    assert len(coverage) == 2
    raw_records = []
    with gzip.open(result / "official_fred_cboe_responses.jsonl.gz", "rt") as stream:
        for line in stream:
            record = json.loads(line)
            content = base64.b64decode(record["content"], validate=True)
            assert source.sha256_bytes(content) == record["sha256"]
            assert b"2026-" not in content
            raw_records.append(record)
    assert {record["identity"] for record in raw_records} == {"VIXCLS", "VXVCLS"}
    stated = (result / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
    assert stated == source.sha256_file(result / "manifest.json")

    with pytest.raises(FileExistsError):
        source.download_cboe_vix_term_structure(
            output,
            session=session,
            minimum_rows=3,
            minimum_complete_pairs=2,
        )
