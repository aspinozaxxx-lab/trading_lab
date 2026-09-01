"""Tests for the transport-only S2 pre-2018 macro source correction."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import pre2018_macro_source as v1
from market_lab.futures import pre2018_macro_source_v2 as v2


class FakeResponse:
    content = b"response"
    headers = {"Content-Type": "text/plain"}

    def raise_for_status(self) -> None:
        return None


class CaptureSession:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: object,
        timeout: float,
        data: bytes | None = None,
    ) -> FakeResponse:
        self.call = {
            "method": method,
            "url": url,
            "headers": headers,
            "timeout": timeout,
            "data": data,
        }
        return FakeResponse()


def _tables() -> v1.MacroSourceTables:
    stlfsi = pd.DataFrame(
        {
            "observation_date": [pd.Timestamp("2012-01-06")],
            "stress_index": [-0.5],
            "available_at": [pd.Timestamp("2012-01-13T05:59:59Z")],
            "complete": [True],
            "stress_state": ["normal_or_below"],
            "retrieved_at_utc": [pd.Timestamp("2026-09-01T07:00:00Z")],
            "source_current_vintage": [True],
            "methodology_version": ["STLFSI4"],
        }
    )
    monetary = pd.DataFrame(
        {
            "source": ["cbr", "cbr"],
            "series_id": ["key_rate", "ruonia"],
            "observation_date": [pd.Timestamp("2013-09-13"), pd.Timestamp("2012-01-10")],
            "publication_date": [pd.NaT, pd.Timestamp("2012-01-11")],
            "available_at": [
                pd.Timestamp("2013-09-12T20:00:00Z"),
                pd.Timestamp("2012-01-11T20:00:00Z"),
            ],
            "value": [5.5, 5.0],
            "availability_rule": [
                "effective_date_plus_one_calendar_day",
                "publication_date_plus_one_calendar_day",
            ],
        }
    )
    coverage = pd.DataFrame({"series_id": ["STLFSI4", "key_rate", "ruonia"], "rows": [1, 1, 1]})
    responses = tuple(
        v1.RawResponse(
            kind=kind,
            method="GET" if index < 2 else "POST",
            url=f"https://official.example/{index}",
            request_body=None if index < 2 else b"soap",
            content=f"response-{index}".encode(),
            headers={"Content-Type": "text/plain"},
            retrieved_at_utc="2026-09-01T07:00:00Z",
        )
        for index, kind in enumerate(
            ("fred_stlfsi4_csv", "cbr_ruonia_html", "cbr_key_rate_soap_xml")
        )
    )
    return v1.MacroSourceTables(stlfsi, monetary, coverage, responses)


def test_default_v2_protocol_is_sealed_and_inherits_S1() -> None:
    protocol = v2.load_protocol()

    assert protocol.config_sha256 == (
        "4ad7f034939b5becff13bab27309350e02c90e94e991c3907888807557dbd2cc"
    )
    assert protocol.parent.config_sha256 == (
        "3daa3c404255f0928135ac7ba5e8c732bacbfefe49ddacd63bccc2fbdaa37826"
    )
    assert protocol.source_start == protocol.parent.source_start
    assert protocol.source_end == protocol.parent.source_end


def test_transport_changes_only_user_agent() -> None:
    capture = CaptureSession()
    session = v2.CurlCompatibleSession(capture)

    response = session.request(
        "POST",
        "https://official.example",
        headers={"User-Agent": "old", "Accept": "text/xml", "X-Test": "same"},
        timeout=30.0,
        data=b"same-body",
    )

    assert response.content == b"response"
    assert capture.call is not None
    assert capture.call["headers"] == {
        "User-Agent": "curl/8.10.1",
        "Accept": "text/xml",
        "X-Test": "same",
    }
    assert capture.call["data"] == b"same-body"
    assert capture.call["timeout"] == 30.0


def test_v2_persistence_records_transport_lineage_and_is_immutable(tmp_path: Path) -> None:
    protocol = replace(v2.load_protocol(), output_directory=tmp_path / "macro-v2")

    result = v2.persist(protocol, _tables())

    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"].endswith("v2")
    assert manifest["parent_S1"]["output_published"] is False
    assert manifest["transport_correction"]["only_changed_field"] == "HTTP_User_Agent"
    assert manifest["request_count"] == 3
    with pytest.raises(FileExistsError):
        v2.persist(protocol, _tables())


def test_v2_persistence_rejects_missing_official_response() -> None:
    tables = _tables()
    invalid = replace(tables, responses=tables.responses[:2])

    with pytest.raises(ValueError, match="exactly the three sealed"):
        v2.persist(v2.load_protocol(), invalid)
