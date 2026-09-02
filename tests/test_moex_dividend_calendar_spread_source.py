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

    with source._dividend_registry():
        assert base.ASSETS == source.ASSETS
        assert base.FuturesAssetSpec is source.DividendAssetSpec
        assert base.discover_spreads is not original_discover

    assert original_assets == base.ASSETS
    assert base.FuturesAssetSpec is original_spec
    assert base.discover_spreads is original_discover
