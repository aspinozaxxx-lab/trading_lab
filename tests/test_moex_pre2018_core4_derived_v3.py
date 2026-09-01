"""Synthetic tests for the sealed gap-aware pre-2018 source derivation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_pre2018_core4_derived as v1
from market_lab.futures import moex_pre2018_core4_derived_v3 as v3


def _controlled_gap() -> pd.DataFrame:
    rows = [
        {
            "asset_code": "SI",
            "effective_date": pd.Timestamp("2012-01-04"),
            "action": "enter",
            "reason": "first_observed_front",
            "contract_id": "Si:SiH2",
            "exit_execution_price": float("nan"),
        },
        {
            "asset_code": "SI",
            "effective_date": pd.Timestamp("2016-12-09"),
            "action": "flat_skip",
            "reason": "hard_fallback_without_next_contract",
            "contract_id": pd.NA,
            "exit_execution_price": 63_437.0,
        },
    ]
    rows.extend(
        {
            "asset_code": "SI",
            "effective_date": pd.Timestamp(value),
            "action": "flat",
            "reason": "no_active_contract",
            "contract_id": pd.NA,
            "exit_execution_price": float("nan"),
        }
        for value in v3.SI_CONTROLLED_GAP_FLAT_DATES
    )
    rows.append(
        {
            "asset_code": "SI",
            "effective_date": pd.Timestamp("2017-01-04"),
            "action": "enter",
            "reason": "first_observed_front",
            "contract_id": "Si:SiH7",
            "exit_execution_price": float("nan"),
        }
    )
    return pd.DataFrame(rows)


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
            "controlled_SI_source_gap": {"missing_return_bridge_created": False},
            "successful_rolls": v3.EXPECTED_ROLLS,
            "action_counts": v3.EXPECTED_ACTION_COUNTS,
            "unresolved_roll_count": 0,
            "unresolved_exit_count": 0,
        },
    )


def test_default_v3_protocol_is_byte_sealed_and_inherits_exact_D2() -> None:
    protocol = v3.load_protocol()

    assert protocol.config_sha256 == (
        "d21dd6505348c31940f17f2f73fa67dbf4706f98c33b4850ba14e96a37d2f2c5"
    )
    assert protocol.parent.config_sha256 == (
        "7b60afbf9aa0c9c9dc5bffa9918c6e113dd414049c4f38b8d826b75d68fc496b"
    )
    assert protocol.source_daily_rows == 30_059
    assert protocol.roll_config == protocol.parent.roll_config


def test_controlled_si_gap_is_flat_and_never_bridged() -> None:
    audit = v3._verify_controlled_si_gap(_controlled_gap())

    assert audit["exit_effective_date"] == "2016-12-09"
    assert audit["reentry_effective_date"] == "2017-01-04"
    assert audit["flat_session_dates"] == list(v3.SI_CONTROLLED_GAP_FLAT_DATES)
    assert audit["missing_return_bridge_created"] is False
    assert audit["position_during_gap"] == "flat_cash"


def test_controlled_si_gap_rejects_a_missing_flat_session() -> None:
    frame = _controlled_gap()
    frame = frame.loc[frame["effective_date"] != pd.Timestamp("2016-12-13")]

    with pytest.raises(ValueError, match="cash-gap sessions changed"):
        v3._verify_controlled_si_gap(frame)


def test_v3_persistence_is_immutable_and_records_failed_D2(tmp_path: Path) -> None:
    parent = v3.load_protocol()
    output = tmp_path / "derived-v3"
    protocol = replace(parent, output_directory=output)

    result = v3.persist_derived(protocol, _safe_tables())

    assert result == output.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_id"].endswith("v3")
    assert manifest["lineage"]["D2_output_published"] is False
    assert manifest["lineage"]["strategy_outcomes_observed_before_D3"] is False
    assert manifest["temporal_semantics"]["missing_return_bridge_created"] is False
    assert manifest["quality_gates"]["unresolved_exit_count"] == 0
    with pytest.raises(FileExistsError):
        v3.persist_derived(protocol, _safe_tables())
