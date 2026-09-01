"""Tests for the physically isolated pre-2026 stock intraday source."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from market_lab.stocks import intraday_pre2026_source as source


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_source(root: Path, tickers: tuple[str, ...] = ("AAA", "BBB")) -> Path:
    root.mkdir()
    results = []
    for index, ticker in enumerate(tickers):
        path = root / f"{ticker}_TQBR_10m_2018-01-01_2026-08-16.parquet"
        frame = pd.DataFrame(
            {
                "open": [100.0 + index, 101.0 + index],
                "high": [101.0 + index, 102.0 + index],
                "low": [99.0 + index, 100.0 + index],
                "close": [100.5 + index, 101.5 + index],
                "volume": [1000, 2000],
                "value": [100_000.0, 202_000.0],
                "timestamp": pd.to_datetime(
                    ["2025-12-30T10:00:00Z", "2026-01-02T10:00:00Z"]
                ),
            }
        )
        frame.to_parquet(path, index=False)
        results.append({"ticker": ticker, "sha256": _sha(path)})
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"source": "MOEX ISS", "results": results}),
        encoding="utf-8-sig",
    )
    return manifest


def _build(tmp_path: Path, tickers: tuple[str, ...] = ("AAA", "BBB")) -> Path:
    source_root = tmp_path / "source"
    manifest = _fixture_source(source_root, tickers)
    return source.build_bundle(
        source_root=source_root,
        source_manifest_path=manifest,
        output_directory=tmp_path / "output",
        expected_tickers=tickers,
        expected_manifest_sha256=_sha(manifest),
        expected_manifest_bytes=manifest.stat().st_size,
        cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        row_group_size=1,
    )


def test_build_physically_excludes_protected_rows_and_derived_columns(tmp_path: Path) -> None:
    output = _build(tmp_path)
    frame = pd.read_parquet(output / "AAA_TQBR_10m_pre2026.parquet")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))

    assert len(frame) == 1
    assert frame.iloc[0]["timestamp"] == pd.Timestamp("2025-12-30T10:00:00Z")
    assert tuple(frame.columns) == source.SOURCE_COLUMNS
    assert manifest["contains_returns_labels_targets_or_pnl"] is False
    assert all(source.audit_bundle(output, expected_tickers=("AAA", "BBB")).values())


def test_build_refuses_source_hash_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    manifest = _fixture_source(source_root, ("AAA",))
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    payload["results"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8-sig")

    with pytest.raises(ValueError, match="source parquet SHA mismatch"):
        source.build_bundle(
            source_root=source_root,
            source_manifest_path=manifest,
            output_directory=tmp_path / "output",
            expected_tickers=("AAA",),
            expected_manifest_sha256=_sha(manifest),
            expected_manifest_bytes=manifest.stat().st_size,
            cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_build_is_immutable(tmp_path: Path) -> None:
    output = _build(tmp_path)
    with pytest.raises(FileExistsError):
        source.build_bundle(
            source_root=tmp_path / "source",
            source_manifest_path=tmp_path / "source/manifest.json",
            output_directory=output,
            expected_tickers=("AAA", "BBB"),
            expected_manifest_sha256=_sha(tmp_path / "source/manifest.json"),
            expected_manifest_bytes=(tmp_path / "source/manifest.json").stat().st_size,
            cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_build_requires_exact_ticker_universe(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    manifest = _fixture_source(source_root, ("AAA", "BBB"))
    with pytest.raises(ValueError, match="ticker universe mismatch"):
        source.build_bundle(
            source_root=source_root,
            source_manifest_path=manifest,
            output_directory=tmp_path / "output",
            expected_tickers=("AAA",),
            expected_manifest_sha256=_sha(manifest),
            expected_manifest_bytes=manifest.stat().st_size,
            cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        )
