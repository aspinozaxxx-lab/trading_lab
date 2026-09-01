"""Synthetic tests for the sealed MOEX 2012-2017 core-four source collector."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_pre2018_core4_source as source
from market_lab.futures.specs import FuturesAssetSpec


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class QueueSession:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def get(self, url: str, *, headers: object, timeout: float) -> FakeResponse:
        del headers, timeout
        self.urls.append(url)
        if not self.payloads:
            raise AssertionError(f"unexpected request: {url}")
        return FakeResponse(self.payloads.pop(0))


def _clock() -> datetime:
    return datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


def _small_protocol() -> source.SourceProtocol:
    parent = source.load_source_protocol()
    rule = source.AssetDiscoveryRule(
        logical_symbol="RI",
        asset_code="RTS",
        search_query="RTS",
        shortname_prefix="RTS",
        expected_months_by_year=((2012, (3, 6)),),
        expected_contract_count=2,
    )
    return replace(
        parent,
        rules=(rule,),
        search_page_size=2,
        maximum_search_pages=5,
        request_interval_seconds=0.0,
    )


def _finder_payload(rows: list[list[object]]) -> dict[str, object]:
    return {"securities": {"columns": list(source.SEARCH_COLUMNS), "data": rows}}


def _detail_payload(secid: str, shortname: str) -> dict[str, object]:
    return {
        "description": {
            "columns": list(source.DESCRIPTION_COLUMNS),
            "data": [
                ["SECID", secid],
                ["SHORTNAME", shortname],
                ["FRSTTRADE", "2011-12-01"],
                ["LSTTRADE", "2012-03-15"],
                ["LSTDELDATE", "2012-03-15"],
            ],
        },
        "boards": {
            "columns": list(source.BOARD_COLUMNS),
            "data": [
                [
                    secid,
                    "RFUD",
                    "2011-12-01",
                    "2012-03-16",
                    "2011-12-01",
                    "2012-03-16",
                    1,
                    0,
                    "futures",
                    "forts",
                ]
            ],
        },
    }


def _daily_payload(secid: str) -> dict[str, object]:
    rows = [
        [
            "RFUD",
            "2012-03-01",
            secid,
            150000.0,
            149000.0,
            151000.0,
            150500.0,
            1_000_000.0,
            10.0,
            100.0,
            10_000_000.0,
            150450.0,
            150300.0,
            5.0,
            "RTS",
        ],
        [
            "RFUD",
            "2012-03-02",
            secid,
            150500.0,
            150000.0,
            152000.0,
            151500.0,
            1_500_000.0,
            12.0,
            110.0,
            11_000_000.0,
            151450.0,
            151200.0,
            7.0,
            "RTS",
        ],
    ]
    return {
        "history": {"columns": list(source.DAILY_COLUMNS), "data": rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, 2, 100]],
        },
    }


def test_default_protocol_is_byte_sealed_and_declares_exact_155_contracts() -> None:
    protocol = source.load_source_protocol()

    assert protocol.source_start == date(2012, 1, 1)
    assert protocol.source_end == date(2017, 12, 31)
    assert sum(rule.expected_contract_count for rule in protocol.rules) == 155
    assert {rule.logical_symbol: len(rule.expected_shortnames) for rule in protocol.rules} == {
        "BR": 71,
        "MIX": 24,
        "RI": 24,
        "SI": 36,
    }
    url = source.history_url(
        protocol,
        "RIH2_2012",
        "RFUD",
        date(2012, 1, 1),
        date(2012, 3, 15),
        0,
    )
    query = parse_qs(urlparse(url).query)
    assert query["from"] == ["2012-01-01"]
    assert query["till"] == ["2012-03-15"]
    assert query["history.columns"] == [",".join(source.DAILY_COLUMNS)]
    finder_query = parse_qs(urlparse(source.search_url(protocol.rules[0], 0, 100)).query)
    assert finder_query["securities.columns"] == ["secid,shortname,group,type"]


def test_discovery_exhausts_pages_and_admits_only_exact_shortnames() -> None:
    protocol = _small_protocol()
    session = QueueSession(
        [
            _finder_payload(
                [
                    ["RIH2_2012", "RTS-3.12", "futures_forts", "futures"],
                    ["RTS-current", "RTS-9.26", "futures_forts", "futures"],
                ]
            ),
            _finder_payload(
                [
                    ["RIM2_2012", "RTS-6.12", "futures_forts", "futures"],
                    ["RTS-option", "RTS-not-exact", "futures_forts", "futures"],
                ]
            ),
            _finder_payload([]),
        ]
    )
    requests_log: list[dict[str, object]] = []

    result = source.discover_contracts(protocol, session, requests_log, _clock)

    assert result["shortname"].tolist() == ["RTS-3.12", "RTS-6.12"]
    assert len(session.urls) == 3
    assert [parse_qs(urlparse(url).query)["start"][0] for url in session.urls] == [
        "0",
        "2",
        "4",
    ]
    assert all(record["request_kind"] == "security_search" for record in requests_log)


def test_discovery_fails_closed_when_one_expected_contract_is_absent() -> None:
    protocol = _small_protocol()
    session = QueueSession(
        [
            _finder_payload(
                [["RIH2_2012", "RTS-3.12", "futures_forts", "futures"]]
            )
        ]
    )

    with pytest.raises(ValueError, match="exact discovery mismatch"):
        source.discover_contracts(protocol, session, [], _clock)


def test_metadata_builds_canonical_contract_and_exact_rfud_segment() -> None:
    protocol = replace(_small_protocol(), rules=(_small_protocol().rules[0],))
    discovery = pd.DataFrame(
        [
            {
                "logical_symbol": "RI",
                "asset_code": "RTS",
                "secid": "RIH2_2012",
                "shortname": "RTS-3.12",
                "group": "futures_forts",
                "type": "futures",
            }
        ]
    )
    session = QueueSession([_detail_payload("RIH2_2012", "RTS-3.12")])

    contracts, boards, segments = source.fetch_contract_metadata(
        protocol,
        discovery,
        session,
        [],
        _clock,
    )

    assert contracts.loc[0, "canonical_contract_id"] == "RTS:RIH2:2012-03-15"
    assert boards.loc[0, "boardid"] == "RFUD"
    assert segments.loc[0, "canonical_contract_id"] == "RTS:RIH2:2012-03-15"


def test_daily_history_uses_exact_cursor_and_preserves_source_fields() -> None:
    protocol = _small_protocol()
    session = QueueSession([_daily_payload("RIH2_2012")])
    segment = {
        "canonical_contract_id": "RTS:RIH2:2012-03-15",
        "canonical_segment_id": "segment-1",
        "secid": "RIH2_2012",
        "boardid": "RFUD",
    }

    result = source.fetch_daily_segment(
        protocol,
        FuturesAssetSpec.from_symbol("RI"),
        segment,
        date(2012, 3, 1),
        date(2012, 3, 15),
        session,
        [],
        _clock,
    )

    assert len(result) == 2
    assert result["canonical_contract_id"].eq("RTS:RIH2:2012-03-15").all()
    assert result["has_trade"].all()
    assert result["has_settlement"].all()
    query = parse_qs(urlparse(session.urls[0]).query)
    assert query["till"] == ["2012-03-15"]
    assert query["iss.only"] == ["history,history.cursor"]


def test_persistence_is_immutable_and_declares_no_returns_targets_or_pnl(
    tmp_path: Path,
) -> None:
    protocol = source.load_source_protocol()
    discovery = pd.DataFrame([{"asset_code": "RTS", "secid": "RIH2_2012"}])
    contracts = pd.DataFrame(
        [{"asset_code": "RTS", "canonical_contract_id": "RTS:RIH2:2012-03-15"}]
    )
    daily = pd.DataFrame([{"asset_code": "RTS", "trade_date": pd.Timestamp("2012-03-01")}])
    collection = source.SourceCollection(
        discovery=discovery,
        contracts=contracts,
        boards=pd.DataFrame([{"secid": "RIH2_2012", "boardid": "RFUD"}]),
        segments=pd.DataFrame([{"canonical_segment_id": "segment-1"}]),
        daily=daily,
        coverage=pd.DataFrame([{"rows": 1}]),
        requests=(
            {
                "request_index": 1,
                "request_kind": "daily_history",
                "asset_code": "RTS",
                "secid": "RIH2_2012",
                "request_url": "https://iss.moex.com/synthetic",
                "retrieved_at_utc": "2026-09-01T06:00:00.000000Z",
                "payload": {"synthetic": True},
            },
        ),
    )
    output = tmp_path / "source-bundle"

    result = source.persist_source(protocol, collection, output)

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    semantics = manifest["temporal_semantics"]
    assert semantics["contains_prices"] is True
    assert semantics["contains_returns_targets_labels_or_pnl"] is False
    assert manifest["access_observation"]["raw_redistribution_allowed"] is False
    assert manifest["artifacts"]["daily"]["rows"] == 1
    with pytest.raises(FileExistsError):
        source.persist_source(protocol, collection, output)
