"""Tests for the sealed stock-futures cash-carry source."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_stock_futures_cash_carry_source as source


def test_protocol_and_identity_catalog_are_exact() -> None:
    protocol = source.load_protocol()
    catalog, raw_series = source.build_contract_catalog(protocol)
    cashflows = source._load_rms_cashflows(protocol)

    assert protocol.config_sha256 == source.CONFIG_SHA256
    assert len(catalog) == 61
    assert len(raw_series) == 5
    assert catalog.groupby("logical_asset").size().to_dict() == source.EXPECTED_COUNTS
    assert tuple(cashflows.columns) == source.RMS_COLUMNS
    assert set(cashflows["logical_asset"]) == set(source.ASSETS)
    assert pd.to_datetime(cashflows["available_at_utc"], utc=True).dt.year.max() <= 2025


def test_dividend_parser_filters_period_and_marks_outcome_only() -> None:
    payload = {
        "dividends": {
            "columns": ["secid", "isin", "registryclosedate", "value", "currencyid"],
            "data": [
                ["GAZP", "RU0007661625", "2022-07-20", 10.0, "RUB"],
                ["GAZP", "RU0007661625", "2024-07-20", 15.0, "RUB"],
            ],
        },
        "dividends.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, 2, 100]],
        },
    }

    frame, cursor = source._parse_dividends(
        payload, "GAZR", pd.Timestamp("2026-09-02T00:00:00Z")
    )

    assert cursor.total == 2
    assert len(frame) == 1
    assert frame.loc[0, "value"] == 15.0
    assert bool(frame.loc[0, "outcome_reference_only"])


def test_raw_archive_is_deterministic(tmp_path) -> None:
    records = [{"kind": "x", "payload": {"b": 2, "a": 1}}]
    first = source._raw_bytes(records)
    second = source._raw_bytes(records)
    path = tmp_path / "raw.jsonl.gz"
    path.write_bytes(first)

    assert first == second
    assert source._read_raw(path) == records
