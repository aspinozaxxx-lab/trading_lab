"""Synthetic tests for the sealed cycle-filtered pre-2018 source derivation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2018_core4_derived as v1
from market_lab.futures import moex_pre2018_core4_derived_v2 as v2


def _contract(logical: str, root: str, month: str, year: int) -> dict[str, object]:
    secid = f"{root}{month}{year % 10}_{year}"
    return {
        "logical_symbol": logical,
        "secid": secid,
        "canonical_contract_id": f"{logical}:{secid}",
    }


def _synthetic_parent() -> tuple[pd.DataFrame, pd.DataFrame]:
    quarterly = ("H", "M", "U", "Z")
    all_months = ("F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z")
    records: list[dict[str, object]] = []
    for year in range(2012, 2018):
        records.extend(_contract("SI", "Si", month, year) for month in quarterly)
        records.extend(_contract("RI", "RI", month, year) for month in quarterly)
        records.extend(_contract("MIX", "MX", month, year) for month in quarterly)
        br_months = tuple(month for month in all_months if not (year == 2017 and month == "F"))
        records.extend(_contract("BR", "BR", month, year) for month in br_months)
    records.extend(
        _contract("SI", "Si", month, 2012) for month in ("N", "Q", "V", "X")
    )
    records.extend(
        _contract("SI", "Si", month, 2013)
        for month in ("F", "G", "J", "K", "N", "Q", "V", "X")
    )
    contracts = pd.DataFrame(records)
    admitted_ids = [
        str(row["canonical_contract_id"])
        for row in records
        if str(row["logical_symbol"]) != "SI"
        or v2._contract_month_code(row) in v2.ADMITTED_MONTH_CODES["SI"]
    ]
    excluded_ids = [
        str(row["canonical_contract_id"])
        for row in records
        if str(row["canonical_contract_id"]) not in admitted_ids
    ]
    daily_ids = [
        admitted_ids[index % len(admitted_ids)]
        for index in range(v2.EXPECTED_ADMITTED_DAILY_ROWS)
    ]
    daily_ids.extend(excluded_ids[index % len(excluded_ids)] for index in range(1_033))
    return pd.DataFrame({"canonical_contract_id": daily_ids}), contracts


def _safe_tables() -> v1.DerivedTables:
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2012-01-03")],
            "asset_code": ["SI"],
            "price": [30_000.0],
        }
    )
    return v1.DerivedTables(
        panel=frame,
        active_contract_map=frame.rename(columns={"trade_date": "effective_date"}),
        contract_observations=frame.copy(),
        spec_proxy=frame.rename(columns={"trade_date": "session_date"}),
        audit={
            "calendar_start": "2012-01-03",
            "calendar_end": "2012-01-03",
            "contract_admission": {"synthetic": True},
            "successful_rolls": v2.EXPECTED_ROLLS,
            "unresolved_roll_count": 0,
            "unresolved_exit_count": 0,
        },
    )


def test_default_v2_protocol_is_byte_sealed() -> None:
    protocol = v2.load_protocol()

    assert protocol.config_sha256 == (
        "7b60afbf9aa0c9c9dc5bffa9918c6e113dd414049c4f38b8d826b75d68fc496b"
    )
    assert protocol.source_daily_rows == 30_059
    assert protocol.source_contracts == 155
    assert protocol.previous_attempt_manifest_sha256 == (
        "73ffe4c3c0a53c034fcd286f2afd6d3b5025f8f9fe598b5f8b8e2d7ecffaa72f"
    )


def test_structural_cycle_admission_excludes_only_twelve_si_serials() -> None:
    daily, contracts = _synthetic_parent()

    admitted_daily, admitted, audit = v2.admit_structural_contract_cycles(daily, contracts)

    assert len(admitted_daily) == 29_026
    assert len(admitted) == 143
    assert audit["admitted_contracts"] == v2.EXPECTED_ADMITTED_CONTRACTS
    assert audit["excluded_contracts"] == 12
    assert audit["excluded_logical_assets"] == ["SI"]
    assert audit["return_or_pnl_used_for_admission"] is False
    si_months = set(admitted.loc[admitted["logical_symbol"] == "SI", "contract_month_code"])
    assert si_months == {"H", "M", "U", "Z"}


def test_contract_month_parser_fails_closed_on_unexpected_secid() -> None:
    with pytest.raises(ValueError, match="unexpected dated futures SECID"):
        v2._contract_month_code({"logical_symbol": "SI", "secid": "Si-perpetual"})


def test_v2_persistence_is_immutable_and_records_D1_supersession(tmp_path: Path) -> None:
    parent = v2.load_protocol()
    output = tmp_path / "derived-v2"
    protocol = replace(
        parent,
        source_directory=v2.PROJECT_ROOT / "data" / "synthetic-parent",
        output_directory=output,
    )

    result = v2.persist_derived(protocol, _safe_tables())

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"].endswith("v2")
    assert manifest["supersedes_source_derivation"]["version"] == 1
    assert manifest["supersedes_source_derivation"]["strategy_outcomes_observed"] is False
    assert manifest["quality_gates"]["unresolved_roll_count"] == 0
    assert manifest["temporal_semantics"]["contains_returns_targets_labels_or_pnl"] is False
    with pytest.raises(FileExistsError):
        v2.persist_derived(protocol, _safe_tables())
