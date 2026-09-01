"""Tests for corrected CNYRUBF source V2."""

from __future__ import annotations

import copy
import json

import pandas as pd

from market_lab.futures import moex_cny_perpetual_source as parent
from market_lab.futures import moex_cny_perpetual_source_v2 as source


def _history(config: dict) -> bytes:
    columns = config["required_history_columns"]
    values = {column: None for column in columns}
    values.update(
        {
            "BOARDID": "RFUD",
            "TRADEDATE": "2025-01-02",
            "SECID": "CNYRUBF",
            "OPEN": 13_000.0,
            "LOW": 12_900.0,
            "HIGH": 13_100.0,
            "CLOSE": 13_050.0,
            "VOLUME": 200,
            "OPENPOSITION": 300,
            "SETTLEPRICE": 13_040.0,
            "SWAPRATE": 2.5,
            "WAPRICE": 13_020.0,
            "NUMTRADES": 100,
            "ASSETCODE": "CNYRUBTOM",
        }
    )
    return json.dumps(
        {
            "history": {"columns": columns, "data": [[values[column] for column in columns]]},
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, 1, 1]],
            },
        }
    ).encode()


def test_v2_changes_only_cursor_total_and_output() -> None:
    v1 = parent.load_config()
    v2 = source.load_config()

    assert v1["source"]["total_rows_observed"] == 764
    assert v2["source"]["total_rows_observed"] == 937
    assert v2["source"]["from"] == v1["source"]["from"]
    assert v2["required_history_columns"] == v1["required_history_columns"]
    assert v2["forbidden_columns"] == v1["forbidden_columns"]
    assert v2["output"]["root"].endswith("-v2")


def test_parent_normalizer_accepts_effective_v2_config() -> None:
    config = copy.deepcopy(source.load_config())
    config["source"]["total_rows_observed"] = 1
    config["source"]["page_size_observed"] = 1
    frame, total, page_size = parent.normalize_page(
        _history(config), 0, pd.Timestamp("2026-09-02T00:00:00Z"), config
    )

    assert total == 1
    assert page_size == 1
    assert frame.iloc[0]["swap_rate"] == 2.5
    assert frame.iloc[0]["security_id"] == "CNYRUBF"
