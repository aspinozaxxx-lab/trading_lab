"""Tests for the forward-only MOEX CNY relative-value collector."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_forward_cny_relative_value_source as source


def _security(secid: str, asset: str, expiry: str) -> dict:
    config = source.load_config()
    row = {column: None for column in config["required_security_columns"]}
    row.update(
        {
            "SECID": secid,
            "BOARDID": "RFUD",
            "ASSETCODE": asset,
            "LASTTRADEDATE": expiry,
            "LASTDELDATE": expiry,
            "MINSTEP": 0.0001,
            "STEPPRICE": 0.1,
            "INITIALMARGIN": 3000.0,
            "BUYSELLFEE": 1.0,
            "SCALPERFEE": 0.5,
            "PREVSETTLEPRICE": 13.0,
            "LOTVOLUME": 1000,
        }
    )
    return row


def _market(secid: str) -> dict:
    config = source.load_config()
    row = {column: None for column in config["required_marketdata_columns"]}
    row.update(
        {
            "SECID": secid,
            "BOARDID": "RFUD",
            "BID": 12.99,
            "OFFER": 13.01,
            "SPREAD": 0.02,
            "LAST": 13.0,
            "SETTLEPRICE": 13.0,
            "NUMTRADES": 100,
            "VOLTODAY": 1000,
            "OPENPOSITION": 5000,
            "SYSTIME": "2026-09-02 18:30:00",
            "TRADEDATE": "2026-09-02",
        }
    )
    return row


def _current_payload(asset: str) -> bytes:
    if asset == "CNYRUBTOM":
        securities = [_security("CNYRUBF", asset, "2100-01-01")]
    else:
        securities = [
            _security("CRU6", asset, "2026-09-17"),
            _security("CRZ6", asset, "2026-12-17"),
            _security("CRH7", asset, "2027-03-18"),
        ]
    markets = [_market(row["SECID"]) for row in securities]
    return json.dumps(
        {
            "securities": {
                "columns": list(securities[0]),
                "data": [list(row.values()) for row in securities],
            },
            "marketdata": {
                "columns": list(markets[0]),
                "data": [list(row.values()) for row in markets],
            },
        }
    ).encode()


def _history_payload() -> bytes:
    columns = source.load_config()["source"]["perpetual_history_columns"]
    row = {
        "BOARDID": "RFUD",
        "TRADEDATE": "2026-09-02",
        "SECID": "CNYRUBF",
        "SETTLEPRICE": 13.0,
        "SWAPRATE": 0.01,
        "NUMTRADES": 100,
        "VOLUME": 1000,
    }
    return json.dumps(
        {
            "history": {"columns": columns, "data": [[row[column] for column in columns]]},
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, 1, 100]],
            },
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
        if "/history/" in url:
            return _Response(_history_payload())
        asset = parse_qs(urlparse(url).query)["assets"][0]
        return _Response(_current_payload(asset))


def test_config_and_urls_are_forward_only() -> None:
    config = source.load_config()

    assert config["temporal_semantics"]["forward_only"] is True
    assert "history" not in source.current_url(config, "perpetual")
    url = source.history_url(config, pd.Timestamp("2026-09-03T15:30:00Z"))
    assert "from=2026-09-02" in url
    assert "till=2026-09-02" in url


def test_normalize_selects_exact_perpetual_and_nearest_two_quarterlies() -> None:
    config = source.load_config()
    retrieval = pd.Timestamp("2026-09-03T15:30:00Z")
    perpetual = source.normalize_current(
        _current_payload("CNYRUBTOM"), "perpetual", retrieval, config
    )
    quarterly = source.normalize_current(
        _current_payload("CNY"), "quarterly", retrieval, config
    )

    assert perpetual["secid"].tolist() == ["CNYRUBF"]
    assert quarterly["secid"].tolist() == ["CRU6", "CRZ6"]
    assert tuple(perpetual.columns) == source.QUOTE_COLUMNS
    assert not set(config["forbidden_columns"]) & set(perpetual.columns)


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-03T15:30:00Z",
    )
    checks = source.audit(snapshot)
    quotes = pd.read_parquet(snapshot / "quotes.parquet")
    funding = pd.read_parquet(snapshot / "funding_history.parquet")

    assert all(checks.values())
    assert len(quotes) == 3
    assert funding["swap_rate"].tolist() == [0.01]
    assert (snapshot / "audit.json").is_file()


def test_first_sealed_day_does_not_request_preseal_history(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T15:30:00Z",
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))

    assert manifest["counts"]["funding_rows"] == 0
    assert not any(name.startswith("history_") for name in manifest["raw"])
    assert all(source.audit(snapshot).values())
