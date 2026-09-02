"""Tests for sealed intraday stock-futures cash-carry source."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_stock_futures_cash_carry_intraday_source as source


def _row() -> dict[str, object]:
    return {
        "contract_id": "GAZR:GZH4:2024-03-22",
        "logical_asset": "GAZR",
        "asset_code": "GAZR",
        "spot_secid": "GAZP",
        "secid": "GZH4",
        "expiration": pd.Timestamp("2024-03-22"),
        "request_from": pd.Timestamp("2024-01-01"),
        "request_till": pd.Timestamp("2024-03-22"),
    }


def test_protocol_pins_same_61_contracts() -> None:
    protocol = source.load_protocol()
    contracts = pd.read_parquet(protocol.v2_root / "contracts.parquet")

    assert protocol.config_sha256 == source.CONFIG_SHA256
    assert len(contracts) == 61
    assert contracts["contract_id"].nunique() == 61


def test_description_and_candle_parsers_are_exact() -> None:
    description = {
        "description": {
            "columns": ["name", "value"],
            "data": [
                ["SECID", "GZH4"],
                ["ASSETCODE", "GAZR"],
                ["LOTSIZE", "100"],
                ["TYPE", "futures"],
                ["FRSTTRADE", "2023-01-19"],
                ["LSTTRADE", "2024-03-21"],
                ["LSTDELDATE", "2024-03-22"],
            ],
        },
        "boards": {
            "columns": ["secid", "boardid"],
            "data": [["GZH4", "RFUD"]],
        },
    }
    spec = source._parse_description(description, _row())
    candles = {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": [
                [
                    16000,
                    16010,
                    16020,
                    15990,
                    100000,
                    10,
                    "2024-03-01 10:00:00",
                    "2024-03-01 10:09:59",
                ]
            ],
        }
    }
    frame = source._parse_candles(candles, spec)

    assert spec["lot_size_shares"] == 100
    assert tuple(frame.columns) == source.CANDLE_COLUMNS
    assert len(frame) == 1
    assert frame.loc[0, "available_at"] == frame.loc[0, "end_timestamp"]
    assert frame.loc[0, "timestamp"].tz is not None
