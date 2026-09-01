"""Tests for the outcome-free calendar-spread active-panel derivation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures import moex_calendar_spread_derived_v1 as derived
from market_lab.futures import moex_calendar_spread_source as source


def _catalog_row(
    *,
    logical_asset: str,
    asset_code: str,
    secid: str,
    near_secid: str,
    far_secid: str,
    near_expiration: str,
    far_expiration: str,
) -> dict[str, Any]:
    row = {column: None for column in source.CATALOG_COLUMNS}
    near = pd.Timestamp(near_expiration)
    far = pd.Timestamp(far_expiration)
    row.update(
        {
            "spread_id": f"{logical_asset}:{secid}:{near.date()}:{far.date()}",
            "logical_asset": logical_asset,
            "asset_code": asset_code,
            "secid": secid,
            "near_secid": near_secid,
            "far_secid": far_secid,
            "archive_code": f"{asset_code}-synthetic-{secid}",
            "series_start": pd.Timestamp("2020-12-01"),
            "spread_last_trade": near,
            "near_expiration": near,
            "far_expiration": far,
            "expiry_gap_days": int((far - near).days),
            "near_expiration_matches_spread_last_trade": True,
            "regular_adjacent_expiry": True,
            "board_id": "RFUD",
            "board_history_from": pd.Timestamp("2020-12-01"),
            "board_history_till": near,
            "iss_request_from": pd.Timestamp("2021-01-01"),
            "iss_request_till": near,
            "archive_request_from": pd.Timestamp("2021-01-01"),
            "archive_request_till": pd.Timestamp("2025-12-31"),
        }
    )
    return row


def _archive_row(catalog_row: dict[str, Any], *, locked: bool = False) -> dict[str, Any]:
    row = {column: None for column in source.ARCHIVE_DAILY_COLUMNS}
    bid = 0.0 if locked else -11.0
    ask = 0.0 if locked else -9.0
    row.update(
        {
            "trade_date": pd.Timestamp("2021-01-11"),
            "available_at": pd.Timestamp("2021-01-12", tz="Europe/Moscow"),
            "spread_id": catalog_row["spread_id"],
            "logical_asset": catalog_row["logical_asset"],
            "asset_code": catalog_row["asset_code"],
            "secid": catalog_row["secid"],
            "archive_code": catalog_row["archive_code"],
            "archive_instrument_id": f"id-{catalog_row['secid']}",
            "near_secid": catalog_row["near_secid"],
            "far_secid": catalog_row["far_secid"],
            "spread_last_trade": catalog_row["spread_last_trade"],
            "near_expiration": catalog_row["near_expiration"],
            "far_expiration": catalog_row["far_expiration"],
            "last": 0.0 if locked else -10.0,
            "bid": bid,
            "ask": ask,
            "high": 0.0 if locked else -8.0,
            "low": 0.0 if locked else -12.0,
            "amount": 100.0,
            "volume": 1000.0,
            "num_trades": 10.0,
            "reported_trade_activity": True,
            "range_complete": True,
            "last_within_range": True,
            "last_outside_range": False,
            "two_sided_quote_fields_complete": True,
            "closing_quote_crossed": False,
            "inside_iss_request_interval": True,
            "inside_series_interval": True,
        }
    )
    return row


def _spec_rows(active_catalog_rows: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for catalog in active_catalog_rows:
        for side in ("near", "far"):
            expiration = pd.Timestamp(catalog[f"{side}_expiration"])
            secid = str(catalog[f"{side}_secid"])
            row = {
                "session_date": pd.Timestamp("2021-01-11"),
                "contract_id": f"{catalog['asset_code']}:{secid}:{expiration.date()}",
                "sizing_observed_session_date": pd.Timestamp("2021-01-08"),
                "sizing_point_value": 10.0,
                "sizing_notional": 10000.0,
                "sizing_tick_cash_value": 10.0,
                "modeled_initial_margin": 1000.0,
                "expected_buffered_initial_margin": 1250.0,
                "sizing_status": "usable",
                "sizing_usable": True,
                "tick_size": 1.0,
                "conservative_fee_per_side": 2.0,
                "approximate": True,
                "historical_exchange_exact": False,
                "broker_exact": False,
            }
            rows.append(row)
    return pd.DataFrame(rows, columns=("session_date", "contract_id", *derived.SPEC_FIELDS))


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    definitions = [
        ("SI", "Si", "SiF1SiG1", "SiF1", "SiG1", "2021-01-21", "2021-02-18"),
        ("SI", "Si", "SiF1SiH1", "SiF1", "SiH1", "2021-01-31", "2021-03-18"),
        ("RI", "RTS", "RIF1RIG1", "RIF1", "RIG1", "2021-01-22", "2021-02-19"),
        ("BR", "BR", "BRF1BRG1", "BRF1", "BRG1", "2021-01-20", "2021-02-17"),
        ("MIX", "MIX", "MXF1MXG1", "MXF1", "MXG1", "2021-01-23", "2021-02-20"),
    ]
    catalog_rows = [
        _catalog_row(
            logical_asset=item[0],
            asset_code=item[1],
            secid=item[2],
            near_secid=item[3],
            far_secid=item[4],
            near_expiration=item[5],
            far_expiration=item[6],
        )
        for item in definitions
    ]
    catalog = pd.DataFrame(catalog_rows, columns=source.CATALOG_COLUMNS)
    archive = pd.DataFrame(
        [
            _archive_row(row, locked=row["logical_asset"] == "BR")
            for row in catalog_rows
        ],
        columns=source.ARCHIVE_DAILY_COLUMNS,
    )
    selected_rows = [catalog_rows[0], *catalog_rows[2:]]
    return catalog, archive, _spec_rows(selected_rows)


def test_real_derived_protocol_is_sealed_and_external() -> None:
    protocol = derived.load_protocol()

    assert protocol.config_sha256 == (
        "657fd42b472797028f5b0194c7b159ac1538ddab5caea8f9c416f0a403e34cd0"
    )
    assert protocol.output_directory.resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
    assert protocol.payload["scope"] == "source_derived_no_returns_targets_or_pnl"


def test_structural_selection_chooses_nearest_and_preserves_locked_quote() -> None:
    catalog, archive, spec = _inputs()

    tables = derived.derive_tables(
        catalog,
        archive,
        spec,
        enforce_sealed_counts=False,
    )

    assert len(tables.candidates) == 5
    assert len(tables.active) == 4
    si = tables.active.loc[tables.active["logical_asset"].eq("SI")].iloc[0]
    assert si["secid"] == "SiF1SiG1"
    br_locked = tables.active.loc[
        tables.active["logical_asset"].eq("BR"), "zero_locked_quote"
    ]
    assert bool(br_locked.iloc[0])
    assert tables.active["both_sizing_usable"].all()
    assert tables.active["spec_observations_strictly_prior"].all()
    assert not any(
        token in str(column).lower()
        for column in tables.active.columns
        for token in derived.FORBIDDEN_COLUMN_TOKENS
    )


def test_equal_nearest_expiry_tie_is_rejected() -> None:
    catalog, archive, spec = _inputs()
    second_si = archive["secid"].eq("SiF1SiH1")
    archive.loc[second_si, "near_expiration"] = pd.Timestamp("2021-01-21")

    with pytest.raises(ValueError, match="contains a tie"):
        derived.derive_tables(
            catalog,
            archive,
            spec,
            enforce_sealed_counts=False,
        )
