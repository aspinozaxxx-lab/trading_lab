"""Tests for the parser-only V2 successor of the MOEX 2008-2011 source."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2012_core_source as v1
from market_lab.futures import moex_pre2012_core_source_v2 as source
from market_lab.futures import moex_pre2018_core4_source as parent
from market_lab.futures.specs import FuturesAssetSpec


def _payload(rows: list[list[object]]) -> dict[str, object]:
    return {
        "history": {"columns": list(parent.DAILY_COLUMNS), "data": rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, len(rows), 100]],
        },
    }


def _inert_row(*, open_value: object = None) -> list[object]:
    return [
        "RFUD",
        "2008-09-12",
        source.KNOWN_INERT_SECID,
        open_value,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "RTS",
    ]


def _active_row() -> list[object]:
    return [
        "RFUD",
        "2008-09-15",
        source.KNOWN_INERT_SECID,
        100.0,
        99.0,
        102.0,
        101.0,
        1000.0,
        10.0,
        20.0,
        2000.0,
        101.0,
        100.5,
        2.0,
        "RTS",
    ]


def _synthetic_collection() -> parent.SourceCollection:
    rows: list[dict[str, object]] = []
    ordinal = 0
    for logical, count in v1.EXPECTED_COUNTS.items():
        for index in range(count):
            ordinal += 1
            secid = (
                source.KNOWN_INERT_SECID
                if logical == "RI" and index == 0
                else f"{logical}{index:02d}_SYNTHETIC"
            )
            rows.append(
                {
                    "ordinal": ordinal,
                    "logical_symbol": logical,
                    "asset_code": v1.ASSET_CODES[logical],
                    "secid": secid,
                    "canonical_contract_id": (
                        f"{v1.ASSET_CODES[logical]}:{secid}:2011-12-16"
                    ),
                    "canonical_segment_id": f"segment-{ordinal:03d}",
                }
            )
    contracts = pd.DataFrame(
        [
            {
                "logical_symbol": row["logical_symbol"],
                "asset_code": row["asset_code"],
                "canonical_contract_id": row["canonical_contract_id"],
                "last_trade_date": pd.NaT,
            }
            for row in rows
        ]
    )
    daily_rows: list[dict[str, object]] = []
    for row in rows:
        inert = row["secid"] == source.KNOWN_INERT_SECID
        daily_rows.append(
            {
                "canonical_contract_id": row["canonical_contract_id"],
                "canonical_segment_id": row["canonical_segment_id"],
                "trade_date": source.KNOWN_INERT_DATE
                if inert
                else pd.Timestamp("2010-01-04"),
                "board_id": "RFUD",
                "secid": row["secid"],
                "asset_code": row["asset_code"],
                "open": None if inert else 100.0,
                "low": None if inert else 99.0,
                "high": None if inert else 102.0,
                "close": None if inert else 101.0,
                "settle": None if inert else 101.0,
                "waprice": None if inert else 100.5,
                "volume": None if inert else 10.0,
                "value": None if inert else 1000.0,
                "num_trades": None if inert else 2.0,
                "open_interest": None if inert else 20.0,
                "open_interest_value": None if inert else 2000.0,
                "reported_trade_activity": not inert,
                "ohlc_complete": not inert,
                "ohlc_missing_with_activity": False,
                "has_trade": not inert,
                "has_settlement": not inert,
            }
        )
    return parent.SourceCollection(
        discovery=pd.DataFrame(
            [
                {
                    "logical_symbol": row["logical_symbol"],
                    "asset_code": row["asset_code"],
                    "secid": row["secid"],
                }
                for row in rows
            ]
        ),
        contracts=contracts,
        boards=pd.DataFrame(
            [{"secid": row["secid"], "boardid": "RFUD"} for row in rows]
        ),
        segments=pd.DataFrame(
            [
                {
                    "canonical_contract_id": row["canonical_contract_id"],
                    "canonical_segment_id": row["canonical_segment_id"],
                }
                for row in rows
            ]
        ),
        daily=pd.DataFrame(daily_rows),
        coverage=pd.DataFrame(
            [
                {"canonical_contract_id": row["canonical_contract_id"], "rows": 1}
                for row in rows
            ]
        ),
        requests=(
            {
                "request_index": 1,
                "request_kind": "synthetic_v2_source_test",
                "request_url": "https://iss.moex.com/synthetic-pre2012-v2",
                "retrieved_at_utc": "2026-09-01T00:00:00.000000Z",
                "payload": {"synthetic": True},
            },
        ),
    )


def test_default_protocol_pins_v1_and_both_source_implementations() -> None:
    protocol = source.load_protocol()

    assert protocol.source.source_start == pd.Timestamp("2008-01-01").date()
    assert protocol.source.source_end == pd.Timestamp("2011-12-31").date()
    assert protocol.source.output_relative.endswith("2008-2011-v2")
    assert protocol.payload["parser_correction"]["universe_dates_endpoints_unchanged"]
    assert set(protocol.dependency_hashes) == {
        "src/market_lab/futures/moex_pre2012_core_source_v2.py",
        "src/market_lab/futures/moex_pre2012_core_source.py",
        "src/market_lab/futures/moex_pre2018_core4_source.py",
    }


def test_parser_preserves_null_placeholder_as_nonexecuting_missing_row() -> None:
    frame, cursor = source.parse_futures_daily_payload_v2(
        _payload([_inert_row(), _active_row()]),
        FuturesAssetSpec.from_symbol("RI"),
        expected_secid=source.KNOWN_INERT_SECID,
    )

    inert = frame.loc[frame["trade_date"].eq(source.KNOWN_INERT_DATE)].iloc[0]
    assert cursor.total == 2
    assert len(frame) == 2
    assert inert[["open", "low", "high", "close", "settle", "waprice"]].isna().all()
    assert not bool(inert["reported_trade_activity"])
    assert not bool(inert["has_trade"])
    assert not bool(inert["has_settlement"])
    assert bool(frame.loc[frame["trade_date"].eq(pd.Timestamp("2008-09-15")), "has_trade"].iloc[0])


def test_parser_correction_is_null_only_not_generic_missing_value_relaxation() -> None:
    with pytest.raises(ValueError, match="ni aktivnosti"):
        source.parse_futures_daily_payload_v2(
            _payload([_inert_row(open_value="")]),
            FuturesAssetSpec.from_symbol("RI"),
            expected_secid=source.KNOWN_INERT_SECID,
        )


def test_parser_context_is_transactional() -> None:
    original = parent.parse_futures_daily_payload

    with source._parser_context():
        assert parent.parse_futures_daily_payload is source.parse_futures_daily_payload_v2

    assert parent.parse_futures_daily_payload is original


def test_v2_source_checks_and_manifest_preserve_inert_count(
    tmp_path: Path,
) -> None:
    protocol = source.load_protocol()
    collection = _synthetic_collection()
    assert all(source._source_checks(protocol, collection).values())
    output = tmp_path / "source-v2"

    source.persist_source(protocol, collection, output)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"] == source.SOURCE_ID
    assert manifest["counts"]["inert_daily_rows"] == 1
    assert manifest["counts"]["by_asset"]["RI"]["inert_daily_rows"] == 1
    assert manifest["parser_correction"]["inert_row_is_zero_return"] is False
    assert all(manifest["source_checks"].values())
    with pytest.raises(FileExistsError):
        source.persist_source(protocol, collection, output)
