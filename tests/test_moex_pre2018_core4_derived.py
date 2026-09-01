"""Tests for the sealed source-only MOEX 2012-2017 causal transformation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2018_core4_derived as derived


def _safe_tables() -> derived.DerivedTables:
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2012-01-03")],
            "asset_code": ["SI"],
            "price": [30_000.0],
        }
    )
    return derived.DerivedTables(
        panel=frame,
        active_contract_map=frame.rename(columns={"trade_date": "effective_date"}),
        contract_observations=frame.copy(),
        spec_proxy=frame.rename(columns={"trade_date": "session_date"}),
        audit={
            "calendar_start": "2012-01-03",
            "calendar_end": "2012-01-03",
            "contains_returns_targets_labels_or_pnl": False,
        },
    )


def test_default_protocol_is_byte_sealed_and_preserves_data_junction_path() -> None:
    protocol = derived.load_protocol()

    assert protocol.config_sha256 == (
        "a633883d4d930906c171559d73051e020beef3ab1ca1359f2ba98136765ffff3"
    )
    assert protocol.source_daily_rows == 30_059
    assert protocol.source_contracts == 155
    assert protocol.source_directory.relative_to(derived.PROJECT_ROOT).as_posix().startswith(
        "data/processed/futures_pre2018/"
    )
    assert protocol.output_directory.relative_to(derived.PROJECT_ROOT).as_posix().startswith(
        "data/processed/futures_pre2018/"
    )


def test_project_path_rejects_parent_escape() -> None:
    with pytest.raises(ValueError, match="escapes project root"):
        derived._project_path("../outside")


def test_asset_mapping_uses_contract_identity_and_requires_all_core_assets() -> None:
    mapping = {"Si": "SI", "RTS": "RI", "BR": "BR", "MIX": "MIX"}
    contracts = pd.DataFrame(
        [
            {
                "canonical_contract_id": f"{source}:contract",
                "expiration_date": pd.Timestamp("2012-03-15"),
                "logical_symbol": logical,
            }
            for source, logical in mapping.items()
        ]
    )
    daily = pd.DataFrame(
        [
            {
                "canonical_contract_id": f"{source}:contract",
                "asset_code": source,
                "trade_date": pd.Timestamp("2012-01-03"),
            }
            for source in mapping
        ]
    )

    result = derived._observations_by_asset(daily, contracts)

    assert set(result) == {"SI", "RI", "BR", "MIX"}
    assert result["RI"].loc[0, "asset_code"] == "RTS"


def test_outcome_columns_are_rejected_fail_closed() -> None:
    with pytest.raises(ValueError, match="outcome columns"):
        derived._assert_source_only_schema(
            {"unsafe": pd.DataFrame({"strategy_return": [0.01]})}
        )


def test_persistence_is_immutable_and_declares_source_only_bundle(
    tmp_path: Path,
) -> None:
    parent = derived.load_protocol()
    output = tmp_path / "derived-source"
    protocol = replace(
        parent,
        source_directory=derived.PROJECT_ROOT / "data" / "synthetic-parent",
        output_directory=output,
    )

    result = derived.persist_derived(protocol, _safe_tables())

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["temporal_semantics"]["contains_prices"] is True
    assert (
        manifest["temporal_semantics"]["contains_returns_targets_labels_or_pnl"]
        is False
    )
    assert manifest["limitations"]["live_admission_possible"] is False
    assert set(manifest["artifacts"]) == {
        "panel",
        "active_contract_map",
        "contract_observations",
        "spec_proxy",
        "audit",
    }
    with pytest.raises(FileExistsError):
        derived.persist_derived(protocol, _safe_tables())
