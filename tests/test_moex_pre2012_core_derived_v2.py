"""Tests for the boundary-only V2 successor of pre-2012 source derivation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2012_core_derived_v1 as v1
from market_lab.futures import moex_pre2012_core_derived_v2 as source


def _manifest_contract(protocol: v1.DerivedProtocol) -> dict[str, object]:
    return {
        "source_id": v1.SOURCE_ID,
        "request_bounds": {
            "from": "2008-01-01",
            "till": "2011-12-31",
            "protected_from": "2026-01-01",
            "all_daily_requests_end_before_2012": True,
        },
        "counts": {
            "contracts": protocol.source_contracts,
            "daily_rows": protocol.source_daily_rows,
            "inert_daily_rows": 2,
        },
        "artifacts": {
            "daily": {"sha256": protocol.source_daily_sha256},
            "raw_archive": {"sha256": protocol.source_raw_sha256},
        },
    }


def _safe_tables() -> v1.derived_base.DerivedTables:
    panel = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2008-10-08")],
            "asset_code": ["SI"],
            "price": [1.0],
        }
    )
    return v1.derived_base.DerivedTables(
        panel=panel,
        active_contract_map=panel.rename(columns={"trade_date": "effective_date"}),
        contract_observations=panel.copy(),
        spec_proxy=panel.rename(columns={"trade_date": "session_date"}),
        audit={
            "calendar_start": "2008-10-08",
            "calendar_end": "2008-10-08",
            "contract_admission": {"synthetic": True},
            "MIX_first_source_session": "2011-09-30",
            "MIX_unavailable_session_count": 0,
            "MIX_unavailable_policy": "explicit_flat_mask_never_backfill",
            "successful_rolls": {asset: 0 for asset in v1.ASSETS},
            "action_counts": {asset: {} for asset in v1.ASSETS},
            "unresolved_roll_count": 0,
            "unresolved_exit_count": 0,
            "panel_rows": 1,
            "active_contract_rows": 1,
        },
    )


def test_default_protocol_pins_failed_D1_and_uses_new_output() -> None:
    protocol = source.load_protocol()

    assert protocol.source_manifest_sha256.startswith("e06fd978")
    assert protocol.output_directory.name.endswith("2008-2011-v2")
    assert protocol.dependency_hashes[
        "src/market_lab/futures/moex_pre2012_core_derived_v1.py"
    ] == source.PARENT_MODULE_SHA256


def test_source_and_derived_boundaries_are_separate() -> None:
    protocol = source.load_protocol()
    manifest = _manifest_contract(protocol)

    assert source._source_manifest_contract_matches(protocol, manifest)
    manifest["request_bounds"]["protected_from"] = "2012-01-01"  # type: ignore[index]
    assert not source._source_manifest_contract_matches(protocol, manifest)


def test_v2_context_is_transactional() -> None:
    original_verifier = v1.verify_and_load_source
    original_source_id = v1.DERIVED_SOURCE_ID

    with source._v2_context():
        assert v1.verify_and_load_source is source.verify_and_load_source
        assert v1.DERIVED_SOURCE_ID == source.DERIVED_SOURCE_ID

    assert original_verifier is v1.verify_and_load_source
    assert original_source_id == v1.DERIVED_SOURCE_ID


def test_v2_persistence_is_separate_and_records_boundary_lineage(
    tmp_path: Path,
) -> None:
    parent = source.load_protocol()
    protocol = replace(parent, output_directory=tmp_path / "derived-v2")

    output = source.persist_derived(protocol, _safe_tables())

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"] == source.DERIVED_SOURCE_ID
    assert manifest["lineage"]["D1_output_published"] is False
    assert manifest["lineage"]["D1_daily_parquet_loaded"] is False
    correction = manifest["boundary_semantics_correction"]
    assert correction["source_acquisition_protected_from"] == "2026-01-01"
    assert correction["derived_market_rows_must_be_before"] == "2012-01-01"
    assert correction["panel_roll_spec_and_availability_rules_unchanged"] is True
    with pytest.raises(FileExistsError):
        source.persist_derived(protocol, _safe_tables())
