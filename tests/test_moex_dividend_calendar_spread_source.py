"""Tests for the sealed dividend-stock calendar-spread source adapter."""

from __future__ import annotations

from market_lab.futures import moex_calendar_spread_source as base
from market_lab.futures import moex_dividend_calendar_spread_source as source


def test_protocol_loads_and_pins_external_cashflow() -> None:
    protocol = source.load_protocol()

    assert protocol.config_sha256 == source.CONFIG_SHA256
    assert protocol.output_directory.name == ("moex-dividend-calendar-spreads-2023-2025-v1")
    assert (
        protocol.dependency_hashes[
            "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/cashflow.parquet"
        ]
        == source.RMS_FILES[
            "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4/cashflow.parquet"
        ]
    )


def test_dividend_asset_registry_is_closed() -> None:
    gazr = source.DividendAssetSpec.from_symbol("gazr")

    assert (gazr.asset_code, gazr.logical_symbol, gazr.security_prefix) == (
        "GAZR",
        "GAZR",
        "GZ",
    )
    assert source.EXPECTED_MISSING_DATE_SPREADS["GAZR"] == ("GZU2GZZ2",)


def test_shared_registry_is_restored_after_adapter_context() -> None:
    original_assets = base.ASSETS
    original_spec = base.FuturesAssetSpec
    original_discover = base.discover_spreads
    original_history_parser = base.parse_spread_history_page

    with source._dividend_registry():
        assert base.ASSETS == source.ASSETS
        assert base.FuturesAssetSpec is source.DividendAssetSpec
        assert base.discover_spreads is not original_discover
        assert base.parse_spread_history_page is not original_history_parser

    assert original_assets == base.ASSETS
    assert base.FuturesAssetSpec is original_spec
    assert base.discover_spreads is original_discover
    assert base.parse_spread_history_page is original_history_parser


def test_blank_uppercase_assetcode_is_normalized_without_mutating_raw() -> None:
    raw = {"history": {"columns": ["SECID", "ASSETCODE"], "data": [["X", ""]]}}

    normalized = source._blank_assetcode_as_missing(raw)

    assert normalized["history"]["data"] == [["X", None]]
    assert raw["history"]["data"] == [["X", ""]]
