from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from market_lab.futures import moex_rgbi_futures_daily_source_v1 as source


def _config() -> dict:
    return yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "configs/moex_rgbi_futures_daily_source_v1.yaml"
        ).read_text(encoding="utf-8-sig")
    )


def _payload() -> dict:
    rows = []
    for index, secid in enumerate(source.EXPECTED_SECIDS):
        expiration = pd.Timestamp("2022-06-01") + pd.offsets.QuarterEnd(index)
        if index == 0:
            expiration = pd.Timestamp("2022-06-01")
        if index == len(source.EXPECTED_SECIDS) - 1:
            expiration = pd.Timestamp("2025-12-01")
        rows.append(
            [
                secid,
                f"RGBI {secid}",
                (expiration - pd.Timedelta(days=100)).date().isoformat(),
                expiration.date().isoformat(),
                "RGBI",
            ]
        )
    return {
        "series": {
            "columns": ["secid", "name", "start_date", "expiration_date", "asset_code"],
            "data": rows,
        }
    }


def test_select_series_requires_exact_presealed_rgbi_contracts() -> None:
    payload = _payload()
    selected = source.select_series(payload, _config())
    assert tuple(selected["secid"].astype(str)) == source.EXPECTED_SECIDS
    assert selected["expiration_date"].min() == pd.Timestamp("2022-06-01")
    assert selected["expiration_date"].max() == pd.Timestamp("2025-12-01")


def test_select_series_rejects_post_development_or_missing_identity() -> None:
    payload = _payload()
    payload["series"]["data"].pop()
    with pytest.raises(ValueError, match="exact series identity"):
        source.select_series(payload, _config())
