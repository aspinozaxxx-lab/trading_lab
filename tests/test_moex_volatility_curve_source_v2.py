"""Tests for the bracketed-header MOEX volatility-curve V2 correction."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_volatility_curve_source as v1
from market_lab.futures import moex_volatility_curve_source_v2 as source


def _archive() -> bytes:
    header = "[#NAME];SMALL_NAME;[TIME];FUTURES_PRICE;S;A;B;C;D;E;T;"
    rows = [
        "RTS-3.21os;RTS-3.21os;20210104190007957;142220;0,15;23,3;78,8;0,15;-14,2;1,09;0,2",
        "MIX-3.21os;MIX-3.21os;20210104190008267;3300;0,10;20;2;3;4;5;0,2",
        "Si-3.21os;Si-3.21os;20210104190008730;75000;0,11;21;2;3;4;5;0,2",
        "BR-2.21os;BR-2.21os;20210104190009111;54,5;0,12;22;2;3;4;5;0,1",
    ]
    body = "\r\n".join([header, *rows, ""]).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("202101.csv", body)
    return buffer.getvalue()


def _protocol(tmp_path: Path, content: bytes) -> v1.VolatilityCurveProtocol:
    return v1.VolatilityCurveProtocol(
        config_path=tmp_path / "v2.yaml",
        config_sha256="c" * 64,
        payload={},
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        download_url="https://ftp.moex.com/pub/FORTS/volat_coeff/202101.zip",
        expected_archive_bytes=len(content),
        archive_member_name="202101.csv",
        output_directory=tmp_path / "v2-output",
    )


def test_v2_normalizes_only_brackets_terminal_cell_and_decimal_comma(tmp_path: Path) -> None:
    content = _archive()
    parsed = source.parse_archive_bytes(content, _protocol(tmp_path, content))

    assert len(parsed.frame) == 4
    assert parsed.root_counts == {"RTS": 1, "MIX": 1, "SI": 1, "BR": 1}
    assert parsed.frame.loc[parsed.frame["asset"].eq("RI"), "a"].iloc[0] == 23.3
    assert parsed.frame.loc[parsed.frame["asset"].eq("BR"), "futures_price"].iloc[0] == 54.5
    assert not (set(parsed.frame.columns.str.lower()) & v1.FORBIDDEN_DERIVED_COLUMNS)


def test_v1_rejects_the_real_bracketed_header_shape(tmp_path: Path) -> None:
    content = _archive()

    with pytest.raises(ValueError, match="header"):
        v1.parse_archive_bytes(content, _protocol(tmp_path, content))


def test_v2_writer_preserves_original_raw_bytes(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.config_path.write_text("synthetic", encoding="utf-8")

    output = source.write_source_from_bytes(
        content,
        protocol,
        acquisition_transport="synthetic_test",
        fetched_at_utc="2026-09-01T00:00:00Z",
    )

    assert (output / "official_moex_volatility_curve_202101.zip").read_bytes() == content
    stored = pd.read_parquet(output / "volatility_curve_core4.parquet")
    replay = source.parse_archive_bytes(content, protocol).frame
    pd.testing.assert_frame_equal(stored, replay)
