"""Tests for the public MOEX volatility-curve change-log pilot."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_volatility_curve_source as source


def _archive(*, duplicate: bool = False, protected: bool = False) -> bytes:
    header = ";".join(source.REQUIRED_COLUMNS)
    time_value = "20260105100000123" if protected else "20210105100000123"
    rows = [
        ["RTS-3.21", "RIH1", time_value, 140000, 0.1, 20, 1, 2, 3, 4, 0.2],
        ["MIX-3.21", "MXH1", "20210105100100123", 3300, 0.2, 21, 1, 2, 3, 4, 0.2],
        ["Si-3.21", "SiH1", "20210105100200123", 75000, 0.3, 22, 1, 2, 3, 4, 0.2],
        ["BR-2.21", "BRG1", "20210105100300123", 54.5, 0.4, 23, 1, 2, 3, 4, 0.1],
        ["GAZR-3.21", "GZH1", "20210105100400123", 22000, 0.5, 24, 1, 2, 3, 4, 0.2],
    ]
    if duplicate:
        rows.append(rows[0])
    body = "\n".join([header, *(";".join(map(str, row)) for row in rows), ""]) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("202101.csv", body.encode("cp1251"))
    return buffer.getvalue()


def _protocol(tmp_path: Path, content: bytes) -> source.VolatilityCurveProtocol:
    return source.VolatilityCurveProtocol(
        config_path=tmp_path / "protocol.yaml",
        config_sha256="b" * 64,
        payload={},
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        download_url="https://ftp.moex.com/pub/FORTS/volat_coeff/202101.zip",
        expected_archive_bytes=len(content),
        archive_member_name="202101.csv",
        output_directory=tmp_path / "curve-output",
    )


def test_parser_preserves_intraday_events_and_coefficients(tmp_path: Path) -> None:
    content = _archive()
    parsed = source.parse_archive_bytes(content, _protocol(tmp_path, content))

    assert parsed.total_archive_rows == 5
    assert parsed.ignored_non_core_rows == 1
    assert parsed.root_counts == {"RTS": 1, "MIX": 1, "SI": 1, "BR": 1}
    assert set(parsed.frame["asset"]) == {"RI", "MIX", "SI", "BR"}
    assert len(parsed.frame) == 4
    assert parsed.frame["event_at"].dt.tz is not None
    assert (
        parsed.frame["available_at"] - parsed.frame["event_at"]
        == pd.Timedelta(minutes=1)
    ).all()
    assert parsed.frame.loc[parsed.frame["asset"].eq("BR"), "futures_price"].iloc[0] == 54.5
    assert not (set(parsed.frame.columns.str.lower()) & source.FORBIDDEN_DERIVED_COLUMNS)


def test_writer_and_raw_replay_are_exact(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.config_path.write_text("synthetic", encoding="utf-8")

    output = source.write_source_from_bytes(
        content,
        protocol,
        fetched_at_utc="2026-09-01T00:00:00Z",
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["counts"]["core_rows"] == 4
    assert manifest["temporal_semantics"]["contains_returns_targets_labels_or_pnl"] is False
    stored = pd.read_parquet(output / "volatility_curve_core4.parquet")
    replay = source.parse_archive_bytes(content, protocol).frame
    pd.testing.assert_frame_equal(stored, replay)


def test_parser_rejects_duplicate_event_instrument(tmp_path: Path) -> None:
    content = _archive(duplicate=True)

    with pytest.raises(ValueError, match="duplicate"):
        source.parse_archive_bytes(content, _protocol(tmp_path, content))


def test_parser_rejects_protected_event(tmp_path: Path) -> None:
    content = _archive(protected=True)

    with pytest.raises(ValueError, match="escaped|protected"):
        source.parse_archive_bytes(content, _protocol(tmp_path, content))


def test_writer_never_overwrites(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.output_directory.mkdir()

    with pytest.raises(FileExistsError):
        source.write_source_from_bytes(content, protocol)
