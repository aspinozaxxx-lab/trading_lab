"""Tests for the sealed, outcome-free MOEX 2008-2011 source wrapper."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_pre2012_core_source as source
from market_lab.futures import moex_pre2018_core4_source as parent


def _synthetic_collection() -> parent.SourceCollection:
    contract_rows: list[dict[str, object]] = []
    discovery_rows: list[dict[str, object]] = []
    board_rows: list[dict[str, object]] = []
    segment_rows: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    coverage_rows: list[dict[str, object]] = []
    ordinal = 0
    for logical, count in source.EXPECTED_COUNTS.items():
        asset_code = source.ASSET_CODES[logical]
        for index in range(count):
            ordinal += 1
            secid = f"{logical}{index:02d}_SYNTHETIC"
            contract_id = f"{asset_code}:{secid}:2011-12-16"
            segment_id = f"segment-{ordinal:03d}"
            discovery_rows.append(
                {
                    "logical_symbol": logical,
                    "asset_code": asset_code,
                    "secid": secid,
                }
            )
            contract_rows.append(
                {
                    "logical_symbol": logical,
                    "asset_code": asset_code,
                    "canonical_contract_id": contract_id,
                    "last_trade_date": pd.NaT,
                }
            )
            board_rows.append({"secid": secid, "boardid": "RFUD"})
            segment_rows.append(
                {
                    "canonical_contract_id": contract_id,
                    "canonical_segment_id": segment_id,
                }
            )
            daily_rows.append(
                {
                    "canonical_contract_id": contract_id,
                    "canonical_segment_id": segment_id,
                    "trade_date": pd.Timestamp("2011-01-03") + pd.Timedelta(days=ordinal),
                    "board_id": "RFUD",
                    "asset_code": asset_code,
                    "open": 1.0,
                }
            )
            coverage_rows.append({"canonical_contract_id": contract_id, "rows": 1})
    return parent.SourceCollection(
        discovery=pd.DataFrame(discovery_rows),
        contracts=pd.DataFrame(contract_rows),
        boards=pd.DataFrame(board_rows),
        segments=pd.DataFrame(segment_rows),
        daily=pd.DataFrame(daily_rows),
        coverage=pd.DataFrame(coverage_rows),
        requests=(
            {
                "request_index": 1,
                "request_kind": "synthetic_source_test",
                "request_url": "https://iss.moex.com/synthetic-pre2012",
                "retrieved_at_utc": "2026-09-01T00:00:00.000000Z",
                "payload": {"synthetic": True},
            },
        ),
    )


def test_default_protocol_is_byte_sealed_before_daily_prices() -> None:
    protocol = source.load_protocol()

    assert protocol.source.source_start == date(2008, 1, 1)
    assert protocol.source.source_end == date(2011, 12, 31)
    assert protocol.source.protected_from == date(2026, 1, 1)
    assert protocol.source.output_relative == (
        "data/processed/futures_pre2012/moex-core3-mix-daily-current-vintage-2008-2011-v1"
    )
    assert {
        rule.logical_symbol: rule.expected_contract_count for rule in protocol.source.rules
    } == source.EXPECTED_COUNTS
    assert set(protocol.dependency_hashes) == {
        "src/market_lab/futures/moex_pre2012_core_source.py",
        "src/market_lab/futures/moex_pre2018_core4_source.py",
    }
    assert protocol.payload["sealed_before_first_daily_price_response"] is True
    assert (
        protocol.payload["metadata_audit_record"]["daily_price_endpoint_reached_before_seal"]
        is False
    )


def test_history_request_is_bounded_to_the_sealed_pre2012_interval() -> None:
    protocol = source.load_protocol()
    url = parent.history_url(
        protocol.source,
        "RIZ1_2011",
        "RFUD",
        date(2011, 9, 16),
        date(2011, 12, 16),
        0,
    )

    query = parse_qs(urlparse(url).query)
    assert query["from"] == ["2011-09-16"]
    assert query["till"] == ["2011-12-16"]
    assert query["history.columns"] == [",".join(parent.DAILY_COLUMNS)]
    assert date.fromisoformat(query["till"][0]) < date(2012, 1, 1)


def test_source_checks_require_exact_81_contract_outcome_free_bundle() -> None:
    protocol = source.load_protocol()
    collection = _synthetic_collection()

    checks = source._source_checks(protocol, collection)

    assert checks
    assert all(checks.values())


def test_persistence_is_immutable_and_records_logical_asset_counts(
    tmp_path: Path,
) -> None:
    protocol = source.load_protocol()
    output = tmp_path / "source-bundle"

    result = source.persist_source(protocol, _synthetic_collection(), output)

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"] == source.SOURCE_ID
    assert manifest["counts"]["contracts"] == 81
    assert manifest["counts"]["by_asset"] == {
        logical: {"contracts": count, "daily_rows": count}
        for logical, count in source.EXPECTED_COUNTS.items()
    }
    assert (
        manifest["temporal_semantics"]["contains_returns_targets_labels_signals_equity_or_pnl"]
        is False
    )
    assert all(manifest["source_checks"].values())
    with pytest.raises(FileExistsError):
        source.persist_source(protocol, _synthetic_collection(), output)


def test_raw_replay_session_requires_exact_url_and_preserves_request_time() -> None:
    retrieved = "2026-09-01T07:08:09.123456Z"
    records = [
        {
            "request_url": "https://iss.moex.com/exact",
            "retrieved_at_utc": retrieved,
            "payload": {"history": {"columns": [], "data": []}},
        }
    ]
    replay = source._ReplaySession(records)

    response = replay.get(
        "https://iss.moex.com/exact",
        headers={"User-Agent": "test"},
        timeout=1.0,
    )

    assert response.json() == records[0]["payload"]
    assert replay.index == 1
    assert replay.clock() == datetime(2026, 9, 1, 7, 8, 9, 123456, tzinfo=UTC)
    mismatch = source._ReplaySession(records)
    with pytest.raises(AssertionError, match="raw replay URL mismatch"):
        mismatch.get(
            "https://iss.moex.com/other",
            headers={"User-Agent": "test"},
            timeout=1.0,
        )


def test_project_relative_path_rejects_escape_and_wrong_root() -> None:
    with pytest.raises(ValueError, match="unsafe pre-2012 source path"):
        source._project_relative_path("../outside")
    with pytest.raises(ValueError, match="must start with data"):
        source._project_relative_path("runs/not-data", "data")
