"""Tests for sealed MOEX CNYRUBF perpetual source."""

from __future__ import annotations

import copy
import json

import pandas as pd

from market_lab.futures import moex_cny_perpetual_source as source


def _small_config() -> dict:
    config = copy.deepcopy(source.load_config())
    config["source"]["page_size_observed"] = 1
    config["source"]["total_rows_observed"] = 1
    return config


def _history() -> bytes:
    columns = source.load_config()["required_history_columns"]
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


def test_config_is_source_only_and_swaprate_is_lagged() -> None:
    config = source.load_config()

    assert config["source"]["total_rows_observed"] == 764
    assert "SWAPRATE" in config["required_history_columns"]
    assert config["temporal_semantics"]["same_day_swaprate_use"] == "forbidden"
    assert config["live_trading_allowed"] is False


def test_normalize_preserves_swaprate_without_outcomes(monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    frame, total, page_size = source.normalize_page(
        _history(), 0, pd.Timestamp("2026-09-02T00:00:00Z"), config
    )

    assert total == 1
    assert page_size == 1
    assert frame.iloc[0]["swap_rate"] == 2.5
    assert frame.iloc[0]["available_at_utc"] == pd.Timestamp("2025-01-02T21:00:00Z")
    assert not set(config["forbidden_columns"]) & set(frame.columns)
