"""Tests for the outcome-free MOEX volatility-curve archive catalog."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from market_lab.futures import moex_volatility_curve_archive_catalog as catalog


def _archive(rows: list[str], member: str = "probe.csv") -> bytes:
    header = "[#NAME];SMALL_NAME;[TIME];S;A;B;C;D;E;T;\r\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, (header + "".join(rows)).encode("cp1251"))
    return stream.getvalue()


def _row(name: str, timestamp: str, maturity: float) -> str:
    value = str(maturity).replace(".", ",")
    return f"{name};{name};{timestamp};0;20;1;1;1;1;{value};\r\n"


def _spec(content: bytes) -> catalog.ArchiveSpec:
    return catalog.ArchiveSpec(
        archive_id="synthetic",
        url="https://example.invalid/probe.zip",
        expected_bytes=len(content),
        cache_file="probe.zip",
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        known_sha256=None,
    )


def test_parser_normalizes_bracketed_header_and_keeps_nonpositive_T() -> None:
    content = _archive(
        [
            _row("RTS-3.21os", "20210105100000000", 0.20),
            _row("Si-3.21os", "20210105100001000", -0.01),
            _row("GAZR-3.21os", "20210105100002000", 0.20),
        ]
    )

    parsed = catalog.parse_archive(content, _spec(content))

    assert parsed.total_rows == 3
    assert parsed.ignored_rows == 1
    assert tuple(parsed.frame["asset"]) == ("RI", "SI")
    assert parsed.frame["curve_feature_eligible"].tolist() == [True, False]
    assert parsed.member_name == "probe.csv"


def test_full_snapshots_cover_both_constant_maturities_for_every_asset() -> None:
    rows: list[str] = []
    for timestamp in pd.date_range("2021-01-05 10:00", "2021-01-05 23:50", freq="10min"):
        encoded = timestamp.strftime("%Y%m%d%H%M%S") + "000"
        for root in ("RTS", "MIX", "Si", "BR"):
            rows.append(_row(f"{root}-near", encoded, 20 / 365))
            rows.append(_row(f"{root}-far", encoded, 120 / 365))
    content = _archive(rows)
    parsed = catalog.parse_archive(content, _spec(content))

    panel = catalog.coverage_panel(parsed.frame)

    assert len(panel) == catalog.EXPECTED_GRID_POINTS * len(catalog.ASSETS)
    assert panel["complete_30d_90d"].all()
    assert tuple(panel.loc[panel["decision_at"].eq(panel["decision_at"].min()), "asset"]) == (
        catalog.ASSETS
    )


def test_evening_only_archive_fails_predeclared_coverage_gate() -> None:
    rows: list[str] = []
    for timestamp in pd.date_range("2021-01-05 19:00", "2021-01-05 23:50", freq="10min"):
        encoded = timestamp.strftime("%Y%m%d%H%M%S") + "000"
        for root in ("RTS", "MIX", "Si", "BR"):
            rows.append(_row(f"{root}-near", encoded, 20 / 365))
            rows.append(_row(f"{root}-far", encoded, 120 / 365))
    content = _archive(rows)
    parsed = catalog.parse_archive(content, _spec(content))

    summary = catalog.archive_summary(parsed, "0" * 64)

    assert summary["day_session_dates"] == 0
    assert summary["evening_session_dates"] == 1
    assert summary["passes_predeclared_coverage_gate"] is False


def test_protected_event_is_rejected() -> None:
    content = _archive([_row("RTS-3.26os", "20260105100000000", 0.2)])
    spec = catalog.ArchiveSpec(
        archive_id="protected",
        url="https://example.invalid/protected.zip",
        expected_bytes=len(content),
        cache_file="protected.zip",
        source_start=pd.Timestamp("2026-01-01"),
        source_end=pd.Timestamp("2026-01-31"),
        known_sha256=None,
    )

    with pytest.raises(ValueError, match="protected"):
        catalog.parse_archive(content, spec)
