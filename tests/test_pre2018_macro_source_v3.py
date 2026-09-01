"""Tests for preserving unknown historical RUONIA publication timing in S3."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import pre2018_macro_source as v1
from market_lab.futures import pre2018_macro_source_v3 as v3


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {"Content-Type": "text/plain"}

    def raise_for_status(self) -> None:
        return None


class QueueSession:
    def __init__(self, payloads: list[bytes]) -> None:
        self.payloads = list(payloads)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: object,
        timeout: float,
        data: bytes | None = None,
    ) -> FakeResponse:
        del method, url, headers, timeout, data
        if not self.payloads:
            raise AssertionError("unexpected request")
        return FakeResponse(self.payloads.pop(0))


def _fred_csv() -> bytes:
    return b"observation_date,STLFSI4\n2012-01-06,-0.5\n"


def _ruonia_html(unknown_marker: str = chr(0xFFFD)) -> bytes:
    headers = "".join(f"<th>h{index}</th>" for index in range(11))
    rows = []
    for observation, publication in (
        ("10.01.2012", unknown_marker),
        ("11.09.2017", "12.09.2017"),
    ):
        values = [
            observation,
            "5,00",
            "100,0",
            "10",
            "8",
            "4,50",
            "4,75",
            "5,25",
            "5,50",
            "Standard",
            publication,
        ]
        rows.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
    return (
        f'<html><table class="data"><tr>{headers}</tr>{"".join(rows)}</table></html>'
    ).encode()


def _key_rate_xml() -> bytes:
    return (
        b"<Envelope><Body><KeyRateXMLResponse><KeyRateXMLResult><diffgram><KeyRate>"
        b"<KR><DT>2013-09-13T00:00:00</DT><Rate>5.50</Rate></KR>"
        b"</KeyRate></diffgram></KeyRateXMLResult></KeyRateXMLResponse></Body></Envelope>"
    )


def _small_protocol() -> v3.MacroSourceV3Protocol:
    protocol = v3.load_protocol()
    source_parent = replace(
        protocol.parent.parent,
        minimum_stlfsi_rows=1,
        minimum_ruonia_rows=1,
        minimum_key_rate_rows=1,
    )
    transport_parent = replace(protocol.parent, parent=source_parent)
    return replace(
        protocol,
        parent=transport_parent,
        expected_ruonia_rows=2,
        expected_explicit_publication_rows=1,
        expected_unknown_publication_rows=1,
    )


def test_default_v3_protocol_is_sealed_and_inherits_S2() -> None:
    protocol = v3.load_protocol()

    assert protocol.config_sha256 == (
        "ae575962f8635b47c7b56108c3ec39e511bf8f9ac615da7787790a016425dbee"
    )
    assert protocol.parent.config_sha256 == (
        "4ad7f034939b5becff13bab27309350e02c90e94e991c3907888807557dbd2cc"
    )
    assert protocol.expected_unknown_publication_rows == 1400


def test_ruonia_unknown_publication_is_preserved_without_inference() -> None:
    frame = v3.parse_ruonia_preserving_unknown(_ruonia_html(), _small_protocol())

    unknown = frame.loc[frame["publication_date"].isna()].iloc[0]
    explicit = frame.loc[frame["publication_date"].notna()].iloc[0]
    assert pd.isna(unknown["available_at"])
    assert unknown["availability_rule"] == "publication_date_unavailable_no_inference"
    assert pd.notna(explicit["available_at"])
    assert explicit["availability_rule"] == "publication_date_plus_one_calendar_day"


def test_ruonia_parser_rejects_an_unrecognized_publication_marker() -> None:
    with pytest.raises(ValueError, match="unknown historical RUONIA publication marker"):
        v3.parse_ruonia_preserving_unknown(_ruonia_html("unknown"), _small_protocol())


def test_collect_and_persist_records_unknown_timing_coverage(tmp_path: Path) -> None:
    protocol = replace(_small_protocol(), output_directory=tmp_path / "macro-v3")
    tables = v3.collect(
        protocol,
        session=QueueSession([_fred_csv(), _ruonia_html(), _key_rate_xml()]),
        retrieved_at_utc="2026-09-01T07:00:00Z",
    )

    result = v3.persist(protocol, tables)

    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"].endswith("v3")
    assert manifest["coverage"]["ruonia_unknown_publication_rows"] == 1
    assert (
        manifest["temporal_semantics"]["RUONIA_unknown_publication"]
        == "available_at_missing_no_inference_no_credit"
    )
    assert manifest["lineage"]["S2_output_published"] is False
    with pytest.raises(FileExistsError):
        v3.persist(protocol, tables)


def test_v3_source_schema_remains_outcome_free() -> None:
    with pytest.raises(ValueError, match="outcome columns"):
        v1._assert_source_only_schema({"unsafe": pd.DataFrame({"equity": [1.0]})})
