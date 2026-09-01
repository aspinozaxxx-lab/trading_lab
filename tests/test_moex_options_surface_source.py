"""Tests for the immutable target-free MOEX options pilot source."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_options_surface_source as source


def _archive(*, first_security_id: str = "RI125000BA1") -> bytes:
    header = ";".join(source.REQUIRED_ARCHIVE_COLUMNS)
    rows = [
        [
            "ROPD",
            "2021-01-04",
            first_security_id,
            100,
            90,
            110,
            105,
            1,
            2,
            3,
            4,
            101,
            102,
            5,
            6,
            7,
            103,
        ],
        [
            "ROPD",
            "2021-01-04",
            "RI125000BM1",
            120,
            110,
            130,
            125,
            1,
            2,
            3,
            4,
            121,
            122,
            -5,
            6,
            7,
            123,
        ],
        ["ROPD", "2021-01-05", "MX3500BB1", 10, 9, 11, 10, 1, 2, 3, 4, 10, 10, 0, 6, 7, 10],
        ["ROPD", "2021-01-05", "SI75000BN1A", 20, 19, 21, 20, 1, 2, 3, 4, 20, 20, 0, 6, 7, 20],
        ["ROPD", "2021-01-06", "BR60BC1", 2, 1, 3, 2, 1, 2, 3, 4, 2, 2, 0, 6, 7, 2],
        ["ROPD", "2021-01-06", "GZ200BA1", 2, 1, 3, 2, 1, 2, 3, 4, 2, 2, 0, 6, 7, 2],
    ]
    body = "\n".join([header, *(";".join(map(str, row)) for row in rows), ""]) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("securities.csv", body.encode("utf-8-sig"))
    return buffer.getvalue()


def _protocol(tmp_path: Path, archive_bytes: bytes) -> source.OptionsSourceProtocol:
    payload = {
        "temporal_semantics": {"same_day_signal_allowed": False},
    }
    return source.OptionsSourceProtocol(
        config_path=tmp_path / "protocol.yaml",
        config_sha256="a" * 64,
        payload=payload,
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        download_url=(
            "https://iss.moex.com/iss/downloads/engines/futures/markets/options/"
            "years/2021/months/01/securities.csv.zip"
        ),
        expected_archive_bytes=len(archive_bytes),
        archive_member_name="securities.csv",
        output_directory=tmp_path / "output",
    )


def test_short_code_parser_decodes_side_month_and_week() -> None:
    call = source.parse_option_short_code("RI125000BA1")
    put = source.parse_option_short_code("si75000bn1a")

    assert call == {
        "source_root": "RI",
        "asset": "RI",
        "strike": 125000.0,
        "settlement_code": "B",
        "option_type": "call",
        "encoded_expiry_month": 1,
        "encoded_expiry_year_digit": 1,
        "encoded_week_code": None,
    }
    assert put is not None
    assert put["asset"] == "SI"
    assert put["option_type"] == "put"
    assert put["encoded_expiry_month"] == 2
    assert put["encoded_week_code"] == "A"
    assert source.parse_option_short_code("GZ200BA1") is None


def test_parser_filters_without_price_or_outcome_selection(tmp_path: Path) -> None:
    content = _archive()
    parsed = source.parse_archive_bytes(content, _protocol(tmp_path, content))

    assert parsed.total_archive_rows == 6
    assert parsed.ignored_non_core_rows == 1
    assert len(parsed.frame) == 5
    assert parsed.root_counts == {"RI": 2, "MX": 1, "SI": 1, "BR": 1}
    assert set(parsed.frame["asset"]) == {"RI", "MIX", "SI", "BR"}
    assert parsed.frame["source_date"].max() < source.PROTECTED_FROM
    assert (parsed.frame["available_at"].dt.hour == 0).all()
    assert not (set(parsed.frame.columns.str.lower()) & source.FORBIDDEN_DERIVED_COLUMNS)


def test_write_and_raw_replay_are_exact(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.config_path.write_text("synthetic", encoding="utf-8")
    output = source.write_source_from_bytes(
        content,
        protocol,
        fetched_at_utc="2026-09-01T00:00:00Z",
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["counts"]["core_rows"] == 5
    assert manifest["temporal_semantics"]["contains_returns_targets_labels_or_pnl"] is False
    stored = pd.read_parquet(output / "options_daily_core4.parquet")
    replay = source.parse_archive_bytes(content, protocol).frame
    pd.testing.assert_frame_equal(stored, replay)
    assert not (tmp_path / "output.tmp").exists()


def test_parser_rejects_unparsed_core_prefix(tmp_path: Path) -> None:
    content = _archive(first_security_id="RI_NOT_CODE_")
    protocol = _protocol(tmp_path, content)

    with pytest.raises(ValueError, match="unparsed core-prefixed"):
        source.parse_archive_bytes(content, protocol)


def test_writer_never_overwrites(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.output_directory.mkdir()

    with pytest.raises(FileExistsError):
        source.write_source_from_bytes(content, protocol)
