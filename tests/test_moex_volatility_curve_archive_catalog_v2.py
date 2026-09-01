"""Tests for conservative MOEX archive catalog V2 schema corrections."""

from __future__ import annotations

import io
import zipfile

import pandas as pd

from market_lab.futures import moex_volatility_curve_archive_catalog as v1
from market_lab.futures import moex_volatility_curve_archive_catalog_v2 as v2


def _zip(text: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("probe.csv", text.encode("utf-8"))
    return stream.getvalue()


def _spec(content: bytes) -> v1.ArchiveSpec:
    return v1.ArchiveSpec(
        "synthetic",
        "https://example.invalid/probe.zip",
        len(content),
        "probe.zip",
        pd.Timestamp("2021-01-01"),
        pd.Timestamp("2021-01-31"),
        None,
    )


def test_exact_duplicate_collapses_and_conflicting_key_is_fully_removed() -> None:
    header = "[#NAME];SMALL_NAME;[TIME];S;A;B;C;D;E;T;\n"
    exact = "RTS-near;RTS-near;20210105100000000;0;20;1;1;1;1;0,05;\n"
    conflict_a = "Si-far;Si-far;20210105100000000;0;20;1;1;1;1;0,30;\n"
    conflict_b = "Si-far;Si-far;20210105100000000;1;21;2;2;2;2;0,30;\n"
    content = _zip(header + exact + exact + conflict_a + conflict_b)

    parsed = v2.parse_archive(content, _spec(content))

    assert isinstance(parsed, v2.ParsedLegacy)
    assert parsed.duplicate_observations == 2
    assert parsed.identical_duplicate_observations == 1
    assert parsed.conflicting_duplicate_observations == 1
    assert parsed.conflicting_keys == 1
    assert parsed.conflicting_rows_removed == 2
    assert parsed.conflicting_T_keys == 0
    assert parsed.resolved_frame["full_name"].tolist() == ["RTS-near"]


def test_combined_schema_is_preserved_but_not_maturity_coverage_eligible() -> None:
    text = (
        "SESS_ID;A;B;C;D;E;S;OPTION_SERIES_ID;FUT_ISIN_ID;ISIN;"
        "SETTLEMENT_PRICE_OPEN;BEGIN\n"
        "1;20;1;1;1;1;0;2;3;RTS-9.21;150000;05.01.2021 10:00\n"
        "1;20;1;1;1;1;0;2;3;GAZR-9.21;30000;05.01.2021 10:00\n"
    )
    content = _zip(text)

    parsed = v2.parse_archive(content, _spec(content))
    summary = v2._combined_summary(parsed, "0" * 64)

    assert isinstance(parsed, v2.ParsedCombined)
    assert parsed.total_rows == 2
    assert parsed.ignored_rows == 1
    assert summary["schema_family"] == "combined_without_T"
    assert summary["passes_predeclared_coverage_gate"] is False
    assert summary["coverage_unavailable_reason"] == "missing_T_and_official_series_expiry_join"
