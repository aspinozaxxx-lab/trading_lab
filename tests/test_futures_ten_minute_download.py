"""Testy izolirovannogo v7 10m downloader tol'ko na fake ISS-session."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures.specs import FuturesAssetSpec
from market_lab.futures.ten_minute_download import (
    TEN_MINUTE_ASSETS,
    TenMinuteDownloadSettings,
    TenMinuteIssDownloader,
    TenMinuteSegmentPlan,
    download_ten_minute_asset,
    finalize_ten_minute_dataset,
    verify_ten_minute_asset,
    verify_ten_minute_dataset,
)


class FakeResponse:
    """Imitiruet uspeshnyi requests.Response bez seti."""

    def __init__(self, payload: dict[str, object]) -> None:
        """Sokhranyaet odin synthetic JSON payload."""
        self.payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        """Podtverzhdaet uspeshnyi synthetic HTTP-status."""

    def json(self) -> dict[str, object]:
        """Vozvrashchaet synthetic JSON payload."""
        return self.payload


class FakeSession:
    """Zapominaet URL i delegiruet payload lokal'nomu dispatcher."""

    def __init__(self, dispatcher: object) -> None:
        """Prinimaet vyzyvaemyi dispatcher bez sozdaniya setevogo klienta."""
        self.dispatcher = dispatcher
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float) -> FakeResponse:
        """Zapominaet timeout-bound GET i vozvrashchaet synthetic response."""
        assert timeout > 0.0
        self.calls.append(url)
        payload = self.dispatcher(url)  # type: ignore[operator]
        return FakeResponse(payload)

    def close(self) -> None:
        """Ne delaet nichego dlya vnedrennoi fake-session."""


def _sha256(path: Path) -> str:
    """Vychislyaet testovyi SHA-256 nebol'shogo artefakta."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _settings() -> TenMinuteDownloadSettings:
    """Otkluchaet pacing/retry v bystryh unit-testah."""
    return TenMinuteDownloadSettings(
        max_retries=0,
        minimum_request_interval_seconds=0.0,
        progress_every_pages=1,
    )


def _candle_payload(begins: list[datetime], *, value: float = 0.0) -> dict[str, object]:
    """Stroit validnuyu candles-stranicu s razreshennym nulevym value."""
    return {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": [
                [
                    100.0,
                    101.0,
                    102.0,
                    99.0,
                    value,
                    10.0,
                    begin.strftime("%Y-%m-%d %H:%M:%S"),
                    (begin + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
                ]
                for begin in begins
            ],
        }
    }


def _write_source_plan(
    source_root: Path,
    asset_code: str,
    secid: str,
    start_date: date = date(2018, 1, 1),
    end_date: date = date(2025, 12, 31),
) -> TenMinuteSegmentPlan:
    """Pishet minimal'nyi, no hash-proveryaemyi v5 source-plan."""
    asset = FuturesAssetSpec(asset_code)
    contract_id = f"{asset_code}:{secid}:2025-12-15"
    segment_id = f"{contract_id}:RFUD:{start_date.isoformat()}:{end_date.isoformat()}"
    plan = TenMinuteSegmentPlan(
        canonical_segment_id=segment_id,
        canonical_contract_id=contract_id,
        secid=secid,
        board_id="RFUD",
        requested_start=start_date,
        requested_end=end_date,
    )
    parquet = (
        source_root / "processed" / "futures_v5" / asset_code / "catalog" / "segments.parquet"
    )
    parquet.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "canonical_segment_id": segment_id,
                "canonical_contract_id": contract_id,
                "secid": secid,
                "boardid": "RFUD",
                "segment_start": pd.Timestamp(start_date),
                "segment_end": pd.Timestamp(end_date),
            }
        ]
    ).to_parquet(parquet, index=False)
    parquet_record = {
        "path": parquet.relative_to(source_root).as_posix(),
        "rows": 1,
        "pages": 1,
        "bytes": parquet.stat().st_size,
        "sha256": _sha256(parquet),
    }
    manifest = {
        "asset": asdict(asset),
        "requested_start": start_date.isoformat(),
        "requested_end": end_date.isoformat(),
        "catalog_artifacts": {"segments": {"parquet": parquet_record}},
        "segment_artifacts": [
            {
                "canonical_segment_id": segment_id,
                "canonical_contract_id": contract_id,
                "secid": secid,
                "boardid": "RFUD",
                "requested_start": start_date.isoformat(),
                "requested_end": end_date.isoformat(),
            }
        ],
    }
    manifest_path = (
        source_root
        / "processed"
        / "futures_v5"
        / asset_code
        / f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, default=str),
        encoding="utf-8-sig",
    )
    return plan


def test_fetch_segment_paginates_500_plus_one_and_preserves_zero_value() -> None:
    """Proveryaet cursor 0/500, page SHA i nulevoi oborot bez podmeny."""
    first = datetime(2024, 1, 1, 10, 0)
    pages = {
        0: _candle_payload([first + timedelta(minutes=10 * index) for index in range(500)]),
        500: _candle_payload([first + timedelta(minutes=5_000)]),
    }
    session = FakeSession(lambda url: pages[int(parse_qs(urlparse(url).query)["start"][0])])
    downloader = TenMinuteIssDownloader(session=session, settings=_settings())
    plan = TenMinuteSegmentPlan(
        "Si:SiH5:2025-03-20:RFUD:2018-01-01:2025-12-31",
        "Si:SiH5:2025-03-20",
        "SiH5",
        "RFUD",
        date(2018, 1, 1),
        date(2025, 12, 31),
    )

    fetched = downloader.fetch_segment(FuturesAssetSpec("Si"), plan)

    assert len(fetched.frame) == 501
    assert (fetched.frame["value"] == 0.0).all()
    assert [page["cursor_start"] for page in fetched.page_audit] == [0, 500]
    assert fetched.page_audit[-1]["terminal"] is True
    assert all(len(page["payload_sha256"]) == 64 for page in fetched.page_audit)


def test_fetch_segment_accepts_honest_empty_segment() -> None:
    """Proveryaet complete_empty vmesto synthetic stroki ili skrytogo otkaza."""
    session = FakeSession(lambda _: _candle_payload([]))
    downloader = TenMinuteIssDownloader(session=session, settings=_settings())
    plan = TenMinuteSegmentPlan(
        "BR:BRZ5:2025-12-01:RFUD:2018-01-01:2025-12-31",
        "BR:BRZ5:2025-12-01",
        "BRZ5",
        "RFUD",
        date(2018, 1, 1),
        date(2025, 12, 31),
    )

    fetched = downloader.fetch_segment(FuturesAssetSpec("BR"), plan)

    assert fetched.frame.empty
    assert list(fetched.frame.columns)
    assert fetched.page_audit[0]["row_count"] == 0


def test_fetch_segment_rejects_duplicate_between_pages() -> None:
    """Proveryaet fail-closed pri ignorirovanii serverom cursor start."""
    first = datetime(2024, 1, 1, 10, 0)
    full = _candle_payload([first + timedelta(minutes=10 * index) for index in range(500)])
    pages = {0: full, 500: _candle_payload([first + timedelta(minutes=4_990)])}
    session = FakeSession(lambda url: pages[int(parse_qs(urlparse(url).query)["start"][0])])
    downloader = TenMinuteIssDownloader(session=session, settings=_settings())
    plan = TenMinuteSegmentPlan(
        "RTS:RIH5:2025-03-20:RFUD:2018-01-01:2025-12-31",
        "RTS:RIH5:2025-03-20",
        "RIH5",
        "RFUD",
        date(2018, 1, 1),
        date(2025, 12, 31),
    )

    with pytest.raises(ValueError, match="Povtor ili nevozrastanie"):
        downloader.fetch_segment(FuturesAssetSpec("RTS"), plan)


def test_holdout_guard_runs_before_any_request() -> None:
    """Proveryaet fizicheskii blok 2026 do vyzova fake-session."""
    session = FakeSession(lambda _: pytest.fail("set' ne dolzhna vyzyvat'sya"))
    downloader = TenMinuteIssDownloader(session=session, settings=_settings())
    plan = TenMinuteSegmentPlan(
        "Si:SiH6:2026-03-19:RFUD:2025-01-01:2026-01-01",
        "Si:SiH6:2026-03-19",
        "SiH6",
        "RFUD",
        date(2025, 1, 1),
        date(2026, 1, 1),
    )

    with pytest.raises(ValueError, match="holdout"):
        downloader.fetch_segment(FuturesAssetSpec("Si"), plan)
    assert not session.calls


def test_asset_resume_and_full_raw_parquet_verification(tmp_path: Path) -> None:
    """Proveryaet completion-marker, resume bez seti i polnyi reparse raw."""
    source_root = tmp_path / "source"
    data_root = tmp_path / "stage"
    _write_source_plan(source_root, "Si", "SiH5")
    payload = _candle_payload([datetime(2024, 1, 1, 10, 0)], value=0.0)
    session = FakeSession(lambda _: payload)
    downloader = TenMinuteIssDownloader(session=session, settings=_settings())

    manifest_path = download_ten_minute_asset(
        data_root,
        source_root,
        "Si",
        downloader,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    record = {
        "asset_code": "Si",
        "path": manifest_path.relative_to(data_root).as_posix(),
        "rows": 1,
        "pages": 1,
        "segments": 1,
        "empty_segments": 0,
        "bytes": manifest_path.stat().st_size,
        "sha256": _sha256(manifest_path),
    }
    assert verify_ten_minute_asset(data_root, source_root, record) == {
        "rows": 1,
        "pages": 1,
        "segments": 1,
    }
    assert manifest["counts"]["rows"] == 1

    no_network = FakeSession(lambda _: pytest.fail("resume ne dolzhen vyzyvat' set'"))
    resumed_path = download_ten_minute_asset(
        data_root,
        source_root,
        "Si",
        TenMinuteIssDownloader(session=no_network, settings=_settings()),
    )
    assert resumed_path == manifest_path
    assert not no_network.calls


def test_full_four_asset_finalize_and_verify_without_network(tmp_path: Path) -> None:
    """Proveryaet, chto dataset-marker voznikayet tol'ko posle vseh chetyreh assetov."""
    source_root = tmp_path / "source"
    data_root = tmp_path / "stage"
    secids = {"Si": "SiH5", "RTS": "RIH5", "BR": "BRH5", "MIX": "MXH5"}
    for asset_code, secid in secids.items():
        _write_source_plan(source_root, asset_code, secid)
    with pytest.raises(FileNotFoundError, match="Net complete"):
        finalize_ten_minute_dataset(data_root)
    downloader = TenMinuteIssDownloader(
        session=FakeSession(lambda _: _candle_payload([])),
        settings=_settings(),
    )
    for asset_code in TEN_MINUTE_ASSETS:
        download_ten_minute_asset(data_root, source_root, asset_code, downloader)

    dataset_path = finalize_ten_minute_dataset(data_root)

    assert dataset_path.is_file()
    assert verify_ten_minute_dataset(data_root, source_root) == {
        "rows": 0,
        "pages": 4,
        "segments": 4,
    }
