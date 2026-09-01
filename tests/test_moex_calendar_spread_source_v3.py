"""Tests for the exact empty-RFUD-interval V3 source correction."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.futures import moex_calendar_spread_source as v1
from market_lab.futures import moex_calendar_spread_source_v2 as v2
from market_lab.futures import moex_calendar_spread_source_v3 as v3


def _empty_row() -> dict[str, Any]:
    return {
        "spread_id": "BR:BRF1BRG1:2020-12-31:2021-02-01",
        "logical_asset": "BR",
        "secid": "BRF1BRG1",
        "archive_code": "BR-1.21-2.21",
        "series_start": pd.Timestamp("2020-12-14"),
        "spread_last_trade": pd.Timestamp("2021-01-04"),
        "board_history_from": pd.Timestamp("2020-12-14"),
        "board_history_till": pd.Timestamp("2020-12-30"),
    }


def test_real_v3_protocol_is_sealed_external_and_parents_exact() -> None:
    protocol = v3.load_protocol()

    assert (
        protocol.config_sha256
        == "3d89c51fe674f3b55282aba808ad6f0336cae502956681203f02b0218022f19c"
    )
    assert protocol.output_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
    assert v1.sha256_file(v2.DEFAULT_CONFIG) == v3.PARENT_CONFIG_SHA256
    assert v1.sha256_file(Path(v2.__file__)) == v3.PARENT_IMPLEMENTATION_SHA256
    assert v1.sha256_file(Path(v1.__file__)) == v2.PARENT_IMPLEMENTATION_SHA256


def test_only_exact_declared_empty_interval_is_admitted() -> None:
    row = _empty_row()

    assert v3._is_exact_declared_empty_interval(
        row,
        date(2021, 1, 1),
        date(2020, 12, 30),
    )

    changed = dict(row)
    changed["board_history_till"] = pd.Timestamp("2020-12-29")
    assert not v3._is_exact_declared_empty_interval(
        changed,
        date(2021, 1, 1),
        date(2020, 12, 29),
    )
    assert not v3._is_exact_declared_empty_interval(
        row,
        date(2021, 1, 2),
        date(2020, 12, 30),
    )


def test_v3_module_contains_no_outcome_engine() -> None:
    text = Path(v3.__file__).read_text(encoding="utf-8-sig").lower()

    for forbidden in ("compute_return", "target_values", "strategy_pnl", "equity_curve"):
        assert forbidden not in text
