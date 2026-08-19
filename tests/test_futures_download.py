"""Testy strogogo futures-downloader tol'ko na fake-session i synthetic payload."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
import requests

from market_lab.futures.download import (
    FuturesDownloadSettings,
    FuturesIssDownloader,
)
from market_lab.futures.specs import FuturesAssetSpec


class FakeResponse:
    """Imitiruet minimal'nyi requests.Response dlya JSON-otveta."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Sohranyaet nezavisimuyu kopiyu synthetic payload."""
        self.payload = deepcopy(payload)

    def raise_for_status(self) -> None:
        """Imitiruet uspeshnyi HTTP-status."""

    def json(self) -> dict[str, Any]:
        """Vozvrashchaet kopiyu, chtoby parsery ne delili sostoyanie."""
        return deepcopy(self.payload)


class FakeSession:
    """Marshrutiziruet GET v synthetic dispatcher bez setevogo dostupa."""

    def __init__(self, dispatcher: Any) -> None:
        """Sohranyaet dispatcher i audit vypolnennyh vyzovov."""
        self.dispatcher = dispatcher
        self.calls: list[tuple[str, float]] = []
        self.headers: dict[str, str] = {}
        self.closed = False

    def get(self, url: str, timeout: float) -> FakeResponse:
        """Vozvrashchaet payload ili probrosyvaet synthetic oshibku."""
        self.calls.append((url, timeout))
        outcome = self.dispatcher(url)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def close(self) -> None:
        """Fiksiruet zakrytie fake-session."""
        self.closed = True


def _settings(**changes: Any) -> FuturesDownloadSettings:
    """Stroit bystrye testovye limity bez real'nogo backoff."""
    values = {
        "timeout_seconds": 7.0,
        "max_retries": 0,
        "retry_backoff_seconds": 0.0,
        "max_pages": 20,
        "oi_window_days": 10,
        "oi_coverage_tolerance_days": 2,
    }
    values.update(changes)
    return FuturesDownloadSettings(**values)


def _series_payload(include_alias: bool = False) -> dict[str, Any]:
    """Stroit series s outright, optional'nym alias i otbroshennym spread."""
    rows = [
        ["SiH4", "Si-3.24", "2024-01-01", "2024-01-04", "Si", "USD", 0],
    ]
    if include_alias:
        rows.append(
            ["SiH4_2024", "Si-3.24", "2024-01-01", "2024-01-04", "Si", "USD", 0]
        )
    rows.append(
        ["SiH4SiM4", "calendar spread", "2024-01-01", "2024-01-04", "Si", "USD", 0]
    )
    return {
        "series": {
            "columns": [
                "secid",
                "name",
                "start_date",
                "expiration_date",
                "asset_code",
                "underlying_asset",
                "is_traded",
            ],
            "data": rows,
        }
    }


def _boards_payload(secid: str, start_date: str, end_date: str) -> dict[str, Any]:
    """Stroit odin datirovannyi RFUD-segment storage-aliasa."""
    return {
        "boards": {
            "columns": ["secid", "boardid", "history_from", "history_till"],
            "data": [[secid, "RFUD", start_date, end_date]],
        }
    }


def _daily_row(secid: str, trade_date: str) -> list[Any]:
    """Stroit validnuyu torgovuyu stroku daily history."""
    return [
        "RFUD",
        trade_date,
        secid,
        100.0,
        99.0,
        102.0,
        101.0,
        1_000_000.0,
        100.0,
        10_000.0,
        1_015_000.0,
        101.5,
        12,
        "Si",
        100.5,
    ]


def _daily_payload(
    secid: str,
    rows: list[list[Any]],
    cursor_index: int,
    cursor_total: int,
    page_size: int,
) -> dict[str, Any]:
    """Stroit daily history vmeste s obyazatel'nym cursor."""
    return {
        "history": {
            "columns": [
                "boardid",
                "tradedate",
                "secid",
                "open",
                "low",
                "high",
                "close",
                "value",
                "volume",
                "openposition",
                "openpositionvalue",
                "settleprice",
                "numtrades",
                "assetcode",
                "waprice",
            ],
            "data": rows,
        },
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[cursor_index, cursor_total, page_size]],
        },
    }


def _candle_payload(begins: list[datetime]) -> dict[str, Any]:
    """Stroit stranicu validnyh desyatiminutnyh svechei."""
    rows = [
        [
            100.0,
            101.0,
            102.0,
            99.0,
            10_000.0,
            100.0,
            begin.strftime("%Y-%m-%d %H:%M:%S"),
            (begin + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
        ]
        for begin in begins
    ]
    return {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": rows,
        }
    }


def _oi_payload(days: list[date]) -> dict[str, Any]:
    """Stroit po dve participant OI-kategorii na kazhduyu torgovuyu datu."""
    rows: list[list[Any]] = []
    for trade_date in days:
        for is_physical in (0, 1):
            rows.append(
                [trade_date.isoformat(), "Si", is_physical, 10, 11, 100, 101, 1, -1]
            )
    return {
        "open_positions": {
            "columns": [
                "tradedate",
                "asset",
                "is_fiz",
                "persons_long",
                "persons_short",
                "open_position_long",
                "open_position_short",
                "oichange_long",
                "oichange_short",
            ],
            "data": rows,
        }
    }


def _query_int(url: str, name: str) -> int:
    """Chitaet odin cislovoi query-parametr synthetic URL."""
    return int(parse_qs(urlparse(url).query)[name][0])


def test_request_retries_timeout_and_always_passes_timeout(tmp_path: Path) -> None:
    """Proveryaet bounded retry i peredachu timeout v Session.get."""
    outcomes: list[object] = [requests.Timeout("synthetic"), _series_payload()]

    def dispatcher(_: str) -> object:
        """Vozvrashchaet timeout, zatem uspeshnyi JSON."""
        return outcomes.pop(0)

    session = FakeSession(dispatcher)
    downloader = FuturesIssDownloader(
        tmp_path,
        session=session,
        settings=_settings(max_retries=1),
    )
    catalog, _ = downloader.fetch_series(FuturesAssetSpec("Si"))
    assert len(catalog.contracts) == 1
    assert len(session.calls) == 2
    assert {timeout for _, timeout in session.calls} == {7.0}


def test_daily_pagination_reaches_exact_cursor_total(tmp_path: Path) -> None:
    """Proveryaet offsets 0/2 i tochno tri stroki po cursor.total."""
    pages = {
        0: _daily_payload(
            "SiH4",
            [_daily_row("SiH4", "2024-01-01"), _daily_row("SiH4", "2024-01-02")],
            0,
            3,
            2,
        ),
        2: _daily_payload("SiH4", [_daily_row("SiH4", "2024-01-03")], 2, 3, 2),
    }
    session = FakeSession(lambda url: pages[_query_int(url, "start")])
    downloader = FuturesIssDownloader(tmp_path, session=session, settings=_settings())
    result = downloader.fetch_daily(
        FuturesAssetSpec("Si"),
        "SiH4",
        "RFUD",
        date(2024, 1, 1),
        date(2024, 1, 3),
    )
    assert len(result.frame) == 3
    assert [_query_int(url, "start") for url in result.urls] == [0, 2]


def test_daily_truncation_fails_closed(tmp_path: Path) -> None:
    """Proveryaet otkaz, esli stranica koroche cursor-obeshchaniya."""
    payload = _daily_payload("SiH4", [_daily_row("SiH4", "2024-01-01")], 0, 3, 2)
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda _: payload),
        settings=_settings(),
    )
    with pytest.raises(ValueError, match="Usechennaya daily-stranica"):
        downloader.fetch_daily(
            FuturesAssetSpec("Si"),
            "SiH4",
            "RFUD",
            date(2024, 1, 1),
            date(2024, 1, 3),
        )


def test_candles_fetches_after_full_500_row_page(tmp_path: Path) -> None:
    """Proveryaet, chto polnaya stranica ne schitaetsya koncom istorii."""
    first = datetime(2024, 1, 1, 10, 0)
    pages = {
        0: _candle_payload([first + timedelta(minutes=10 * index) for index in range(500)]),
        500: _candle_payload([first + timedelta(minutes=5_000)]),
    }
    session = FakeSession(lambda url: pages[_query_int(url, "start")])
    downloader = FuturesIssDownloader(tmp_path, session=session, settings=_settings())
    result = downloader.fetch_candles(
        FuturesAssetSpec("Si"),
        "SiH4",
        "RFUD",
        date(2024, 1, 1),
        date(2024, 1, 5),
    )
    assert len(result.frame) == 501
    assert [_query_int(url, "start") for url in result.urls] == [0, 500]
    assert {_query_int(url, "limit") for url in result.urls} == {500}


def test_candles_rejects_duplicate_across_pages(tmp_path: Path) -> None:
    """Proveryaet fail-closed pri ignorirovanii serverom parametra start."""
    first = datetime(2024, 1, 1, 10, 0)
    full = _candle_payload([first + timedelta(minutes=10 * index) for index in range(500)])
    duplicate = _candle_payload([first + timedelta(minutes=4_990)])
    pages = {0: full, 500: duplicate}
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda url: pages[_query_int(url, "start")]),
        settings=_settings(),
    )
    with pytest.raises(ValueError, match="Povtor ili nevozrastanie"):
        downloader.fetch_candles(
            FuturesAssetSpec("Si"),
            "SiH4",
            "RFUD",
            date(2024, 1, 1),
            date(2024, 1, 5),
        )


def test_participant_oi_pages_by_date_and_checks_coverage(tmp_path: Path) -> None:
    """Proveryaet neperesekayushchiesya okna i obe kategorii OI."""
    def dispatcher(url: str) -> dict[str, Any]:
        """Stroit OI stroki tochnogo zaproshennogo dvuhdnevnogo okna."""
        query = parse_qs(urlparse(url).query)
        window_start = date.fromisoformat(query["from"][0])
        window_end = date.fromisoformat(query["till"][0])
        days = [
            window_start + timedelta(days=index)
            for index in range((window_end - window_start).days + 1)
        ]
        return _oi_payload(days)

    session = FakeSession(dispatcher)
    downloader = FuturesIssDownloader(
        tmp_path,
        session=session,
        settings=_settings(oi_window_days=2, oi_coverage_tolerance_days=1),
    )
    result = downloader.fetch_participant_oi(
        FuturesAssetSpec("Si"),
        date(2024, 1, 1),
        date(2024, 1, 4),
    )
    assert len(result.frame) == 8
    assert len(result.pages) == 2
    assert [parse_qs(urlparse(url).query)["from"][0] for url in result.urls] == [
        "2024-01-01",
        "2024-01-03",
    ]


def test_participant_oi_accepts_category_major_server_order(tmp_path: Path) -> None:
    """Proveryaet vse daty yurlic pered vsemi datami fizlic kak v real'nom ISS."""
    payload = _oi_payload([date(2024, 1, 1), date(2024, 1, 2)])
    rows = payload["open_positions"]["data"]
    payload["open_positions"]["data"] = [rows[0], rows[2], rows[1], rows[3]]
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda _: payload),
        settings=_settings(oi_window_days=2, oi_coverage_tolerance_days=1),
    )

    result = downloader.fetch_participant_oi(
        FuturesAssetSpec("Si"),
        date(2024, 1, 1),
        date(2024, 1, 2),
    )

    assert len(result.frame) == 4
    assert result.frame["trade_date"].is_monotonic_increasing
    assert result.frame.attrs["raw_time_inversion_count"] == 0


def test_participant_oi_audits_shuffled_dates_without_losing_rows(tmp_path: Path) -> None:
    """Proveryaet raw-inversii kak quality-metriku pri polnom unique nabore."""
    payload = _oi_payload(
        [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    )
    rows = payload["open_positions"]["data"]
    payload["open_positions"]["data"] = [
        rows[0],
        rows[4],
        rows[2],
        rows[1],
        rows[5],
        rows[3],
    ]
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda _: payload),
        settings=_settings(oi_window_days=3, oi_coverage_tolerance_days=1),
    )

    result = downloader.fetch_participant_oi(
        FuturesAssetSpec("Si"),
        date(2024, 1, 1),
        date(2024, 1, 3),
    )

    assert len(result.frame) == 6
    assert result.frame.attrs["raw_time_inversion_count"] == 2


def test_participant_oi_rejects_uncovered_tail(tmp_path: Path) -> None:
    """Proveryaet obnaruzhenie tikhogo usecheniya poslednego OI-okna."""
    payload = _oi_payload([date(2024, 1, 1)])
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda _: payload),
        settings=_settings(oi_window_days=10, oi_coverage_tolerance_days=1),
    )
    with pytest.raises(ValueError, match="ne pokryvaet konec"):
        downloader.fetch_participant_oi(
            FuturesAssetSpec("Si"),
            date(2024, 1, 1),
            date(2024, 1, 4),
        )


def test_daily_only_asset_download_persists_alias_audit_atomically(tmp_path: Path) -> None:
    """Proveryaet all-alias catalog, Parquet, raw gzip i manifest bez candles."""
    def dispatcher(url: str) -> dict[str, Any]:
        """Marshrutiziruet vse endpointy odnogo synthetic asset-nabora."""
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/series.json"):
            return _series_payload(include_alias=True)
        if "/history/" in parsed.path:
            secid = Path(parsed.path).stem
            trade_date = "2024-01-02" if secid == "SiH4" else "2024-01-03"
            return _daily_payload(secid, [_daily_row(secid, trade_date)], 0, 1, 100)
        if "/openpositions/" in parsed.path:
            start = date.fromisoformat(query["from"][0])
            end = date.fromisoformat(query["till"][0])
            return _oi_payload(
                [start + timedelta(days=index) for index in range((end - start).days + 1)]
            )
        if parsed.path.endswith("/securities/SiH4.json"):
            return _boards_payload("SiH4", "2024-01-01", "2024-01-02")
        if parsed.path.endswith("/securities/SiH4_2024.json"):
            return _boards_payload("SiH4_2024", "2024-01-03", "2024-01-04")
        raise AssertionError(f"Neozhidannyi URL: {url}")

    session = FakeSession(dispatcher)
    downloader = FuturesIssDownloader(tmp_path, session=session, settings=_settings())
    result = downloader.download_asset(
        FuturesAssetSpec("Si"),
        date(2024, 1, 1),
        date(2024, 1, 4),
        include_candles=False,
    )
    assert result.contracts == 2
    assert result.excluded == 1
    assert result.board_segments == 2
    assert result.daily_rows == 2
    assert result.candle_rows == 0
    assert result.participant_oi_rows == 8
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["pagination"]["candles_included"] is False
    assert len(manifest["segment_artifacts"]) == 2
    assert all(item["candles_10m"] is None for item in manifest["segment_artifacts"])
    excluded_path = tmp_path / manifest["catalog_artifacts"]["excluded"]["parquet"]["path"]
    excluded = pd.read_parquet(excluded_path)
    assert excluded["exclusion_reason"].tolist() == ["calendar_spread_or_service"]
    raw_path = tmp_path / manifest["catalog_artifacts"]["series"]["raw"]["path"]
    raw = json.loads(gzip.decompress(raw_path.read_bytes()).decode("utf-8"))
    assert len(raw["requests"]) == 1
    assert not any(path.name.startswith(".") for path in tmp_path.rglob("*"))
    assert not any("candles" in url for url, _ in session.calls)


def test_holdout_2026_is_blocked_before_any_request(tmp_path: Path) -> None:
    """Proveryaet fizicheskii guard netronutogo futures holdout 2026."""
    session = FakeSession(lambda _: AssertionError("set' ne dolzhna vyzyvat'sya"))
    downloader = FuturesIssDownloader(tmp_path, session=session, settings=_settings())
    with pytest.raises(ValueError, match="holdout"):
        downloader.download_asset(
            FuturesAssetSpec("Si"),
            date(2025, 1, 1),
            date(2026, 1, 1),
            include_candles=False,
        )
    assert not session.calls


def test_schema_failure_writes_no_artifacts(tmp_path: Path) -> None:
    """Proveryaet, chto nekorrektnyi series ne sozdaet raw ili processed failov."""
    malformed = _series_payload()
    malformed["series"]["columns"].remove("expiration_date")
    malformed["series"]["data"] = [row[:-1] for row in malformed["series"]["data"]]
    downloader = FuturesIssDownloader(
        tmp_path,
        session=FakeSession(lambda _: malformed),
        settings=_settings(),
    )
    with pytest.raises(ValueError):
        downloader.download_asset(
            FuturesAssetSpec("Si"),
            date(2024, 1, 1),
            date(2024, 1, 4),
            include_candles=False,
        )
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]
