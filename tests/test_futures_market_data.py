"""Testy strogih parserov futures market data bez setevogo dostupa."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import (
    FuturesAssetSpec,
    parse_futures_candles_payload,
    parse_futures_daily_payload,
    parse_futures_participant_oi_payload,
)


def _daily_payload() -> dict[str, object]:
    """Stroit traded i settlement-only stroki vmeste s cursor."""
    columns = [
        "BOARDID",
        "TRADEDATE",
        "SECID",
        "OPEN",
        "LOW",
        "HIGH",
        "CLOSE",
        "VALUE",
        "VOLUME",
        "OPENPOSITION",
        "OPENPOSITIONVALUE",
        "SETTLEPRICE",
        "NUMTRADES",
        "ASSETCODE",
        "WAPRICE",
    ]
    return {
        "history": {
            "columns": columns,
            "data": [
                [
                    "RFUD",
                    "2018-03-01",
                    "SiH8_2018",
                    100.0,
                    99.0,
                    103.0,
                    102.0,
                    1_000_000.0,
                    10_000.0,
                    50_000.0,
                    5_075_000.0,
                    101.5,
                    500,
                    "Si",
                    101.25,
                ],
                [
                    "RFUD",
                    "2018-03-16",
                    "SiH8_2018",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    104.0,
                    0,
                    None,
                    None,
                ],
            ],
        },
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, 250, 100]],
        },
    }


def test_daily_parser_preserves_settlement_only_and_cursor() -> None:
    """Proveryaet traded/settlement flag i vosstanovlenie starogo pustogo ASSETCODE."""
    frame, cursor = parse_futures_daily_payload(
        _daily_payload(),
        FuturesAssetSpec("Si"),
        expected_secid="SiH8_2018",
    )
    assert frame["has_trade"].tolist() == [True, False]
    assert frame["has_settlement"].tolist() == [True, True]
    assert frame["asset_code"].tolist() == ["Si", "Si"]
    assert pd.isna(frame.iloc[1]["close"])
    assert frame.iloc[1]["settle"] == 104.0
    assert cursor.next_index == 100


def test_daily_parser_preserves_reported_trade_without_ohlc_as_nonexecutable() -> None:
    """Proveryaet real'nuyu anomaliyu ISS bez podstanovki synthetic OHLC."""
    payload = _daily_payload()
    anomaly = payload["history"]["data"][0].copy()
    anomaly[1] = "2019-04-19"
    anomaly[2] = "SiM0"
    anomaly[3:7] = [None, None, None, None]
    anomaly[7] = 7_654_507.0
    anomaly[8] = 113.0
    anomaly[9] = 264.0
    anomaly[10] = 17_976_816.0
    anomaly[11] = 68_094.0
    anomaly[12] = 1
    anomaly[14] = 0.0
    payload["history"]["data"] = [anomaly]
    payload["history.cursor"]["data"] = [[0, 1, 100]]

    frame, _ = parse_futures_daily_payload(
        payload,
        FuturesAssetSpec("Si"),
        expected_secid="SiM0",
    )

    row = frame.iloc[0]
    assert bool(row["reported_trade_activity"])
    assert not bool(row["ohlc_complete"])
    assert bool(row["ohlc_missing_with_activity"])
    assert not bool(row["has_trade"])
    assert bool(row["has_settlement"])
    assert pd.isna(row["open"])
    assert row["waprice"] == 0.0
    assert row["open_interest_value"] == 17_976_816.0


def test_candles_parser_sorts_and_converts_moscow_time_to_utc() -> None:
    """Proveryaet UTC, sortirovku i sohranenie nulevogo futures value."""
    payload = {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": [
                [
                    101.0,
                    102.0,
                    103.0,
                    100.0,
                    0.0,
                    20.0,
                    "2024-01-10 10:00:00",
                    "2024-01-10 10:10:00",
                ],
                [
                    100.0,
                    101.0,
                    102.0,
                    99.0,
                    0.0,
                    10.0,
                    "2024-01-10 09:50:00",
                    "2024-01-10 10:00:00",
                ],
            ],
        }
    }
    frame = parse_futures_candles_payload(payload, FuturesAssetSpec("Si"), "SiH4")
    assert frame["volume"].tolist() == [10.0, 20.0]
    assert str(frame.iloc[0]["timestamp"]) == "2024-01-10 06:50:00+00:00"
    assert (frame["value"] == 0.0).all()


def test_participant_oi_is_asset_level_and_allows_signed_changes() -> None:
    """Proveryaet dve kategorii lic i signed oichange bez contract-podmeny."""
    payload = {
        "open_positions": {
            "columns": [
                "tradedate",
                "asset",
                "is_fiz",
                "persons_long",
                "persons_short",
                "open_position_long",
                "open_position_short",
                "oichange_long",
                "oichange_short",
            ],
            "data": [
                ["2024-06-03", "Si", 0, 100, 80, 1000, 900, -10, 20],
                ["2024-06-03", "Si", 1, 1000, 900, 2000, 2100, 10, -20],
            ],
        }
    }
    frame = parse_futures_participant_oi_payload(payload, FuturesAssetSpec("Si"))
    assert frame["is_physical"].tolist() == [False, True]
    assert frame["oi_change_long"].tolist() == [-10, 10]
    assert frame["asset_code"].nunique() == 1
