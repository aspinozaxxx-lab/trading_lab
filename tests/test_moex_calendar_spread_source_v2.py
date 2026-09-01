"""Tests for the isolated parser-only calendar-spread source V2 correction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures import moex_calendar_spread_source as v1
from market_lab.futures import moex_calendar_spread_source_v2 as v2


def _catalog_row() -> dict[str, Any]:
    return {
        "spread_id": "SI:SiZ5SiH6:2025-12-18:2026-03-19",
        "logical_asset": "SI",
        "asset_code": "Si",
        "secid": "SiZ5SiH6",
        "near_secid": "SiZ5",
        "far_secid": "SiH6",
        "archive_code": "Si-12.25-3.26",
        "series_start": pd.Timestamp("2025-09-12"),
        "spread_last_trade": pd.Timestamp("2025-12-18"),
        "near_expiration": pd.Timestamp("2025-12-18"),
        "far_expiration": pd.Timestamp("2026-03-19"),
        "board_id": "RFUD",
    }


def _payload(assetcode: Any) -> dict[str, Any]:
    columns = [
        "BOARDID",
        "TRADEDATE",
        "SECID",
        "OPEN",
        "LOW",
        "HIGH",
        "CLOSE",
        "OPENPOSITIONVALUE",
        "VALUE",
        "VOLUME",
        "OPENPOSITION",
        "SETTLEPRICE",
        "SWAPRATE",
        "WAPRICE",
        "CHANGE",
        "QTY",
        "NUMTRADES",
        "SHORTNAME",
        "ASSETCODE",
    ]
    row = [
        "RFUD",
        "2025-09-15",
        "SiZ5SiH6",
        -25.0,
        -31.0,
        -20.0,
        -22.0,
        1000.0,
        5000.0,
        50.0,
        10.0,
        -23.0,
        None,
        -24.0,
        None,
        50.0,
        5.0,
        "SiZ5SiH6",
        assetcode,
    ]
    return {
        "history": {"columns": columns, "data": [row]},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, 1, 100]],
        },
    }


def test_real_v2_protocol_is_sealed_external_and_parent_exact() -> None:
    protocol = v2.load_protocol()

    assert (
        protocol.config_sha256
        == "be770102469677a3d5b88c79e976799298072aa77c45c405b31387a9fb809173"
    )
    assert protocol.output_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
    assert v1.sha256_file(v1.DEFAULT_CONFIG) == v2.PARENT_CONFIG_SHA256
    assert v1.sha256_file(Path(v1.__file__)) == v2.PARENT_IMPLEMENTATION_SHA256


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_only_blank_assetcode_is_normalized_without_mutating_raw(blank: str) -> None:
    payload = _payload(blank)

    parsed, cursor = v2.parse_spread_history_page(payload, _catalog_row())

    assert cursor.total == 1
    assert parsed["asset_code"].tolist() == ["Si"]
    assert parsed["close"].tolist() == [-22.0]
    assert payload["history"]["data"][0][-1] == blank


def test_nonblank_mismatched_assetcode_remains_rejected() -> None:
    with pytest.raises(ValueError, match="returned another asset code"):
        v2.parse_spread_history_page(_payload("RTS"), _catalog_row())


def test_parent_parser_patch_is_always_restored() -> None:
    original = v1.parse_spread_history_page

    with (
        pytest.raises(RuntimeError, match="synthetic stop"),
        v2._patched_parent_parser(),
    ):
        assert v1.parse_spread_history_page is v2.parse_spread_history_page
        raise RuntimeError("synthetic stop")

    assert v1.parse_spread_history_page is original
