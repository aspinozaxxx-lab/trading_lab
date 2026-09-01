"""Tests for preserving and masking finite nonpositive MOEX curve maturity."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_volatility_curve_source as v1
from market_lab.futures import moex_volatility_curve_source_v2 as v2
from market_lab.futures import moex_volatility_curve_source_v3 as source


def _archive() -> bytes:
    header = "[#NAME];SMALL_NAME;[TIME];FUTURES_PRICE;S;A;B;C;D;E;T;"
    rows = [
        "RTS-3.21os;RTS-3.21os;20210104190007957;142220;0,15;23,3;78,8;0,15;-14,2;1,09;0,2",
        "RTS-06.01.21os;RTS-06.01.21os;20210106235007957;142220;0,15;23,3;78,8;0,15;-14,2;1,09;-0,0001",
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
        config_path=tmp_path / "v3.yaml",
        config_sha256="d" * 64,
        payload={
            "source": {"archive_sha256": __import__("hashlib").sha256(content).hexdigest()}
        },
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        download_url="https://ftp.moex.com/pub/FORTS/volat_coeff/202101.zip",
        expected_archive_bytes=len(content),
        archive_member_name="202101.csv",
        output_directory=tmp_path / "v3-output",
    )


def test_v3_preserves_negative_T_and_masks_it(tmp_path: Path) -> None:
    content = _archive()
    parsed = source.parse_archive_bytes(content, _protocol(tmp_path, content))

    assert len(parsed.frame) == 5
    expired = parsed.frame.loc[parsed.frame["years_to_expiry"].le(0.0)]
    assert len(expired) == 1
    assert expired["expired_or_at_expiry"].all()
    assert not expired["curve_feature_eligible"].any()
    assert parsed.frame.loc[parsed.frame["years_to_expiry"].gt(0.0), "curve_feature_eligible"].all()


def test_v2_rejects_the_same_negative_T_row(tmp_path: Path) -> None:
    content = _archive()

    with pytest.raises(ValueError, match="positive"):
        v2.parse_archive_bytes(content, _protocol(tmp_path, content))


def test_v3_writer_requires_exact_archive_sha(tmp_path: Path) -> None:
    content = _archive()
    protocol = _protocol(tmp_path, content)
    protocol.config_path.write_text("synthetic", encoding="utf-8")
    mutated = bytearray(content)
    mutated[-1] ^= 1

    with pytest.raises(ValueError, match="SHA-256"):
        source.write_source_from_bytes(
            bytes(mutated),
            protocol,
            acquisition_transport="synthetic_test",
        )
