"""Tests for the official MOEX option-series identifier schema probe."""

from __future__ import annotations

import json

import pytest

from market_lab.futures import moex_option_series_calendar_probe as probe


def _response(columns: list[str], rows: list[list[object]]) -> bytes:
    return json.dumps({"options": {"columns": columns, "data": rows}}).encode()


def test_parser_detects_exact_numeric_option_series_identifier() -> None:
    content = _response(
        ["asset_code", "series_name", "expiration_date", "option_series_id", "series_type"],
        [
            ["RTS", "RTS-9.21M010921", "2021-09-01", 123, "W"],
            ["GAZR", "GAZR-9.21M010921", "2021-09-01", 456, "W"],
        ],
    )

    parsed = probe.parse_response(content)

    assert parsed.total_rows == 2
    assert parsed.core_rows == 1
    assert parsed.identifier_columns == ("option_series_id",)
    assert parsed.frame["option_series_id"].tolist() == [123]


def test_documented_schema_without_numeric_identifier_remains_valid_probe() -> None:
    content = _response(
        ["asset_code", "series_name", "expiration_date", "series_type"],
        [["SI", "Si-9.21M010921", "2021-09-01", "W"]],
    )

    parsed = probe.parse_response(content)

    assert parsed.core_rows == 1
    assert parsed.identifier_columns == ()


def test_market_fields_are_rejected_from_metadata_probe() -> None:
    content = _response(
        ["asset_code", "series_name", "expiration_date", "price"],
        [["BR", "BR-9.21M010921", "2021-09-01", 70.0]],
    )

    with pytest.raises(ValueError, match="market fields"):
        probe.parse_response(content)
