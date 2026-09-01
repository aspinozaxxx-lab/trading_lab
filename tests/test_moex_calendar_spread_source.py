"""Tests for the source-only official MOEX calendar-spread collector."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures import moex_calendar_spread_source as source
from market_lab.futures.specs import FuturesAssetSpec


def test_real_source_protocol_is_sealed_and_external() -> None:
    protocol = source.load_protocol()

    assert (
        protocol.config_sha256
        == "7268753933efb4c9633f3e314ebc1d67cf4a7d63e4290e0f3a0142bacce8048e"
    )
    assert protocol.output_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
    assert protocol.payload["scope"] == "source_only_no_returns_targets_or_pnl"


def _series_payload() -> dict[str, Any]:
    columns = [
        "secid",
        "name",
        "start_date",
        "expiration_date",
        "asset_code",
        "underlying_asset",
        "is_traded",
    ]
    return {
        "series": {
            "columns": columns,
            "data": [
                ["SiZ0", "Si-12.20", "2019-01-01", "2020-12-17", "Si", "USD", 0],
                ["SiH1", "Si-3.21", "2020-01-01", "2021-03-18", "Si", "USD", 0],
                ["SiM1", "Si-6.21", "2020-06-01", "2021-06-17", "Si", "USD", 0],
                [
                    "SiZ0SiH1",
                    "SiZ0SiH1",
                    "2020-12-14",
                    "2020-12-17",
                    "Si",
                    "USD",
                    0,
                ],
                [
                    "SiH1SiM1",
                    "SiH1SiM1",
                    "2020-12-14",
                    "2021-03-18",
                    "Si",
                    "USD",
                    0,
                ],
                [
                    "SiH1BRM1",
                    "cross-root service",
                    "2020-12-14",
                    "2021-03-18",
                    "Si",
                    "USD",
                    0,
                ],
            ],
        }
    }


def _catalog_row() -> dict[str, Any]:
    return {
        "spread_id": "SI:SiH1SiM1:2021-03-18:2021-06-17",
        "logical_asset": "SI",
        "asset_code": "Si",
        "secid": "SiH1SiM1",
        "near_secid": "SiH1",
        "far_secid": "SiM1",
        "archive_code": "Si-3.21-6.21",
        "series_start": pd.Timestamp("2020-12-14"),
        "spread_last_trade": pd.Timestamp("2021-03-18"),
        "near_expiration": pd.Timestamp("2021-03-18"),
        "far_expiration": pd.Timestamp("2021-06-17"),
        "expiry_gap_days": 91,
        "near_expiration_matches_spread_last_trade": True,
        "regular_adjacent_expiry": True,
        "board_id": "RFUD",
        "board_history_from": pd.Timestamp("2020-12-14"),
        "board_history_till": pd.Timestamp("2021-03-18"),
        "iss_request_from": pd.Timestamp("2021-01-01"),
        "iss_request_till": pd.Timestamp("2021-03-18"),
        "archive_request_from": pd.Timestamp("2021-01-01"),
        "archive_request_till": pd.Timestamp("2025-12-31"),
    }


def _history_payload(
    *,
    index: int = 0,
    total: int = 2,
    rows: list[list[Any]] | None = None,
) -> dict[str, Any]:
    columns = [
        "BOARDID",
        "TRADEDATE",
        "SECID",
        "OPEN",
        "LOW",
        "HIGH",
        "CLOSE",
        "OPENPOSITIONVALUE",
        "VALUE",
        "VOLUME",
        "OPENPOSITION",
        "SETTLEPRICE",
        "SWAPRATE",
        "WAPRICE",
        "CHANGE",
        "QTY",
        "NUMTRADES",
        "SHORTNAME",
        "ASSETCODE",
    ]
    default_rows = [
        [
            "RFUD",
            "2021-01-11",
            "SiH1SiM1",
            -25.0,
            -31.0,
            -20.0,
            -22.0,
            1000.0,
            5000.0,
            50.0,
            10.0,
            -23.0,
            None,
            -24.0,
            None,
            50.0,
            5.0,
            "SiH1SiM1",
            "Si",
        ],
        [
            "RFUD",
            "2021-01-12",
            "SiH1SiM1",
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            None,
            0.0,
            None,
            0.0,
            0.0,
            "SiH1SiM1",
            "Si",
        ],
    ]
    return {
        "history": {"columns": columns, "data": default_rows if rows is None else rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[index, total, 100]],
        },
    }


def _archive_form_html() -> bytes:
    return b"""<!doctype html><html><body>
<form name="aspnetForm" method="post"
 action="./archive-spreads.aspx?code=Si-3.21-6.21" id="aspnetForm">
<input type="hidden" name="__VIEWSTATE" value="sealed-viewstate" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="generator" />
<input type="radio" name="sorting" value="1" checked="checked" />
<input type="radio" name="sorting" value="2" />
<select name="ctl00$PageContent$ctrlSpreads$ddlBaseActives">
  <option selected="selected" value="Si">Si</option>
</select>
<select name="ctl00$PageContent$ctrlSpreads$ddlSpreads">
  <option selected="selected" value="Si-3.21-6.21">Si-3.21-6.21</option>
</select>
<input type="hidden"
 name="ctl00$PageContent$ctrlSpreads$CascadingDropDown1_ClientState" value="Si" />
<input type="hidden"
 name="ctl00$PageContent$ctrlSpreads$CascadingDropDown2_ClientState"
 value="Si-3.21-6.21" />
<input type="submit" name="ignored-submit" value="Search" />
<a href="javascript:__doPostBack(
 'ctl00$PageContent$ctrlSpreads$lbExportToCsvComma','')">CSV</a>
</form></body></html>"""


def _archive_csv(*, protected: bool = False) -> bytes:
    first_date = "1/1/2026 12:00:00 AM" if protected else "1/11/2021 12:00:00 AM"
    document = (
        "moment,isin,small_name,best_pk,best_pr,cena,min_cena,max_cena,"
        "c_deal,kol_cb,sum_rub,base_small_name,\r\n"
        f"{first_date},123,Si-3.21-6.21,-30.0,-20.0,-25.0,-31.0,-20.0,"
        "5,50,5000.0,Si,\r\n"
        "1/12/2021 12:00:00 AM,123,Si-3.21-6.21,0.0,0.0,0.0,0.0,0.0,"
        "0,0,0.0,Si,\r\n"
    )
    return document.encode("cp1251")


def test_closed_discovery_maps_exact_adjacent_legs() -> None:
    result = source.discover_spreads(
        _series_payload(),
        FuturesAssetSpec.from_symbol("SI"),
        source_start=date(2021, 1, 1),
        source_end=date(2021, 12, 31),
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["secid"] == "SiH1SiM1"
    assert row["near_secid"] == "SiH1"
    assert row["far_secid"] == "SiM1"
    assert row["archive_code"] == "Si-3.21-6.21"
    assert row["expiry_gap_days"] == 91
    assert bool(row["regular_adjacent_expiry"])
    assert bool(row["near_expiration_matches_spread_last_trade"])
    assert row["spread_id"] == "SI:SiH1SiM1:2021-03-18:2021-06-17"


def test_official_archive_form_reconstructs_exact_csv_postback() -> None:
    fields = source.parse_archive_form(
        _archive_form_html(),
        asset_code="Si",
        archive_code="Si-3.21-6.21",
    )

    assert fields["__VIEWSTATE"] == "sealed-viewstate"
    assert fields["sorting"] == "1"
    assert fields["__EVENTTARGET"] == source.ARCHIVE_EXPORT_TARGET
    assert fields["__EVENTARGUMENT"] == ""
    assert "ignored-submit" not in fields


def test_public_archive_csv_preserves_signed_and_zero_values() -> None:
    parsed = source.parse_archive_csv(
        _archive_csv(),
        _catalog_row(),
        date(2021, 1, 1),
        date(2021, 3, 18),
    )

    assert parsed["last"].tolist() == [-25.0, 0.0]
    assert parsed["bid"].tolist() == [-30.0, 0.0]
    assert parsed["reported_trade_activity"].tolist() == [True, False]
    assert parsed["last_within_range"].all()
    assert parsed["inside_iss_request_interval"].all()
    assert parsed["archive_instrument_id"].tolist() == ["123", "123"]


def test_public_archive_csv_rejects_protected_market_values() -> None:
    with pytest.raises(ValueError, match="protected market values"):
        source.parse_archive_csv(
            _archive_csv(protected=True),
            _catalog_row(),
            date(2021, 1, 1),
            date(2025, 12, 31),
        )


def test_archive_spread_list_requires_exact_unique_official_identity() -> None:
    payload = {
        "d": [
            {"name": "Si-3.21-6.21", "value": "Si-3.21-6.21"},
            {"name": "Si-6.21-9.21", "value": "Si-6.21-9.21"},
        ]
    }

    assert source.parse_archive_spread_list(payload) == (
        "Si-3.21-6.21",
        "Si-6.21-9.21",
    )
    payload["d"].append(payload["d"][0])
    with pytest.raises(ValueError, match="duplicates"):
        source.parse_archive_spread_list(payload)


class _StaticArchiveClient:
    def __init__(self) -> None:
        self.posted_fields: dict[str, str] | None = None

    def get_bytes(self, url: str) -> tuple[bytes, dict[str, str]]:
        assert url.endswith("?code=Si-3.21-6.21")
        return _archive_form_html(), {
            "content_type": "text/html; charset=utf-8",
            "content_disposition": "",
        }

    def post_form_bytes(
        self, url: str, fields: dict[str, str]
    ) -> tuple[bytes, dict[str, str]]:
        assert url.endswith("?code=Si-3.21-6.21")
        self.posted_fields = fields
        return _archive_csv(), {
            "content_type": "application/csv; charset=windows-1251",
            "content_disposition": "attachment;filename=ArchiveSpreads.csv",
        }


def test_public_archive_fetch_preserves_exact_page_and_csv_bodies() -> None:
    client = _StaticArchiveClient()
    parsed, records = source._fetch_public_archive(
        client,  # type: ignore[arg-type]
        FuturesAssetSpec.from_symbol("SI"),
        _catalog_row(),
        date(2021, 1, 1),
        date(2025, 12, 31),
    )

    assert len(parsed) == 2
    assert client.posted_fields is not None
    assert client.posted_fields["__EVENTTARGET"] == source.ARCHIVE_EXPORT_TARGET
    assert [record.kind for record in records] == ["archive_page", "archive_csv"]
    assert source._response_body_bytes(records[0].payload) == _archive_form_html()
    assert source._response_body_bytes(records[1].payload) == _archive_csv()


def test_signed_and_zero_spread_prices_are_preserved() -> None:
    parsed, cursor = source.parse_spread_history_page(
        _history_payload(), _catalog_row()
    )

    assert cursor.total == 2
    assert parsed["open"].tolist() == [-25.0, 0.0]
    assert parsed["settle"].tolist() == [-23.0, 0.0]
    assert parsed["ohlc_complete"].all()
    assert parsed["has_settlement"].all()
    assert parsed["reported_trade_activity"].tolist() == [True, False]
    assert parsed["available_at"].dt.tz is not None
    assert parsed.loc[0, "available_at"] == pd.Timestamp(
        "2021-01-12T00:00:00", tz="Europe/Moscow"
    )


def test_signed_ohlc_invariant_fails_closed() -> None:
    payload = _history_payload()
    payload["history"]["data"][0][5] = -30.0

    with pytest.raises(ValueError, match="signed OHLC invariant"):
        source.parse_spread_history_page(payload, _catalog_row())


class _StaticClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        return self.payload


def test_history_fetch_proves_cursor_and_protected_boundary() -> None:
    client = _StaticClient(_history_payload())
    frame, records = source._fetch_history(
        client,  # type: ignore[arg-type]
        FuturesAssetSpec.from_symbol("SI"),
        _catalog_row(),
        date(2021, 1, 1),
        date(2021, 3, 18),
    )

    assert len(frame) == 2
    assert len(records) == 1
    assert "till=2021-03-18" in client.urls[0]
    with pytest.raises(ValueError, match="protected"):
        source._fetch_history(
            client,  # type: ignore[arg-type]
            FuturesAssetSpec.from_symbol("SI"),
            _catalog_row(),
            date(2025, 12, 31),
            date(2026, 1, 1),
        )


def test_truncated_history_page_is_rejected() -> None:
    payload = _history_payload(total=3)
    client = _StaticClient(payload)

    with pytest.raises(ValueError, match="truncated"):
        source._fetch_history(
            client,  # type: ignore[arg-type]
            FuturesAssetSpec.from_symbol("SI"),
            _catalog_row(),
            date(2021, 1, 1),
            date(2021, 3, 18),
        )


def test_raw_archive_is_deterministic_and_replayable() -> None:
    record = source.RawRecord(
        kind="history",
        logical_asset="SI",
        secid="SiH1SiM1",
        spread_id=_catalog_row()["spread_id"],
        archive_code="Si-3.21-6.21",
        request_from="2021-01-01",
        request_till="2021-03-18",
        url="https://iss.moex.test/history",
        payload=_history_payload(),
    )

    first = source._raw_archive_bytes([record])
    second = source._raw_archive_bytes([record])
    decoded = json.loads(gzip.decompress(first).decode("utf-8"))

    assert first == second
    assert decoded["spread_id"] == record.spread_id
    assert decoded["payload"]["history.cursor"]["data"] == [[0, 2, 100]]
