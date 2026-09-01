"""Tests for the immutable forward-only MOEX option-surface collector."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_forward_option_surface_source as source


def _payload(asset: str) -> bytes:
    config = source.load_config()
    secid = f"{asset}TEST"
    security = {column: None for column in config["required_security_columns"]}
    security.update(
        {
            "SECID": secid,
            "BOARDID": "ROPD",
            "MINSTEP": 1.0,
            "LASTTRADEDATE": "2026-09-17",
            "LASTDELDATE": "2026-09-17",
            "ASSETCODE": asset,
            "PREVSETTLEPRICE": 100.0,
            "OPTIONTYPE": "C",
            "STEPPRICE": 1.0,
            "BUYSELLFEE": 1.0,
            "SCALPERFEE": 0.5,
            "EXERCISEFEE": 2.0,
            "STRIKE": 90000.0,
            "UNDERLYINGASSET": f"{asset}U6",
            "UNDERLYINGSETTLEPRICE": 88000.0,
        }
    )
    market = {column: None for column in config["required_marketdata_columns"]}
    market.update(
        {
            "SECID": secid,
            "BOARDID": "ROPD",
            "BID": 99.0,
            "OFFER": 101.0,
            "SPREAD": 2.0,
            "OPEN": 100.0,
            "HIGH": 105.0,
            "LOW": 95.0,
            "LAST": 100.0,
            "SETTLEPRICE": 100.0,
            "NUMTRADES": 10,
            "VOLTODAY": 20,
            "SYSTIME": "2026-09-01 18:50:00",
            "OPENPOSITION": 30,
            "TRADE_SESSION_DATE": "2026-09-01",
        }
    )
    return json.dumps(
        {
            "securities": {
                "columns": list(security),
                "data": [list(security.values())],
            },
            "marketdata": {"columns": list(market), "data": [list(market.values())]},
        }
    ).encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 30.0
        asset = parse_qs(urlparse(url).query)["assets"][0]
        return _Response(_payload(asset))


def test_config_seal_and_urls_are_forward_only() -> None:
    config = source.load_config()

    assert config["temporal_semantics"]["forward_only"] is True
    assert config["future_economic_protocol_minimums"]["naked_short_options"] == "forbidden"
    url = source.request_url(config, "Si")
    assert "assets=Si" in url
    assert "iss.meta=off" in url
    assert "history" not in url


def test_normalize_preserves_quotes_and_has_no_outcomes() -> None:
    config = source.load_config()
    frame = source.normalize_response(
        _payload("Si"), "Si", pd.Timestamp("2026-09-01T20:00:00Z"), config
    )

    assert tuple(frame.columns) == source.OUTPUT_COLUMNS
    assert frame.iloc[0]["asset_code"] == "SI"
    assert frame.iloc[0]["bid"] == 99.0
    assert frame.iloc[0]["offer"] == 101.0
    assert frame.iloc[0]["available_at_utc"] == "2026-09-01T20:00:00+00:00"
    assert not set(config["forbidden_columns"]) & set(frame.columns)


def test_normalize_rejects_asset_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        source.normalize_response(
            _payload("BR"),
            "Si",
            pd.Timestamp("2026-09-01T20:00:00Z"),
            source.load_config(),
        )


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-01T20:00:00Z",
    )
    checks = source.audit(snapshot)
    stored = pd.read_parquet(snapshot / "option_surface.parquet")

    assert all(checks.values())
    assert len(stored) == 4
    assert set(stored["asset_code"]) == {"SI", "RI", "BR", "MIX"}
    assert (snapshot / "audit.json").is_file()
