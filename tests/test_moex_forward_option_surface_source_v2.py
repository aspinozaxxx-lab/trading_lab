"""Tests for timestamped and margin-aware forward option source V2."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_forward_option_surface_source_v2 as source


def _payload(asset: str) -> bytes:
    config = source._compat_config()
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
            "PREVOPENPOSITION": 25,
            "IMNP": 1000.0,
            "IMP": 1100.0,
            "IMBUY": 900.0,
            "IMTIME": "2026-09-03 09:59:00",
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
            "SYSTIME": "2026-09-03 10:00:00",
            "OPENPOSITION": 30,
            "TRADE_SESSION_DATE": "2026-09-03",
            "QUANTITY": 3,
            "UPDATETIME": "09:59:58",
            "TIME": "09:59:57",
            "SEQNUM": 12345,
            "OICHANGE": 5,
        }
    )
    return json.dumps(
        {
            "securities": {"columns": list(security), "data": [list(security.values())]},
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
        assert timeout == 30.0
        asset = parse_qs(urlparse(url).query)["assets"][0]
        return _Response(_payload(asset))


def test_config_is_forward_only_and_depth_is_not_claimed() -> None:
    config = source.load_config()
    assert config["temporal_semantics"]["forward_only"] is True
    assert config["schema_probe_only"]["public_depth_fields_nonnull_rows_all_four_assets"] == 0
    assert config["live_trading_allowed"] is False


def test_normalize_preserves_added_exchange_fields() -> None:
    frame = source.normalize_response(
        _payload("Si"),
        "Si",
        pd.Timestamp("2026-09-03T07:00:00Z"),
        source._compat_config(),
    )
    row = frame.iloc[0]
    assert tuple(frame.columns) == source.OUTPUT_COLUMNS
    assert row["market_update_time"] == "09:59:58"
    assert row["last_trade_time"] == "09:59:57"
    assert row["exchange_sequence_number"] == 12345
    assert row["initial_margin_buy"] == 900.0


def test_preboundary_collection_fails_before_network(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="precedes sealed boundary"):
        source.collect(
            tmp_path,
            session=_Session(),
            retrieved_at="2026-09-02T21:24:59Z",
        )


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-03T07:00:00Z",
    )
    checks = source.audit(snapshot)
    stored = pd.read_parquet(snapshot / "option_surface.parquet")
    assert all(checks.values())
    assert len(stored) == 4
    assert stored["exchange_sequence_number"].notna().all()
    assert (snapshot / "audit.json").is_file()
