"""Tests for the sealed source-only monthly RVI futures daily bundle."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import moex_rvi_futures_daily_source_v1 as source


def _series_payload() -> dict:
    rows = []
    month_codes = "FGHJKMNQUVXZ"
    for year in range(2019, 2026):
        for month in range(1, 13):
            expiration = pd.Timestamp(year=year, month=month, day=15) + pd.offsets.Week(
                weekday=3
            )
            if year == 2019 and month == 1:
                expiration = pd.Timestamp("2019-01-17")
            if year == 2025 and month == 12:
                expiration = pd.Timestamp("2025-12-18")
            secid = f"VI{month_codes[month - 1]}{year % 10}"
            rows.append(
                [
                    secid,
                    f"RVI-{month}.{year % 100:02d}",
                    (expiration - pd.Timedelta(days=75)).date().isoformat(),
                    expiration.date().isoformat(),
                    source.ASSET_CODE,
                ]
            )
    return {
        "series": {
            "columns": ["secid", "name", "start_date", "expiration_date", "asset_code"],
            "data": rows,
        }
    }


def _history_payload(secid: str, date: str = "2025-11-03") -> dict:
    columns = list(source.HISTORY_COLUMNS)
    values = {
        "BOARDID": "RFUD",
        "TRADEDATE": date,
        "SECID": secid,
        "OPEN": 31.0,
        "LOW": 30.0,
        "HIGH": 33.0,
        "CLOSE": 32.0,
        "OPENPOSITIONVALUE": 100000.0,
        "VALUE": 50000.0,
        "VOLUME": 20.0,
        "OPENPOSITION": 100.0,
        "SETTLEPRICE": 32.1,
        "SWAPRATE": None,
        "WAPRICE": 31.8,
        "CHANGE": 1.0,
        "QTY": 2.0,
        "NUMTRADES": 10.0,
        "SHORTNAME": "RVI-12.25",
        "ASSETCODE": source.ASSET_CODE,
    }
    return {"history": {"columns": columns, "data": [[values[name] for name in columns]]}}


def test_protocol_and_urls_are_fixed() -> None:
    config = source.load_config()

    assert source.CONFIG_SHA256.startswith("bb4aec1d")
    assert "asset_code=RVI" in source._series_url(config)
    url = source._history_url(config, "VIZ5", 0, "2025-10-03")
    assert "/securities/VIZ5.json?" in url
    assert "start=0" in url


def test_select_series_requires_exact_monthly_grid() -> None:
    config = source.load_config()
    series = source.select_series(_series_payload(), config)

    assert len(series) == 84
    assert series["expiration_date"].min() == pd.Timestamp("2019-01-17")
    assert series["expiration_date"].max() == pd.Timestamp("2025-12-18")
    assert series["secid"].is_unique


def test_rebuild_preserves_market_fields_without_derived_outcomes() -> None:
    config = source.load_config()
    series_payload = _series_payload()
    raw = [{"kind": "series", "payload": series_payload}]
    raw.append(
        {
            "kind": "history",
            "secid": "VIZ5",
            "payload": _history_payload("VIZ5"),
        }
    )

    series, daily = source.rebuild(raw, config)

    assert len(series) == 84
    assert len(daily) == 1
    assert daily.loc[0, "open"] == 31.0
    assert daily.loc[0, "num_trades"] == 10.0
    assert pd.isna(daily.loc[0, "swap_rate"])
    forbidden = {value.casefold() for value in config["forbidden_derived_columns"]}
    assert not forbidden.intersection(column.casefold() for column in daily.columns)


def test_rebuild_rejects_protected_history() -> None:
    config = source.load_config()
    raw = [{"kind": "series", "payload": _series_payload()}]
    raw.append(
        {
            "kind": "history",
            "secid": "VIZ5",
            "payload": _history_payload("VIZ5", "2026-01-02"),
        }
    )

    with pytest.raises(ValueError, match="protected 2026"):
        source.rebuild(raw, config)
