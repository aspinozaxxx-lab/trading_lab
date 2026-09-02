"""Tests for the sealed source-only RUONIA/RUSFAR futures bundle."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_ruonia_rusfar_futures_source_v1 as source


def _series_payload(asset: str, prefix: str) -> dict:
    rows = []
    expirations = pd.date_range("2019-06-30", periods=79, freq="ME")
    expirations = expirations.to_series().map(
        lambda value: value - pd.offsets.BDay(0)
    ).tolist()
    expirations[-1] = pd.Timestamp("2025-12-30")
    expirations[0] = pd.Timestamp("2019-06-28")
    month_codes = "FGHJKMNQUVXZ"
    for expiration in expirations:
        code = month_codes[expiration.month - 1]
        secid = f"{prefix}{code}{expiration.year % 10}"
        rows.append(
            [
                secid,
                f"{asset}-{expiration:%m.%y}",
                (expiration - pd.Timedelta(days=365)).date().isoformat(),
                expiration.date().isoformat(),
                asset,
                asset,
                0,
            ]
        )
    return {
        "series": {
            "columns": [
                "secid",
                "name",
                "start_date",
                "expiration_date",
                "asset_code",
                "underlying_asset",
                "is_traded",
            ],
            "data": rows,
        }
    }


def test_protocol_and_source_urls_are_fixed() -> None:
    config = source.load_config()

    assert source.CONFIG_SHA256.startswith("0e7db967")
    assert "asset_code=RUON" in source._series_url(config, "RUON")
    assert "securities%2FMFZ5.json" not in source._history_url(
        config, "MFZ5", 0, "2025-01-03"
    )
    assert "/securities/MFZ5.json?" in source._history_url(
        config, "MFZ5", 0, "2025-01-03"
    )


def test_metadata_selection_requires_exact_same_expiration_pairs() -> None:
    config = source.load_config()
    pairs = source.select_pairs(
        {
            "ruonia": _series_payload("RUON", "RR"),
            "rusfar": _series_payload("1MFR", "MF"),
        },
        config,
    )

    assert len(pairs) == 79
    assert pairs["expiration_date"].min() == pd.Timestamp("2019-06-28")
    assert pairs["expiration_date"].max() == pd.Timestamp("2025-12-30")
    assert pairs[["ruonia_secid", "rusfar_secid"]].notna().all(axis=None)
