"""Tests for deterministic persistence normalization in pre-2012 derived V3."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2012_core_derived_v1 as v1
from market_lab.futures import moex_pre2012_core_derived_v3 as source


def _tables() -> v1.derived_base.DerivedTables:
    panel = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2008-10-08"), pd.Timestamp("2008-10-09")],
            "asset_code": ["SI", "MIX"],
            "curve_valid": pd.Series([True, False], dtype="object"),
            "participant_snapshot_complete": pd.Series([False, False], dtype="object"),
            "price": [1.0, pd.NA],
        }
    )
    audit = {
        "calendar_start": "2008-10-08",
        "calendar_end": "2008-10-09",
        "contract_admission": {
            "admitted_month_codes": {
                asset: tuple(codes) for asset, codes in v1.ADMITTED_MONTH_CODES.items()
            }
        },
        "MIX_first_source_session": "2011-09-30",
        "MIX_unavailable_session_count": 1,
        "MIX_unavailable_policy": "explicit_flat_mask_never_backfill",
        "successful_rolls": {asset: 0 for asset in v1.ASSETS},
        "action_counts": {asset: {} for asset in v1.ASSETS},
        "unresolved_roll_count": 0,
        "unresolved_exit_count": 0,
        "panel_rows": 2,
        "active_contract_rows": 2,
    }
    return v1.derived_base.DerivedTables(
        panel=panel,
        active_contract_map=panel.rename(columns={"trade_date": "effective_date"}),
        contract_observations=panel.copy(),
        spec_proxy=panel.rename(columns={"trade_date": "session_date"}),
        audit=audit,
    )


def test_default_protocol_pins_failed_D2_and_new_output() -> None:
    protocol = source.load_protocol()

    assert protocol.output_directory.name.endswith("2008-2011-v3")
    assert protocol.dependency_hashes[
        "src/market_lab/futures/moex_pre2012_core_derived_v2.py"
    ] == source.PARENT_MODULE_SHA256


def test_normalization_changes_only_representation() -> None:
    original = _tables()

    normalized = source.normalize_persistence_types(original)

    assert str(normalized.panel["curve_valid"].dtype) == "bool"
    assert str(normalized.panel["participant_snapshot_complete"].dtype) == "bool"
    assert normalized.panel["curve_valid"].tolist() == [True, False]
    codes = normalized.audit["contract_admission"]["admitted_month_codes"]
    assert all(isinstance(values, list) for values in codes.values())
    assert codes == {asset: list(values) for asset, values in v1.ADMITTED_MONTH_CODES.items()}
    assert isinstance(
        original.audit["contract_admission"]["admitted_month_codes"]["SI"], tuple
    )


def test_normalization_rejects_missing_boolean() -> None:
    tables = _tables()
    tables.panel.loc[0, "curve_valid"] = pd.NA

    with pytest.raises(ValueError, match="found missing curve_valid"):
        source.normalize_persistence_types(tables)


def test_v3_persistence_records_failed_D2_and_is_immutable(tmp_path: Path) -> None:
    parent = source.load_protocol()
    protocol = replace(parent, output_directory=tmp_path / "derived-v3")
    tables = source.normalize_persistence_types(_tables())

    output = source.persist_derived(protocol, tables)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"] == source.DERIVED_SOURCE_ID
    assert manifest["lineage"]["D2_manifest_sha256"] == (
        source.FAILED_D2_MANIFEST_SHA256
    )
    correction = manifest["deterministic_persistence_correction"]
    assert correction["boolean_values_changed"] is False
    assert correction["month_code_values_changed"] is False
    assert correction["market_value_mismatch_count_in_D2_diagnosis"] == 0
    with pytest.raises(FileExistsError):
        source.persist_derived(protocol, tables)
