"""Synthetic tests for the sealed 2012-2017 external macro source collector."""

from __future__ import annotations

import base64
import gzip
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import pre2018_macro_source as macro


class FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


class QueueSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: object,
        timeout: float,
        data: bytes | None = None,
    ) -> FakeResponse:
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "timeout": timeout, "data": data}
        )
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def _fred_csv() -> bytes:
    return b"observation_date,STLFSI4\n2012-01-06,-0.5\n2012-01-13,.\n"


def _ruonia_html() -> bytes:
    headers = "".join(f"<th>h{index}</th>" for index in range(11))
    values = [
        "10.01.2012",
        "5,00",
        "100,0",
        "10",
        "8",
        "4,50",
        "4,75",
        "5,25",
        "5,50",
        "Standard",
        "11.01.2012",
    ]
    row = "".join(f"<td>{value}</td>" for value in values)
    return f'<html><table class="data"><tr>{headers}</tr><tr>{row}</tr></table></html>'.encode()


def _key_rate_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b"<Envelope><Body><KeyRateXMLResponse><KeyRateXMLResult><diffgram><KeyRate>"
        b"<KR><DT>2013-09-13T00:00:00</DT><Rate>5.50</Rate></KR>"
        b"</KeyRate></diffgram></KeyRateXMLResult></KeyRateXMLResponse></Body></Envelope>"
    )


def _small_protocol() -> macro.MacroSourceProtocol:
    return replace(
        macro.load_protocol(),
        minimum_stlfsi_rows=1,
        minimum_ruonia_rows=1,
        minimum_key_rate_rows=1,
    )


def test_default_protocol_is_byte_sealed_and_urls_are_server_bounded() -> None:
    protocol = macro.load_protocol()

    assert protocol.config_sha256 == (
        "3daa3c404255f0928135ac7ba5e8c732bacbfefe49ddacd63bccc2fbdaa37826"
    )
    assert macro.fred_url(protocol).endswith(
        "id=STLFSI4&cosd=2012-01-01&coed=2017-12-31"
    )
    assert protocol.output_directory.relative_to(macro.PROJECT_ROOT).as_posix().startswith(
        "data/processed/info_radar/"
    )


def test_stlfsi_parser_preserves_missing_and_uses_following_thursday() -> None:
    frame = macro.parse_stlfsi(_fred_csv(), _small_protocol())

    assert frame["complete"].tolist() == [True, False]
    assert frame["stress_state"].tolist() == ["normal_or_below", "missing"]
    assert frame.loc[0, "available_at"] == macro.stlfsi_available_at(
        pd.Timestamp("2012-01-06").date()
    )


def test_collect_uses_exact_three_sources_and_causal_availability() -> None:
    session = QueueSession(
        [
            FakeResponse(_fred_csv(), "text/csv"),
            FakeResponse(_ruonia_html(), "text/html"),
            FakeResponse(_key_rate_xml(), "text/xml"),
        ]
    )

    tables = macro.collect(
        _small_protocol(),
        session=session,
        retrieved_at_utc="2026-09-01T07:00:00Z",
    )

    assert [request["method"] for request in session.requests] == ["GET", "GET", "POST"]
    assert tables.monetary["series_id"].tolist() == ["key_rate", "ruonia"]
    assert tables.monetary["available_at"].dt.tz is not None
    assert tables.stlfsi["retrieved_at_utc"].dt.tz is not None
    assert len(tables.responses) == 3


def test_persistence_is_immutable_and_raw_archive_replays(tmp_path: Path) -> None:
    session = QueueSession(
        [
            FakeResponse(_fred_csv(), "text/csv"),
            FakeResponse(_ruonia_html(), "text/html"),
            FakeResponse(_key_rate_xml(), "text/xml"),
        ]
    )
    protocol = replace(_small_protocol(), output_directory=tmp_path / "macro-source")
    tables = macro.collect(
        protocol,
        session=session,
        retrieved_at_utc="2026-09-01T07:00:00Z",
    )

    result = macro.persist(protocol, tables)

    assert result == protocol.output_directory.resolve()
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["request_count"] == 3
    assert (
        manifest["temporal_semantics"][
            "contains_MOEX_prices_returns_targets_labels_or_pnl"
        ]
        is False
    )
    with gzip.open(result / "official_macro_responses.jsonl.gz", "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    assert len(records) == 3
    assert base64.b64decode(records[0]["content"]) == _fred_csv()
    with pytest.raises(FileExistsError):
        macro.persist(protocol, tables)


def test_source_schema_rejects_outcome_columns() -> None:
    with pytest.raises(ValueError, match="outcome columns"):
        macro._assert_source_only_schema(
            {"unsafe": pd.DataFrame({"prediction_return": [0.1]})}
        )
