"""Synthetic tests for the bounded target-free MOEX FUTOI source."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import futoi_source


def _rows() -> list[list[object]]:
    return [
        [
            7,
            12,
            "2020-05-12",
            "10:00:00",
            "Si",
            "YUR",
            -10,
            40,
            -50,
            4,
            5,
            "2020-05-12 10:00:07",
        ],
        [
            7,
            12,
            "2020-05-12",
            "10:00:00",
            "Si",
            "FIZ",
            10,
            20,
            -10,
            8,
            2,
            "2020-05-12 10:00:07",
        ],
    ]


class FakeResponse:
    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "futoi": {
                "columns": list(futoi_source.ISS_COLUMNS),
                "data": self._rows,
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
        assert headers["User-Agent"] == futoi_source.USER_AGENT
        assert timeout == 60.0
        self.urls.append(url)
        return FakeResponse(self.rows)


def _raw_frame(rows: list[list[object]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(rows or _rows(), columns=futoi_source.ISS_COLUMNS)


def test_request_is_closed_and_strictly_pre_2026() -> None:
    url = futoi_source._request_url(
        "Si", pd.Timestamp("2020-05-01"), pd.Timestamp("2025-12-31")
    )
    query = parse_qs(urlparse(url).query)

    assert query["till"] == ["2025-12-31"]
    assert query["latest"] == ["1"]
    assert query["futoi.columns"] == [",".join(futoi_source.ISS_COLUMNS)]
    assert "trade_session_date" not in query["futoi.columns"][0]
    with pytest.raises(ValueError, match="protected"):
        futoi_source._request_url(
            "Si", pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01")
        )


def test_fetch_uses_one_bounded_latest_per_date_request() -> None:
    session = FakeSession(_rows())
    frame, archive = futoi_source.fetch_futoi_period(
        session,
        "Si",
        pd.Timestamp("2020-05-01"),
        pd.Timestamp("2020-12-31"),
    )

    assert len(frame) == 2
    assert len(archive) == 1
    assert len(session.urls) == 1
    assert parse_qs(urlparse(session.urls[0]).query)["latest"] == ["1"]


def test_normalization_proves_pair_identity_and_delivery_lag() -> None:
    normalized = futoi_source.normalize_futoi_history(_raw_frame(), "Si")

    assert len(normalized) == 2
    assert set(normalized["client_group"]) == {"FIZ", "YUR"}
    assert normalized["net_position"].sum() == 0
    assert normalized["reported_pair_balance_exact"].all()
    assert normalized["asset_code"].eq("SI").all()
    lag = normalized["available_at"] - normalized["published_at"]
    assert lag.eq(pd.Timedelta(minutes=1)).all()
    assert normalized["contains_prices_returns_targets_or_pnl"].eq(False).all()  # noqa: E712


def test_missing_pair_and_protected_publication_fail_closed() -> None:
    with pytest.raises(ValueError, match="FIZ/YUR pair"):
        futoi_source.normalize_futoi_history(_raw_frame(_rows()[:1]), "Si")

    protected = _rows()
    protected[0][-1] = "2026-01-01 00:00:00"
    protected[1][-1] = "2026-01-01 00:00:00"
    with pytest.raises(ValueError, match="protected"):
        futoi_source.normalize_futoi_history(_raw_frame(protected), "Si")


def test_download_writes_hashed_full_and_daily_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(futoi_source, "SOURCE_START", pd.Timestamp("2020-05-01"))
    monkeypatch.setattr(futoi_source, "SOURCE_END", pd.Timestamp("2020-12-31"))
    monkeypatch.setattr(futoi_source, "TICKERS", ("Si",))
    output = tmp_path / "futoi"

    result = futoi_source.download_futoi_source(
        output,
        session=FakeSession(_rows()),
        fetched_at_utc="2026-09-01T00:00:00Z",
        request_delay_seconds=0.0,
    )

    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    daily = pd.read_parquet(result / "futoi_daily_last.parquet")
    assert len(daily) == 2
    assert manifest["request_count"] == 1
    assert manifest["rows_by_ticker"] == {"Si": 2}
    assert manifest["artifacts"]["processed_daily_last"][
        "sha256"
    ] == futoi_source.sha256_file(
        result / "futoi_daily_last.parquet"
    )
    assert manifest["access_observation"]["raw_redistribution_allowed"] is False
    with pytest.raises(FileExistsError):
        futoi_source.download_futoi_source(output, session=FakeSession(_rows()))
