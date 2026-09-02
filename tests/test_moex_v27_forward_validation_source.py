"""Tests for immutable V27 forward market and macro snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_v27_forward_validation_source as source


def _security(secid: str, asset: str, expiry: str) -> dict:
    required = source.load_config()["market_source"]["current_snapshot_fields"]["security"]
    row = {column: None for column in required}
    row.update(
        {
            "SECID": secid,
            "BOARDID": "RFUD",
            "ASSETCODE": asset,
            "LASTTRADEDATE": expiry,
            "LASTDELDATE": expiry,
            "MINSTEP": 1.0,
            "STEPPRICE": 1.0,
            "INITIALMARGIN": 20_000.0,
            "BUYSELLFEE": 1.0,
            "SCALPERFEE": 0.5,
            "PREVSETTLEPRICE": 100_000.0,
        }
    )
    return row


def _market(secid: str) -> dict:
    required = source.load_config()["market_source"]["current_snapshot_fields"]["marketdata"]
    row = {column: None for column in required}
    row.update(
        {
            "SECID": secid,
            "BOARDID": "RFUD",
            "BID": 99_999.0,
            "OFFER": 100_001.0,
            "OPEN": 99_900.0,
            "HIGH": 100_100.0,
            "LOW": 99_800.0,
            "LAST": 100_000.0,
            "SETTLEPRICE": 100_000.0,
            "NUMTRADES": 100,
            "VOLTODAY": 1000,
            "OPENPOSITION": 5000,
            "SYSTIME": "2026-09-02 23:40:00",
            "TRADEDATE": "2026-09-02",
        }
    )
    return row


def _market_payload(asset: str) -> bytes:
    prefix = {"Si": "Si", "RTS": "RI", "BR": "BR", "MIX": "MX"}[asset]
    securities = [
        _security(f"{prefix}U6", asset, "2026-09-17"),
        _security(f"{prefix}Z6", asset, "2026-12-17"),
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


def _ruonia_html() -> bytes:
    headers = "".join(f"<th>header {index}</th>" for index in range(11))
    values = (
        "02.09.2026",
        "16,00",
        "100",
        "10",
        "5",
        "15,9",
        "15,95",
        "16,05",
        "16,1",
        "",
        "02.09.2026",
    )
    cells = "".join(f"<td>{value}</td>" for value in values)
    return f'<html><table class="data"><tr>{headers}</tr><tr>{cells}</tr></table></html>'.encode()


def _key_rate_xml() -> bytes:
    return (
        b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        b'<soap:Body><KeyRateXMLResponse xmlns="http://web.cbr.ru/">'
        b'<KeyRateXMLResult><KeyRate xmlns=""><KR><DT>2026-08-01T00:00:00</DT>'
        b"<Rate>18.0</Rate></KR></KeyRate></KeyRateXMLResult>"
        b"</KeyRateXMLResponse></soap:Body></soap:Envelope>"
    )


def _fred_csv() -> bytes:
    return b"observation_date,STLFSI4\n2026-08-28,-0.25\n"


class _Response:
    def __init__(self, content: bytes, content_type: str = "application/json") -> None:
        self.content = content
        self.headers: Mapping[str, str] = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 30.0
        if "fredgraph.csv" in url:
            return _Response(_fred_csv(), "text/csv")
        if "ruonia" in url:
            return _Response(_ruonia_html(), "text/html")
        asset = parse_qs(urlparse(url).query)["assets"][0]
        return _Response(_market_payload(asset))

    def post(
        self,
        url: str,
        *,
        data: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        assert url.endswith("DailyInfo.asmx")
        assert b"KeyRateXML" in data
        assert headers["SOAPAction"] == "http://web.cbr.ru/KeyRateXML"
        assert timeout == 30.0
        return _Response(_key_rate_xml(), "text/xml")


def test_config_seals_byte_identical_v27_and_long_forward_window() -> None:
    config = source.load_config()

    assert config["parent_v27"]["protocol_sha256"].startswith("7a9a44cf")
    assert config["frozen_economics"]["key_rate_boundary_percent"] == 20.0
    assert config["frozen_economics"]["ruonia_applied_rate_fraction"] == 0.5
    assert config["sequential_validation"]["warmup_common_sessions"] == 252
    assert config["sequential_validation"]["evaluation_common_sessions_minimum"] == 504


def test_market_normalization_keeps_full_chain_without_outcomes() -> None:
    config = source.load_config()
    frame = source.normalize_market(
        _market_payload("Si"),
        "SI",
        "decision_eod",
        pd.Timestamp("2026-09-02T20:45:00Z"),
        config,
    )

    assert frame["secid"].tolist() == ["SiU6", "SiZ6"]
    assert tuple(frame.columns) == source.MARKET_COLUMNS
    assert frame["source_date"].dt.date.astype(str).unique().tolist() == ["2026-09-02"]
    assert not set(config["forbidden_source_columns"]) & set(frame.columns)


def test_macro_forward_availability_never_predates_capture() -> None:
    retrieval = pd.Timestamp("2026-09-03T20:45:00Z")
    macro = pd.concat(
        [
            source.parse_fred_forward(_fred_csv(), retrieval),
            source.normalize_cbr_forward(_ruonia_html(), _key_rate_xml(), retrieval),
        ],
        ignore_index=True,
    )

    assert set(macro["series_id"]) == {"stlfsi4", "ruonia", "key_rate"}
    assert pd.to_datetime(macro["forward_available_at_utc"], utc=True).ge(retrieval).all()


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        snapshot_kind="decision_eod",
        session=_Session(),
        retrieved_at="2026-09-02T20:45:00Z",
    )
    checks = source.audit(snapshot)
    market = pd.read_parquet(snapshot / "market.parquet")
    macro = pd.read_parquet(snapshot / "macro.parquet")

    assert all(checks.values())
    assert len(market) == 8
    assert set(market["logical_asset"]) == {"SI", "RI", "BR", "MIX"}
    assert set(macro["series_id"]) == {"stlfsi4", "ruonia", "key_rate"}
    assert (snapshot / "audit.json").is_file()
