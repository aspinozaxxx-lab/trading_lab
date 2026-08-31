"""Synthetic tests for complete, bounded MOEX FUTOI intraday acquisition."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import futoi_intraday_source as source
from market_lab.futures import futoi_source as daily_source


def _point(clock: str, sequence: int, published: str) -> list[list[object]]:
    return [
        [
            7,
            sequence,
            "2020-05-12",
            clock,
            "Si",
            "YUR",
            -10 - sequence,
            40,
            -50 - sequence,
            4,
            5,
            published,
        ],
        [
            7,
            sequence,
            "2020-05-12",
            clock,
            "Si",
            "FIZ",
            10 + sequence,
            20 + sequence,
            -10,
            8,
            2,
            published,
        ],
    ]


def _rows() -> list[list[object]]:
    return [
        *_point("10:00:00", 12, "2020-05-12 10:00:07"),
        *_point("10:05:00", 13, "2020-05-12 10:05:08"),
    ]


class FakeResponse:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "futoi": {
                "columns": list(daily_source.ISS_COLUMNS),
                "data": self.rows,
            }
        }


class FakeSession:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 60.0
        self.urls.append(url)
        query = parse_qs(urlparse(url).query)
        if query.get("latest") == ["1"]:
            return FakeResponse(self.rows[-2:])
        return FakeResponse(self.rows)


def _raw(rows: list[list[object]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows or _rows(), columns=daily_source.ISS_COLUMNS)


def test_intraday_request_is_one_day_without_sampling_or_offset() -> None:
    url = source._intraday_request_url("Si", pd.Timestamp("2025-12-30"))
    query = parse_qs(urlparse(url).query)

    assert query["from"] == ["2025-12-30"]
    assert query["till"] == ["2025-12-30"]
    assert "latest" not in query
    assert "start" not in query
    assert query["futoi.columns"] == [",".join(daily_source.ISS_COLUMNS)]
    with pytest.raises(ValueError, match="pre-2026"):
        source._intraday_request_url("Si", pd.Timestamp("2026-01-01"))


def test_intraday_day_matches_official_daily_latest_pair() -> None:
    raw = _raw()
    latest = daily_source.normalize_futoi_history(_raw(_rows()[-2:]), "Si")

    verified = source.verify_intraday_day(
        raw,
        "Si",
        pd.Timestamp("2020-05-12"),
        daily_latest=latest,
    )

    assert len(verified) == 4
    assert verified[["source_date", "source_time", "ticker"]].drop_duplicates().shape[0] == 2
    assert verified.groupby("source_time")["client_group"].nunique().eq(2).all()
    assert verified["available_at"].max() == pd.Timestamp("2020-05-12T07:06:08Z")


def test_response_at_official_row_cap_fails_closed() -> None:
    session = FakeSession([_rows()[0]] * source.MAX_RESPONSE_ROWS)

    with pytest.raises(ValueError, match="1000-row cap"):
        source.fetch_intraday_day(
            "Si",
            pd.Timestamp("2020-05-12"),
            session=session,
        )


def test_wrong_daily_latest_proof_is_rejected() -> None:
    latest = daily_source.normalize_futoi_history(_raw(_rows()[-2:]), "Si")
    latest.loc[latest["client_group"].eq("FIZ"), "net_position"] += 1

    with pytest.raises(AssertionError):
        source.verify_intraday_day(
            _raw(),
            "Si",
            pd.Timestamp("2020-05-12"),
            daily_latest=latest,
        )


def test_download_writes_resumable_hashed_intraday_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source, "SOURCE_START", pd.Timestamp("2020-05-12"))
    monkeypatch.setattr(source, "SOURCE_END", pd.Timestamp("2020-05-12"))
    monkeypatch.setattr(source, "TICKERS", ("Si",))
    output = tmp_path / "intraday"
    staging = tmp_path / "staging"
    session = FakeSession(_rows())

    result = source.download_futoi_intraday_source(
        output,
        staging_directory=staging,
        session=session,
        max_workers=1,
        request_delay_seconds=0.0,
        fetched_at_utc="2026-09-01T00:00:00Z",
    )

    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    intraday = pd.read_parquet(result / "futoi_intraday.parquet")
    coverage = pd.read_parquet(result / "coverage.parquet")
    assert len(intraday) == 4
    assert len(coverage) == 1
    assert intraday["conservative_available_at"].eq(
        pd.Timestamp("2026-09-01T00:00:00Z")
    ).all()
    assert manifest["request_count"] == 2
    assert manifest["network_requests_this_run"] == 2
    assert manifest["single_date_intraday_request_count"] == 1
    assert manifest["artifacts"]["processed_intraday"]["rows"] == 4
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_or_pnl"] is False
    assert manifest["temporal_semantics"]["historical_2020_2025_backtest_admissible"] is False
    assert manifest["access_observation"]["raw_redistribution_allowed"] is False
    assert (staging / "plan.json").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(FileExistsError):
        source.download_futoi_intraday_source(
            output,
            staging_directory=staging,
            session=FakeSession(_rows()),
            max_workers=1,
        )
