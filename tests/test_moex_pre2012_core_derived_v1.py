"""Synthetic tests for the sealed variable-availability pre-2012 derivation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import moex_pre2012_core_derived_v1 as source
from market_lab.futures import moex_pre2018_core4_derived as derived_base
from market_lab.futures import panel as panel_core


def _mix_dates() -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    observed = pd.DatetimeIndex(
        [source.EXPECTED_MIX_START]
        + list(pd.date_range("2011-10-01", periods=52, freq="D"))
        + [source.EXPECTED_MIX_END]
    )
    unavailable = pd.date_range(end="2011-09-29", periods=727, freq="D")
    return unavailable.append(observed), observed


def _partial_mix_panel(observed: pd.DatetimeIndex) -> pd.DataFrame:
    rows = len(observed)
    return pd.DataFrame(
        {
            "trade_date": observed,
            "asset_code": pd.Series(["MIX"] * rows, dtype="string"),
            "active_contract_id": pd.Series(["MIX:MXZ1"] * rows, dtype="string"),
            "active_contract_action": pd.Series(["hold"] * rows, dtype="string"),
            "active_contract_reason": pd.Series(["front_retained"] * rows, dtype="string"),
            "active_contract_valid": pd.Series([True] * rows, dtype="boolean"),
            "active_contract_carry_unfilled": pd.Series([False] * rows, dtype="boolean"),
            "active_expiry_horizon_censored": pd.Series([False] * rows, dtype="boolean"),
            "active_chain_id": [1] * rows,
            "open": [1.0] * rows,
            "high": [1.0] * rows,
            "low": [1.0] * rows,
            "close": [1.0] * rows,
            "volume": [1.0] * rows,
            "open_interest": [1.0] * rows,
            "raw_ohlc_missing_with_activity": pd.Series(
                [False] * rows, dtype="boolean"
            ),
            "raw_ohlc_complete": pd.Series([True] * rows, dtype="boolean"),
            "curve_observed_through": observed,
            "curve_available_at": pd.Series(["decision_close"] * rows, dtype="string"),
            "front_contract_id": pd.Series(["MIX:MXZ1"] * rows, dtype="string"),
            "next_contract_id": pd.Series([pd.NA] * rows, dtype="string"),
            "front_settle": [1.0] * rows,
            "next_settle": [np.nan] * rows,
            "front_expiration_date": [source.EXPECTED_MIX_END] * rows,
            "next_expiration_date": [pd.NaT] * rows,
            "front_days_to_expiry": [1.0] * rows,
            "next_days_to_expiry": [np.nan] * rows,
            "roll_yield": [np.nan] * rows,
            "curve_valid": pd.Series([False] * rows, dtype="boolean"),
            "participant_source_date": [pd.NaT] * rows,
            "participant_lag_sessions": [np.nan] * rows,
            "participant_snapshot_complete": pd.Series(
                [False] * rows, dtype="boolean"
            ),
            "physical_long": [np.nan] * rows,
            "physical_short": [np.nan] * rows,
            "legal_long": [np.nan] * rows,
            "legal_short": [np.nan] * rows,
        }
    )


def _partial_mix_active(observed: pd.DatetimeIndex) -> pd.DataFrame:
    rows = len(observed)
    frame = pd.DataFrame(
        {
            "effective_date": observed,
            "decision_date": observed - pd.Timedelta(days=1),
            "observed_through": observed - pd.Timedelta(days=1),
            "asset_code": ["MIX"] * rows,
            "contract_id": ["MIX:MXZ1"] * rows,
            "secid": ["MXZ1_2011"] * rows,
            "expiration_date": [source.EXPECTED_MIX_END] * rows,
            "action": ["hold"] * rows,
            "reason": ["front_retained"] * rows,
            "roll": [False] * rows,
            "plan_tradable": [True] * rows,
            "expiry_horizon_censored": [False] * rows,
            "carry_unfilled": [False] * rows,
            "execution_open_available": [True] * rows,
            "feature_input_valid": [True] * rows,
            "chain_id": [1] * rows,
            "forward_additive_adjustment": [0.0] * rows,
        }
    )
    for column in source.MIX_ACTIVE_MARKET_COLUMNS:
        frame[column] = 1.0
    for column in (
        "reported_trade_activity",
        "ohlc_complete",
        "ohlc_missing_with_activity",
        "has_trade",
        "has_settlement",
    ):
        frame[column] = column != "ohlc_missing_with_activity"
    return frame


def _safe_tables() -> derived_base.DerivedTables:
    panel = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2008-10-08")],
            "asset_code": ["SI"],
            "price": [1.0],
        }
    )
    active = panel.rename(columns={"trade_date": "effective_date"})
    return derived_base.DerivedTables(
        panel=panel,
        active_contract_map=active,
        contract_observations=panel.copy(),
        spec_proxy=panel.rename(columns={"trade_date": "session_date"}),
        audit={
            "calendar_start": "2008-10-08",
            "calendar_end": "2008-10-08",
            "contract_admission": {"synthetic": True},
            "MIX_first_source_session": "2011-09-30",
            "MIX_unavailable_session_count": 0,
            "MIX_unavailable_policy": "explicit_flat_mask_never_backfill",
            "successful_rolls": {asset: 0 for asset in source.ASSETS},
            "action_counts": {asset: {} for asset in source.ASSETS},
            "unresolved_roll_count": 0,
            "unresolved_exit_count": 0,
            "panel_rows": 1,
            "active_contract_rows": 1,
        },
    )


def test_default_protocol_is_byte_sealed_and_source_only() -> None:
    protocol = source.load_protocol()

    assert protocol.source_manifest_sha256.startswith("e06fd978")
    assert protocol.source_daily_rows == 8_381
    assert protocol.source_contracts == 81
    assert protocol.output_directory.name.endswith("2008-2011-v1")
    assert protocol.roll_config.confirmation_days == 2
    assert set(protocol.dependency_hashes) == {
        "src/market_lab/futures/moex_pre2012_core_derived_v1.py",
        "src/market_lab/futures/moex_pre2018_core4_derived.py",
        "src/market_lab/futures/panel.py",
        "src/market_lab/futures/roll.py",
        "src/market_lab/futures/spec_proxy.py",
        "src/market_lab/io_utils.py",
    }


def test_contract_month_code_supports_historical_mix_root() -> None:
    assert source._contract_month_code(
        {"logical_symbol": "MIX", "secid": "MXZ1_2011"}
    ) == "Z"
    assert source._contract_month_code(
        {"logical_symbol": "SI", "secid": "SiH9_2009"}
    ) == "H"
    with pytest.raises(ValueError, match="contract root mismatch"):
        source._contract_month_code({"logical_symbol": "MIX", "secid": "MIXZ1"})


def test_panel_universe_context_is_transactional() -> None:
    original = panel_core.REQUIRED_LOGICAL_ASSETS

    with source._panel_universe(source.CORE3):
        assert panel_core.REQUIRED_LOGICAL_ASSETS == source.CORE3

    assert original == panel_core.REQUIRED_LOGICAL_ASSETS


def test_mix_expansion_is_explicit_flat_mask_without_market_backfill() -> None:
    calendar, observed = _mix_dates()
    panel = source._expand_mix_panel(_partial_mix_panel(observed), calendar)
    active = source._expand_mix_active(_partial_mix_active(observed), calendar)
    unavailable_panel = panel.iloc[: source.EXPECTED_MIX_UNAVAILABLE_SESSIONS]
    unavailable_active = active.iloc[: source.EXPECTED_MIX_UNAVAILABLE_SESSIONS]

    assert len(panel) == source.EXPECTED_MASTER_SESSIONS
    assert unavailable_panel["active_contract_reason"].eq(
        "asset_not_yet_available"
    ).all()
    assert not unavailable_panel["active_contract_valid"].any()
    assert unavailable_panel[list(source.MIX_PANEL_MARKET_COLUMNS)].isna().all(axis=None)
    assert unavailable_active["reason"].eq("asset_not_yet_available").all()
    assert not unavailable_active["plan_tradable"].any()
    assert unavailable_active[list(source.MIX_ACTIVE_MARKET_COLUMNS)].isna().all(
        axis=None
    )


def test_persistence_is_immutable_and_declares_variable_availability(
    tmp_path: Path,
) -> None:
    parent = source.load_protocol()
    protocol = replace(parent, output_directory=tmp_path / "derived")

    output = source.persist_derived(protocol, _safe_tables())

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"] == source.DERIVED_SOURCE_ID
    assert manifest["variable_availability"]["master_assets"] == list(source.CORE3)
    assert manifest["variable_availability"]["MIX_unavailable_policy"] == (
        "explicit_flat_mask_never_backfill"
    )
    assert manifest["temporal_semantics"][
        "contains_returns_targets_labels_signals_equity_or_pnl"
    ] is False
    with pytest.raises(FileExistsError):
        source.persist_derived(protocol, _safe_tables())


def test_source_only_schema_rejects_outcome_columns() -> None:
    with pytest.raises(ValueError, match="outcome columns"):
        derived_base._assert_source_only_schema(
            {"bad": pd.DataFrame({"trade_date": [pd.Timestamp("2008-01-01")], "return": [0.1]})}
        )
